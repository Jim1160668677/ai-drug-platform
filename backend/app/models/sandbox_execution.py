"""沙箱执行记录模型 — 代码执行工具的不可篡改审计

设计来源：2026-07-18-agent-functional-design.md §5
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SandboxStatus:
    """沙箱执行状态枚举"""
    QUEUED = "queued"        # 已入队等待执行
    RUNNING = "running"      # 容器执行中
    COMPLETED = "completed"  # 正常结束（exit_code 可能非 0）
    FAILED = "failed"        # 启动失败或异常终止
    TIMEOUT = "timeout"      # 超时强杀
    KILLED = "killed"        # 用户/系统主动杀掉


class SandboxExecution(Base, UUIDMixin, TimestampMixin):
    """沙箱执行记录 — 每次代码执行的完整审计

    不可篡改：建议在数据库层面通过触发器防止 UPDATE/DELETE（与 AuditLog 同策略）。
    """

    __tablename__ = "sandbox_executions"
    __table_args__ = (
        # 按任务查询其所有沙箱执行
        Index("ix_sandbox_task", "task_id"),
        # 按用户审计
        Index("ix_sandbox_user_created", "user_id", "created_at"),
        # 按状态过滤（如找出所有 timeout 的执行）
        Index("ix_sandbox_status", "status"),
    )

    task_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("agent_tasks.id"), nullable=True, index=True
    )
    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # 代码与语言
    code: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="python", nullable=False)
    stdin: Mapped[Optional[str]] = mapped_column(Text)

    # 执行结果
    stdout: Mapped[Optional[str]] = mapped_column(Text)
    stderr: Mapped[Optional[str]] = mapped_column(Text)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer)

    # 资源使用
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    memory_kb: Mapped[Optional[int]] = mapped_column(Integer)

    # 容器信息
    container_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), default=SandboxStatus.QUEUED, nullable=False
    )

    # 额外元数据（如镜像版本、资源限制配置）
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)

    def __repr__(self) -> str:
        return f"<SandboxExecution {self.id} status={self.status} lang={self.language}>"
