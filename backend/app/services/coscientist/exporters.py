"""Co-Scientist 报告导出器 — SDTM HO 域 + FHIR ResearchStudy + Markdown 报告

Phase B5 报告导出功能：将 Co-Scientist 运行结果导出为标准化格式。

支持的导出格式：
1. SDTM 自定义域（CDISC SDTMIG 3.3 兼容）：
   - HO 域（Hypothesis Outcomes）: 假设及评分、排名
   - TS 域（Trial Summary）: 运行元数据
   - DL 域（Debate Logs）: 辩论记录
2. FHIR R4 ResearchStudy Bundle：与 HIS/EMR 系统互操作
   - ResearchStudy: 主资源（运行）
   - ResearchSubject: 每个假设作为研究对象
3. Markdown 报告：人类可读的综合报告

设计原则：
- 与现有 SDTMExporter/FHIRExporter 风格一致（项目级导出）
- 异步 DB 操作，所有 IO 都在 AsyncSession 中执行
- 严格类型检查，所有 None 字段显式处理
- 单元测试覆盖率 ≥ 80%

参考：
- CDISC SDTMIG 3.3: https://www.cdisc.org/standards/foundational/sdtmig
- FHIR R4 ResearchStudy: https://hl7.org/fhir/researchstudy.html
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.coscientist_run import (
    CoScientistDebateLog,
    CoScientistRun,
    RunStatus,
)
from app.models.hypothesis import Hypothesis, HypothesisStatus

logger = logging.getLogger(__name__)


# ========== 常量映射 ==========

def _elo_bucket(score: Optional[float]) -> str:
    """Elo 分数分级（用于 HOSCD 字段）"""
    if score is None:
        return "UNKNOWN"
    if score >= 1200:
        return "HIGH"
    if score >= 1000:
        return "MID"
    return "LOW"


# 运行状态 → SDTM TS 域状态
_RUN_STATUS_TO_SDTM: Dict[str, str] = {
    RunStatus.PENDING: "PLANNED",
    RunStatus.RUNNING: "ONGOING",
    RunStatus.AWAITING_FEEDBACK: "ONGOING",
    RunStatus.COMPLETED: "COMPLETED",
    RunStatus.FAILED: "FAILED",
    RunStatus.CANCELLED: "CANCELLED",
}

# 运行状态 → FHIR ResearchStudy.status
_RUN_STATUS_TO_FHIR: Dict[str, str] = {
    RunStatus.PENDING: "in-progress",
    RunStatus.RUNNING: "in-progress",
    RunStatus.AWAITING_FEEDBACK: "in-progress",
    RunStatus.COMPLETED: "completed",
    RunStatus.FAILED: "stopped",
    RunStatus.CANCELLED: "stopped",
}

# 案例类型 → 中文显示
_CASE_DISPLAY: Dict[str, str] = {
    "aml": "AML 药物重定位",
    "liver_fibrosis": "肝纤维化表观遗传靶点",
    "amr": "AMR 细菌基因转移机制",
    "custom": "自定义研究目标",
}

# 假设状态 → FHIR ResearchSubject.status
_HYP_STATUS_TO_FHIR: Dict[str, str] = {
    HypothesisStatus.DRAFT: "candidate",
    HypothesisStatus.ANALYZING: "active",
    HypothesisStatus.COMPLETED: "active",
    HypothesisStatus.MERGED: "completed",
    HypothesisStatus.ARCHIVED: "completed",
    HypothesisStatus.ELIMINATED: "failed",
    HypothesisStatus.ELIMINATED_BY_EXPERT: "failed",
    HypothesisStatus.DEBATING: "active",
    HypothesisStatus.EVOLVING: "active",
}


# ========== SDTM 导出器 ==========


class CoScientistSDTMExporter:
    """Co-Scientist SDTM 导出器 — 自定义 HO/TS/DL 域

    域设计：
    - HO（Hypothesis Outcomes）: 自定义 findings 域，每个假设一行
      - HOSEQ: 假设序号（按 rank 排序，1-based）
      - HOTERM: 假设名称
      - HOCAT: 类别（evolution_strategy: initial/enhancement/combination/simplification）
      - HOSCD: 评分代码（elo bucket: HIGH/MID/LOW/UNKNOWN）
      - HOORRES: 原始结果（hypothesis status）
      - HOTSTRESC: 标准化结果（rank 字符串）
      - HOBLFL: 基线标记（Y 表示初始假设）
      - HODTC: 时间戳
    - TS（Trial Summary）: 运行级元数据（5 条固定参数）
    - DL（Debate Logs）: 辩论记录，每场辩论一行
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export(self, run_id: UUID) -> Dict[str, Any]:
        """导出 Co-Scientist 运行为 SDTM 格式

        Args:
            run_id: Co-Scientist 运行 ID
        Returns:
            {"domains": {"HO": [...], "TS": [...], "DL": [...]},
             "metadata": {"study_id", "version", "export_time", "source", "run_id", "record_counts"}}
        Raises:
            NotFoundError: 运行不存在
        """
        run = await self.db.get(CoScientistRun, run_id)
        if not run:
            raise NotFoundError(
                f"Co-Scientist 运行不存在: {run_id}",
                details={"run_id": str(run_id)},
            )

        study_id = f"CS-{str(run_id)[:8].upper()}"
        usubjid = str(run_id)

        # 加载假设（按 rank 排序，rank 为空时按 elo_score 降序）
        hypotheses = (
            await self.db.execute(
                select(Hypothesis)
                .where(Hypothesis.coscientist_run_id == run_id)
                .order_by(
                    Hypothesis.rank.asc().nullslast(),
                    Hypothesis.elo_score.desc().nullslast(),
                )
            )
        ).scalars().all()

        # 加载辩论日志（按轮次排序）
        debates = (
            await self.db.execute(
                select(CoScientistDebateLog)
                .where(CoScientistDebateLog.run_id == run_id)
                .order_by(CoScientistDebateLog.round_num.asc())
            )
        ).scalars().all()

        # 构建各域
        ho_records = self._build_ho_domain(study_id, usubjid, hypotheses)
        ts_records = self._build_ts_domain(study_id, run)
        dl_records = self._build_dl_domain(study_id, usubjid, debates)

        return {
            "domains": {
                "HO": ho_records,
                "TS": ts_records,
                "DL": dl_records,
            },
            "metadata": {
                "study_id": study_id,
                "version": "SDTMIG 3.3 (Custom HO/DL domains)",
                "export_time": datetime.now(timezone.utc).isoformat(),
                "source": "Co-Scientist",
                "run_id": str(run_id),
                "record_counts": {
                    "HO": len(ho_records),
                    "TS": len(ts_records),
                    "DL": len(dl_records),
                },
            },
        }

    def _build_ho_domain(
        self,
        study_id: str,
        usubjid: str,
        hypotheses: List[Hypothesis],
    ) -> List[Dict[str, Any]]:
        """构建 HO 域 — 每个假设一行"""
        records: List[Dict[str, Any]] = []
        for idx, h in enumerate(hypotheses, 1):
            is_baseline = h.evolution_strategy in (None, "", "initial")
            records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "HO",
                    "USUBJID": usubjid,
                    "HOSEQ": idx,
                    "HOTERM": (h.name or "")[:200],
                    "HOCAT": h.evolution_strategy or "initial",
                    "HOSCD": _elo_bucket(h.elo_score),
                    "HOORRES": h.status or "draft",
                    "HOTSTRESC": str(h.rank) if h.rank is not None else "",
                    "HOBLFL": "Y" if is_baseline else "",
                    "HODTC": h.created_at.isoformat() if h.created_at else "",
                }
            )
        return records

    def _build_ts_domain(
        self, study_id: str, run: CoScientistRun
    ) -> List[Dict[str, Any]]:
        """构建 TS 域 — 运行级元数据（5 条固定参数）"""
        return [
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "TITLE",
                "TSPARM": "研究目标",
                "TSVAL": (run.research_goal or "")[:500],
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "STYPE",
                "TSPARM": "案例类型",
                "TSVAL": run.case_type or "custom",
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "PHASE",
                "TSPARM": "当前阶段",
                "TSVAL": run.current_phase or "N/A",
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "STATUS",
                "TSPARM": "运行状态",
                "TSVAL": _RUN_STATUS_TO_SDTM.get(run.status, "UNKNOWN"),
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "ROUND",
                "TSPARM": "运行轮次",
                "TSVAL": f"{run.current_round}/{run.max_rounds}",
            },
        ]

    def _build_dl_domain(
        self,
        study_id: str,
        usubjid: str,
        debates: List[CoScientistDebateLog],
    ) -> List[Dict[str, Any]]:
        """构建 DL 域 — 辩论记录"""
        records: List[Dict[str, Any]] = []
        for idx, d in enumerate(debates, 1):
            # 优先用修正后的假设作为 TERM，回退到正方论据
            term = (d.refined_hypothesis or d.proponent_argument or "")[:200]
            records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "DL",
                    "USUBJID": usubjid,
                    "DLSEQ": idx,
                    "DLTERM": term,
                    "DLCAT": "scientific_debate",
                    "DLORRES": (
                        f"consensus={d.consensus_score:.3f}"
                        if d.consensus_score is not None
                        else "consensus=N/A"
                    ),
                    "DLSTRESC": "AGREED" if d.mechanism_agreed else "DISPUTED",
                    "DLDTC": d.created_at.isoformat() if d.created_at else "",
                }
            )
        return records

    def to_csv(self, sdtm_data: Dict[str, Any]) -> str:
        """将 SDTM 数据转为 CSV 字符串（多域拼接，与 SDTMExporter 风格一致）"""
        output = io.StringIO()
        domains = sdtm_data.get("domains", {})
        metadata = sdtm_data.get("metadata", {})

        # 元数据头
        output.write("# CDISC SDTM Export (Co-Scientist)\n")
        output.write(f"# Study: {metadata.get('study_id', '')}\n")
        output.write(f"# Version: {metadata.get('version', '')}\n")
        output.write(f"# Source: {metadata.get('source', '')}\n")
        output.write(f"# Export Time: {metadata.get('export_time', '')}\n")
        output.write(f"# Record Counts: {metadata.get('record_counts', {})}\n\n")

        for domain_name, records in domains.items():
            if not records:
                continue
            output.write(f"--- {domain_name} Domain ---\n")
            fieldnames = list(records[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow(record)
            output.write("\n")

        return output.getvalue()


# ========== FHIR ResearchStudy 导出器 ==========


class CoScientistFHIRExporter:
    """Co-Scientist FHIR R4 导出器 — ResearchStudy 资源

    映射关系：
    - CoScientistRun → ResearchStudy（主资源）
    - Hypothesis → ResearchStudy.arm + ResearchSubject（每个假设一个 subject）
    - CoScientistDebateLog → ResearchStudy.note（辩论摘要，限 20 条）
    - meta_review → ResearchStudy.objective
    - total_cost_usd / total_token_usage → ResearchStudy.extension

    FHIR R4 规范参考：https://hl7.org/fhir/researchstudy.html
    """

    # 限制 note 条数，避免 Bundle 过大
    _MAX_NOTES = 20

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_research_study(self, run_id: UUID) -> Dict[str, Any]:
        """导出 ResearchStudy Bundle

        Args:
            run_id: Co-Scientist 运行 ID
        Returns:
            FHIR Bundle（transaction 类型），包含 ResearchStudy + ResearchSubject
        Raises:
            NotFoundError: 运行不存在
        """
        run = await self.db.get(CoScientistRun, run_id)
        if not run:
            raise NotFoundError(
                f"Co-Scientist 运行不存在: {run_id}",
                details={"run_id": str(run_id)},
            )

        # 加载假设（按 rank 排序）
        hypotheses = (
            await self.db.execute(
                select(Hypothesis)
                .where(Hypothesis.coscientist_run_id == run_id)
                .order_by(
                    Hypothesis.rank.asc().nullslast(),
                    Hypothesis.elo_score.desc().nullslast(),
                )
            )
        ).scalars().all()

        # 加载辩论日志（按轮次排序）
        debates = (
            await self.db.execute(
                select(CoScientistDebateLog)
                .where(CoScientistDebateLog.run_id == run_id)
                .order_by(CoScientistDebateLog.round_num.asc())
            )
        ).scalars().all()

        entries: List[Dict[str, Any]] = []

        # 1. ResearchStudy 主资源
        study = self._build_research_study(run, hypotheses, debates)
        entries.append(self._make_entry(study))

        # 2. 每个假设 → ResearchSubject
        for h in hypotheses:
            subject = self._build_research_subject(h, run)
            entries.append(self._make_entry(subject))

        bundle = {
            "resourceType": "Bundle",
            "id": f"cs-bundle-{run_id}",
            "type": "transaction",
            "meta": {
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
                "profile": ["http://hl7.org/fhir/4.0/StructureDefinition/Bundle"],
            },
            "total": len(entries),
            "entry": entries,
        }

        logger.info(
            "Co-Scientist FHIR Bundle 导出完成: run=%s, resources=%d",
            run_id,
            len(entries),
        )
        return bundle

    def _build_research_study(
        self,
        run: CoScientistRun,
        hypotheses: List[Hypothesis],
        debates: List[CoScientistDebateLog],
    ) -> Dict[str, Any]:
        """构建 ResearchStudy 主资源"""
        study: Dict[str, Any] = {
            "resourceType": "ResearchStudy",
            "id": str(run.id),
            "status": _RUN_STATUS_TO_FHIR.get(run.status, "unknown"),
            "identifier": [
                {
                    "system": "urn:oid:1.3.6.1.4.1.31146.6",
                    "value": f"CS-{str(run.id)[:8].upper()}",
                    "use": "official",
                }
            ],
            "title": f"Co-Scientist Run: {_CASE_DISPLAY.get(run.case_type, '自定义')}",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/research-study-type",
                            "code": run.case_type or "custom",
                            "display": _CASE_DISPLAY.get(
                                run.case_type, "自定义研究目标"
                            ),
                        }
                    ]
                }
            ],
            "focus": [{"text": run.research_goal or ""}],
            "period": {
                "start": run.started_at.isoformat() if run.started_at else None,
                "end": run.completed_at.isoformat() if run.completed_at else None,
            },
            "enrollment": len(hypotheses),
            "meta": {
                "lastUpdated": run.updated_at.isoformat() if run.updated_at else None,
                "tag": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
                        "code": "AI",
                        "display": "AI-Generated Research",
                    }
                ],
            },
        }

        # 每个假设 → arm
        if hypotheses:
            study["arm"] = [
                {
                    "name": (h.name or f"Hypothesis-{i}")[:200],
                    "type": {"text": h.evolution_strategy or "initial"},
                    "description": (h.description or h.mechanism or "")[:1000],
                }
                for i, h in enumerate(hypotheses, 1)
            ]

        # objective = meta_review
        if run.meta_review:
            study["objective"] = [
                {
                    "name": "Meta Review",
                    "description": run.meta_review,
                }
            ]

        # note: 辩论摘要（限 20 条）
        if debates:
            study["note"] = [
                {
                    "text": (
                        f"Round {d.round_num}: "
                        f"consensus={d.consensus_score:.3f}, "
                        f"mechanism_agreed={d.mechanism_agreed}"
                    )
                }
                for d in debates[: self._MAX_NOTES]
                if d.consensus_score is not None or d.mechanism_agreed is not None
            ]

        # extension: 成本 / token 用量
        extensions: List[Dict[str, Any]] = []
        if run.total_cost_usd is not None:
            extensions.append(
                {
                    "url": "http://example.org/fhir/StructureDefinition/totalCostUsd",
                    "valueDecimal": float(run.total_cost_usd),
                }
            )
        if run.total_token_usage and run.total_token_usage.get("total"):
            extensions.append(
                {
                    "url": "http://example.org/fhir/StructureDefinition/tokenUsage",
                    "valueInteger": int(run.total_token_usage["total"]),
                }
            )
        if extensions:
            study["extension"] = extensions

        return study

    def _build_research_subject(
        self, hyp: Hypothesis, run: CoScientistRun
    ) -> Dict[str, Any]:
        """构建 ResearchSubject 资源（每个假设一个）"""
        subject: Dict[str, Any] = {
            "resourceType": "ResearchSubject",
            "id": f"rs-{hyp.id}",
            "status": _HYP_STATUS_TO_FHIR.get(hyp.status, "candidate"),
            "study": {"reference": f"ResearchStudy/{run.id}"},
            "individual": {"display": hyp.name or f"Hypothesis-{hyp.id}"},
            "period": {
                "start": hyp.created_at.isoformat() if hyp.created_at else None
            },
            "meta": {
                "lastUpdated": hyp.updated_at.isoformat() if hyp.updated_at else None
            },
        }

        # 扩展字段：Elo / Rank / 评分维度
        extensions: List[Dict[str, Any]] = []
        if hyp.elo_score is not None:
            extensions.append(
                {
                    "url": "http://example.org/fhir/StructureDefinition/eloScore",
                    "valueDecimal": float(hyp.elo_score),
                }
            )
        if hyp.rank is not None:
            extensions.append(
                {
                    "url": "http://example.org/fhir/StructureDefinition/rank",
                    "valueInteger": int(hyp.rank),
                }
            )
        # 4 个评分维度（0-10）
        for dim_name, dim_value in [
            ("noveltyScore", hyp.novelty_score),
            ("plausibilityScore", hyp.plausibility_score),
            ("testabilityScore", hyp.testability_score),
            ("safetyScore", hyp.safety_score),
        ]:
            if dim_value is not None:
                extensions.append(
                    {
                        "url": f"http://example.org/fhir/StructureDefinition/{dim_name}",
                        "valueDecimal": float(dim_value),
                    }
                )
        if extensions:
            subject["extension"] = extensions

        return subject

    def _make_entry(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """构建 Bundle entry"""
        resource_id = resource.get("id", "")
        resource_type = resource.get("resourceType", "")
        return {
            "fullUrl": f"urn:uuid:{resource_id}" if resource_id else "",
            "resource": resource,
            "request": {
                "method": "POST",
                "url": resource_type,
            },
        }


# ========== Markdown 报告生成器 ==========


class CoScientistMarkdownExporter:
    """Co-Scientist Markdown 报告生成器 — 人类可读的综合报告

    生成包含以下章节的 Markdown 报告：
    1. 基本信息（运行 ID、状态、案例类型、研究目标）
    2. 假设排名表（Top N，含 Elo/评分维度）
    3. 辩论摘要（每轮共识度）
    4. 元评审报告（meta_review）
    5. 成本与资源消耗
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_markdown(
        self, run_id: UUID, top_n: int = 10
    ) -> str:
        """生成 Markdown 格式的综合报告

        Args:
            run_id: Co-Scientist 运行 ID
            top_n: 显示前 N 个假设（默认 10）
        Returns:
            Markdown 字符串
        Raises:
            NotFoundError: 运行不存在
        """
        run = await self.db.get(CoScientistRun, run_id)
        if not run:
            raise NotFoundError(
                f"Co-Scientist 运行不存在: {run_id}",
                details={"run_id": str(run_id)},
            )

        hypotheses = (
            await self.db.execute(
                select(Hypothesis)
                .where(Hypothesis.coscientist_run_id == run_id)
                .order_by(
                    Hypothesis.rank.asc().nullslast(),
                    Hypothesis.elo_score.desc().nullslast(),
                )
                .limit(top_n)
            )
        ).scalars().all()

        debates = (
            await self.db.execute(
                select(CoScientistDebateLog)
                .where(CoScientistDebateLog.run_id == run_id)
                .order_by(CoScientistDebateLog.round_num.asc())
            )
        ).scalars().all()

        lines: List[str] = []
        # 标题
        lines.append(
            f"# Co-Scientist 运行报告 — {_CASE_DISPLAY.get(run.case_type, '自定义')}"
        )
        lines.append("")
        lines.append(
            f"> 生成时间: {datetime.now(timezone.utc).isoformat()}"
        )
        lines.append("")

        # 1. 基本信息
        lines.append("## 1. 基本信息")
        lines.append("")
        lines.append(f"- **运行 ID**: `{run.id}`")
        lines.append(f"- **状态**: {run.status}")
        lines.append(f"- **案例类型**: {_CASE_DISPLAY.get(run.case_type, run.case_type or 'N/A')}")
        lines.append(f"- **当前阶段**: {run.current_phase or 'N/A'}")
        lines.append(f"- **运行轮次**: {run.current_round}/{run.max_rounds}")
        if run.started_at:
            lines.append(f"- **开始时间**: {run.started_at.isoformat()}")
        if run.completed_at:
            lines.append(f"- **完成时间**: {run.completed_at.isoformat()}")
        if run.duration_sec is not None:
            lines.append(f"- **耗时**: {run.duration_sec:.1f} 秒")
        lines.append("")
        lines.append("### 研究目标")
        lines.append("")
        lines.append(f"> {run.research_goal}")
        lines.append("")

        # 2. 假设排名
        lines.append(f"## 2. 假设排名（Top {len(hypotheses)}）")
        lines.append("")
        if hypotheses:
            lines.append(
                "| 排名 | 名称 | Elo | 策略 | 新颖性 | 可信度 | 可测性 | 安全性 | 状态 |"
            )
            lines.append("|------|------|-----|------|--------|--------|--------|--------|------|")
            for h in hypotheses:
                rank_str = f"#{h.rank}" if h.rank is not None else "N/A"
                elo_str = f"{h.elo_score:.0f}" if h.elo_score is not None else "N/A"
                nov = f"{h.novelty_score:.1f}" if h.novelty_score is not None else "-"
                plau = f"{h.plausibility_score:.1f}" if h.plausibility_score is not None else "-"
                test = f"{h.testability_score:.1f}" if h.testability_score is not None else "-"
                safe = f"{h.safety_score:.1f}" if h.safety_score is not None else "-"
                name = (h.name or "N/A")[:60]
                lines.append(
                    f"| {rank_str} | {name} | {elo_str} | {h.evolution_strategy or 'initial'} | "
                    f"{nov} | {plau} | {test} | {safe} | {h.status} |"
                )
        else:
            lines.append("_暂无假设数据_")
        lines.append("")

        # 3. 辩论摘要
        lines.append("## 3. 辩论摘要")
        lines.append("")
        if debates:
            lines.append("| 轮次 | 共识度 | 机制一致 | 摘要 |")
            lines.append("|------|--------|----------|------|")
            for d in debates:
                consensus = (
                    f"{d.consensus_score:.3f}"
                    if d.consensus_score is not None
                    else "N/A"
                )
                agreed = "✓" if d.mechanism_agreed else "✗"
                summary = (
                    (d.judge_assessment or d.proponent_argument or "")[:80]
                )
                lines.append(f"| {d.round_num} | {consensus} | {agreed} | {summary} |")
        else:
            lines.append("_暂无辩论记录_")
        lines.append("")

        # 4. 元评审
        if run.meta_review:
            lines.append("## 4. 元评审报告")
            lines.append("")
            lines.append(run.meta_review)
            lines.append("")

        # 5. 成本与资源
        lines.append("## 5. 资源消耗")
        lines.append("")
        if run.total_cost_usd is not None:
            lines.append(f"- **总成本**: ${run.total_cost_usd:.6f}")
        if run.total_token_usage:
            usage = run.total_token_usage
            lines.append(
                f"- **Token 用量**: prompt={usage.get('prompt', 0)}, "
                f"completion={usage.get('completion', 0)}, "
                f"total={usage.get('total', 0)}"
            )
        if run.error_message:
            lines.append(f"- **错误信息**: {run.error_message}")
        lines.append("")

        # 6. 专家反馈
        if run.expert_feedback:
            lines.append("## 6. 专家反馈历史")
            lines.append("")
            for fb in run.expert_feedback:
                round_num = fb.get("round", "?")
                feedback_text = fb.get("feedback_text", "")
                feedback_type = fb.get("feedback_type", "N/A")
                lines.append(f"- **轮次 {round_num}** ({feedback_type}): {feedback_text}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            f"*本报告由 AI 药物研发平台 Co-Scientist 引擎自动生成 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*"
        )

        return "\n".join(lines)


__all__ = [
    "CoScientistSDTMExporter",
    "CoScientistFHIRExporter",
    "CoScientistMarkdownExporter",
]
