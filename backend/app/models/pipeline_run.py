"""流水线运行记录 — 持久化追踪一键流水线执行状态"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PipelineRunStatus:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_project_status", "project_id", "status"),
        Index("ix_pipeline_runs_triggered_by", "triggered_by"),
    )

    project_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PipelineRunStatus.PENDING, nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(30), default="fast_screen", nullable=False)
    max_targets: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    molecules_per_target: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    molecule_strategy: Mapped[str] = mapped_column(String(30), default="fragment", nullable=False)
    skip_existing: Mapped[bool] = mapped_column(default=True, nullable=False)
    enable_hypothesis: Mapped[bool] = mapped_column(default=True, nullable=False)
    current_step: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    steps_status: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    completed_steps: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logs: Mapped[Optional[List[dict]]] = mapped_column(JSON, default=list, nullable=True)
    triggered_by: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<PipelineRun {self.id} project={self.project_id} status={self.status}>"

    def add_log(self, level: str, step: str, message: str, **kwargs: Any) -> None:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "step": step,
            "message": message,
        }
        if kwargs:
            log_entry["details"] = kwargs
        if self.logs is None:
            self.logs = []
        self.logs.append(log_entry)

    def update_step_status(self, step_name: str, status: str, **kwargs: Any) -> None:
        if self.steps_status is None:
            self.steps_status = {}
        self.steps_status[step_name] = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
            **kwargs,
        }
        if status in (StepStatus.SUCCESS, StepStatus.PARTIAL):
            if step_name not in (self.completed_steps or []):
                if self.completed_steps is None:
                    self.completed_steps = []
                self.completed_steps.append(step_name)

    def get_resume_point(self) -> Optional[str]:
        step_order = [
            "target_discovery",
            "molecule_generation",
            "treatment_matching",
            "hypothesis_generation",
        ]
        for step in step_order:
            step_info = (self.steps_status or {}).get(step, {})
            status = step_info.get("status", "")
            if status not in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                return step
        return None
