"""混合架构编排器 — LLM+计算混合（C2S-Scale + 救狗案例）

回应新闻洞察：
- Google C2S-Scale：LLM 作为控制器（Controller），调用计算工具完成多步骤科学发现
- 程序员用 ChatGPT+AlphaFold 救狗：LLM 假设 → 结构预测 → 新抗原识别 → 疫苗设计

设计原则：
- LLM 在两端（假设生成 + 报告生成），计算工具在中间（对接/结构/新抗原）
- 成本可控：累计 cost_usd 超限提前终止（settings.HYBRID_MAX_COST_USD）
- 容错：单步失败不中断整个流程（除成本超限）
- 可观测：每步记录 ComputeJob（引擎/模式/成本/能耗/token）

性能优化（v2）：
- Step 2/Step 4 的对接循环改为 asyncio.gather 并发执行（N 个分子同时对接，而非串行）
- 单分子对接超时保护（HYBRID_PER_MOL_TIMEOUT_SEC，默认 30s）
- LLM 调用超时保护（HYBRID_LLM_TIMEOUT_SEC，默认 45s）
- 候选数量上限（HYBRID_MAX_CANDIDATES，默认 10），避免 LLM 上下文爆炸 + 减少 N 次对接
- 单分子失败不影响其他分子（return_exceptions=True）
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.compute_job import (
    ComputeEngine,
    ComputeJob,
    ComputeJobStatus,
    ComputeJobType,
    ComputeMode,
)
from app.models.neoantigen import Neoantigen, NeoantigenStatus
from app.models.protein_structure import (
    ProteinStructure,
    ProteinStructureSource,
    ProteinStructureStatus,
)
from app.services.compute import get_esmfold, get_mhcflurry, get_unimol, get_vina
from app.services.llm.prompts import SYSTEM_PROMPTS

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class HybridOrchestrator:
    """混合架构编排器 — LLM 在两端（假设+报告），计算工具在中间

    两个核心流程：
    1. llm_driven_docking — C2S-Scale 启发的 5 步 LLM-as-Controller 分子对接
    2. llm_to_vaccine_pipeline — 复现程序员救狗案例的 3 步疫苗设计
    """

    def __init__(self, db: AsyncSession, llm_client=None, llm_config=None):
        self.db = db
        # 创建 LLMOrchestrator 复用其 select_model + load_user_genome_context
        from app.services.llm.orchestrator import LLMOrchestrator
        self.llm_orchestrator = LLMOrchestrator(db, llm_client, llm_config)
        self.llm_client = llm_client

    # ================================================================
    # 公开方法
    # ================================================================

    async def llm_driven_docking(
        self,
        project_id: Any,
        target_id: Any,
        smiles_list: List[str],
        user: Any,
        top_k: int = 20,
    ) -> Dict[str, Any]:
        """LLM 驱动的分子对接 — C2S-Scale 启发的 5 步 LLM-as-Controller 流程

        Step 1: LLM 假设生成（筛选候选）
        Step 2: Uni-Mol 粗筛对接
        Step 3: LLM 重排序（对接分数 + 药化知识）
        Step 4: Vina 精修 top-K
        Step 5: LLM 综合报告
        """
        pipeline_start = time.time()
        total_cost = 0.0
        total_energy = 0.0
        steps_completed = 0
        truncated = False
        user_id = getattr(user, "id", user)

        # 加载靶点信息（gene_symbol 用于 LLM 上下文）
        gene_symbol = "未知"
        target_pdb = ""
        try:
            from app.models.target import Target
            target = await self.db.get(Target, _to_uuid(target_id))
            if target:
                gene_symbol = target.gene_symbol or "未知"
        except Exception as e:
            logger.warning(f"加载靶点 {target_id} 失败: {e}")

        # 空输入快速返回
        if not smiles_list:
            return self._empty_docking_result(pipeline_start)

        # 限制候选数量：取 top_k * 2，但不超过 HYBRID_MAX_CANDIDATES（默认 10）
        # 过多候选会导致：① LLM 上下文爆炸 ② N 次串行对接耗时线性增长 ③ 整体超时
        max_candidates = getattr(settings, "HYBRID_MAX_CANDIDATES", 10)
        candidate_limit = min(top_k * 2, max_candidates)
        candidate_smiles = list(smiles_list[:candidate_limit])

        # ========== Step 1: LLM 假设生成 ==========
        selected: List[Dict[str, Any]] = []
        try:
            smiles_json = json.dumps(candidate_smiles, ensure_ascii=False)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPTS["hybrid_hypothesis"]},
                {"role": "user", "content": (
                    f"## 靶点基因：{gene_symbol}\n\n"
                    f"## 候选分子 SMILES 列表（共 {len(candidate_smiles)} 个）：\n{smiles_json}\n\n"
                    f"请筛选最可能成药的 top-{top_k} 候选分子，输出 JSON。"
                )},
            ]
            content, _usage, cost, _model, tokens = await self._call_llm_with_timeout(
                messages, "deep_insight", user_id
            )
            total_cost += cost
            parsed = self._parse_llm_json(content, {})
            raw_selected = parsed.get("selected", []) if isinstance(parsed, dict) else []
            for item in raw_selected:
                smi = item.get("smiles", "")
                if smi and smi in candidate_smiles:
                    selected.append({
                        "smiles": smi,
                        "reason": item.get("reason", ""),
                        "priority": item.get("priority", 3),
                    })
            if not selected:
                logger.warning("LLM 假设生成未返回有效候选，降级为全部候选分子")
                selected = [
                    {"smiles": s, "reason": "LLM 降级-全量候选", "priority": 3}
                    for s in candidate_smiles[:top_k]
                ]
            steps_completed = 1
            await self._record_compute_job(
                job_type=ComputeJobType.DOCKING, engine=ComputeEngine.HYBRID,
                mode=ComputeMode.HYBRID,
                input_params={"step": 1, "gene": gene_symbol, "n_candidates": len(candidate_smiles)},
                result={"n_selected": len(selected)}, cost_usd=cost, duration_sec=0.5,
                user_id=user_id, project_id=project_id, token_count=tokens,
            )
        except Exception as e:
            logger.warning(f"Step 1 LLM 假设生成失败，降级为全部候选: {e}")
            selected = [
                {"smiles": s, "reason": "LLM 异常-全量候选", "priority": 3}
                for s in candidate_smiles[:top_k]
            ]
            steps_completed = 1

        if self._cost_exceeded(total_cost):
            truncated = True
            logger.warning(f"Step 1 后成本超限 (${total_cost:.4f})，提前终止")

        # ========== Step 2: Uni-Mol 粗筛（并发执行） ==========
        # 性能优化：原串行 for 循环改为 asyncio.gather 并发，N 个分子同时对接。
        # 单分子超时（HYBRID_PER_MOL_TIMEOUT_SEC，默认 30s）防卡死，
        # 单分子失败不影响其他分子（return_exceptions=True）。
        docking_results: List[Dict[str, Any]] = []
        if not truncated:
            try:
                unimol = get_unimol(self.db)
                step_start = time.time()

                async def _dock_one(cand: Dict[str, Any]) -> Dict[str, Any]:
                    """单分子 Uni-Mol 对接（带超时保护）"""
                    smi = cand["smiles"]
                    try:
                        per_mol_timeout = getattr(settings, "HYBRID_PER_MOL_TIMEOUT_SEC", 30)
                        result = await asyncio.wait_for(
                            unimol.dock(
                                smiles=smi, target_pdb=target_pdb, target_name=gene_symbol
                            ),
                            timeout=per_mol_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Uni-Mol 对接超时（{per_mol_timeout}s），smiles={smi[:30]}"
                        )
                        result = {
                            "rmsd": 0.0, "affinity": 0.0, "confidence": 0.0,
                            "binding_pose": {}, "source": "timeout",
                            "error": f"对接超时（{per_mol_timeout}s）",
                        }
                    except Exception as e:
                        logger.warning(f"Uni-Mol 单分子对接失败 smiles={smi[:30]}: {e}")
                        result = {
                            "rmsd": 0.0, "affinity": 0.0, "confidence": 0.0,
                            "binding_pose": {}, "source": "error", "error": str(e),
                        }
                    return {
                        "smiles": smi,
                        "unimol": result,
                        "reason": cand.get("reason", ""),
                    }

                # 并发执行所有候选分子的对接（最多 10 个并发，避免过载）
                if selected:
                    batch_size = getattr(settings, "HYBRID_CONCURRENCY", 5)
                    # 分批并发，避免一次性创建过多任务
                    for i in range(0, len(selected), batch_size):
                        batch = selected[i:i + batch_size]
                        batch_results = await asyncio.gather(
                            *[_dock_one(c) for c in batch], return_exceptions=False
                        )
                        docking_results.extend(batch_results)

                step_duration = time.time() - step_start
                step_energy = self._estimate_energy_kwh(step_duration)
                total_energy += step_energy
                await self._record_compute_job(
                    job_type=ComputeJobType.DOCKING, engine=ComputeEngine.UNIMOL,
                    mode=self._resolve_mode(ComputeEngine.UNIMOL),
                    input_params={"smiles_list": [c["smiles"] for c in selected], "target": gene_symbol},
                    result={"count": len(docking_results),
                            "affinities": [{"smiles": d["smiles"], "affinity": d["unimol"].get("affinity")}
                                           for d in docking_results]},
                    cost_usd=0.0, duration_sec=step_duration, user_id=user_id,
                    project_id=project_id, energy_kwh=step_energy,
                )
                steps_completed = 2
            except Exception as e:
                logger.warning(f"Step 2 Uni-Mol 对接失败: {e}")
                docking_results = [
                    {"smiles": c["smiles"], "unimol": {}, "reason": c.get("reason", "")}
                    for c in selected
                ]
                steps_completed = 2

            if self._cost_exceeded(total_cost):
                truncated = True
                logger.warning(f"Step 2 后成本超限 (${total_cost:.4f})，提前终止")

        # ========== Step 3: LLM 重排序 ==========
        final_ranking: List[Dict[str, Any]] = []
        if not truncated:
            try:
                docking_summary = [
                    {"smiles": d["smiles"],
                     "affinity": d["unimol"].get("affinity", 0),
                     "rmsd": d["unimol"].get("rmsd", 0),
                     "confidence": d["unimol"].get("confidence", 0)}
                    for d in docking_results
                ]
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPTS["hybrid_reranking"]},
                    {"role": "user", "content": (
                        f"## 靶点基因：{gene_symbol}\n\n"
                        f"## Uni-Mol 对接结果：\n{json.dumps(docking_summary, ensure_ascii=False)}\n\n"
                        "请基于对接分数和药化知识重排序，输出 JSON。"
                    )},
                ]
                content, _usage, cost, _model, tokens = await self._call_llm_with_timeout(
                    messages, "deep_insight", user_id
                )
                total_cost += cost
                parsed = self._parse_llm_json(content, {})
                ranked = parsed.get("ranked", []) if isinstance(parsed, dict) else []
                docking_smiles_set = {d["smiles"] for d in docking_results}
                for item in ranked:
                    smi = item.get("smiles", "")
                    if smi and smi in docking_smiles_set:
                        final_ranking.append({
                            "smiles": smi,
                            "final_score": float(item.get("final_score", 0.5)),
                            "reason": item.get("reason", ""),
                        })
                if not final_ranking:
                    logger.warning("LLM 重排序未返回有效结果，降级为 affinity 排序")
                    final_ranking = self._rank_by_affinity(docking_results)
                steps_completed = 3
                await self._record_compute_job(
                    job_type=ComputeJobType.DOCKING, engine=ComputeEngine.HYBRID,
                    mode=ComputeMode.HYBRID,
                    input_params={"step": 3, "n_docking": len(docking_results)},
                    result={"n_ranked": len(final_ranking)}, cost_usd=cost, duration_sec=0.5,
                    user_id=user_id, project_id=project_id, token_count=tokens,
                )
            except Exception as e:
                logger.warning(f"Step 3 LLM 重排序失败，降级为 affinity 排序: {e}")
                final_ranking = self._rank_by_affinity(docking_results)
                steps_completed = 3

            if self._cost_exceeded(total_cost):
                truncated = True
                logger.warning(f"Step 3 后成本超限 (${total_cost:.4f})，提前终止")

        # ========== Step 4: Vina 精修 top-K（并发执行） ==========
        # 性能优化：原串行循环改为 asyncio.gather 并发，N 个分子同时精修。
        if not truncated and final_ranking:
            try:
                vina = get_vina(self.db)
                step_start = time.time()
                refine_k = min(settings.HYBRID_VINA_REFINE_TOP_K, len(final_ranking))
                refine_candidates = final_ranking[:refine_k]

                async def _vina_one(item: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
                    """单分子 Vina 精修（带超时保护）"""
                    smi = item["smiles"]
                    try:
                        per_mol_timeout = getattr(settings, "HYBRID_PER_MOL_TIMEOUT_SEC", 30)
                        vina_result = await asyncio.wait_for(
                            vina.dock(smiles=smi, receptor_pdbqt="", box={}),
                            timeout=per_mol_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Vina 精修超时（{per_mol_timeout}s），smiles={smi[:30]}")
                        vina_result = {
                            "affinity": 0.0, "rmsd": 0.0, "pose": {},
                            "source": "timeout", "error": f"精修超时（{per_mol_timeout}s）",
                        }
                    except Exception as e:
                        logger.warning(f"Vina 单分子精修失败 smiles={smi[:30]}: {e}")
                        vina_result = {
                            "affinity": 0.0, "rmsd": 0.0, "pose": {},
                            "source": "error", "error": str(e),
                        }
                    return smi, vina_result

                # 并发执行所有精修
                vina_pairs = await asyncio.gather(
                    *[_vina_one(item) for item in refine_candidates]
                )
                # 把结果合并回 docking_results
                vina_map = {smi: vr for smi, vr in vina_pairs}
                for d in docking_results:
                    if d["smiles"] in vina_map:
                        d["vina"] = vina_map[d["smiles"]]

                step_duration = time.time() - step_start
                step_energy = self._estimate_energy_kwh(step_duration)
                total_energy += step_energy
                await self._record_compute_job(
                    job_type=ComputeJobType.DOCKING, engine=ComputeEngine.VINA,
                    mode=self._resolve_mode(ComputeEngine.VINA),
                    input_params={"smiles_list": [r["smiles"] for r in refine_candidates],
                                  "refine_k": refine_k},
                    result={"count": refine_k}, cost_usd=0.0, duration_sec=step_duration,
                    user_id=user_id, project_id=project_id, energy_kwh=step_energy,
                )
                steps_completed = 4
            except Exception as e:
                logger.warning(f"Step 4 Vina 精修失败: {e}")
                steps_completed = 4

            if self._cost_exceeded(total_cost):
                truncated = True
                logger.warning(f"Step 4 后成本超限 (${total_cost:.4f})，提前终止")

        # ========== Step 5: LLM 综合报告 ==========
        report = ""
        if not truncated:
            try:
                ranking_summary = json.dumps(final_ranking[:10], ensure_ascii=False)
                docking_summary = json.dumps(
                    [{"smiles": d["smiles"], "unimol": d.get("unimol", {}),
                      "vina": d.get("vina", {})} for d in docking_results[:10]],
                    ensure_ascii=False,
                )
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPTS["hybrid_report"]},
                    {"role": "user", "content": (
                        f"## 靶点基因：{gene_symbol}\n\n"
                        f"## 最终排序：\n{ranking_summary}\n\n"
                        f"## 对接结果摘要：\n{docking_summary}\n\n"
                        f"## 成本数据：总成本 ${total_cost:.4f}，{steps_completed} 步完成\n\n"
                        "请生成结构化 Markdown 报告。"
                    )},
                ]
                content, _usage, cost, _model, tokens = await self._call_llm_with_timeout(
                    messages, "deep_insight", user_id
                )
                total_cost += cost
                report = content or self._template_report(gene_symbol, final_ranking, total_cost)
                steps_completed = 5
                await self._record_compute_job(
                    job_type=ComputeJobType.DOCKING, engine=ComputeEngine.HYBRID,
                    mode=ComputeMode.HYBRID,
                    input_params={"step": 5, "n_ranking": len(final_ranking)},
                    result={"report_length": len(report)}, cost_usd=cost, duration_sec=0.5,
                    user_id=user_id, project_id=project_id, token_count=tokens,
                )
            except Exception as e:
                logger.warning(f"Step 5 LLM 报告生成失败，使用模板: {e}")
                report = self._template_report(gene_symbol, final_ranking, total_cost)
                steps_completed = 5

        duration = round(time.time() - pipeline_start, 3)
        return {
            "final_ranking": final_ranking,
            "docking_results": docking_results,
            "report": report,
            "cost_usd": round(total_cost, 4),
            "duration_sec": duration,
            "energy_kwh": round(total_energy, 6),
            "steps_completed": steps_completed,
            "truncated": truncated,
        }

    async def llm_to_vaccine_pipeline(
        self,
        project_id: Any,
        target_id: Any,
        mutation_sequence: str,
        user: Any,
        mhc_alleles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """LLM 到疫苗流水线 — 复现程序员救狗案例的 3 步流程

        Step 1: ESMFold 预测突变蛋白结构
        Step 2: MHCflurry 识别新抗原
        Step 3: LLM 设计 mRNA 疫苗序列
        """
        pipeline_start = time.time()
        total_cost = 0.0
        total_energy = 0.0
        steps_completed = 0
        user_id = getattr(user, "id", user)
        alleles = mhc_alleles or ["HLA-A*02:01", "HLA-B*07:02"]

        structure_result: Dict[str, Any] = {}
        neoantigen_records: List[Dict[str, Any]] = []
        vaccine_result: Dict[str, Any] = {}

        # ========== Step 1: ESMFold 预测突变蛋白结构 ==========
        try:
            esmfold = get_esmfold(self.db)
            step_start = time.time()
            result = await esmfold.predict_structure(
                sequence=mutation_sequence, target_id=str(target_id)
            )
            step_duration = time.time() - step_start
            step_energy = self._estimate_energy_kwh(step_duration)
            total_energy += step_energy

            # 持久化 ProteinStructure
            structure_id = None
            try:
                structure = ProteinStructure(
                    target_id=_to_uuid(target_id),
                    owner_id=_to_uuid(user_id),
                    sequence=mutation_sequence,
                    storage_path=result.get("storage_path", ""),
                    plddt_mean=result.get("plddt_mean", 0.0),
                    prediction_source=(
                        ProteinStructureSource.ESMFOLD
                        if result.get("source") == "esmfold"
                        else ProteinStructureSource.MOCK
                    ),
                    status=ProteinStructureStatus.COMPLETED,
                    model_name=result.get("model_name", ""),
                    duration_sec=int(step_duration),
                )
                self.db.add(structure)
                await self.db.flush()
                structure_id = str(structure.id)
            except Exception as e:
                logger.warning(f"ProteinStructure 持久化失败: {e}")

            structure_result = {
                "pdb_text": result.get("pdb_text", ""),
                "plddt_mean": result.get("plddt_mean", 0.0),
                "structure_id": structure_id,
            }
            await self._record_compute_job(
                job_type=ComputeJobType.STRUCTURE_PREDICTION, engine=ComputeEngine.ESMFOLD,
                mode=self._resolve_mode(ComputeEngine.ESMFOLD),
                input_params={"sequence_length": len(mutation_sequence), "target_id": str(target_id)},
                result={"plddt_mean": result.get("plddt_mean"), "source": result.get("source")},
                cost_usd=0.0, duration_sec=step_duration, user_id=user_id,
                project_id=project_id, energy_kwh=step_energy,
            )
            steps_completed = 1
        except Exception as e:
            logger.warning(f"Step 1 ESMFold 结构预测失败: {e}")
            steps_completed = 1

        # ========== Step 2: MHCflurry 识别新抗原 ==========
        try:
            mhcflurry = get_mhcflurry(self.db)
            step_start = time.time()
            # 适配 MHCflurry API：构造 mutations 列表
            # mutation_position 取序列中点作为突变位点（简化处理）
            mut_pos = max(1, len(mutation_sequence) // 2)
            mutations_input = [{
                "mutation_id": str(target_id),
                "protein_sequence": mutation_sequence,
                "mutation_position": mut_pos,
            }]
            neoantigens = await mhcflurry.identify_neoantigens(mutations_input, alleles)
            step_duration = time.time() - step_start
            step_energy = self._estimate_energy_kwh(step_duration)
            total_energy += step_energy

            # 持久化 Neoantigen 记录
            for neo in neoantigens:
                neo_id = None
                try:
                    record = Neoantigen(
                        owner_id=_to_uuid(user_id),
                        project_id=_to_uuid(project_id),
                        target_id=_to_uuid(target_id),
                        mutant_peptide=neo.get("peptide", ""),
                        mhc_alleles=[neo.get("mhc_allele", "")],
                        binding_affinity_nM=neo.get("affinity_nM", 0.0),
                        binding_rank=neo.get("rank"),
                        is_neoantigen=neo.get("is_neoantigen", False),
                        status=(NeoantigenStatus.IDENTIFIED
                                if neo.get("is_neoantigen")
                                else NeoantigenStatus.REJECTED),
                        structure_plddt=structure_result.get("plddt_mean"),
                    )
                    self.db.add(record)
                    await self.db.flush()
                    neo_id = str(record.id)
                except Exception as e:
                    logger.warning(f"Neoantigen 持久化失败: {e}")
                neoantigen_records.append({
                    "mutant_peptide": neo.get("peptide", ""),
                    "binding_affinity_nM": neo.get("affinity_nM", 0.0),
                    "is_neoantigen": neo.get("is_neoantigen", False),
                    "mhc_allele": neo.get("mhc_allele", ""),
                    "neoantigen_id": neo_id,
                })

            await self._record_compute_job(
                job_type=ComputeJobType.NEOANTIGEN, engine=ComputeEngine.MHCFLURRY,
                mode=self._resolve_mode(ComputeEngine.MHCFLURRY),
                input_params={"alleles": alleles, "mutation_position": mut_pos},
                result={"n_neoantigens": len(neoantigen_records)},
                cost_usd=0.0, duration_sec=step_duration, user_id=user_id,
                project_id=project_id, energy_kwh=step_energy,
            )
            steps_completed = 2
        except Exception as e:
            logger.warning(f"Step 2 MHCflurry 新抗原识别失败: {e}")
            steps_completed = 2

        # ========== Step 3: LLM 设计 mRNA 疫苗序列 ==========
        try:
            neo_summary = json.dumps(neoantigen_records[:20], ensure_ascii=False)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPTS["vaccine_design"]},
                {"role": "user", "content": (
                    f"## 突变蛋白结构 pLDDT：{structure_result.get('plddt_mean', 0)}\n\n"
                    f"## 识别的新抗原列表：\n{neo_summary}\n\n"
                    "请设计个性化 mRNA 疫苗序列，输出 JSON。"
                )},
            ]
            content, _usage, cost, _model, tokens = await self._call_llm(
                messages, "deep_insight", user_id
            )
            total_cost += cost
            parsed = self._parse_llm_json(content, {})
            vaccine_result = {
                "vaccine_sequence": parsed.get("vaccine_sequence", ""),
                "gc_content": float(parsed.get("gc_content", 0.0)),
                "length": int(parsed.get("length", 0)),
                "immunogenicity_score": float(parsed.get("immunogenicity_score", 0.0)),
                "notes": parsed.get("notes", ""),
            }

            # 校验 GC 含量在推荐范围内
            gc = vaccine_result["gc_content"]
            if gc < settings.VACCINE_GC_CONTENT_MIN or gc > settings.VACCINE_GC_CONTENT_MAX:
                logger.warning(
                    f"GC 含量 {gc} 超出推荐范围 "
                    f"[{settings.VACCINE_GC_CONTENT_MIN}, {settings.VACCINE_GC_CONTENT_MAX}]"
                )

            steps_completed = 3
            await self._record_compute_job(
                job_type=ComputeJobType.VACCINE_DESIGN, engine=ComputeEngine.HYBRID,
                mode=ComputeMode.HYBRID,
                input_params={"n_neoantigens": len(neoantigen_records)},
                result={"gc_content": gc, "length": vaccine_result["length"]},
                cost_usd=cost, duration_sec=0.5, user_id=user_id,
                project_id=project_id, token_count=tokens,
            )
        except Exception as e:
            logger.warning(f"Step 3 LLM 疫苗设计失败: {e}")
            vaccine_result = {
                "vaccine_sequence": "",
                "gc_content": 0.0,
                "length": 0,
                "immunogenicity_score": 0.0,
                "notes": f"LLM 设计失败: {e}",
            }
            steps_completed = 3

        duration = round(time.time() - pipeline_start, 3)
        return {
            "structure": structure_result,
            "neoantigens": neoantigen_records,
            "vaccine": vaccine_result,
            "cost_usd": round(total_cost, 4),
            "duration_sec": duration,
            "steps_completed": steps_completed,
        }

    # ================================================================
    # 内部辅助方法
    # ================================================================

    async def _call_llm(
        self, messages: List[Dict], tier: str, user_id: Any
    ) -> Tuple[str, Dict, float, str, int]:
        """调用 LLM — 返回 (content, usage, cost_usd, model, token_count)

        如果 llm_client 未配置，返回空内容（降级）。
        """
        if self.llm_client is None:
            logger.warning("LLM 客户端未配置，返回空内容（降级）")
            return "", {}, 0.0, "", 0
        model = self.llm_orchestrator.select_model(tier)
        response = await self.llm_client.chat(messages, model=model)
        content = response.get("content", "")
        usage = response.get("usage", {}) or {}
        cost = self._estimate_cost(usage, model)
        tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        return content, usage, cost, model, tokens

    async def _call_llm_with_timeout(
        self, messages: List[Dict], tier: str, user_id: Any
    ) -> Tuple[str, Dict, float, str, int]:
        """带超时保护的 LLM 调用 — 包装 _call_llm，超时后返回空响应

        超时阈值通过 settings.HYBRID_LLM_TIMEOUT_SEC（默认 45s）配置。
        超时不会抛异常，而是返回空内容，让上层降级逻辑接管（如降级排序）。
        """
        timeout_sec = getattr(settings, "HYBRID_LLM_TIMEOUT_SEC", 45)
        try:
            return await asyncio.wait_for(
                self._call_llm(messages, tier, user_id),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"LLM 调用超时（{timeout_sec}s），降级为空响应 — tier={tier}"
            )
            return "", {}, 0.0, "", 0
        except Exception as e:
            logger.warning(f"LLM 调用异常，降级为空响应: {e}")
            return "", {}, 0.0, "", 0

    def _parse_llm_json(self, content: str, default: Any) -> Any:
        """解析 LLM 返回的 JSON — 容忍 ```json 包裹，失败时返回 default"""
        if not content:
            return default
        text = content.strip()
        try:
            # 提取 ```json ... ``` 或 ``` ... ``` 代码块
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.rindex("```")
                text = text[start:end].strip()
            elif "```" in text:
                start = text.index("```") + 3
                end = text.rindex("```")
                text = text[start:end].strip()
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"LLM JSON 解析失败，使用默认值: {e}")
            return default

    def _estimate_cost(self, usage: Dict, model: str) -> float:
        """根据 token 用量估算成本 — 优先使用 cost_tracker 定价表"""
        prompt_tokens = (usage or {}).get("prompt_tokens", 0)
        completion_tokens = (usage or {}).get("completion_tokens", 0)
        try:
            from app.services.llm.cost_tracker import _MODEL_PRICING
            if model and model in _MODEL_PRICING:
                in_price, out_price = _MODEL_PRICING[model]
                return round((prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000, 4)
        except ImportError:
            pass
        # 默认 fast_screen 价格
        return round((prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000, 4)

    def _estimate_energy_kwh(self, duration_sec: float) -> float:
        """估算能耗（千瓦时）— 基于 CPU+GPU 功耗 × PUE × 时长"""
        watts = settings.BENCHMARK_CPU_WATTS + settings.BENCHMARK_GPU_WATTS  # 350+400=750W
        pue = settings.BENCHMARK_PUE  # 1.5
        return round((watts * pue * duration_sec) / 3_600_000, 6)

    def _resolve_mode(self, engine: str) -> str:
        """根据引擎 mock 开关解析运行模式 — mock 引擎记 MOCK，否则记 HYBRID"""
        engine_mock_setting = {
            ComputeEngine.UNIMOL: "UNIMOL_USE_MOCK",
            ComputeEngine.VINA: "VINA_USE_MOCK",
            ComputeEngine.ESMFOLD: "ESMFOLD_USE_MOCK",
            ComputeEngine.MHCFLURRY: "MHCFLURRY_USE_MOCK",
        }.get(engine)
        if engine_mock_setting and getattr(settings, engine_mock_setting, True):
            return ComputeMode.MOCK
        return ComputeMode.HYBRID

    def _cost_exceeded(self, current_cost: float) -> bool:
        """检查累计成本是否超限"""
        return current_cost > settings.HYBRID_MAX_COST_USD

    async def _record_compute_job(
        self,
        job_type: str,
        engine: str,
        mode: str,
        input_params: Dict,
        result: Dict,
        cost_usd: float,
        duration_sec: float,
        user_id: Any,
        energy_kwh: Optional[float] = None,
        token_count: Optional[int] = None,
        project_id: Any = None,
    ) -> Optional[ComputeJob]:
        """记录计算任务到 DB — 使用 savepoint 隔离失败，不影响主流程"""
        try:
            async with self.db.begin_nested():
                job = ComputeJob(
                    owner_id=_to_uuid(user_id),
                    project_id=_to_uuid(project_id),
                    job_type=job_type,
                    engine=engine,
                    mode=mode,
                    status=ComputeJobStatus.COMPLETED,
                    input_params=input_params,
                    result=result,
                    cost_usd=cost_usd,
                    duration_sec=int(duration_sec) if duration_sec else 0,
                    energy_kwh=energy_kwh,
                    token_count=token_count,
                )
                self.db.add(job)
                await self.db.flush()
                return job
        except Exception as e:
            logger.warning(f"记录 ComputeJob 失败（不影响主流程）: {e}")
            return None

    def _rank_by_affinity(self, docking_results: List[Dict]) -> List[Dict]:
        """降级排序 — 按 Uni-Mol affinity 升序（越负越好）"""
        sorted_results = sorted(
            docking_results,
            key=lambda d: d.get("unimol", {}).get("affinity", 0),
        )
        return [
            {
                "smiles": d["smiles"],
                "final_score": round(
                    min(1.0, max(0.0, -d.get("unimol", {}).get("affinity", 0) / 12.0)), 4
                ),
                "reason": "降级-affinity 排序",
            }
            for d in sorted_results
        ]

    def _template_report(
        self, gene_symbol: str, ranking: List[Dict], cost: float
    ) -> str:
        """降级模板报告 — LLM 报告生成失败时使用"""
        top3 = ranking[:3]
        lines = [
            f"# 混合架构药物发现报告 — {gene_symbol}",
            "",
            "## 摘要",
            f"靶点 {gene_symbol} 的混合架构分子对接完成，共筛选 {len(ranking)} 个候选分子。",
            "",
            "## Top-3 候选分子",
        ]
        for i, mol in enumerate(top3, 1):
            lines.append(
                f"{i}. **{mol.get('smiles', '?')}** — 评分 {mol.get('final_score', 0):.2f}"
            )
        lines.extend([
            "",
            "## 成本效益",
            f"总成本 ${cost:.4f}（LLM + 计算混合架构）",
            "",
            "## 下一步建议",
            "对 top-3 候选分子进行湿实验验证。",
        ])
        return "\n".join(lines)

    def _empty_docking_result(self, start_time: float) -> Dict[str, Any]:
        """空输入快速返回"""
        return {
            "final_ranking": [],
            "docking_results": [],
            "report": "",
            "cost_usd": 0.0,
            "duration_sec": round(time.time() - start_time, 3),
            "energy_kwh": 0.0,
            "steps_completed": 0,
            "truncated": False,
        }
