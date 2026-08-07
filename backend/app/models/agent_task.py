"""Agent 任务模型 — 单条用户消息触发的 ReAct 执行单元

设计来源：2026-07-18-agent-functional-design.md §5
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class TaskStatus:
    """任务状态枚举 — 状态机见设计文档 §2"""
    PENDING = "pending"                    # 已创建未启动
    PLANNING = "planning"                  # Planner 生成 DAG 中
    RUNNING = "running"                    # ReAct 主循环执行中
    AWAITING_CONFIRMATION = "awaiting"     # 等待用户确认副作用操作
    COMPLETED = "completed"                # 正常完成
    FAILED = "failed"                      # 执行失败
    CANCELLED = "cancelled"                # 用户取消


# 终态集合（用于查询与清理）
TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class AgentTask(Base, UUIDMixin, TimestampMixin):
    """Agent 任务 — 一次完整的 ReAct 推理执行

    生命周期：pending → planning → running → (awaiting)* → completed/failed/cancelled
    包含规划结果（plan）、执行结果（result）、错误信息（error）、
    token 用量与成本（用于预算控制）。
    """

    __tablename__ = "agent_tasks"
    __table_args__ = (
        # 会话内活跃任务查询
        Index("ix_agent_tasks_session_status", "session_id", "status"),
        # 用户级任务查询（如"我的任务"列表）
        Index("ix_agent_tasks_user_status", "user_id", "status"),
        # 子任务查询（DAG 节点关系）
        Index("ix_agent_tasks_parent", "parent_task_id"),
    )

    session_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=False, index=True
    )
    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    parent_task_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("agent_tasks.id"), nullable=True
    )

    # 用户原始问题
    query: Mapped[str] = mapped_column(Text, nullable=False)

    # 规划结果：{steps: [{id, tool, args, depends_on}], parallel_layers: [[id,...]]}
    plan: Mapped[Optional[dict]] = mapped_column(JSON)

    # 执行状态
    status: Mapped[str] = mapped_column(
        String(20), default=TaskStatus.PENDING, nullable=False, index=True
    )
    current_step: Mapped[Optional[int]] = mapped_column(Integer)

    # 结果与错误
    result: Mapped[Optional[dict]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)

    # 计量
    started_at: Mapped[Optional[str]] = mapped_column(String(40))
    completed_at: Mapped[Optional[str]] = mapped_column(String(40))
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON)  # {prompt, completion, total}
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float)

    # 关系
    session: Mapped["AgentSession"] = relationship(
        "AgentSession", back_populates="tasks"
    )
    # 自引用：子任务列表
    subtasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask",
        backref="parent",
        remote_side="AgentTask.id",
        foreign_keys="AgentTask.parent_task_id",
    )

    def __repr__(self) -> str:
        return f"<AgentTask {self.id} status={self.status} query={self.query[:50]!r}>"
