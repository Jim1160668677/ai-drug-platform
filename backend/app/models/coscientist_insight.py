"""Co-Scientist AI 洞察模型 — 自动化嵌入式协作层的核心数据实体

设计来源：Nature Co-Scientist 论文 "scientist-in-the-loop" 协作范式。
将科学推理引擎从"目的地页面"重构为"嵌入工作流的协作者"：
- 业务事件（数据解析/靶点发现/实验完成/对接完成/结构预测/评测完成/筛选完成/疫苗设计/基因组解读）
  自动触发推理（异步多智能体辩论）
- 推理产出的高排名假设转化为"AI 洞察"，主动推送到对应业务页面
- 用户可在业务页面原地"采纳/忽略"洞察，采纳时调用 promote 端点创建实体
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, Float, ForeignKey, Index, JSON, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class InsightType:
    """洞察类型枚举 — 对应12个模块的自动触发场景"""
    RESEARCH_DIRECTION = "research_direction"
    DRUG_REPURPOSING = "drug_repurposing"
    SYNERGY_TARGET = "synergy_target"
    HYPOTHESIS_VERIFICATION = "hypothesis_verification"
    FAILURE_ANALYSIS = "failure_analysis"
    COMBINATION_THERAPY = "combination_therapy"
    DRUGLIKENESS_OPT = "druglikeness_optimization"
    PERSONALIZED_THERAPY = "personalized_therapy"
    BINDING_MODE_ANALYSIS = "binding_mode_analysis"
    ALLOSTERIC_SITE = "allosteric_site"
    BENCHMARK_GAP = "benchmark_gap"
    CONDITIONAL_AMPLIFIER = "conditional_amplifier"
    VACCINE_OPTIMIZATION = "vaccine_optimization"


class InsightStatus:
    PENDING = "pending"
    READ = "read"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class EntityType:
    DATASET = "dataset"
    TARGET = "target"
    MOLECULE = "molecule"
    EXPERIMENT = "experiment"
    TREATMENT = "treatment"
    HYPOTHESIS = "hypothesis"
    GENOME = "genome"
    ASSESSMENT = "assessment"
    DOCKING_JOB = "docking_job"
    STRUCTURE = "structure"
    BENCHMARK = "benchmark"
    SCREENING = "screening"
    VACCINE = "vaccine"
    PROJECT = "project"


class TriggerEvent:
    DATA_PARSED = "data_parsed"
    TARGETS_DISCOVERED = "targets_discovered"
    EXPERIMENT_COMPLETED = "experiment_completed"
    EXPERIMENT_FAILED = "experiment_failed"
    TREATMENT_GENERATED = "treatment_generated"
    MOLECULE_GENERATED = "molecule_generated"
    GENOME_INTERPRETED = "genome_interpreted"
    DOCKING_COMPLETED = "docking_completed"
    STRUCTURE_PREDICTED = "structure_predicted"
    BENCHMARK_COMPLETED = "benchmark_completed"
    SCREENING_COMPLETED = "screening_completed"
    VACCINE_DESIGNED = "vaccine_designed"


TRIGGER_TO_INSIGHT_TYPE = {
    TriggerEvent.DATA_PARSED: InsightType.RESEARCH_DIRECTION,
    TriggerEvent.TARGETS_DISCOVERED: InsightType.DRUG_REPURPOSING,
    TriggerEvent.EXPERIMENT_COMPLETED: InsightType.HYPOTHESIS_VERIFICATION,
    TriggerEvent.EXPERIMENT_FAILED: InsightType.FAILURE_ANALYSIS,
    TriggerEvent.TREATMENT_GENERATED: InsightType.COMBINATION_THERAPY,
    TriggerEvent.MOLECULE_GENERATED: InsightType.DRUGLIKENESS_OPT,
    TriggerEvent.GENOME_INTERPRETED: InsightType.PERSONALIZED_THERAPY,
    TriggerEvent.DOCKING_COMPLETED: InsightType.BINDING_MODE_ANALYSIS,
    TriggerEvent.STRUCTURE_PREDICTED: InsightType.ALLOSTERIC_SITE,
    TriggerEvent.BENCHMARK_COMPLETED: InsightType.BENCHMARK_GAP,
    TriggerEvent.SCREENING_COMPLETED: InsightType.CONDITIONAL_AMPLIFIER,
    TriggerEvent.VACCINE_DESIGNED: InsightType.VACCINE_OPTIMIZATION,
}


class CoScientistInsight(Base, UUIDMixin, TimestampMixin):
    """Co-Scientist AI 洞察 — 自动推理产出的可操作建议

    表名：coscientist_insights
    来源：auto_triggered 的 CoScientistRun 完成后，由 insights 服务从高排名假设中提取
    去向：用户在业务页面采纳后，调用 promote 端点创建实体
    """

    __tablename__ = "coscientist_insights"
    __table_args__ = (
        Index("ix_insights_project_status", "project_id", "status"),
        Index("ix_insights_entity", "entity_type", "entity_id"),
        Index("ix_insights_user", "user_id"),
    )

    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True,
        comment="洞察归属用户",
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), nullable=True,
        comment="关联项目",
    )
    source_run_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("coscientist_runs.id", ondelete="SET NULL"), nullable=True,
        comment="产出此洞察的运行",
    )
    trigger_event: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="自动触发事件类型",
    )

    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="关联实体类型",
    )
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="关联实体 ID",
    )
    entity_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="关联实体名称快照",
    )

    insight_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="洞察类型",
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="洞察标题",
    )
    summary: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="洞察摘要",
    )
    details: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="洞察详情",
    )

    suggested_action: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="建议操作类型",
    )
    action_payload: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="采纳时的 promote 参数",
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, default=InsightStatus.PENDING,
        comment="洞察状态",
    )

    accepted_entity_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="采纳后创建的实体 ID",
    )
    accepted_at: Mapped[Optional[object]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="采纳时间",
    )

    confidence_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="置信度 0-1",
    )

    def __repr__(self) -> str:
        return f"<CoScientistInsight {self.insight_type}:{self.title[:30]} ({self.status})>"


__all__ = [
    "CoScientistInsight",
    "InsightType",
    "InsightStatus",
    "EntityType",
    "TriggerEvent",
    "TRIGGER_TO_INSIGHT_TYPE",
]
