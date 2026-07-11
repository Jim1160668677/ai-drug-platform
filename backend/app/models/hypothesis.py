"""假设模型 — 多假设并行管理（Hypothesis Sandbox）+ 假设分析记录"""
from decimal import Decimal
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class HypothesisStatus:
    DRAFT = "draft"            # 草稿
    ANALYZING = "analyzing"    # 分析中
    COMPLETED = "completed"    # 已完成
    MERGED = "merged"          # 已合并
    ARCHIVED = "archived"      # 已归档
    ELIMINATED = "eliminated"  # 已淘汰（P1 新增 — 对齐设计规范）


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

    # 关联
    project = relationship("Project", back_populates="hypotheses")
    analyses: Mapped[List["HypothesisAnalysis"]] = relationship(
        "HypothesisAnalysis", back_populates="hypothesis", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Hypothesis {self.name} ({self.status})>"


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
