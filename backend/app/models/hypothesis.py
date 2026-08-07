"""假设模型 — 多假设并行管理（Hypothesis Sandbox）+ 假设分析记录 + Co-Scientist 扩展"""
from decimal import Decimal
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class HypothesisStatus:
    DRAFT = "draft"            # 草稿
    ANALYZING = "analyzing"    # 分析中
    COMPLETED = "completed"    # 已完成
    MERGED = "merged"          # 已合并
    ARCHIVED = "archived"      # 已归档
    ELIMINATED = "eliminated"  # 已淘汰（P1 新增 — 对齐设计规范）
    # Co-Scientist 扩展状态
    DEBATING = "debating"            # 辩论中
    EVOLVING = "evolving"            # 进化中
    ELIMINATED_BY_EXPERT = "eliminated_by_expert"  # 被专家否决


class EvolutionStrategy:
    """假设进化策略枚举（Co-Scientist）"""
    INITIAL = "initial"                  # 初始假设（非进化产生）
    ENHANCEMENT = "enhancement"          # 增强：基于 flaws 改进
    COMBINATION = "combination"          # 合并：融合多个假设
    SIMPLIFICATION = "simplification"    # 简化：降低复杂度


class Hypothesis(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "hypotheses"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    mechanism: Mapped[Optional[str]] = mapped_column(Text)  # 疾病机制假设
    strategy: Mapped[Optional[str]] = mapped_column(Text)  # 治疗策略方向
    status: Mapped[str] = mapped_column(String(20), default=HypothesisStatus.DRAFT)
    analysis_config: Mapped[Optional[dict]] = mapped_column(JSON)  # 分析配置
    analysis_result: Mapped[Optional[dict]] = mapped_column(JSON)  # 分析结果
    target_list: Mapped[Optional[list]] = mapped_column(JSON)  # 候选靶点列表
    forced_deep_analysis: Mapped[Optional[bool]] = mapped_column(default=False)  # 创始人强制深度分析
    force_reason: Mapped[Optional[str]] = mapped_column(Text)  # 强制分析理由
    created_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))

    # ===== Co-Scientist 扩展字段（新增字段，均 nullable 向后兼容）=====
    elo_score: Mapped[Optional[float]] = mapped_column(
        Float, default=1000.0, nullable=True
    )  # Elo 锦标赛评分（初始 1000）
    experimental_elo_adjustment: Mapped[Optional[float]] = mapped_column(
        Float, default=0.0, nullable=True
    )  # 实验驱动的 Elo 调整量（与 LLM 评分分离，展示层区分）
    experimental_validation_count: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, nullable=True
    )  # 已关联的验证实验数量
    novelty_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 新颖性 0-10
    plausibility_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 可信度 0-10
    testability_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 可测试性 0-10
    safety_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 安全性 0-10
    parent_ids: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True
    )  # 父假设 ID 列表（进化树）
    evolution_strategy: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # enhancement/combination/simplification/initial
    evolution_history: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True
    )  # [{round, strategy, change_summary, from_elo, to_elo}]
    debate_log: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True
    )  # [{round, proponent, opponent, judge, consensus}]
    critique_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # ReflectionAgent 的批判摘要
    coscientist_run_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("coscientist_runs.id"), nullable=True, index=True
    )  # 关联 Co-Scientist 运行
    rank: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 当前排名（Elo Tournament 产出）

    # 关联
    project = relationship("Project", back_populates="hypotheses")
    analyses: Mapped[List["HypothesisAnalysis"]] = relationship(
        "HypothesisAnalysis", back_populates="hypothesis", cascade="all, delete-orphan"
    )
    failure_knowledge: Mapped[List["FailureKnowledge"]] = relationship("FailureKnowledge", back_populates="hypothesis")

    def __init__(self, **kwargs):
        """初始化 — 设置 Python 层面默认值（弥补 SQLAlchemy default 仅在 DB 层生效的不足）"""
        kwargs.setdefault('elo_score', 1000.0)
        kwargs.setdefault('experimental_elo_adjustment', 0.0)
        kwargs.setdefault('experimental_validation_count', 0)
        kwargs.setdefault('status', HypothesisStatus.DRAFT)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Hypothesis {self.name} ({self.status}) elo={self.elo_score}>"


class HypothesisAnalysis(Base, UUIDMixin, TimestampMixin):
    """假设分析记录 — 每次执行 run-analysis 的详细记录

    设计来源：repowiki/zh/content/数据库设计/数据库Schema设计/分析结果模型/科学假设模型.md
    """
    __tablename__ = "hypothesis_analyses"

    hypothesis_id: Mapped[UUIDType] = mapped_column(ForeignKey("hypotheses.id"), nullable=False, index=True)
    report_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("target_reports.id"))
    analysis_tier: Mapped[str] = mapped_column(String(20), nullable=False)  # quick / deep
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    summary: Mapped[Optional[str]] = mapped_column(Text)  # 分析摘要
    result_data: Mapped[Optional[dict]] = mapped_column(JSON)  # 详细结果数据

    # 关联
    hypothesis = relationship("Hypothesis", back_populates="analyses")

    def __repr__(self) -> str:
        return f"<HypothesisAnalysis {self.hypothesis_id} (tier={self.analysis_tier})>"
