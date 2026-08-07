"""上下文记忆模型 — 持久化 Context Memory（论文核心组件）

设计来源：Nature Co-Scientist 论文的「持久化 Context Memory」架构。
解决现有系统推理过程无持久化、运行结束即丢失的痛点（缺口 #4）。

核心能力：
1. 跨模式上下文共享：chat / reasoning / agent 三模式读写同一会话的记忆
2. 故障重启恢复：Supervisor 每轮写快照，重启时从最近快照恢复 hypotheses + round + context
3. 上下文压缩：importance 分级 + expires_at 自动清理，控制单会话内存 <4MB
4. 实体引用追踪：记录假设 / 靶点 / 分子 / 数据集等实体的引用关系，构建数据知识图谱
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class MemoryType:
    """上下文记忆类型枚举

    覆盖论文 Context Memory 的 7 类记忆：
    - message: 用户/助手消息（对话历史）
    - snapshot: 推理过程快照（Supervisor 每轮写一次，用于故障重启）
    - entity_ref: 实体引用（靶点/分子/假设/数据集等实体的引用记录）
    - feedback: 专家反馈（用户对假设/结果的评分与修正）
    - data_feature: 数据特征（数据集解析后的统计特征，供推理引用）
    - research_goal: 研究目标（会话级研究目标，可被规则引擎触发更新）
    - hypothesis_state: 假设状态（当前假设列表 + Elo 分数 + 排名）
    """
    MESSAGE = "message"
    SNAPSHOT = "snapshot"
    ENTITY_REF = "entity_ref"
    FEEDBACK = "feedback"
    DATA_FEATURE = "data_feature"
    RESEARCH_GOAL = "research_goal"
    HYPOTHESIS_STATE = "hypothesis_state"


class ContextMemory(Base, UUIDMixin, TimestampMixin):
    """上下文记忆条目 — 一条不可变记忆记录

    设计原则：
    - 不可变追加（append-only）：记忆一旦写入不可修改，保证推理过程可追溯
    - 重要性分级：importance 0-1，低于阈值的记忆在压缩时优先丢弃
    - 自动过期：expires_at 到期后由 cleanup_expired 清理（消息类默认 30 天，快照类默认 7 天）
    - 跨会话引用：run_id / project_id 允许跨会话检索项目级记忆

    content JSON 结构因 memory_type 而异：
    - message: {"role": "user|assistant|tool", "content": "...", "tool_calls": [...], "ts": "..."}
    - snapshot: {"round": int, "phase": str, "hypotheses": [...], "context_summary": "..."}
    - entity_ref: {"entity_type": "target|molecule|hypothesis|dataset", "entity_id": uuid, "relation": "..."}
    - feedback: {"target": uuid, "score": float, "text": "...", "constraints": [...]}
    - data_feature: {"dataset_id": uuid, "features": {...}, "summary": "..."}
    - research_goal: {"goal": "...", "constraints": [...], "updated_by": "user|rule|agent"}
    - hypothesis_state: {"hypotheses": [{"id": uuid, "text": "...", "elo": float, "rank": int}], "round": int}
    """

    __tablename__ = "context_memory"
    __table_args__ = (
        # 会话级记忆查询：按时间倒序获取会话记忆
        Index("ix_context_memory_session_type", "session_id", "memory_type"),
        # 运行级快照查询：获取某次推理运行的快照（故障重启用）
        Index("ix_context_memory_run_type", "run_id", "memory_type"),
        # 项目级记忆查询：跨会话检索项目记忆
        Index("ix_context_memory_project", "project_id"),
        # 过期清理：批量查询过期记忆
        Index("ix_context_memory_expires", "expires_at"),
    )

    # 关联键（至少 session_id / run_id 二选一）
    session_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("unified_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("coscientist_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )  # 关联 CoScientistRun（reasoning 模式）
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )  # 项目级记忆（跨会话共享）
    user_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    memory_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 记忆键（同类型内唯一标识，如 message 的序号、snapshot 的 round、entity_ref 的 entity_id）
    key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    importance: Mapped[float] = mapped_column(
        Float, default=0.5, nullable=False
    )  # 0-1，压缩时优先丢弃低重要性记忆

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # NULL 表示永不过期

    # 关联
    session = relationship(
        "UnifiedSession",
        back_populates="context_memories",
        foreign_keys=[session_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ContextMemory {self.id} type={self.memory_type} "
            f"session={self.session_id} run={self.run_id} importance={self.importance}>"
        )
