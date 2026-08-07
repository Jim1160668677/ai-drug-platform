"""Co-Scientist 运行模型 — 研究运行实例 + 辩论日志

基于 Nature 论文 Co-Scientist 的多智能体科学推理引擎数据模型。
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class RunStatus:
    """Co-Scientist 运行状态枚举"""
    PENDING = "pending"                    # 已创建，待执行
    RUNNING = "running"                    # 执行中
    AWAITING_FEEDBACK = "awaiting_feedback"  # 等待专家反馈
    COMPLETED = "completed"                # 已完成
    FAILED = "failed"                      # 失败
    CANCELLED = "cancelled"                # 已取消


class RunPhase:
    """Co-Scientist 运行阶段枚举（7 阶段流水线）"""
    GENERATION = "generation"              # 1. 假设生成
    PROXIMITY = "proximity"                # 2. 相似度/去重
    REFLECTION = "reflection"              # 3. 评审批判
    DEBATE = "debate"                      # 4. 科学辩论
    RANKING = "ranking"                    # 5. Elo 锦标赛排名
    EVOLUTION = "evolution"                # 6. 假设进化
    META_REVIEW = "meta_review"            # 7. 高层综合


class CaseType:
    """案例类型枚举

    三个验证案例（AML/肝纤维化/AMR）已按用户要求永久删除。
    保留 CUSTOM 以支持自定义研究目标。
    历史数据中的旧 case_type 值仍可正常查询（仅作为字符串存储，无外键约束）。
    """
    CUSTOM = "custom"                      # 自定义研究目标


class CoScientistRun(Base, UUIDMixin, TimestampMixin):
    """Co-Scientist 研究运行实例

    一次完整的 Co-Scientist 运行包含多轮 Generation→Reflection→Debate→Ranking→Evolution 循环，
    最终由 MetaReview 产出综合报告。运行状态通过 WebSocket 实时推送。
    """
    __tablename__ = "coscientist_runs"
    __table_args__ = (
        Index("ix_coscientist_runs_user_status", "user_id", "status"),
        Index("ix_coscientist_runs_project", "project_id"),
    )

    user_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    session_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=True
    )  # 可选关联 Agent 会话

    research_goal: Mapped[str] = mapped_column(Text, nullable=False)  # 自然语言研究目标
    case_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # custom（历史记录可能含 aml/liver_fibrosis/amr）

    status: Mapped[str] = mapped_column(
        String(30), default=RunStatus.PENDING, nullable=False
    )
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    current_phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # 运行配置
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {initial_hyp_count, debate_rounds, convergence_threshold, elo_k_factor, ...}

    # 结果
    final_rankings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    meta_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expert_feedback: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # [{round, feedback_text, feedback_type, target_hypothesis_id, parsed_constraints}]

    # 计量
    total_token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 关联
    hypotheses: Mapped[List["Hypothesis"]] = relationship(
        "Hypothesis", backref="coscientist_run"
    )
    debate_logs: Mapped[List["CoScientistDebateLog"]] = relationship(
        "CoScientistDebateLog", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<CoScientistRun {self.id} status={self.status} "
            f"round={self.current_round}/{self.max_rounds} phase={self.current_phase}>"
        )


class CoScientistDebateLog(Base, UUIDMixin, TimestampMixin):
    """辩论日志记录 — 每场辩论一行

    记录 Scientific Debate 的正反方论据、裁判判定、共识度和修正后的假设。
    """
    __tablename__ = "coscientist_debate_logs"
    __table_args__ = (
        Index("ix_coscientist_debate_run_round", "run_id", "round_num"),
    )

    run_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("coscientist_runs.id"), nullable=False, index=True
    )
    hypothesis_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("hypotheses.id"), nullable=False, index=True
    )
    round_num: Mapped[int] = mapped_column(Integer, nullable=False)

    proponent_argument: Mapped[str] = mapped_column(Text, nullable=False)  # 正方论据
    opponent_argument: Mapped[str] = mapped_column(Text, nullable=False)   # 反方论据
    judge_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 裁判评估
    consensus_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 共识度 0-1
    mechanism_agreed: Mapped[Optional[bool]] = mapped_column(
        nullable=True
    )  # 核心机制是否达成一致

    refined_hypothesis: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # 辩论后修正的假设

    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 关联
    run = relationship("CoScientistRun", back_populates="debate_logs")

    def __repr__(self) -> str:
        return (
            f"<CoScientistDebateLog run={self.run_id} "
            f"hyp={self.hypothesis_id} round={self.round_num} "
            f"consensus={self.consensus_score}>"
        )
