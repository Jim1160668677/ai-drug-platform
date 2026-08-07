"""端到端药物发现流水线 — 串联靶点发现 → 分子生成+评估 → 治疗方案匹配

复用三个核心服务：
1. TargetIdentifier.discover() — 靶点发现
2. MoleculeDesigner.generate_molecules() + assess_druglikeness/predict_admet/explain_molecule — 分子生成与评估
3. TreatmentPlanner.optimize() + 逐靶点方案生成 — 治疗方案匹配

设计原则：
- 复用现有服务，不重写业务逻辑
- 幂等：重复运行不产生重复数据
- 容错：单步失败不中断整个流水线
- 可观测：返回每步状态、耗时、结果摘要
- 持久化：每个步骤独立 commit，支持断点续传
- 结构化日志：记录每步的输入、输出、耗时、错误
"""
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.molecule import Molecule
from app.models.pipeline_run import PipelineRun, PipelineRunStatus, StepStatus
from app.models.project import Project
from app.models.target import Target
from app.models.treatment import Treatment, TreatmentStatus, TreatmentType

logger = logging.getLogger(__name__)


class PipelineStepStatus:
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


STEP_ORDER = [
    "target_discovery",
    "molecule_generation",
    "treatment_matching",
    "hypothesis_generation",
]


class DiscoveryPipeline:
    """端到端药物发现流水线编排器"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._pipeline_run: Optional[PipelineRun] = None

    # ---------- PipelineRun 持久化追踪 ----------

    async def _create_pipeline_run(
        self,
        project_id: UUID,
        tier: str,
        max_targets: int,
        molecules_per_target: int,
        molecule_strategy: str,
        skip_existing: bool,
        enable_hypothesis: bool,
        triggered_by: Optional[UUID] = None,
    ) -> PipelineRun:
        pipeline_run = PipelineRun(
            project_id=project_id,
            status=PipelineRunStatus.PENDING,
            tier=tier,
            max_targets=max_targets,
            molecules_per_target=molecules_per_target,
            molecule_strategy=molecule_strategy,
            skip_existing=skip_existing,
            enable_hypothesis=enable_hypothesis,
            triggered_by=triggered_by,
        )
        self.db.add(pipeline_run)
        await self.db.commit()
        await self.db.refresh(pipeline_run)
        self._pipeline_run = pipeline_run
        return pipeline_run

    async def _mark_running(self) -> None:
        if not self._pipeline_run:
            return
        self._pipeline_run.status = PipelineRunStatus.RUNNING
        self._pipeline_run.started_at = datetime.utcnow()
        await self.db.commit()

    async def _mark_completed(self, duration: float, summary: Dict[str, Any]) -> None:
        if not self._pipeline_run:
            return
        self._pipeline_run.status = PipelineRunStatus.COMPLETED
        self._pipeline_run.completed_at = datetime.utcnow()
        self._pipeline_run.duration_sec = duration
        self._pipeline_run.summary = summary
        self._pipeline_run.add_log(
            "info", "pipeline", "流水线执行完成",
            duration_sec=duration, summary=summary,
        )
        await self.db.commit()

    async def _mark_failed(self, error: Exception) -> None:
        if not self._pipeline_run:
            return
        self._pipeline_run.status = PipelineRunStatus.FAILED
        self._pipeline_run.error_message = str(error)
        self._pipeline_run.completed_at = datetime.utcnow()
        self._pipeline_run.add_log(
            "error", "pipeline", f"流水线执行失败: {str(error)}",
            error_type=type(error).__name__,
        )
        await self.db.commit()

    # ---------- 结构化日志 ----------

    async def _log_step_start(self, step_name: str) -> None:
        if self._pipeline_run:
            self._pipeline_run.add_log(
                "info", step_name, "步骤开始执行",
                pipeline_run_id=str(self._pipeline_run.id),
            )
            self._pipeline_run.current_step = step_name
            await self.db.commit()

    async def _log_step_complete(
        self, step_name: str, status: str, duration_sec: float, **kwargs: Any
    ) -> None:
        if self._pipeline_run:
            self._pipeline_run.update_step_status(
                step_name, status, duration_sec=duration_sec, **kwargs
            )
            log_level = "info" if status in (StepStatus.SUCCESS, StepStatus.PARTIAL) else "error"
            self._pipeline_run.add_log(
                log_level, step_name, f"步骤{status}",
                duration_sec=duration_sec,
                **kwargs,
            )
            await self.db.commit()

    async def _log_step_error(self, step_name: str, error: Exception) -> None:
        if self._pipeline_run:
            self._pipeline_run.add_log(
                "error", step_name, f"步骤异常: {str(error)}",
                error_type=type(error).__name__,
            )
            self._pipeline_run.error_message = str(error)
            await self.db.commit()

    # ---------- 统一步骤执行框架 ----------

    async def _execute_step(
        self,
        step_name: str,
        runner: Callable[[], Any],
        success_extras: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        await self._log_step_start(step_name)
        try:
            result = await runner()
            status = result.get("status", StepStatus.FAILED)
            duration = result.get("duration_sec", 0)

            if status in (PipelineStepStatus.SUCCESS, PipelineStepStatus.PARTIAL):
                await self.db.commit()
                logger.info(
                    "[pipeline] 步骤 %s 完成: status=%s duration=%.3fs",
                    step_name, status, duration,
                )
            else:
                logger.warning(
                    "[pipeline] 步骤 %s 返回失败状态: %s", step_name, status,
                )

            extras = success_extras or {}
            merged_extras = {
                k: v for k, v in result.items()
                if k not in ("status", "duration_sec", "error")
            }
            merged_extras.update(extras)
            await self._log_step_complete(
                step_name, status, duration, **merged_extras,
            )
            return result
        except Exception as e:
            logger.error(
                "[pipeline] 步骤 %s 异常: %s", step_name, e, exc_info=True,
            )
            await self._log_step_error(step_name, e)
            await self.db.rollback()
            err_result: Dict[str, Any] = {
                "status": PipelineStepStatus.FAILED,
                "error": str(e),
                "duration_sec": 0,
            }
            await self._log_step_complete(
                step_name, StepStatus.FAILED, 0, error=str(e),
            )
            return err_result

    # ---------- 主入口 ----------

    async def run(
        self,
        project_id: UUID,
        dataset_id: Optional[UUID] = None,
        tier: str = "fast_screen",
        max_targets: int = 5,
        molecules_per_target: int = 15,
        molecule_strategy: str = "fragment",
        skip_existing: bool = True,
        current_user: Any = None,
        enable_hypothesis: bool = True,
        hypothesis_config: Optional[Dict[str, Any]] = None,
        custom_steps: Optional[List[Dict[str, Any]]] = None,
        resume_from_step: Optional[str] = None,
        skip_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        pipeline_start = time.time()

        project = await self.db.get(Project, project_id)
        if not project:
            logger.warning("[pipeline] 项目 %s 不存在", project_id)
            return {
                "project_id": str(project_id),
                "duration_sec": 0,
                "error": "项目不存在",
                "steps": {},
                "summary": {"total_targets": 0, "total_molecules": 0, "total_treatments": 0},
            }

        triggered_by = current_user.id if current_user else None
        pipeline_run = await self._create_pipeline_run(
            project_id=project_id,
            tier=tier,
            max_targets=max_targets,
            molecules_per_target=molecules_per_target,
            molecule_strategy=molecule_strategy,
            skip_existing=skip_existing,
            enable_hypothesis=enable_hypothesis,
            triggered_by=triggered_by,
        )

        # 自动断点续传：仅当 PipelineRun 处于失败/暂停状态时才自动恢复
        if not resume_from_step and pipeline_run.status in (PipelineRunStatus.FAILED, PipelineRunStatus.PAUSED):
            resume_point = pipeline_run.get_resume_point()
            if resume_point:
                resume_from_step = resume_point
                logger.info("[pipeline] 自动断点续传: 从步骤 %s 恢复", resume_from_step)
                pipeline_run.add_log(
                    "info", resume_from_step,
                    f"自动断点续传：从步骤 {resume_from_step} 恢复执行",
                )
                await self.db.commit()

        await self._mark_running()

        skip_steps_set = set(skip_steps or [])

        def should_run(step_name: str) -> bool:
            if step_name in skip_steps_set:
                return False
            if resume_from_step:
                resume_idx = STEP_ORDER.index(resume_from_step) if resume_from_step in STEP_ORDER else 0
                step_idx = STEP_ORDER.index(step_name) if step_name in STEP_ORDER else 0
                return step_idx >= resume_idx
            return True

        def skipped_result(reason: str = "被 resume_from_step/skip_steps 跳过") -> Dict[str, Any]:
            return {
                "status": PipelineStepStatus.SKIPPED,
                "reason": reason,
                "duration_sec": 0,
            }

        steps_result: Dict[str, Any] = {}
        targets: List[Target] = []
        molecules: List[Molecule] = []

        # ========== Step 1: 靶点发现 ==========
        step1_name = "target_discovery"
        if not should_run(step1_name):
            steps_result[step1_name] = skipped_result()
            pipeline_run.update_step_status(step1_name, StepStatus.SKIPPED, reason="resume/skip")
            pipeline_run.add_log("info", step1_name, "步骤跳过（resume/skip）")
            await self.db.commit()
            target_stmt = (
                select(Target)
                .where(Target.project_id == project_id)
                .order_by(Target.confidence_score.desc().nullslast())
                .limit(max_targets)
            )
            target_result = await self.db.execute(target_stmt)
            targets = list(target_result.scalars().all())
        else:
            step1 = await self._execute_step(
                step1_name,
                lambda: self._step1_discover_targets(
                    project_id=project_id,
                    dataset_id=dataset_id,
                    tier=tier,
                ),
            )
            steps_result[step1_name] = step1
            if step1.get("status") != StepStatus.FAILED:
                target_stmt = (
                    select(Target)
                    .where(Target.project_id == project_id)
                    .order_by(Target.confidence_score.desc().nullslast())
                    .limit(max_targets)
                )
                target_result = await self.db.execute(target_stmt)
                targets = list(target_result.scalars().all())

        # ========== Step 2: 分子生成+评估 ==========
        step2_name = "molecule_generation"
        if not should_run(step2_name):
            steps_result[step2_name] = skipped_result()
            pipeline_run.update_step_status(step2_name, StepStatus.SKIPPED, reason="resume/skip")
            pipeline_run.add_log("info", step2_name, "步骤跳过（resume/skip）")
            await self.db.commit()
            if targets:
                target_ids = [t.id for t in targets]
                mol_stmt = select(Molecule).where(Molecule.target_id.in_(target_ids))
                mol_result = await self.db.execute(mol_stmt)
                molecules = list(mol_result.scalars().all())
        elif targets:
            step2 = await self._execute_step(
                step2_name,
                lambda: self._step2_generate_molecules(
                    targets=targets,
                    molecules_per_target=molecules_per_target,
                    molecule_strategy=molecule_strategy,
                    skip_existing=skip_existing,
                ),
            )
            steps_result[step2_name] = step2
            if step2.get("status") != StepStatus.FAILED:
                target_ids = [t.id for t in targets]
                mol_stmt = select(Molecule).where(Molecule.target_id.in_(target_ids))
                mol_result = await self.db.execute(mol_stmt)
                molecules = list(mol_result.scalars().all())
        else:
            steps_result[step2_name] = {
                "status": PipelineStepStatus.SKIPPED,
                "reason": "无可用靶点，跳过分子生成",
                "duration_sec": 0,
                "molecules_saved": 0,
            }
            pipeline_run.update_step_status(step2_name, StepStatus.SKIPPED, reason="no_targets")
            await self.db.commit()

        # ========== Step 3: 治疗方案匹配 ==========
        step3_name = "treatment_matching"
        if not should_run(step3_name):
            steps_result[step3_name] = skipped_result()
            pipeline_run.update_step_status(step3_name, StepStatus.SKIPPED, reason="resume/skip")
            await self.db.commit()
        else:
            step3 = await self._execute_step(
                step3_name,
                lambda: self._step3_match_treatments(
                    project_id=project_id,
                    targets=targets,
                    molecules=molecules,
                    skip_existing=skip_existing,
                ),
            )
            steps_result[step3_name] = step3

        # ========== Step 4: 假设生成（可选，默认启用） ==========
        step4_name = "hypothesis_generation"
        if enable_hypothesis and should_run(step4_name):
            step4 = await self._execute_step(
                step4_name,
                lambda: self._step4_generate_hypotheses(
                    project_id=project_id,
                    targets=targets,
                    molecules=molecules,
                    hypothesis_config=hypothesis_config or {},
                ),
            )
            steps_result[step4_name] = step4
        elif enable_hypothesis:
            steps_result[step4_name] = skipped_result()
            pipeline_run.update_step_status(step4_name, StepStatus.SKIPPED, reason="resume/skip")
            await self.db.commit()

        # ========== Step 5: 自定义步骤（可选） ==========
        if custom_steps:
            custom_result = await self._execute_step(
                "custom_steps",
                lambda: self._run_custom_steps(
                    project_id=project_id,
                    custom_steps=custom_steps,
                    context={
                        "targets": targets,
                        "molecules": molecules,
                        "steps_result": steps_result,
                    },
                ),
            )
            steps_result["custom_steps"] = custom_result

        # ========== 完成 ==========
        duration = round(time.time() - pipeline_start, 3)
        skipped_list = [
            s for s in steps_result
            if isinstance(steps_result.get(s), dict)
            and steps_result[s].get("status") == PipelineStepStatus.SKIPPED
        ]

        summary = {
            "total_targets": len(targets),
            "total_molecules": len(molecules),
            "total_treatments": steps_result.get("treatment_matching", {}).get("treatments_created", 0),
            "total_hypotheses": steps_result.get("hypothesis_generation", {}).get("hypotheses_generated", 0),
            "custom_steps_executed": len(custom_steps) if custom_steps else 0,
            "skipped_steps": skipped_list,
            "resumed_from": resume_from_step,
        }

        await self._mark_completed(duration, summary)

        logger.info(
            "[pipeline] 项目 %s 流水线完成: %d 靶点 / %d 分子 / %d 治疗方案 / %.1fs",
            project_id, len(targets), len(molecules),
            summary["total_treatments"], duration,
        )

        return {
            "project_id": str(project_id),
            "duration_sec": duration,
            "pipeline_run_id": str(pipeline_run.id),
            "steps": steps_result,
            "summary": summary,
        }

    # ---------- 业务步骤实现（保持原有逻辑） ----------

    async def _step1_discover_targets(
        self,
        project_id: UUID,
        dataset_id: Optional[UUID],
        tier: str,
    ) -> Dict[str, Any]:
        from app.services.analyzer.target_identifier import TargetIdentifier

        start = time.time()
        identifier = TargetIdentifier(self.db)
        result = await identifier.discover(
            project_id=project_id,
            dataset_id=dataset_id,
            tier=tier,
        )

        duration = round(time.time() - start, 3)
        return {
            "status": PipelineStepStatus.SUCCESS,
            "targets_found": result.get("count", 0),
            "tier": tier,
            "duration_sec": duration,
            "error": None,
        }

    async def _step2_generate_molecules(
        self,
        targets: List[Target],
        molecules_per_target: int,
        molecule_strategy: str,
        skip_existing: bool,
    ) -> Dict[str, Any]:
        from app.services.analyzer.molecule_designer import (
            MoleculeDesigner,
            assess_druglikeness,
            predict_admet,
            explain_molecule,
        )

        start = time.time()
        designer = MoleculeDesigner(self.db)

        targets_processed = 0
        total_generated = 0
        total_saved = 0
        errors: List[str] = []

        for target in targets:
            targets_processed += 1

            if skip_existing:
                existing_mol_stmt = (
                    select(Molecule)
                    .where(Molecule.target_id == target.id)
                    .limit(1)
                )
                existing_mol = await self.db.execute(existing_mol_stmt)
                if existing_mol.scalar_one_or_none():
                    continue

            try:
                gen_result = await designer.generate_molecules(
                    target_id=str(target.id),
                    strategy=molecule_strategy,
                    n=molecules_per_target,
                    seed_smiles=None,
                    constraints={},
                )

                if gen_result.get("error"):
                    errors.append(f"靶点 {target.gene_symbol}: {gen_result['error']}")
                    continue

                molecules_data = gen_result.get("molecules", [])
                scored_candidates: List[tuple] = []

                for mol in molecules_data:
                    smiles = mol.get("smiles", "")
                    if not smiles:
                        continue

                    props = assess_druglikeness(smiles)
                    if props.get("error"):
                        continue

                    score = props.get("druglikeness_score", 0)
                    passes_ro5 = props.get("passes_rule_of_five", False)

                    admet = predict_admet(smiles)
                    explanation = explain_molecule(smiles)

                    if passes_ro5 and score >= 60:
                        scored_candidates.append(
                            (score, mol, props, {"admet": admet, "explain": explanation})
                        )

                if not scored_candidates:
                    for mol in molecules_data:
                        smiles = mol.get("smiles", "")
                        if not smiles:
                            continue
                        props = assess_druglikeness(smiles)
                        if props.get("error"):
                            continue
                        score = props.get("druglikeness_score", 0)
                        admet = predict_admet(smiles)
                        explanation = explain_molecule(smiles)
                        scored_candidates.append(
                            (score, mol, props, {"admet": admet, "explain": explanation})
                        )

                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                top_candidates = scored_candidates[:10]

                for score, mol, props, extra in top_candidates:
                    smiles = mol.get("smiles", "")

                    dup_stmt = (
                        select(Molecule)
                        .where(Molecule.target_id == target.id)
                        .where(Molecule.smiles == smiles)
                    )
                    dup_result = await self.db.execute(dup_stmt)
                    if dup_result.scalar_one_or_none():
                        continue

                    new_mol = Molecule(
                        target_id=target.id,
                        smiles=smiles,
                        name=mol.get("name"),
                        molecular_weight=props.get("mw"),
                        logp=props.get("logp"),
                        properties={
                            **props,
                            **extra,
                            "source": mol.get("source", "pipeline_fragment"),
                            "strategy": molecule_strategy,
                            "druglikeness_score": score,
                        },
                        designed_by="pipeline",
                        source=mol.get("source", "pipeline_fragment"),
                    )
                    self.db.add(new_mol)
                    total_saved += 1

                total_generated += len(molecules_data)

            except Exception as e:
                error_msg = f"靶点 {target.gene_symbol} 分子生成失败: {e}"
                logger.warning(error_msg)
                errors.append(error_msg)

        if total_saved > 0:
            await self.db.flush()

        duration = round(time.time() - start, 3)
        status = PipelineStepStatus.SUCCESS
        if total_saved == 0 and errors:
            status = PipelineStepStatus.FAILED
        elif errors:
            status = PipelineStepStatus.PARTIAL

        return {
            "status": status,
            "targets_processed": targets_processed,
            "molecules_generated": total_generated,
            "molecules_saved": total_saved,
            "errors": errors,
            "duration_sec": duration,
        }

    async def _step3_match_treatments(
        self,
        project_id: UUID,
        targets: List[Target],
        molecules: List[Molecule],
        skip_existing: bool,
    ) -> Dict[str, Any]:
        from app.services.optimizer.treatment_planner import TreatmentPlanner

        start = time.time()
        treatments_created = 0
        errors: List[str] = []

        for target in targets:
            try:
                gene = target.gene_symbol or "未知"

                if skip_existing:
                    existing_stmt = (
                        select(Treatment)
                        .where(Treatment.project_id == project_id)
                        .where(Treatment.name.like(f"{gene}%"))
                        .limit(1)
                    )
                    existing = await self.db.execute(existing_stmt)
                    if existing.scalar_one_or_none():
                        continue

                target_mols = [m for m in molecules if m.target_id == target.id]
                mol_ids = [str(m.id) for m in target_mols] if target_mols else None

                approved_drugs = target.approved_drugs or []
                has_approved = len(approved_drugs) > 0

                if has_approved:
                    therapy_name = f"{gene} 靶向治疗（获批药物）"
                    therapy_type = TreatmentType.TARGETED
                    config = {
                        "strategy": "approved_targeted",
                        "drugs": approved_drugs,
                        "mechanism": f"靶向 {gene} 通路",
                    }
                elif target_mols:
                    therapy_name = f"{gene} 候选分子治疗"
                    therapy_type = TreatmentType.TARGETED
                    config = {
                        "strategy": "candidate_molecule",
                        "molecules": [
                            {"smiles": m.smiles, "name": m.name}
                            for m in target_mols[:3]
                        ],
                        "mechanism": f"靶向 {gene} 通路（实验性分子）",
                    }
                else:
                    therapy_name = f"{gene} 探索性治疗"
                    therapy_type = TreatmentType.TARGETED
                    config = {
                        "strategy": "exploratory",
                        "mechanism": f"靶向 {gene} 通路（待验证）",
                    }

                confidence = target.confidence_score or 0.5
                efficacy_score = min(0.95, confidence + (0.1 if has_approved else 0))
                risk_score = max(0.05, 1.0 - confidence - (0.1 if has_approved else 0))

                treatment = Treatment(
                    project_id=project_id,
                    name=therapy_name,
                    therapy_type=therapy_type,
                    status=TreatmentStatus.PROPOSED,
                    target_ids=[str(target.id)],
                    molecule_ids=mol_ids,
                    config=config,
                    efficacy_score=efficacy_score,
                    risk_score=risk_score,
                )
                self.db.add(treatment)
                treatments_created += 1
            except Exception as e:
                errors.append(f"靶点 {target.gene_symbol} 治疗方案生成失败: {e}")
                logger.warning(f"治疗方案生成失败: {e}")

        try:
            planner = TreatmentPlanner(self.db)
            optimize_result = await planner.optimize(project_id)
            if optimize_result.get("optimal"):
                treatments_created += 1
        except Exception as e:
            errors.append(f"组合优化失败: {e}")
            logger.warning(f"组合优化失败: {e}")

        if treatments_created > 0:
            await self.db.flush()

        duration = round(time.time() - start, 3)
        status = PipelineStepStatus.SUCCESS
        if treatments_created == 0 and errors:
            status = PipelineStepStatus.FAILED
        elif errors:
            status = PipelineStepStatus.PARTIAL

        return {
            "status": status,
            "treatments_created": treatments_created,
            "errors": errors,
            "duration_sec": duration,
        }

    async def _step4_generate_hypotheses(
        self,
        project_id: UUID,
        targets: List[Target],
        molecules: List[Molecule],
        hypothesis_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        from app.services.knowledge.hypothesis_generator import HypothesisGenerator

        start = time.time()
        generator = HypothesisGenerator(self.db)

        use_llm = hypothesis_config.get("use_llm", True)
        mode = hypothesis_config.get("mode", "hybrid")
        max_hypotheses = hypothesis_config.get("max_hypotheses", 5)

        context = hypothesis_config.get("context") or {}
        if targets and not context.get("de_genes"):
            context["de_genes"] = [
                {"gene": t.gene_symbol, "confidence": t.confidence_score}
                for t in targets[:10]
            ]
        if molecules and not context.get("molecules"):
            context["molecules"] = [
                {
                    "smiles": m.smiles,
                    "composite_score": (m.properties or {}).get("druglikeness_score", 0),
                    "properties": m.properties or {},
                }
                for m in molecules[:20]
            ]

        llm_client = None
        if use_llm:
            try:
                from app.core.deps import get_llm_client_with_config
                llm_client = await get_llm_client_with_config(self.db)
            except Exception as e:
                logger.warning(f"假设生成 LLM 客户端获取失败，降级规则模式: {e}")

        hypotheses = await generator.generate(
            project_id=str(project_id),
            context=context,
            max_hypotheses=max_hypotheses,
            use_llm=use_llm,
            llm_client=llm_client,
            mode=mode,
        )

        duration = round(time.time() - start, 3)

        saved_count = 0
        try:
            from app.models.hypothesis import Hypothesis, HypothesisStatus
            for h in hypotheses:
                hyp = Hypothesis(
                    project_id=project_id,
                    name=h.get("title", "自动生成假设"),
                    description=h.get("description", ""),
                    mechanism=h.get("category", ""),
                    strategy=h.get("source", "pipeline"),
                    analysis_config={
                        "supporting_evidence": h.get("supporting_evidence", []),
                        "verification_method": h.get("verification_method", ""),
                        "confidence": h.get("confidence", 0.5),
                        "mode": mode,
                        "use_llm": use_llm,
                    },
                    status=HypothesisStatus.PENDING,
                )
                self.db.add(hyp)
                saved_count += 1
            if saved_count > 0:
                await self.db.flush()
        except Exception as e:
            logger.warning(f"假设持久化失败（可忽略，仅返回结果）: {e}")

        return {
            "status": PipelineStepStatus.SUCCESS,
            "hypotheses_generated": len(hypotheses),
            "hypotheses_saved": saved_count,
            "mode": mode,
            "use_llm": use_llm,
            "hypotheses": hypotheses,
            "duration_sec": duration,
        }

    async def _run_custom_steps(
        self,
        project_id: UUID,
        custom_steps: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        executed = []
        failed = []

        for step in custom_steps:
            step_name = step.get("name", f"custom_{step.get('type', 'unknown')}")
            step_type = step.get("type", "custom")
            step_config = step.get("config", {})

            try:
                result = await self._execute_custom_step(
                    step_type=step_type,
                    step_config=step_config,
                    project_id=project_id,
                    context=context,
                )
                executed.append({
                    "name": step_name,
                    "type": step_type,
                    "status": "success",
                    "result": result,
                })
            except Exception as e:
                logger.error(f"自定义步骤 {step_name} 执行失败: {e}", exc_info=True)
                failed.append({
                    "name": step_name,
                    "type": step_type,
                    "status": "failed",
                    "error": str(e),
                })

        return {
            "status": PipelineStepStatus.SUCCESS if not failed else PipelineStepStatus.PARTIAL,
            "executed": executed,
            "failed": failed,
            "total": len(custom_steps),
            "success_count": len(executed),
            "failed_count": len(failed),
            "duration_sec": 0,
        }

    async def _execute_custom_step(
        self,
        step_type: str,
        step_config: Dict[str, Any],
        project_id: UUID,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        molecules = context.get("molecules", [])
        targets = context.get("targets", [])

        if step_type == "assess":
            from app.services.analyzer.molecule_designer import assess_druglikeness
            results = []
            for m in molecules[:step_config.get("limit", 50)]:
                smiles = m.smiles if hasattr(m, "smiles") else m.get("smiles", "")
                if smiles:
                    results.append({"smiles": smiles, "assessment": assess_druglikeness(smiles)})
            return {"assessed": len(results), "results": results}

        elif step_type == "dock":
            return {
                "status": "skipped",
                "reason": "对接步骤需要 DiffDock 客户端配置",
                "molecules_count": len(molecules),
            }

        elif step_type == "analyze":
            return {
                "status": "skipped",
                "reason": "分析步骤需要数据集配置",
                "targets_count": len(targets),
            }

        elif step_type == "feedback":
            return {
                "status": "skipped",
                "reason": "反馈步骤需要临床数据配置",
            }

        elif step_type == "custom":
            callback_module = step_config.get("callback_module")
            callback_function = step_config.get("callback_function", "execute")
            if not callback_module:
                return {"status": "skipped", "reason": "未提供 callback_module"}

            import importlib
            try:
                mod = importlib.import_module(callback_module)
                func = getattr(mod, callback_function)
                result = await func(
                    project_id=project_id,
                    context=context,
                    config=step_config,
                    db=self.db,
                )
                return {"status": "success", "result": result}
            except (ImportError, AttributeError) as e:
                return {"status": "failed", "reason": f"回调加载失败: {e}"}

        else:
            return {"status": "skipped", "reason": f"未知步骤类型: {step_type}"}
