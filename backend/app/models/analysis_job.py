"""分析任务模型 — 分级分析策略（快速筛查 / 深度洞察）"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AnalysisTier:
    """分析层级"""
    FAST_SCREEN = "fast_screen"      # 快速筛查 (<$5/<5min)
    DEEP_INSIGHT = "deep_insight"    # 深度洞察 (<$20/<30min)


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "analysis_jobs"

    project_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("projects.id"), index=True)
    hypothesis_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("hypotheses.id"))
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)  # target_discover/repurpose/chat/dock...
    tier: Mapped[str] = mapped_column(String(20), default=AnalysisTier.FAST_SCREEN)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING, index=True)
    input_params: Mapped[Optional[dict]] = mapped_column(JSON)
    result: Mapped[Optional[dict]] = mapped_column(JSON)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)  # 实际花费
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)  # 实际耗时
    model_used: Mapped[Optional[str]] = mapped_column(String(100))  # 使用的模型
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))

    def __repr__(self) -> str:
        return f"<AnalysisJob {self.job_type} ({self.tier}/{self.status})>"
