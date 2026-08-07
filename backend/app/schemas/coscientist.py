"""Co-Scientist Pydantic Schemas - 请求/响应模型

基于 Nature 论文 Co-Scientist 多智能体科学推理引擎的 API 契约。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.coscientist_run import CaseType, RunPhase, RunStatus


# ========== 运行创建 ==========

class RunCreate(BaseModel):
    """提交研究目标，启动 Co-Scientist 运行"""
    research_goal: str = Field(..., min_length=10, max_length=5000, description="自然语言研究目标")
    project_id: Optional[UUID] = Field(None, description="关联项目 ID")
    case_type: Optional[str] = Field(None, description="案例类型: custom（自定义研究目标）。历史值 aml/liver_fibrosis/amr 已删除，仅作为字符串兼容旧记录")
    max_rounds: int = Field(5, ge=1, le=10, description="最大迭代轮数")
    initial_hypothesis_count: int = Field(5, ge=3, le=10, description="初始假设数量")
    config: Optional[Dict[str, Any]] = Field(None, description="运行配置覆盖")


class RunResponse(BaseModel):
    """运行详情响应"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    research_goal: str
    case_type: Optional[str] = None
    status: str = RunStatus.PENDING
    current_round: int = 0
    max_rounds: int = 5
    current_phase: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    # final_rankings 实际为排名后的假设列表（List），非字典；用 Any 兼容 list/dict/None
    final_rankings: Optional[Any] = None
    meta_review: Optional[str] = None
    expert_feedback: Optional[List[Dict[str, Any]]] = None
    total_cost_usd: Optional[float] = None
    duration_sec: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RunListResponse(BaseModel):
    """运行列表分页响应"""
    items: List[RunResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ========== 专家反馈 ==========

class FeedbackPayload(BaseModel):
    """专家反馈请求"""
    feedback_text: str = Field(..., min_length=1, max_length=10000, description="反馈文本")
    feedback_type: str = Field(
        ...,
        description="反馈类型: constraint(约束)/approval(认可)/rejection(否决)/new_evidence(新证据)",
    )
    target_hypothesis_id: Optional[UUID] = Field(None, description="可选：针对特定假设")


class FeedbackResponse(BaseModel):
    """反馈提交响应"""
    accepted: bool
    message: str
    applied_round: Optional[int] = None
    parsed_constraints: Optional[Dict[str, Any]] = None


# ========== 假设排名 ==========

class RankedHypothesisView(BaseModel):
    """排名假设视图"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    mechanism: Optional[str] = None
    elo_score: float = 1000.0
    novelty_score: Optional[float] = None
    plausibility_score: Optional[float] = None
    testability_score: Optional[float] = None
    safety_score: Optional[float] = None
    rank: Optional[int] = None
    evolution_strategy: Optional[str] = None
    parent_ids: Optional[List[str]] = None
    critique_summary: Optional[str] = None
    status: str = "draft"
    experimental_elo_adjustment: Optional[float] = None
    experimental_validation_count: Optional[int] = None


class RankingsResponse(BaseModel):
    """排名响应"""
    run_id: UUID
    round_num: int
    rankings: List[RankedHypothesisView]
    total_hypotheses: int


# ========== 辩论日志 ==========

class DebateLogView(BaseModel):
    """辩论日志视图"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    hypothesis_id: UUID
    round_num: int
    proponent_argument: str
    opponent_argument: str
    judge_assessment: Optional[str] = None
    consensus_score: Optional[float] = None
    mechanism_agreed: Optional[bool] = None
    refined_hypothesis: Optional[str] = None
    cost_usd: Optional[float] = None
    created_at: datetime


class DebateListResponse(BaseModel):
    """辩论日志列表响应"""
    run_id: UUID
    debates: List[DebateLogView]
    total: int


# ========== 进化树 ==========

class EvolutionNode(BaseModel):
    """进化树节点"""
    hypothesis_id: str
    name: str
    evolution_strategy: str
    parent_ids: List[str] = Field(default_factory=list)
    elo_score: float = 1000.0
    round_num: int = 0
    rank: Optional[int] = None


class EvolutionEdge(BaseModel):
    """进化树边"""
    from_id: str
    to_id: str
    strategy: str


class EvolutionTreeResponse(BaseModel):
    """进化树响应"""
    run_id: UUID
    nodes: List[EvolutionNode]
    edges: List[EvolutionEdge]
    total_rounds: int


# ========== Meta-review ==========

class MetaReviewResponse(BaseModel):
    """Meta-review 报告响应"""
    run_id: UUID
    meta_review: str
    final_rankings: Optional[Any] = None
    total_cost_usd: Optional[float] = None
    duration_sec: Optional[float] = None
    completed_at: Optional[datetime] = None


# ========== 案例 ==========

class CaseInfo(BaseModel):
    """案例信息"""
    case_type: str
    name: str
    description: str
    research_goal_template: str
    expected_benchmarks: Dict[str, Any]


class CaseListResponse(BaseModel):
    """案例列表响应"""
    cases: List[CaseInfo]


class CaseRunRequest(BaseModel):
    """案例运行请求"""
    project_id: Optional[UUID] = None
    max_rounds: int = Field(3, ge=1, le=10)
    custom_goal: Optional[str] = Field(None, max_length=5000, description="自定义研究目标（覆盖案例预设）")


# ========== WebSocket 事件 ==========

class CoScientistWSEvent(BaseModel):
    """Co-Scientist WebSocket 推送事件信封

    type 取值：
    - round_started: 轮次开始 {round_num, phase}
    - generation_done: 假设生成完成 {hypotheses}
    - debate_round: 辩论回合 {hypothesis_id, round, proponent, opponent, consensus}
    - elo_update: Elo 评分更新 {hypothesis_id, old_elo, new_elo, match_result}
    - evolution: 假设进化 {parent_ids, child_id, strategy}
    - ranking_updated: 排名更新 {ranked_list}
    - feedback_required: 需要专家反馈 {reason, current_hypotheses}
    - meta_review_done: Meta-review 完成 {report}
    - run_completed: 运行完成 {final_rankings}
    - error: 错误 {error, code}
    """
    type: str
    run_id: str
    timestamp: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class CoScientistWSClientMessage(BaseModel):
    """Co-Scientist WebSocket 客户端消息

    type 取值：
    - subscribe: 订阅运行进度
    - unsubscribe: 取消订阅
    - feedback: 提交专家反馈
    - cancel: 取消运行
    - ping: 心跳
    """
    type: str
    run_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


# ========== Agent 活动状态 ==========

class AgentActivity(BaseModel):
    """单个 Agent 活动状态"""
    agent_name: str
    status: str = "idle"  # idle/running/completed/failed
    current_task: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    token_usage: Optional[Dict[str, int]] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class AgentActivityFeedResponse(BaseModel):
    """Agent 活动流响应"""
    run_id: UUID
    agents: List[AgentActivity]
    current_phase: Optional[str] = None
    current_round: int = 0


# ========== AI 智能生成研究目标 ==========

class GenerateGoalRequest(BaseModel):
    """AI 生成研究目标请求"""
    topic: str = Field(..., min_length=2, max_length=500, description="研究主题关键词或描述")
    project_id: Optional[UUID] = Field(None, description="关联项目 ID（用于上下文感知）")
    case_type: Optional[str] = Field(None, description="可选：指定案例类型风格")


class GenerateGoalResponse(BaseModel):
    """AI 生成研究目标响应"""
    research_goal: str = Field(..., description="生成的研究目标文本（可直接用于创建运行）")
    suggested_case_type: Optional[str] = Field(None, description="建议的案例类型")
    suggested_max_rounds: int = Field(3, description="建议最大迭代轮数")
    suggested_initial_count: int = Field(5, description="建议初始假设数量")
    framework: List[str] = Field(default_factory=list, description="研究框架要点")
    key_questions: List[str] = Field(default_factory=list, description="关键科学问题")
    content_suggestions: List[str] = Field(default_factory=list, description="内容建议")