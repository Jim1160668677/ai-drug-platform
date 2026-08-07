"""EvidenceCollector — 证据收集服务（架构下沉组件）

设计来源：方向 A（管道嵌入+追溯）的核心组件。
将原本散落在端点层（coscientist.py:_collect_project_evidence）和服务层
（auto_trigger.py:_collect_entity_context）的数据收集逻辑下沉为独立服务，
实现数据收集的集中化、可复用与可追溯。

核心能力：
1. collect_project_evidence：聚合项目前期所有分析结果（靶点/分子/治疗/实验/数据集/假设）
2. collect_entity_context：按触发事件收集关联实体的上下文证据
3. collect_evidence_bundle：组合收集，返回结构化证据包（文本+结构化数据+来源溯源）
4. 数据溯源：每次收集写入 ReasoningTraceStore，记录数据来源与统计

解除反向依赖：auto_trigger 不再 from app.api.v1.endpoints.coscientist import _collect_*，
而是 from app.services.intelligence.evidence_collector import EvidenceCollector。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class EvidenceSource:
    """单个证据来源条目（用于溯源）"""
    source_type: str        # targets/molecules/treatments/experiments/datasets/hypotheses/entity
    count: int = 0          # 收集到的条数
    detail: str = ""        # 来源描述（如 "已发现靶点 15 个"）
    snippets_kept: List[str] = field(default_factory=list)  # top-3 命中片段原文（限长100字）
    content_fingerprint: str = ""  # 证据内容哈希（用于结论→证据反查）


@dataclass
class EvidenceBundle:
    """结构化证据包 — EvidenceCollector 的统一返回结构"""
    text: str = ""
    sources: List[EvidenceSource] = field(default_factory=list)
    structured: Dict[str, Any] = field(default_factory=dict)
    project_id: Optional[str] = None
    entity_id: Optional[str] = None
    trigger_event: Optional[str] = None

    @property
    def total_items(self) -> int:
        return sum(s.count for s in self.sources)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_length": len(self.text),
            "total_items": self.total_items,
            "sources": [
                {
                    "source_type": s.source_type,
                    "count": s.count,
                    "detail": s.detail,
                    "snippets_kept": s.snippets_kept,
                    "content_fingerprint": s.content_fingerprint,
                }
                for s in self.sources
            ],
            "project_id": self.project_id,
            "entity_id": self.entity_id,
            "trigger_event": self.trigger_event,
        }

    @property
    def fingerprints(self) -> List[str]:
        """返回所有证据来源的内容指纹列表"""
        return [s.content_fingerprint for s in self.sources if s.content_fingerprint]


class EvidenceCollector:
    """证据收集器 — 统一数据整合接口

    用法：
        collector = EvidenceCollector(db)
        text = await collector.collect_project_evidence(project_id)
        bundle = await collector.collect_evidence_bundle(
            trigger_event="data_parsed", project_id=pid, entity_id=eid,
        )
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self._db = db

    async def _get_session(self) -> AsyncSession:
        if self._db is not None:
            return self._db
        from app.db.session import async_session_factory
        return async_session_factory()

    async def _should_close(self, session: AsyncSession) -> bool:
        return self._db is None

    @staticmethod
    def _extract_snippets(data_lines: List[str], max_snippets: int = 3, max_chars: int = 100) -> List[str]:
        """从数据行中提取 top-N 命中片段原文（限长）"""
        snippets: List[str] = []
        for line in data_lines[:max_snippets]:
            cleaned = line.strip()
            if cleaned.startswith("-"):
                cleaned = cleaned[1:].strip()
            if len(cleaned) > max_chars:
                cleaned = cleaned[:max_chars] + "…"
            snippets.append(cleaned)
        return snippets

    @staticmethod
    def _compute_fingerprint(text: str) -> str:
        """为证据文本生成内容哈希（SHA-256 前 16 字节 hex）

        用于实现"结论→证据片段"反查链路（v2.0 建议四）。
        相同文本产生相同指纹，支持跨会话引用验证。
        """
        import hashlib
        if not text:
            return ""
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return h[:16]

    @staticmethod
    def _build_evidence_source(
        source_type: str,
        data_lines: List[str],
        detail: str = "",
        max_snippets: int = 3,
    ) -> "EvidenceSource":
        """构建 EvidenceSource 并自动计算内容指纹"""
        snippets = EvidenceCollector._extract_snippets(data_lines, max_snippets)
        combined_text = " | ".join(snippets) if snippets else detail
        fingerprint = EvidenceCollector._compute_fingerprint(combined_text)
        return EvidenceSource(
            source_type=source_type,
            count=len(data_lines),
            detail=detail,
            snippets_kept=snippets,
            content_fingerprint=fingerprint,
        )

    # ========== 项目级证据收集 ==========

    async def collect_project_evidence(self, project_id: str) -> str:
        """收集项目前期所有分析结果作为推理证据（文本模式，向后兼容）"""
        bundle = await self.collect_project_evidence_bundle(project_id)
        return bundle.text

    async def collect_project_evidence_bundle(self, project_id: str) -> EvidenceBundle:
        """收集项目证据并返回结构化证据包（带溯源 + top-3 片段保留）"""
        try:
            project_uuid = UUID(str(project_id))
        except (ValueError, TypeError):
            return EvidenceBundle(project_id=project_id)

        lines: List[str] = []
        sources: List[EvidenceSource] = []
        structured: Dict[str, Any] = {}

        async with (await self._get_session()) as db:
            (
                targets, molecules, treatments, experiments, datasets,
                hypotheses, genomes, uploads, validations, compute_jobs, consents,
            ) = await self._query_project_data(db, project_uuid)

        if targets:
            lines.append("## 已发现靶点")
            target_list = []
            data_lines: List[str] = []
            for t in targets[:15]:
                conf = f"（置信度 {float(t.confidence_score):.2f}）" if t.confidence_score else ""
                line = f"- {t.gene_symbol}{conf}: {t.gene_name or ''}"
                lines.append(line)
                data_lines.append(line)
                target_list.append({
                    "gene_symbol": t.gene_symbol,
                    "gene_name": t.gene_name,
                    "confidence_score": float(t.confidence_score) if t.confidence_score else None,
                })
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            fp = self._compute_fingerprint(" | ".join(snippets))
            sources.append(EvidenceSource("targets", len(targets), f"已发现靶点 {len(targets)} 个", snippets_kept=snippets, content_fingerprint=fp))
            structured["targets"] = target_list

        if molecules:
            lines.append("## 候选分子")
            mol_list = []
            data_lines = []
            for m in molecules[:15]:
                props = m.properties or {}
                score = props.get("druglikeness_score", props.get("composite_score", "N/A"))
                line = f"- {m.smiles[:50] if m.smiles else 'N/A'} (评分: {score})"
                lines.append(line)
                data_lines.append(line)
                mol_list.append({"smiles": m.smiles, "score": score})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            fp = self._compute_fingerprint(" | ".join(snippets))
            sources.append(EvidenceSource("molecules", len(molecules), f"候选分子 {len(molecules)} 个", snippets_kept=snippets, content_fingerprint=fp))
            structured["molecules"] = mol_list

        if treatments:
            lines.append("## 治疗方案")
            treat_list = []
            data_lines = []
            for t in treatments[:10]:
                eff = f"疗效 {float(t.efficacy_score):.2f}" if t.efficacy_score else "疗效未知"
                risk = f"风险 {float(t.risk_score):.2f}" if t.risk_score else ""
                line = f"- {t.name} ({t.therapy_type}): {eff} {risk}"
                lines.append(line)
                data_lines.append(line)
                monitoring = t.monitoring_data or {}
                if monitoring.get("outcomes"):
                    lines.append(f"  监测记录: {len(monitoring['outcomes'])} 条结局")
                if monitoring.get("adverse_events"):
                    lines.append(f"  不良事件: {len(monitoring['adverse_events'])} 条")
                treat_list.append({"name": t.name, "therapy_type": t.therapy_type})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            fp = self._compute_fingerprint(" | ".join(snippets))
            sources.append(EvidenceSource("treatments", len(treatments), f"治疗方案 {len(treatments)} 个", snippets_kept=snippets, content_fingerprint=fp))
            structured["treatments"] = treat_list

        if experiments:
            lines.append("## 实验结果")
            exp_list = []
            data_lines = []
            for e in experiments[:15]:
                result = e.result or {}
                status = e.status
                success = "成功" if e.success else "未达标"
                line = f"- {e.name} ({e.exp_type}): {status} / {success}"
                lines.append(line)
                data_lines.append(line)
                if result.get("efficacy") is not None:
                    lines.append(f"  疗效指标: {result['efficacy']}")
                if result.get("inhibition_rate") is not None:
                    lines.append(f"  抑制率: {result['inhibition_rate']}%")
                if result.get("response"):
                    lines.append(f"  RECIST 响应: {result['response']}")
                exp_list.append({"name": e.name, "exp_type": e.exp_type, "status": status})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            fp = self._compute_fingerprint(" | ".join(snippets))
            sources.append(EvidenceSource("experiments", len(experiments), f"实验结果 {len(experiments)} 个", snippets_kept=snippets, content_fingerprint=fp))
            structured["experiments"] = exp_list

        if datasets:
            lines.append("## 数据集分析结果")
            ds_list = []
            data_lines = []
            for ds in datasets[:5]:
                summary = ds.parsed_summary or {}
                line = f"- {ds.name} ({ds.data_type})"
                lines.append(line)
                data_lines.append(line)
                analysis = summary.get("analysis_results") or {}
                if isinstance(analysis, dict):
                    de = analysis.get("de") or {}
                    if isinstance(de, dict):
                        genes = de.get("genes") or []
                        if genes:
                            top_genes = [g.get("gene", g.get("gene_id", "")) for g in genes[:5] if isinstance(g, dict)]
                            lines.append(f"  差异基因: 共 {len(genes)} 个，Top: {', '.join(top_genes)}")
                    pathways = analysis.get("pathways") or summary.get("pathways") or []
                    if pathways:
                        top_paths = [p.get("name", "") for p in pathways[:3] if isinstance(p, dict)]
                        lines.append(f"  富集通路: {', '.join(top_paths)}")
                    clusters = analysis.get("clusters") or summary.get("clusters") or []
                    if clusters:
                        lines.append(f"  细胞亚群: {len(clusters)} 个")
                ds_list.append({"name": ds.name, "data_type": ds.data_type})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("datasets", len(datasets), f"数据集 {len(datasets)} 个", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["datasets"] = ds_list

        if hypotheses:
            lines.append("## 已有研究假设")
            hyp_list = []
            data_lines = []
            for h in hypotheses[:10]:
                line = f"- {h.name}: {h.description[:100] if h.description else ''}"
                lines.append(line)
                data_lines.append(line)
                hyp_list.append({"name": h.name, "description": h.description})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("hypotheses", len(hypotheses), f"已有假设 {len(hypotheses)} 个", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["hypotheses"] = hyp_list

        if genomes:
            lines.append("## 个人基因组风险评估")
            g_list = []
            data_lines = []
            for g in genomes[:5]:
                risk = g.overall_risk_score or 0.0
                level = g.risk_level or "unknown"
                loci = g.core_loci_matched or 0
                aux = g.auxiliary_loci_matched or 0
                line = f"- 风险评分 {risk:.2f} (等级: {level}, 核心位点: {loci}, 辅助位点: {aux})"
                lines.append(line)
                data_lines.append(line)
                g_list.append({"overall_risk_score": risk, "risk_level": level,
                          "core_loci_matched": loci, "auxiliary_loci_matched": aux})
                traits = g.risk_traits or []
                if isinstance(traits, list) and traits:
                    top_traits = [t.get("trait_name") if isinstance(t, dict) else str(t) for t in traits[:3]]
                    if top_traits:
                        lines.append(f"  主要关联疾病特征: {', '.join(top_traits)}")
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("genomes", len(genomes), f"基因组解读 {len(genomes)} 份", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["genomes"] = g_list

        if uploads:
            lines.append("## 基因组数据上传")
            up_list = []
            data_lines = []
            for u in uploads[:5]:
                dtype = getattr(u, "data_type") or "unknown"
                matched = getattr(u, "total_snps_matched") or 0
                status = getattr(u, "status") or "unknown"
                line = f"- {dtype}: {status}, SNPs 匹配数: {matched}"
                lines.append(line)
                data_lines.append(line)
                up_list.append({"data_type": dtype, "status": status, "total_snps_matched": matched})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("genome_uploads", len(uploads), f"SNP/基因组上传 {len(uploads)} 份", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["genome_uploads"] = up_list

        if validations:
            lines.append("## 验证结果")
            v_list = []
            data_lines = []
            for v in validations[:5]:
                vtype = getattr(v, "validation_type") or "unknown"
                passed = getattr(v, "passed_count") or 0
                total = getattr(v, "total_count") or 0
                rate = passed / total if total else 0
                line = f"- {vtype}: 通过 {passed}/{total} ({rate:.0%})"
                lines.append(line)
                data_lines.append(line)
                v_list.append({"validation_type": vtype, "pass_rate": rate})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("validations", len(validations), f"验证结果 {len(validations)} 项", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["validations"] = v_list

        if compute_jobs:
            lines.append("## 计算任务结果")
            c_list = []
            data_lines = []
            for j in compute_jobs[:5]:
                jtype = getattr(j, "job_type") or getattr(j, "engine") or "compute"
                status = getattr(j, "status") or "unknown"
                result = j.result or {}
                aff = result.get("affinity") if isinstance(result, dict) else None
                extra = f" 亲和力: {aff}" if aff else ""
                line = f"- {jtype}: {status}{extra}"
                lines.append(line)
                data_lines.append(line)
                c_list.append({"job_type": jtype, "status": status})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("compute_jobs", len(compute_jobs), f"计算任务 {len(compute_jobs)} 个", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["compute_jobs"] = c_list

        if consents:
            lines.append("## 知情同意记录")
            c2_list = []
            data_lines = []
            for c in consents[:5]:
                purpose = getattr(c, "consent_purpose") or "general"
                line = f"- 已授予: {purpose}"
                lines.append(line)
                data_lines.append(line)
                c2_list.append({"purpose": purpose})
            lines.append("")
            snippets = self._extract_snippets(data_lines)
            sources.append(EvidenceSource("consents", len(consents), f"知情同意 {len(consents)} 条", snippets_kept=snippets, content_fingerprint=self._compute_fingerprint(" | ".join(snippets))))
            structured["consents"] = c2_list

        text = ""
        if lines:
            text = "# 项目前期分析数据汇总\n\n" + "\n".join(lines)

        logger.info(
            "[EvidenceCollector] 项目 %s 证据: %d 靶点 / %d 分子 / %d 治疗 / %d 实验 / %d 数据集 / %d 假设 / %d 基因组 / %d 验证 / %d 计算",
            project_id, len(targets), len(molecules), len(treatments),
            len(experiments), len(datasets), len(hypotheses),
            len(genomes), len(validations), len(compute_jobs),
        )

        return EvidenceBundle(
            text=text, sources=sources, structured=structured, project_id=project_id,
        )

    async def _query_project_data(self, db: AsyncSession, project_uuid: UUID):
        """并行查询项目所有相关数据（含基因组、蛋白结构、对接结果）"""
        import asyncio

        from app.models.dataset import Dataset
        from app.models.experiment import Experiment
        from app.models.hypothesis import Hypothesis
        from app.models.molecule import Molecule
        from app.models.target import Target
        from app.models.treatment import Treatment
        from app.models.personal_genome import (
            PersonalGenomeUpload,
            RiskAssessment,
        )
        from app.models.validation import Validation
        from app.models.compute_job import ComputeJob
        from app.models.consent import ConsentRecord

        targets_task = db.execute(
            select(Target).where(Target.project_id == project_uuid).limit(20)
        )
        molecules_task = db.execute(
            select(Molecule)
            .join(Target, Molecule.target_id == Target.id, isouter=True)
            .where(Target.project_id == project_uuid)
            .limit(20)
        )
        treatments_task = db.execute(
            select(Treatment).where(Treatment.project_id == project_uuid).limit(10)
        )
        experiments_task = db.execute(
            select(Experiment).where(Experiment.project_id == project_uuid)
            .order_by(Experiment.created_at.desc()).limit(15)
        )
        datasets_task = db.execute(
            select(Dataset).where(Dataset.project_id == project_uuid)
            .where(Dataset.parse_status == "completed").limit(5)
        )
        hypotheses_task = db.execute(
            select(Hypothesis).where(Hypothesis.project_id == project_uuid).limit(10)
        )
        # 新增：个人基因组解读结果
        genome_task = db.execute(
            select(RiskAssessment).where(
                RiskAssessment.project_id == project_uuid
            ).order_by(RiskAssessment.overall_risk_score.desc()).limit(5)
        )
        # 新增：SNP 芯片/VCF 上传记录
        uploads_task = db.execute(
            select(PersonalGenomeUpload).where(
                PersonalGenomeUpload.project_id == project_uuid
            ).limit(5)
        )
        # 新增：验证结果
        validations_task = db.execute(
            select(Validation).where(
                Validation.project_id == project_uuid
            ).order_by(Validation.created_at.desc()).limit(5)
        )
        # 新增：计算任务（对接/结构预测）
        compute_task = db.execute(
            select(ComputeJob).where(
                ComputeJob.project_id == project_uuid,
                ComputeJob.status == "completed",
            ).order_by(ComputeJob.created_at.desc()).limit(5)
        )
        # 新增：知情同意记录
        consent_task = db.execute(
            select(ConsentRecord).where(
                ConsentRecord.project_id == project_uuid,
                ConsentRecord.status == "granted",
            ).limit(5)
        )

        (
            targets_r, molecules_r, treatments_r, experiments_r, datasets_r,
            hypotheses_r, genome_r, uploads_r, validations_r, compute_r,
            consent_r,
        ) = await asyncio.gather(
            targets_task, molecules_task, treatments_task, experiments_task,
            datasets_task, hypotheses_task, genome_task, uploads_task,
            validations_task, compute_task, consent_task,
        )

        return (
            targets_r.scalars().all(),
            molecules_r.scalars().all(),
            treatments_r.scalars().all(),
            experiments_r.scalars().all(),
            datasets_r.scalars().all(),
            hypotheses_r.scalars().all(),
            genome_r.scalars().all(),
            uploads_r.scalars().all(),
            validations_r.scalars().all(),
            compute_r.scalars().all(),
            consent_r.scalars().all(),
        )

    # ========== 实体级上下文收集 ==========

    async def collect_entity_context(
        self, trigger_event: str, entity_id: Optional[str], project_id: Optional[str] = None,
    ) -> str:
        """收集触发实体的上下文证据（文本模式，向后兼容）"""
        bundle = await self.collect_entity_context_bundle(trigger_event, entity_id, project_id)
        return bundle.text

    async def collect_entity_context_bundle(
        self, trigger_event: str, entity_id: Optional[str], project_id: Optional[str] = None,
    ) -> EvidenceBundle:
        """收集实体上下文并返回结构化证据包（带溯源）"""
        if not entity_id:
            return EvidenceBundle(
                project_id=project_id, entity_id=entity_id, trigger_event=trigger_event,
            )

        from app.models.coscientist_insight import TriggerEvent

        try:
            async with (await self._get_session()) as db:
                lines: List[str] = []
                structured: Dict[str, Any] = {}
                source_detail = ""

                if trigger_event == TriggerEvent.DATA_PARSED:
                    source_detail = await self._collect_dataset_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.TARGETS_DISCOVERED:
                    source_detail = await self._collect_target_entity(db, entity_id, lines, structured)
                elif trigger_event in (TriggerEvent.EXPERIMENT_COMPLETED, TriggerEvent.EXPERIMENT_FAILED):
                    source_detail = await self._collect_experiment_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.MOLECULE_GENERATED:
                    source_detail = await self._collect_molecule_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.GENOME_INTERPRETED:
                    source_detail = await self._collect_genome_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.DOCKING_COMPLETED:
                    source_detail = await self._collect_docking_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.STRUCTURE_PREDICTED:
                    source_detail = await self._collect_structure_entity(db, entity_id, lines, structured)
                elif trigger_event == TriggerEvent.BENCHMARK_COMPLETED:
                    source_detail = await self._collect_benchmark_entity(db, entity_id, lines, structured)
                elif trigger_event in (TriggerEvent.SCREENING_COMPLETED, TriggerEvent.VACCINE_DESIGNED):
                    source_detail = await self._collect_compute_job_entity(db, entity_id, lines, structured)

                text = "\n".join(lines) if lines else ""
                sources = [EvidenceSource("entity", 1, source_detail)] if source_detail else []

                return EvidenceBundle(
                    text=text, sources=sources, structured=structured,
                    project_id=project_id, entity_id=entity_id, trigger_event=trigger_event,
                )
        except Exception as e:
            logger.warning("[EvidenceCollector] 收集实体上下文失败: %s", e)
            return EvidenceBundle(
                project_id=project_id, entity_id=entity_id, trigger_event=trigger_event,
            )

    async def _collect_dataset_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.dataset import Dataset
        ds = await db.get(Dataset, UUID(entity_id))
        if not ds:
            return ""
        lines.append(f"## 触发数据集：{ds.name}")
        structured["dataset"] = {"name": ds.name, "data_type": ds.data_type}
        summary = ds.parsed_summary or {}
        analysis = summary.get("analysis_results") or {}
        if isinstance(analysis, dict):
            de = analysis.get("de") or {}
            if isinstance(de, dict) and de.get("genes"):
                top = [g.get("gene", "") for g in de["genes"][:10] if isinstance(g, dict)]
                lines.append(f"差异基因 Top10: {', '.join(top)}")
            pathways = analysis.get("pathways") or []
            if pathways:
                top_p = [p.get("name", "") for p in pathways[:5] if isinstance(p, dict)]
                lines.append(f"富集通路 Top5: {', '.join(top_p)}")
        return f"触发数据集 {ds.name}"

    async def _collect_target_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.target import Target
        t = await db.get(Target, UUID(entity_id))
        if not t:
            return ""
        conf = f"（置信度 {float(t.confidence_score):.2f}）" if t.confidence_score else ""
        lines.append(f"## 触发靶点：{t.gene_symbol}{conf}")
        if t.gene_name:
            lines.append(f"基因全名: {t.gene_name}")
        structured["target"] = {"gene_symbol": t.gene_symbol, "gene_name": t.gene_name}
        return f"触发靶点 {t.gene_symbol}"

    async def _collect_experiment_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.experiment import Experiment
        e = await db.get(Experiment, UUID(entity_id))
        if not e:
            return ""
        lines.append(f"## 触发实验：{e.name}（类型 {e.exp_type}）")
        lines.append(f"状态: {e.status} / {'成功' if e.success else '未达标'}")
        result = e.result or {}
        if result.get("efficacy") is not None:
            lines.append(f"疗效指标: {result['efficacy']}")
        if result.get("inhibition_rate") is not None:
            lines.append(f"抑制率: {result['inhibition_rate']}%")
        if result.get("response"):
            lines.append(f"RECIST 响应: {result['response']}")
        if result.get("error"):
            lines.append(f"错误信息: {result['error']}")
        structured["experiment"] = {"name": e.name, "exp_type": e.exp_type, "status": e.status}
        return f"触发实验 {e.name}"

    async def _collect_molecule_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.molecule import Molecule
        m = await db.get(Molecule, UUID(entity_id))
        if not m:
            return ""
        lines.append("## 触发分子")
        lines.append(f"SMILES: {m.smiles[:80] if m.smiles else 'N/A'}")
        props = m.properties or {}
        score = props.get("druglikeness_score", props.get("composite_score", "N/A"))
        lines.append(f"类药性评分: {score}")
        structured["molecule"] = {"smiles": m.smiles, "score": score}
        return "触发分子"

    async def _collect_genome_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.personal_genome import RiskAssessment
        a = await db.get(RiskAssessment, UUID(entity_id))
        if not a:
            return ""
        lines.append("## 触发风险评估")
        lines.append(f"整体风险评分: {a.overall_risk_score}")
        lines.append(f"风险等级: {a.risk_level}")
        lines.append(f"核心位点匹配: {a.core_loci_matched}")
        lines.append(f"辅助位点匹配: {a.auxiliary_loci_matched}")
        structured["risk_assessment"] = {
            "overall_risk_score": a.overall_risk_score, "risk_level": a.risk_level,
        }
        return "触发风险评估"

    async def _collect_docking_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.compute_job import ComputeJob
        j = await db.get(ComputeJob, UUID(entity_id))
        if not j:
            return ""
        lines.append(f"## 触发对接任务：{j.case_id or j.id}")
        lines.append(f"引擎: {j.engine} / 状态: {j.status}")
        result = j.result or {}
        if result.get("affinity") is not None:
            lines.append(f"亲和力: {result['affinity']}")
        if result.get("rmsd") is not None:
            lines.append(f"RMSD: {result['rmsd']}")
        if result.get("final_ranking"):
            lines.append(f"最终排名: {result['final_ranking'][:3]}")
        structured["docking_job"] = {"engine": j.engine, "status": j.status}
        return f"触发对接任务 {j.case_id or j.id}"

    async def _collect_structure_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.protein_structure import ProteinStructure
        s = await db.get(ProteinStructure, UUID(entity_id))
        if not s:
            return ""
        lines.append("## 触发蛋白结构")
        if s.binding_site_residues:
            lines.append(f"结合位点残基: {s.binding_site_residues[:10]}")
        structured["protein_structure"] = {"binding_site_residues": s.binding_site_residues}
        return "触发蛋白结构"

    async def _collect_benchmark_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.benchmark_report import BenchmarkReport
        r = await db.get(BenchmarkReport, UUID(entity_id))
        if not r:
            return ""
        lines.append(f"## 触发基准报告：case={r.case_id} mode={r.mode}")
        lines.append(f"指标: {r.metrics}")
        if r.summary:
            lines.append(f"摘要: {r.summary}")
        lines.append(f"成本节省: {r.cost_saving_pct}% / 精度变化: {r.accuracy_change_pct}%")
        structured["benchmark_report"] = {"case_id": r.case_id, "mode": r.mode}
        return f"触发基准报告 {r.case_id}"

    async def _collect_compute_job_entity(self, db, entity_id, lines, structured) -> str:
        from app.models.compute_job import ComputeJob
        j = await db.get(ComputeJob, UUID(entity_id))
        if not j:
            return ""
        lines.append(f"## 触发任务：{j.case_id or j.id}（类型 {j.job_type}）")
        result = j.result or {}
        if result.get("amplifiers"):
            lines.append(f"条件放大器: {len(result['amplifiers'])} 个")
        if result.get("neoantigens"):
            lines.append(f"新抗原: {len(result['neoantigens'])} 个")
        if result.get("vaccine"):
            lines.append("疫苗设计: 已生成")
        structured["compute_job"] = {"case_id": j.case_id, "job_type": j.job_type}
        return f"触发任务 {j.case_id or j.id}"

    # ========== 组合收集（管道嵌入入口） ==========

    async def collect_evidence_bundle(
        self, trigger_event: Optional[str] = None, project_id: Optional[str] = None,
        entity_id: Optional[str] = None, extra_evidence: Optional[str] = None,
        trace_store: Optional[Any] = None, run_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
    ) -> EvidenceBundle:
        """组合收集证据 — 管道嵌入的统一入口

        依次收集：项目证据 + 实体上下文 + 额外证据，拼接为完整证据包。
        可选写入 ReasoningTraceStore 记录数据来源溯源。
        """
        parts: List[str] = []
        all_sources: List[EvidenceSource] = []
        all_structured: Dict[str, Any] = {}

        if project_id:
            proj_bundle = await self.collect_project_evidence_bundle(project_id)
            if proj_bundle.text:
                parts.append(proj_bundle.text)
            all_sources.extend(proj_bundle.sources)
            all_structured["project"] = proj_bundle.structured

        if trigger_event and entity_id:
            ent_bundle = await self.collect_entity_context_bundle(
                trigger_event, entity_id, project_id,
            )
            if ent_bundle.text:
                parts.append(ent_bundle.text)
            all_sources.extend(ent_bundle.sources)
            all_structured["entity"] = ent_bundle.structured

        if extra_evidence:
            parts.append(f"## 触发事件附加上下文\n{extra_evidence}")
            all_sources.append(EvidenceSource("extra", 1, "附加上下文"))

        combined_text = "\n\n".join(parts)

        bundle = EvidenceBundle(
            text=combined_text, sources=all_sources, structured=all_structured,
            project_id=project_id, entity_id=entity_id, trigger_event=trigger_event,
        )

        if trace_store is not None and all_sources:
            try:
                await trace_store.append(
                    step_type="evidence_collection",
                    run_id=run_id, session_id=session_id,
                    agent_name="evidence_collector",
                    input_data={
                        "trigger_event": trigger_event,
                        "project_id": project_id,
                        "entity_id": entity_id,
                    },
                    output_data={
                        "text_length": len(combined_text),
                        "total_items": bundle.total_items,
                        "sources": [s.__dict__ for s in all_sources],
                    },
                    decision_basis=f"收集 {bundle.total_items} 项证据，来自 {len(all_sources)} 个来源",
                )
            except Exception as e:
                logger.warning("[EvidenceCollector] 写入溯源失败（不影响主流程）: %s", e)

        return bundle

    # ========== 三级输出 + 预算裁剪（瓶颈 B）==========

    _LEVEL_ITEM_LIMITS = {
        "summary": {"targets": 3, "molecules": 3, "treatments": 3, "experiments": 2,
                    "datasets": 1, "hypotheses": 2, "genomes": 1, "genome_uploads": 1,
                    "validations": 1, "compute_jobs": 1, "consents": 1, "others": 1},
        "compact": {"targets": 5, "molecules": 5, "treatments": 5, "experiments": 4,
                    "datasets": 2, "hypotheses": 3, "genomes": 3, "genome_uploads": 2,
                    "validations": 2, "compute_jobs": 2, "consents": 1, "others": 2},
    }
    _LEVEL_ORDER = ["summary", "compact", "full"]

    async def collect_project_evidence_with_budget(
        self,
        project_id: str,
        level: str = "compact",
        token_budget_chars: int = 4000,
    ) -> str:
        if level not in self._LEVEL_ORDER:
            level = "compact"
        bundle = self.collect_project_evidence_bundle(project_id)
        import inspect
        if inspect.isawaitable(bundle):
            bundle = await bundle

        if not bundle or not bundle.text:
            return ""

        raw = bundle.text
        if level == "full":
            if len(raw) <= token_budget_chars:
                return raw
            return self._trim_sections_to_budget(raw, token_budget_chars, from_head=False)

        limits = self._LEVEL_ITEM_LIMITS[level]
        trimmed = self._apply_level_limits(bundle, limits)
        if len(trimmed) <= token_budget_chars:
            return trimmed
        return self._trim_sections_to_budget(trimmed, token_budget_chars, from_head=True)

    def _apply_level_limits(self, bundle, limits: Dict[str, int]) -> str:
        import re
        text = bundle.text
        sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
        out_parts: List[str] = []
        section_name_map = {
            "已发现靶点": "targets",
            "候选分子": "molecules",
            "治疗方案": "treatments",
            "实验记录": "experiments",
            "实验结果": "experiments",
            "数据集": "datasets",
            "数据集分析结果": "datasets",
            "已有研究假设": "hypotheses",
            "个人基因组风险评估": "genomes",
            "基因组数据上传": "genome_uploads",
            "验证结果": "validations",
            "计算任务结果": "compute_jobs",
            "知情同意记录": "consents",
        }
        for sec in sections:
            if not sec.strip():
                continue
            lines = sec.splitlines()
            header = lines[0]
            match = re.match(r"^##\s*(.+)$", header.strip())
            key = match.group(1).strip() if match else ""
            mapping_key = section_name_map.get(key, "others")
            limit = limits.get(mapping_key, limits.get("others", 999))
            items = [ln for ln in lines[1:] if ln.lstrip().startswith("-")]
            rest = [ln for ln in lines[1:] if not ln.lstrip().startswith("-")]
            if len(items) > limit:
                kept = items[:limit]
                dropped = len(items) - limit
                total = len(items)
                tail_line = f"  （其余 {dropped} 条省略，完整数据共 {total} 条，完整数据请调工具查询）"
                body = kept + [tail_line] + rest
            else:
                body = items + rest
            new_sec = "\n".join([header] + body)
            out_parts.append(new_sec)
        return "\n\n".join(out_parts).strip() + "\n"

    def _trim_sections_to_budget(self, text: str, budget: int, from_head: bool) -> str:
        import re
        sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
        sections = [s for s in sections if s.strip()]
        order = sections if from_head else list(reversed(sections))
        result: List[str] = []
        budget_used = 0
        for sec in order:
            cost = len(sec) + 2
            if budget_used + cost <= budget:
                (result.append if from_head else result.insert)(0, sec)
                budget_used += cost
            else:
                lines = sec.splitlines()
                header = lines[0]
                snippet = " ".join(l.lstrip() for l in lines[1:3] if l.strip())[:80]
                brief = f"{header}\n  {snippet}{'…' if len(snippet) >= 80 else ''}"
                if budget_used + len(brief) + 2 <= budget:
                    (result.append if from_head else result.insert)(0, brief)
                    budget_used += len(brief) + 2
                break
        return "\n\n".join(result).strip()


__all__ = ["EvidenceCollector", "EvidenceBundle", "EvidenceSource"]
