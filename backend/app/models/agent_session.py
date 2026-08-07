"""Agent 会话模型 — 跨多轮对话的上下文容器

设计来源：2026-07-18-agent-functional-design.md §5
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class SessionStatus:
    """会话状态枚举"""
    ACTIVE = "active"          # 活跃中，可继续对话
    ARCHIVED = "archived"      # 已归档，只读
    DELETED = "deleted"        # 已软删除，对用户不可见


class AgentSession(Base, UUIDMixin, TimestampMixin):
    """Agent 会话 — 一个用户的连续对话上下文

    一个会话可包含多个 AgentTask（每条用户消息对应一个任务）。
    上下文存储在 context JSON 字段，结构：
    {
        "messages": [{"role": "user|assistant|tool", "content": "...",
                       "tool_calls": [...], "tool_results": [...], "ts": "..."}],
        "summary": "历史摘要（压缩后）",
        "token_count": 1234
    }
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        # 用户活跃会话查询：列出某用户的活跃会话
        Index("ix_agent_sessions_user_status", "user_id", "status"),
        # 按最后消息时间排序会话列表
        Index("ix_agent_sessions_last_msg", "last_message_at"),
        # 项目级会话过滤
        Index("ix_agent_sessions_project", "project_id"),
    )

    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=SessionStatus.ACTIVE, nullable=False
    )
    context: Mapped[Optional[dict]] = mapped_column(
        JSON, default=lambda: {"messages": [], "summary": None, "token_count": 0}
    )
    last_message_at: Mapped[Optional[str]] = mapped_column(String(40))
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    # 关联统一智能会话（agent 模式作为 UnifiedSession 的子会话）
    # nullable 向后兼容：旧 AgentSession 记录无此字段，UnifiedOrchestrator 可独立运行
    unified_session_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("unified_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 反向关系
    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentSession {self.id} user={self.user_id} status={self.status}>"
