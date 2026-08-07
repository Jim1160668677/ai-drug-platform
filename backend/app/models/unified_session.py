"""统一智能会话模型 — 融合 AI 问答 / 科学推理 / Agent 工作台

设计来源：Nature Co-Scientist 论文（s41586-026-10644-y）的「自然语言接口 +
持久化 Context Memory」架构。统一会话是三模式协作的根容器：

- chat 模式：单/多轮自然语言问答（复用 LLMRouter + RAG + KG + 基因组）
- reasoning 模式：多智能体科学推理（复用 Supervisor 7 阶段 + Context Memory 快照）
- agent 模式：ReAct 任务规划与执行（复用 AgentEngine + 22 工具）

统一会话通过 context_memory / reasoning_trace 实现跨模式上下文共享与推理追溯。
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UnifiedSessionStatus:
    """统一会话状态枚举"""
    ACTIVE = "active"            # 活跃中，可继续交互
    ARCHIVED = "archived"        # 已归档，只读
    DELETED = "deleted"          # 已软删除，对用户不可见


class PrimaryMode:
    """会话主模式枚举

    primary_mode 是「默认模式」，用户可通过 ModeSwitcher 临时切换；
    每条消息的实际路由模式记录在 reasoning_trace.step_type / context_memory 中。
    """
    CHAT = "chat"                # AI 问答（默认）
    REASONING = "reasoning"      # 科学推理
    AGENT = "agent"              # Agent 工作台
    AUTO = "auto"                # 自动路由（IntentRouter 决策）


class UnifiedSession(Base, UUIDMixin, TimestampMixin):
    """统一智能会话 — 融合三模式的根容器

    一个统一会话可关联：
    - 多条 context_memory（消息历史 / 快照 / 实体引用 / 反馈 / 数据特征 / 研究目标 / 假设状态）
    - 多条 reasoning_trace（每个 agent 调用 / LLM 调用 / 决策点）
    - 多个 CoScientistRun（reasoning 模式触发的运行实例，复用 CoScientistRun.session_id）
    - 多个 AgentSession（agent 模式触发的任务会话，通过 AgentSession.unified_session_id 反向关联）

    context JSON 字段缓存最近交互快照（结构同 AgentSession.context），
    完整历史持久化到 context_memory 表。
    """

    __tablename__ = "unified_sessions"
    __table_args__ = (
        # 用户活跃会话查询：列出某用户的活跃会话
        Index("ix_unified_sessions_user_status", "user_id", "status"),
        # 按最后消息时间排序会话列表
        Index("ix_unified_sessions_last_msg", "last_message_at"),
        # 项目级会话过滤
        Index("ix_unified_sessions_project", "project_id"),
    )

    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=UnifiedSessionStatus.ACTIVE, nullable=False
    )
    # 会话主模式（默认模式，可被单条消息的 force_mode 覆盖）
    primary_mode: Mapped[str] = mapped_column(
        String(20), default=PrimaryMode.AUTO, nullable=False
    )

    # 上下文缓存（最近交互快照，完整历史在 context_memory 表）
    # 结构：{"messages": [...], "summary": str|None, "token_count": int,
    #        "active_run_id": str|None, "mode_history": [...]}
    context: Mapped[Optional[dict]] = mapped_column(
        JSON, default=lambda: {"messages": [], "summary": None, "token_count": 0}
    )

    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 扩展元数据（模式偏好 / UI 状态 / 灰度开关等）
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)

    # 反向关系
    context_memories: Mapped[List["ContextMemory"]] = relationship(
        "ContextMemory",
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="ContextMemory.session_id",
    )
    reasoning_traces: Mapped[List["ReasoningTrace"]] = relationship(
        "ReasoningTrace",
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="ReasoningTrace.session_id",
    )

    def __repr__(self) -> str:
        return (
            f"<UnifiedSession {self.id} user={self.user_id} "
            f"mode={self.primary_mode} status={self.status}>"
        )
