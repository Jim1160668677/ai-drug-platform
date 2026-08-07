"""推理追溯模型 — 推理过程可追溯（论文核心组件）

设计来源：Nature Co-Scientist 论文的「推理过程可追溯性」要求 + 用户需求。
解决现有系统推理过程无持久化追溯、依赖内存事件流、运行结束即丢失的痛点（缺口 #4）。

与 ProgressTracker 事件流的关系：
- 事件流（内存，限 1000 条）：实时推送 WebSocket，运行结束即丢失
- reasoning_trace（DB 永久）：持久化每个 agent 调用 / LLM 调用 / 决策点
- 通过 trace_callback 桥接：ProgressTracker.emit 时同步写 trace

记录粒度：
- 每个 agent 调用（agent_name + input_data + output_data）
- 每次 LLM 调用（prompt_tokens + completion_tokens + cost_usd + llm_call_id）
- 每个决策点（decision_basis + 选择的分支）
- 每个 phase/round 边界（phase_start / phase_end / round_start / round_end）
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class StepType:
    """推理步骤类型枚举

    覆盖推理全过程的关键节点：
    - 消息类：user_message / assistant_message
    - 调用类：agent_call / llm_call / tool_call
    - 决策类：decision_point（含 decision_basis）
    - 边界类：phase_start / phase_end / round_start / round_end
    - 算法类：debate / ranking / evolution
    - 反馈类：feedback
    """
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    AGENT_CALL = "agent_call"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    DECISION_POINT = "decision_point"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    ROUND_START = "round_start"
    ROUND_END = "round_end"
    DEBATE = "debate"
    RANKING = "ranking"
    EVOLUTION = "evolution"
    FEEDBACK = "feedback"


class TraceStatus:
    """推理步骤状态枚举"""
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReasoningTrace(Base, UUIDMixin, TimestampMixin):
    """推理追溯记录 — 一个不可变的推理步骤

    设计原则：
    - 不可变追加（append-only）：步骤一旦写入不可修改，保证推理过程可审计
    - 树形结构：parent_step_id 构建步骤树（如 agent_call 下挂 llm_call + tool_call）
    - 成本可观测：prompt_tokens / completion_tokens / cost_usd 支持成本分解查询
    - 决策可追溯：decision_basis 记录为什么选择此分支（论文要求）

    input_data / output_data JSON 结构因 step_type 而异：
    - agent_call: {"agent_name": "...", "task": "..."} / {"result": ..., "hypotheses": [...]}
    - llm_call: {"messages": [...], "model": "..."} / {"content": "...", "usage": {...}}
    - tool_call: {"tool": "...", "args": {...}} / {"result": ...}
    - decision_point: {"options": [...], "selected": "..."} / {"chosen": "...", "reason": "..."}
    - debate: {"hypothesis_id": uuid, "pro": "...", "con": "..."} / {"verdict": "...", "score": float}
    """

    __tablename__ = "reasoning_trace"
    __table_args__ = (
        # 运行级追溯查询：按时间正序获取某次推理的完整 trace
        Index("ix_reasoning_trace_run_created", "run_id", "created_at"),
        # 会话级追溯查询：跨运行获取会话 trace
        Index("ix_reasoning_trace_session_created", "session_id", "created_at"),
        # 步骤类型过滤：快速定位某类步骤（如所有 decision_point）
        Index("ix_reasoning_trace_step_type", "step_type"),
        # 父步骤查询：构建步骤树
        Index("ix_reasoning_trace_parent", "parent_step_id"),
        # agent 维度统计：分析某 agent 的调用频率与成本
        Index("ix_reasoning_trace_agent", "agent_name"),
    )

    # 关联键（session_id / run_id 至少一个）
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    session_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("unified_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 父步骤（构建步骤树，如 agent_call → llm_call + tool_call）
    parent_step_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("reasoning_trace.id", ondelete="SET NULL"), nullable=True
    )

    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Co-Scientist 7 阶段：generation / proximity / reflection / debate / ranking / evolution / meta_review
    phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    round_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # LLM 调用关联（step_type=llm_call 时填写）
    llm_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 决策依据（step_type=decision_point 时填写，论文要求可追溯）
    decision_basis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 成本与计量
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default=TraceStatus.COMPLETED, nullable=False
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 关联
    session = relationship(
        "UnifiedSession",
        back_populates="reasoning_traces",
        foreign_keys=[session_id],
    )
    parent = relationship(
        "ReasoningTrace",
        remote_side="ReasoningTrace.id",
        backref="children",
        foreign_keys=[parent_step_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ReasoningTrace {self.id} type={self.step_type} "
            f"agent={self.agent_name} phase={self.phase} round={self.round_num} "
            f"status={self.status} cost=${self.cost_usd or 0:.4f}>"
        )
