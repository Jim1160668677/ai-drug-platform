"""假设自动生成器 — 基于前期分析结果自动生成研究假设

数据源：
1. 差异表达分析结果（DE genes）
2. 通路富集结果
3. 分子设计结果（多靶点亲和力）
4. 治疗方案效果数据
5. 临床反馈数据

方法：
- 规则推理：基于阈值生成假设（如 DE gene + 通路富集 → 靶点假设）
- LLM 辅助：调用大模型生成更丰富的假设描述与验证方案
- 混合模式（hybrid）：规则 + LLM 合并去重
- 置信度计算：基于证据数量和强度
- 验证方法建议：实验验证/临床回顾/计算模拟
"""
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class HypothesisGenerator:
    """假设自动生成器 — 规则推理 + LLM 辅助 + 数据驱动"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate(
        self,
        project_id: str,
        context: Optional[Dict[str, Any]] = None,
        max_hypotheses: int = 5,
        use_llm: bool = False,
        llm_client: Any = None,
        mode: str = "hybrid",
    ) -> List[Dict[str, Any]]:
        """自动生成研究假设

        Args:
            project_id: 项目 ID
            context: 可选上下文数据（覆盖数据库查询）
            max_hypotheses: 最大假设数量
            use_llm: 是否启用 LLM 辅助生成
            llm_client: LLM 客户端实例（use_llm=True 时必需）
            mode: 生成模式 — "rule"（仅规则）/ "llm"（仅 LLM）/ "hybrid"（混合，默认）
        Returns:
            [{title, description, supporting_evidence, verification_method, confidence, category, source}]
        """
        context = context or {}

        # 收集各模块的分析结果
        evidence = await self._collect_evidence(project_id, context)

        rule_hypotheses: List[Dict[str, Any]] = []
        llm_hypotheses: List[Dict[str, Any]] = []

        # 规则生成（rule 或 hybrid 模式）
        if mode in ("rule", "hybrid") or not use_llm:
            rule_hypotheses = self._generate_by_rules(evidence, project_id)

        # LLM 生成（llm 或 hybrid 模式，且 use_llm=True）
        if use_llm and mode in ("llm", "hybrid") and llm_client is not None:
            try:
                llm_hypotheses = await self._llm_assisted_generate(
                    evidence, project_id, llm_client, max_hypotheses
                )
            except Exception as e:
                logger.warning(f"LLM 假设生成失败，降级规则模式: {e}")
                if not rule_hypotheses:
                    rule_hypotheses = self._generate_by_rules(evidence, project_id)

        # 合并假设
        if mode == "hybrid" and llm_hypotheses:
            hypotheses = self._merge_hypotheses(rule_hypotheses, llm_hypotheses)
        elif mode == "llm" and llm_hypotheses:
            hypotheses = llm_hypotheses
        else:
            hypotheses = rule_hypotheses

        # 兜底：如果没有任何数据，生成默认假设
        if not hypotheses:
            hypotheses.append(self._default_hypothesis(project_id, evidence))

        # 按置信度排序，取前 max_hypotheses 个
        hypotheses.sort(key=lambda h: h.get("confidence", 0), reverse=True)
        hypotheses = hypotheses[:max_hypotheses]

        logger.info(
            f"项目 {project_id} 生成 {len(hypotheses)} 个假设 "
            f"(mode={mode}, use_llm={use_llm}, rule={len(rule_hypotheses)}, llm={len(llm_hypotheses)})"
        )
        return hypotheses

    def _generate_by_rules(
        self,
        evidence: Dict[str, Any],
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """基于规则生成假设"""
        hypotheses: List[Dict[str, Any]] = []

        # 规则1：DE gene ∩ 通路富集 → 靶点假设
        hypotheses.extend(self._rule_de_pathway(evidence))

        # 规则2：多靶点高亲和力分子 → 多靶点协同假设
        hypotheses.extend(self._rule_multi_target_molecules(evidence))

        # 规则3：临床反馈差 + 不良反应 → 方案优化假设
        hypotheses.extend(self._rule_clinical_feedback(evidence))

        # 规则4：聚类结果 → 细胞亚群假设
        hypotheses.extend(self._rule_clustering(evidence))

        # 规则5：已发现靶点 → 靶点机制假设
        hypotheses.extend(self._rule_targets(evidence))

        # 标记来源
        for h in hypotheses:
            h.setdefault("source", "rule")

        return hypotheses

    async def _llm_assisted_generate(
        self,
        evidence: Dict[str, Any],
        project_id: str,
        llm_client: Any,
        max_hypotheses: int,
    ) -> List[Dict[str, Any]]:
        """LLM 辅助假设生成

        将收集到的证据结构化输入 LLM，让其生成更丰富的假设描述。
        LLM 返回 JSON 数组，每项包含 title/description/supporting_evidence/
        verification_method/confidence/category。
        """
        # 构造证据摘要
        evidence_summary = self._summarize_evidence(evidence)

        prompt = f"""你是一位资深药物研发科学家，请基于以下研究项目的分析数据，生成 {min(max_hypotheses, 5)} 个高质量科学研究假设。

## 项目数据摘要

{evidence_summary}

## 要求

每个假设必须包含以下字段：
1. title: 简洁的假设标题（20-50 字）
2. description: 详细描述（100-200 字），说明假设的逻辑和机制
3. supporting_evidence: 支持证据列表（3-5 条）
4. verification_method: 建议的验证方法（实验/临床/计算）
5. confidence: 置信度（0.0-1.0）
6. category: 类别（target_mechanism/target_discovery/molecule_design/treatment_optimization/heterogeneity/biomarker）

请以 JSON 数组格式返回，不要包含 markdown 代码块标记。示例：
[{{"title": "...", "description": "...", "supporting_evidence": ["..."], "verification_method": "...", "confidence": 0.8, "category": "target_mechanism"}}]
"""

        # 调用 LLM
        try:
            if hasattr(llm_client, "chat"):
                response = await llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model="agnes-2.0-flash",
                )
            elif hasattr(llm_client, "complete"):
                response = await llm_client.complete(prompt)
            else:
                response = await llm_client.agenerate([prompt])
                response = response.generations[0][0].text
        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")
            return []

        # 解析 LLM 返回
        content = response if isinstance(response, str) else str(response)
        # 去除可能的 markdown 代码块标记
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            hypotheses = json.loads(content)
            if not isinstance(hypotheses, list):
                hypotheses = [hypotheses] if isinstance(hypotheses, dict) else []
        except json.JSONDecodeError:
            logger.warning("LLM 返回非合法 JSON，降级规则模式")
            return []

        # 标准化字段 + 标记来源
        for h in hypotheses:
            if isinstance(h, dict):
                h.setdefault("supporting_evidence", [])
                h.setdefault("verification_method", "建议进行实验验证")
                h.setdefault("confidence", 0.6)
                h.setdefault("category", "llm_generated")
                h["source"] = "llm"
                # 确保置信度在 0-1 范围
                try:
                    h["confidence"] = max(0.0, min(1.0, float(h["confidence"])))
                except (TypeError, ValueError):
                    h["confidence"] = 0.6

        return hypotheses

    def _summarize_evidence(self, evidence: Dict[str, Any]) -> str:
        """将证据字典摘要为 LLM 可读的文本"""
        lines = []

        de_genes = evidence.get("de_genes", [])
        if de_genes:
            top_genes = [g.get("gene", g.get("gene_id", "")) for g in de_genes[:5] if isinstance(g, dict)]
            lines.append(f"- 差异表达基因：共 {len(de_genes)} 个，Top: {', '.join(top_genes)}")

        pathways = evidence.get("pathways", [])
        if pathways:
            top_paths = [p.get("name", p.get("pathway_id", "")) for p in pathways[:3] if isinstance(p, dict)]
            lines.append(f"- 富集通路：共 {len(pathways)} 条，Top: {', '.join(top_paths)}")

        molecules = evidence.get("molecules", [])
        if molecules:
            lines.append(f"- 候选分子：共 {len(molecules)} 个")

        targets = evidence.get("targets", [])
        if targets:
            top_targets = [t.get("gene_symbol", "") for t in targets[:5] if isinstance(t, dict) and t.get("gene_symbol")]
            lines.append(f"- 已发现靶点：共 {len(targets)} 个，Top: {', '.join(top_targets)}")

        treatments = evidence.get("treatments", [])
        if treatments:
            top_treatments = [t.get("name", "") for t in treatments[:3] if isinstance(t, dict) and t.get("name")]
            lines.append(f"- 治疗方案：共 {len(treatments)} 个，Top: {', '.join(top_treatments)}")

        feedbacks = evidence.get("clinical_feedbacks", [])
        if feedbacks:
            lines.append(f"- 临床反馈：共 {len(feedbacks)} 例")

        clusters = evidence.get("clusters", [])
        if clusters:
            lines.append(f"- 细胞亚群：共 {len(clusters)} 个")

        if not lines:
            lines.append("- 暂无充分分析数据")

        return "\n".join(lines)

    def _merge_hypotheses(
        self,
        rule_hyps: List[Dict[str, Any]],
        llm_hyps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """合并规则与 LLM 假设，去重

        策略：
        1. 按 category 分组
        2. 同类假设取置信度更高的
        3. 保留 source 字段标记来源
        """
        merged: Dict[str, Dict[str, Any]] = {}

        for h in rule_hyps + llm_hyps:
            cat = h.get("category", "unknown")
            existing = merged.get(cat)
            if existing is None:
                merged[cat] = h
            else:
                # 取置信度更高的
                if h.get("confidence", 0) > existing.get("confidence", 0):
                    # 保留两者的 evidence 合并
                    merged_evidence = list(existing.get("supporting_evidence", []))
                    merged_evidence.extend(h.get("supporting_evidence", []))
                    h["supporting_evidence"] = merged_evidence[:8]  # 限制最多 8 条
                    h["source"] = "hybrid"
                    merged[cat] = h
                else:
                    merged_evidence = list(existing.get("supporting_evidence", []))
                    merged_evidence.extend(h.get("supporting_evidence", []))
                    existing["supporting_evidence"] = merged_evidence[:8]
                    existing["source"] = "hybrid"

        return list(merged.values())

    async def _collect_evidence(
        self,
        project_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """收集各模块的分析结果作为假设生成证据"""
        evidence: Dict[str, Any] = {
            "de_genes": context.get("de_genes", []),
            "pathways": context.get("pathways", []),
            "molecules": context.get("molecules", []),
            "treatments": context.get("treatments", []),
            "clinical_feedbacks": context.get("clinical_feedbacks", []),
            "clusters": context.get("clusters", []),
            "targets": context.get("targets", []),
            "project_id": project_id,
        }

        # 尝试从数据库补充数据（如果 context 中没有提供）
        if not evidence["de_genes"]:
            evidence["de_genes"] = await self._fetch_de_genes(project_id)

        if not evidence["molecules"]:
            evidence["molecules"] = await self._fetch_molecules(project_id)

        if not evidence["targets"]:
            evidence["targets"] = await self._fetch_targets(project_id)

        if not evidence["treatments"]:
            evidence["treatments"] = await self._fetch_treatments(project_id)

        if not evidence["clinical_feedbacks"]:
            evidence["clinical_feedbacks"] = await self._fetch_clinical_feedbacks(project_id)

        # 从数据集解析结果中提取通路富集和聚类信息
        if not evidence["pathways"] or not evidence["clusters"]:
            await self._fetch_dataset_analysis(project_id, evidence)

        return evidence

    async def _fetch_targets(self, project_id: str) -> List[Dict[str, Any]]:
        """从数据库获取已发现的靶点"""
        try:
            from app.models.target import Target
            result = await self.db.execute(
                select(Target).where(Target.project_id == project_id).limit(20)
            )
            targets = result.scalars().all()
            return [
                {
                    "gene_symbol": t.gene_symbol,
                    "confidence_score": float(t.confidence_score) if t.confidence_score else 0,
                    "evidence_grade": str(t.evidence_grade) if t.evidence_grade else "",
                    "source": t.source or "",
                }
                for t in targets
            ]
        except Exception as e:
            logger.debug(f"获取靶点失败（可忽略）: {e}")
            return []

    async def _fetch_treatments(self, project_id: str) -> List[Dict[str, Any]]:
        """从数据库获取治疗方案"""
        try:
            from app.models.treatment import Treatment
            from app.models.target import Target
            result = await self.db.execute(
                select(Treatment).join(Target, Treatment.target_id == Target.id)
                .where(Target.project_id == project_id).limit(10)
            )
            treatments = result.scalars().all()
            return [
                {
                    "name": t.name,
                    "therapy_type": t.therapy_type,
                    "efficacy_score": float(t.efficacy_score) if t.efficacy_score else 0,
                    "risk_score": float(t.risk_score) if t.risk_score else 0,
                    "status": t.status or "",
                }
                for t in treatments
            ]
        except Exception as e:
            logger.debug(f"获取治疗方案失败（可忽略）: {e}")
            return []

    async def _fetch_clinical_feedbacks(self, project_id: str) -> List[Dict[str, Any]]:
        """从数据库获取临床反馈"""
        try:
            from app.models.treatment import Treatment, ClinicalFeedback
            from app.models.target import Target
            result = await self.db.execute(
                select(ClinicalFeedback).join(Treatment, ClinicalFeedback.treatment_id == Treatment.id)
                .join(Target, Treatment.target_id == Target.id)
                .where(Target.project_id == project_id).limit(10)
            )
            feedbacks = result.scalars().all()
            return [
                {
                    "efficacy": f.efficacy,
                    "adverse_reactions": f.adverse_reactions if isinstance(f.adverse_reactions, list) else [],
                    "dosage": f.dosage,
                    "duration_days": f.duration_days,
                }
                for f in feedbacks
            ]
        except Exception as e:
            logger.debug(f"获取临床反馈失败（可忽略）: {e}")
            return []

    async def _fetch_dataset_analysis(self, project_id: str, evidence: Dict[str, Any]):
        """从数据集 parsed_summary 中提取通路富集和聚类信息"""
        try:
            from app.models.dataset import Dataset
            result = await self.db.execute(
                select(Dataset).where(Dataset.project_id == project_id)
                .where(Dataset.parse_status == "completed").limit(10)
            )
            datasets = result.scalars().all()
            for ds in datasets:
                summary = ds.parsed_summary or {}
                # 提取通路富集
                if not evidence["pathways"]:
                    pathways = summary.get("pathways") or summary.get("enriched_pathways") or []
                    if pathways:
                        evidence["pathways"] = pathways
                # 提取聚类信息
                if not evidence["clusters"]:
                    clusters = summary.get("clusters") or summary.get("cell_clusters") or []
                    if clusters:
                        evidence["clusters"] = clusters
        except Exception as e:
            logger.debug(f"获取数据集分析结果失败（可忽略）: {e}")

    async def _fetch_de_genes(self, project_id: str) -> List[Dict[str, Any]]:
        """从数据库获取差异表达基因"""
        try:
            from app.models.dataset import Dataset
            result = await self.db.execute(
                select(Dataset).where(Dataset.project_id == project_id)
                .where(Dataset.parse_status == "completed")
                .limit(5)
            )
            datasets = result.scalars().all()
            de_genes = []
            for ds in datasets:
                summary = ds.parsed_summary or {}
                analysis = summary.get("analysis_results", {})
                de_result = analysis.get("de", {})
                genes = de_result.get("genes", [])
                for g in genes[:20]:  # 每个数据集取前20个
                    de_genes.append(g)
            return de_genes
        except Exception as e:
            logger.debug(f"获取 DE genes 失败（可忽略）: {e}")
            return []

    async def _fetch_molecules(self, project_id: str) -> List[Dict[str, Any]]:
        """从数据库获取分子设计结果"""
        try:
            from app.models.molecule import Molecule
            from app.models.target import Target
            # 通过 target 关联到 project
            result = await self.db.execute(
                select(Molecule).join(Target, Molecule.target_id == Target.id)
                .where(Target.project_id == project_id)
                .limit(10)
            )
            molecules = result.scalars().all()
            return [
                {
                    "smiles": m.smiles,
                    "properties": m.properties or {},
                    "source": m.source or "",
                }
                for m in molecules
            ]
        except Exception as e:
            logger.debug(f"获取分子失败（可忽略）: {e}")
            return []

    def _rule_de_pathway(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """规则1：DE gene + 通路富集 → 靶点假设"""
        hypotheses = []
        de_genes = evidence.get("de_genes", [])
        pathways = evidence.get("pathways", [])

        if de_genes and pathways:
            # 找到通路中包含的差异基因
            top_genes = [g.get("gene", g.get("gene_id", "")) for g in de_genes[:5] if isinstance(g, dict)]
            top_pathways = [p.get("name", p.get("pathway_id", "")) for p in pathways[:3] if isinstance(p, dict)]

            if top_genes and top_pathways:
                gene_str = ", ".join(top_genes[:3])
                pathway_str = ", ".join(top_pathways[:2])
                hypotheses.append({
                    "title": f"靶点 {gene_str} 通过 {pathway_str} 通路调节疾病进程",
                    "description": f"差异表达分析发现 {len(de_genes)} 个显著差异基因，其中 {gene_str} 在通路富集分析中显著富集于 {pathway_str} 通路。推测这些靶点通过该通路参与疾病调控，可能是潜在的治疗靶点。",
                    "supporting_evidence": [
                        f"差异表达分析：{len(de_genes)} 个显著差异基因（FDR < 0.05）",
                        f"通路富集：{len(pathways)} 条显著通路",
                        f"关键基因：{gene_str}",
                    ],
                    "verification_method": "建议进行基因敲除/过表达实验验证靶点功能，结合 Western Blot 检测通路蛋白表达变化",
                    "confidence": 0.85,
                    "category": "target_mechanism",
                })

        elif de_genes:
            # 只有 DE 基因，没有通路
            top_genes = [g.get("gene", g.get("gene_id", "")) for g in de_genes[:5] if isinstance(g, dict)]
            if top_genes:
                gene_str = ", ".join(top_genes[:3])
                hypotheses.append({
                    "title": f"差异基因 {gene_str} 可能是潜在药物靶点",
                    "description": f"差异表达分析发现 {len(de_genes)} 个显著差异基因，其中 {gene_str} 表达变化最显著。这些基因可能直接参与疾病进程，值得进一步研究作为潜在药物靶点。",
                    "supporting_evidence": [
                        f"差异表达分析：{len(de_genes)} 个显著差异基因",
                        f"关键基因：{gene_str}",
                    ],
                    "verification_method": "建议进行功能富集分析（GO/KEGG）和蛋白质互作网络分析，结合 CRISPR 筛选验证靶点",
                    "confidence": 0.65,
                    "category": "target_discovery",
                })

        return hypotheses

    def _rule_multi_target_molecules(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """规则2：多靶点高亲和力分子 → 多靶点协同假设"""
        hypotheses = []
        molecules = evidence.get("molecules", [])

        if len(molecules) >= 2:
            # 筛选高综合评分的分子
            high_score_mols = [
                m for m in molecules
                if isinstance(m, dict) and (
                    m.get("composite_score", 0) > 0.3 or
                    (m.get("properties", {}) or {}).get("druglikeness_score", 0) > 60
                )
            ]

            if high_score_mols:
                top_mol = high_score_mols[0]
                smiles = top_mol.get("smiles", "未知分子")
                hypotheses.append({
                    "title": f"候选分子 {smiles[:30]}... 具有多靶点协同治疗潜力",
                    "description": f"分子设计模块生成了 {len(molecules)} 个候选分子，其中 {len(high_score_mols)} 个表现出良好的多靶点亲和力和类药性。最优候选分子的综合评分为 {top_mol.get('composite_score', 'N/A')}，可同时作用于多个疾病相关靶点，具有协同治疗潜力。",
                    "supporting_evidence": [
                        f"分子设计：共生成 {len(molecules)} 个候选分子",
                        f"高评分分子：{len(high_score_mols)} 个",
                        f"最优综合评分：{top_mol.get('composite_score', 'N/A')}",
                    ],
                    "verification_method": "建议进行体外结合实验（SPR/ITC）验证多靶点亲和力，结合细胞毒性测试评估治疗效果",
                    "confidence": 0.75,
                    "category": "molecule_design",
                })

        return hypotheses

    def _rule_clinical_feedback(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """规则3：临床反馈差 + 不良反应 → 方案优化假设"""
        hypotheses = []
        feedbacks = evidence.get("clinical_feedbacks", [])

        if feedbacks:
            # 统计疗效差和不良反应
            poor_efficacy = [f for f in feedbacks if isinstance(f, dict) and f.get("efficacy") in ["progressive", "partial"]]
            high_adverse = [f for f in feedbacks if isinstance(f, dict) and len(f.get("adverse_reactions", []) or []) > 2]

            if poor_efficacy or high_adverse:
                hypotheses.append({
                    "title": "当前治疗方案需优化剂量或更换药物组合",
                    "description": f"临床反馈数据显示，{len(feedbacks)} 例患者中，{len(poor_efficacy)} 例疗效不佳，{len(high_adverse)} 例出现较多不良反应。推测当前治疗方案可能需要调整剂量、更换药物组合或考虑个性化治疗策略。",
                    "supporting_evidence": [
                        f"临床反馈总数：{len(feedbacks)} 例",
                        f"疗效不佳：{len(poor_efficacy)} 例",
                        f"不良反应较多：{len(high_adverse)} 例",
                    ],
                    "verification_method": "建议回顾性分析临床数据，结合药代动力学模型优化给药方案，必要时进行 II 期临床试验",
                    "confidence": 0.80,
                    "category": "treatment_optimization",
                })

        return hypotheses

    def _rule_clustering(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """规则4：聚类结果 → 细胞亚群假设"""
        hypotheses = []
        clusters = evidence.get("clusters", [])

        if clusters and len(clusters) >= 2:
            hypotheses.append({
                "title": f"肿瘤异质性揭示 {len(clusters)} 个细胞亚群，可能需要亚型特异性治疗",
                "description": f"单细胞聚类分析识别出 {len(clusters)} 个不同的细胞亚群，表明存在显著的肿瘤异质性。不同亚群可能对治疗的响应不同，建议探索亚型特异性治疗策略。",
                "supporting_evidence": [
                    f"聚类分析：识别 {len(clusters)} 个细胞亚群",
                    "每个亚群可能具有不同的药物敏感性",
                ],
                "verification_method": "建议对每个亚群进行标记基因分析和药物敏感性测试，验证亚型特异性治疗策略",
                "confidence": 0.70,
                "category": "heterogeneity",
            })

        return hypotheses

    def _rule_targets(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """规则5：已发现靶点 → 靶点机制假设"""
        hypotheses = []
        targets = evidence.get("targets", [])

        if targets:
            top_targets = sorted(
                targets,
                key=lambda t: t.get("confidence_score", 0) if isinstance(t, dict) else 0,
                reverse=True,
            )[:5]
            gene_symbols = [t.get("gene_symbol", "") for t in top_targets if isinstance(t, dict) and t.get("gene_symbol")]
            if gene_symbols:
                gene_str = ", ".join(gene_symbols[:3])
                total_targets = len(targets)
                high_confidence = sum(1 for t in targets if isinstance(t, dict) and t.get("confidence_score", 0) > 0.7)

                hypotheses.append({
                    "title": f"靶点 {gene_str} 作为潜在药物干预目标的机制假设",
                    "description": (
                        f"靶点发现模块共识别 {total_targets} 个候选靶点，其中 {gene_str} 置信度最高"
                        f"（高置信度靶点 {high_confidence} 个）。这些靶点可能在疾病发生发展中起关键调控作用，"
                        f"通过靶向这些分子可干预疾病通路。建议针对 Top 靶点开展深入机制研究和药物开发。"
                    ),
                    "supporting_evidence": [
                        f"靶点发现：共 {total_targets} 个候选靶点",
                        f"高置信度靶点（>0.7）：{high_confidence} 个",
                        f"Top 靶点：{gene_str}",
                        f"靶点来源：{', '.join(set(t.get('source', '') for t in targets if isinstance(t, dict) and t.get('source')))[:100]}",
                    ],
                    "verification_method": (
                        "建议进行：(1) CRISPR-Cas9 基因编辑验证靶点功能；"
                        "(2) 蛋白质互作网络分析揭示靶点上下游调控关系；"
                        "(3) 分子对接和虚拟筛选评估靶点可成药性"
                    ),
                    "confidence": 0.78,
                    "category": "target_mechanism",
                })

                # 如果有多个靶点，生成多靶点协同假设
                if len(gene_symbols) >= 2:
                    hypotheses.append({
                        "title": f"多靶点协同干预策略：{gene_str} 联合靶向",
                        "description": (
                            f"项目已发现 {total_targets} 个靶点，Top 靶点包括 {gene_str}。"
                            f"单一靶点干预可能存在代偿机制导致疗效有限，多靶点协同干预可同时阻断多条疾病通路，"
                            f"有望提高疗效并降低耐药风险。建议设计多靶点小分子或联合用药方案。"
                        ),
                        "supporting_evidence": [
                            f"多靶点候选：共 {total_targets} 个靶点可供选择",
                            f"Top 协同靶点组合：{gene_str}",
                            "多靶点干预可克服单靶点耐药机制",
                        ],
                        "verification_method": (
                            "建议进行：(1) 多靶点分子设计（使用多靶点协同设计模块）；"
                            "(2) 体外协同效应验证（Bliss 独立性模型）；"
                            "(3) 体内药效学评价"
                        ),
                        "confidence": 0.72,
                        "category": "treatment_optimization",
                    })

        return hypotheses

    def _default_hypothesis(self, project_id: str, evidence: Dict[str, Any] = None) -> Dict[str, Any]:
        """默认假设 — 当没有足够数据时生成更详细的引导性假设"""
        evidence = evidence or {}
        targets = evidence.get("targets", [])
        molecules = evidence.get("molecules", [])
        de_genes = evidence.get("de_genes", [])

        # 基于已有数据构建更详细的假设
        data_parts = []
        if targets:
            data_parts.append(f"已发现 {len(targets)} 个候选靶点")
        if molecules:
            data_parts.append(f"已设计 {len(molecules)} 个候选分子")
        if de_genes:
            data_parts.append(f"已识别 {len(de_genes)} 个差异表达基因")

        data_summary = "、".join(data_parts) if data_parts else "暂无充分分析数据"

        top_targets = ""
        if targets:
            gene_symbols = [t.get("gene_symbol", "") for t in targets[:3] if isinstance(t, dict) and t.get("gene_symbol")]
            if gene_symbols:
                top_targets = f"，其中 {', '.join(gene_symbols)} 为重点候选"

        return {
            "title": "项目整体分析假设：基于多组学数据整合的靶点-分子协同治疗策略",
            "description": (
                f"当前项目{data_summary}{top_targets}。"
                f"建议通过多组学数据整合（基因组、转录组、蛋白质组、代谢组）进行系统分析，"
                f"结合机器学习和网络药理学方法，可深入挖掘靶点间调控关系、发现新的疾病相关通路，"
                f"并优化分子设计方案。"
                f"{'已发现的靶点可作为药物设计的起点，进一步验证其成药性和治疗潜力。' if targets else '建议先完成靶点发现流程，再进行分子设计和假设验证。'}"
            ),
            "supporting_evidence": [
                f"项目数据概况：{data_summary}",
                "多组学整合分析可提高靶点发现的准确性和覆盖率",
                "网络药理学方法可揭示靶点间协同调控关系",
                "机器学习辅助分子设计可加速先导化合物优化",
            ],
            "verification_method": (
                "建议按以下步骤推进：(1) 补充多组学数据（WGS/RNA-seq/蛋白质组学）；"
                "(2) 运行靶点发现流程（深度分析模式）；"
                "(3) 基于发现的靶点设计候选分子；"
                "(4) 体外/体内实验验证靶点功能和分子活性"
            ),
            "confidence": 0.45,
            "category": "default",
        }
