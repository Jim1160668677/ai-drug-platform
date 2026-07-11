"""工作流运行记录 — Nextflow 任务追踪"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class WorkflowStatus:
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class WorkflowRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_runs"

    project_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("projects.id"), index=True)
    pipeline_name: Mapped[str] = mapped_column(String(200), nullable=False)  # 如 scrna_pipeline
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(50))
    params: Mapped[Optional[dict]] = mapped_column(JSON)  # 运行参数
    status: Mapped[str] = mapped_column(String(20), default=WorkflowStatus.SUBMITTED, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(100))  # Nextflow run id
    trace_url: Mapped[Optional[str]] = mapped_column(String(500))  # 追踪 URL
    output_path: Mapped[Optional[str]] = mapped_column(String(1000))  # 输出路径
    duration_sec: Mapped[Optional[int]] = mapped_column()
    error: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))

    def __repr__(self) -> str:
        return f"<WorkflowRun {self.pipeline_name} ({self.status})>"
