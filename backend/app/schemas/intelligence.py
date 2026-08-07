"""统一智能系统 API Schemas — 22 个端点的请求/响应模型

覆盖五大功能域：
1. 会话管理（4）：创建/列表/详情/归档
2. 统一对话（3）：对话/流式/强制模式
3. 上下文与追溯（5）：上下文/追溯/步骤树/成本/决策链
4. 证据收集与分析（4）：项目证据/实体上下文/解读/数据集解读
5. 多模态与规则引擎（6）：标准化/视觉解析/规则列表/详情/执行/验证
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


# ========== 1. 会话管理 ==========

class SessionCreate(BaseModel):
    """创建统一会话"""
    title: str = Field("新会话", min_length=1, max_length=200, description="会话标题")
    project_id: Optional[UUID] = Field(None, description="关联项目 ID")
    primary_mode: str = Field("auto", description="主模式: chat/reasoning/agent/auto")


class SessionResponse(BaseSchema):
    """会话响应"""
    id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    title: str
    status: str
    primary_mode: str
    context: Optional[Dict[str, Any]] = None
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseSchema):
    """会话列表响应"""
    items: List[SessionResponse]
    total: int


class SessionArchive(BaseModel):
    """归档会话请求"""
    status: str = Field("archived", description="目标状态: archived/deleted")


# ========== 2. 统一对话 ==========

class ChatRequest(BaseModel):
    """统一对话请求"""
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    project_id: Optional[UUID] = Field(None, description="项目 ID（覆盖会话）")
    force_mode: Optional[str] = Field(None, description="强制模式: chat/reasoning/agent/hybrid")
    capability_hint: Optional[str] = Field(None, description="能力提示: qa/reasoning/agent/auto（Agent网关使用）")
    tier: Optional[str] = Field(None, description="档位: turbo/standard/deep,None 或 auto 时智能推荐")


class ChatResponse(BaseSchema):
    """统一对话响应"""
    answer: str = Field("", description="助手回复")
    mode: str = Field("chat", description="实际路由模式")
    intent: Optional[Dict[str, Any]] = None
    session_id: str
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    tier: str = Field("standard", description="实际使用的档位")
    tier_reason: Optional[str] = Field(None, description="档位选择原因")


class TierSuggestRequest(BaseModel):
    """档位推荐请求"""
    message: str = Field(..., min_length=1, max_length=5000, description="用户消息")


class TierSuggestResponse(BaseSchema):
    """档位推荐响应"""
    tier: str = Field(..., description="推荐档位 turbo/standard/deep")
    reason: str = Field("", description="推荐原因")
    confidence: float = Field(0.0, description="意图置信度 0-1")
    tier_config: Dict[str, Any] = Field(default_factory=dict, description="档位配置")


class ForceModeRequest(BaseModel):
    """强制切换模式请求"""
    mode: str = Field(..., description="目标模式: chat/reasoning/agent/hybrid")


# ========== 3. 上下文与追溯 ==========

class ContextMemoryItem(BaseSchema):
    """上下文记忆条目"""
    id: UUID
    type: str
    content: Any
    importance: float = 0.5
    created_at: Optional[datetime] = None


class ContextResponse(BaseSchema):
    """上下文响应"""
    session_id: str
    memories: List[ContextMemoryItem]
    context_prompt: str = ""


class TraceStep(BaseSchema):
    """推理步骤"""
    id: UUID
    step_type: str
    agent_name: Optional[str] = None
    phase: Optional[str] = None
    round_num: Optional[int] = None
    decision_basis: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_sec: Optional[float] = None
    status: str = "completed"
    created_at: Optional[datetime] = None
    evidence: Optional[Dict[str, Any]] = None


class TraceResponse(BaseSchema):
    """推理追溯响应"""
    session_id: str
    total_steps: int
    traces: List[TraceStep]


class TraceTreeResponse(BaseSchema):
    """步骤树响应"""
    roots: List[Dict[str, Any]]
    total_steps: int
    total_cost: float = 0.0


class CostBreakdownResponse(BaseSchema):
    """成本分解响应"""
    total_cost: float = 0.0
    total_tokens: int = 0
    by_agent: Dict[str, float] = Field(default_factory=dict)
    by_phase: Dict[str, float] = Field(default_factory=dict)
    by_step_type: Dict[str, float] = Field(default_factory=dict)


class DecisionChainResponse(BaseSchema):
    """决策链响应"""
    decisions: List[Dict[str, Any]]


# ========== 4. 证据收集与分析 ==========

class EvidenceCollectRequest(BaseModel):
    """证据收集请求"""
    project_id: Optional[UUID] = Field(None, description="项目 ID")
    trigger_event: Optional[str] = Field(None, description="触发事件类型")
    entity_id: Optional[UUID] = Field(None, description="触发实体 ID")
    extra_evidence: Optional[str] = Field(None, description="额外证据文本")


class EvidenceSourceItem(BaseSchema):
    """证据来源条目"""
    source_type: str
    count: int
    detail: str = ""
    snippets_kept: List[str] = Field(default_factory=list, description="保留的top-3命中片段原文（限长100字）")


class EvidenceResponse(BaseSchema):
    """证据收集响应"""
    text: str = ""
    sources: List[EvidenceSourceItem] = Field(default_factory=list)
    total_items: int = 0
    project_id: Optional[str] = None
    entity_id: Optional[str] = None
    trigger_event: Optional[str] = None


class AnalysisInterpretRequest(BaseModel):
    """解读请求"""
    message: str = Field(..., min_length=1, description="分析目标/问题")
    analysis_data: Optional[Dict[str, Any]] = Field(None, description="已有分析数据")
    project_id: Optional[UUID] = Field(None, description="项目 ID")
    intent: Optional[str] = Field(None, description="指定意图")


class AnalysisInterpretResponse(BaseSchema):
    """解读响应"""
    intent: str
    conclusion: str
    hypothesis: str
    recommendations: List[str] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    model: str = ""
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    evidence_summary: Optional[Dict[str, Any]] = None


class DatasetInterpretRequest(BaseModel):
    """数据集解读请求"""
    message: Optional[str] = Field(None, description="解读方向（可选）")
    project_id: Optional[UUID] = Field(None, description="项目 ID（补充上下文）")


# ========== 5. 多模态与规则引擎 ==========

class MultimodalNormalizeRequest(BaseModel):
    """多模态标准化请求"""
    text: Optional[str] = Field(None, description="文本输入")
    image_paths: Optional[List[str]] = Field(None, description="本地图像文件路径列表")
    image_urls: Optional[List[str]] = Field(None, description="图像 URL 列表")
    image_base64: Optional[List[str]] = Field(None, description="图像 base64 编码列表")
    file_paths: Optional[List[str]] = Field(None, description="文件路径列表")
    structured_data: Optional[Dict[str, Any]] = Field(None, description="结构化数据")


class MultimodalNormalizeResponse(BaseSchema):
    """多模态标准化响应"""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    primary_text: str = ""
    has_image: bool = False
    modalities: List[str] = Field(default_factory=list)
    textualized: str = ""


class VisionAnalyzeRequest(BaseModel):
    """视觉解析请求"""
    image_data_uri: str = Field(..., description="图像数据 URI 或 URL")
    prompt: str = Field(..., description="分析提示词")
    analysis_type: Optional[str] = Field(
        None, description="分析类型: pathology/protein_structure/molecule_structure/chart/general"
    )
    focus: Optional[str] = Field(None, description="关注焦点")


class VisionAnalyzeResponse(BaseSchema):
    """视觉解析响应"""
    description: str
    model: str = ""
    usage: Dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    duration_sec: float = 0.0


class RuleResponse(BaseSchema):
    """规则详情响应"""
    id: str
    name: str
    when: Dict[str, Any]
    then: List[Dict[str, Any]]
    priority: int = 0
    enabled: bool = True
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class RuleSetResponse(BaseSchema):
    """规则集响应"""
    name: str
    version: str = "1.0"
    description: Optional[str] = None
    rules: List[RuleResponse] = Field(default_factory=list)


class RuleListResponse(BaseSchema):
    """规则列表响应"""
    presets: List[str] = Field(default_factory=list)
    rulesets: List[RuleSetResponse] = Field(default_factory=list)
    total_rules: int = 0


class RuleExecuteRequest(BaseModel):
    """规则执行请求"""
    preset: Optional[str] = Field(None, description="内置 preset 名称")
    yaml_content: Optional[str] = Field(None, description="自定义 YAML 内容（与 preset 二选一）")
    context: Dict[str, Any] = Field(..., description="求值上下文")
    tags: Optional[List[str]] = Field(None, description="仅执行含指定标签的规则")


class RuleExecutionResultItem(BaseSchema):
    """单条规则执行结果"""
    rule_id: str
    rule_name: str
    matched: bool
    actions_executed: int = 0
    outputs: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class RuleExecuteResponse(BaseSchema):
    """规则执行响应"""
    ruleset_name: str
    total_rules: int
    matched_rules: int
    executed_actions: int
    results: List[RuleExecutionResultItem]
    context_changes: Dict[str, Any] = Field(default_factory=dict)
    duration_sec: float = 0.0


class RuleValidateRequest(BaseModel):
    """规则验证请求"""
    yaml_content: str = Field(..., description="待验证的 YAML 内容")


class RuleValidateResponse(BaseSchema):
    """规则验证响应"""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    rules_count: int = 0
    ruleset_name: Optional[str] = None


__all__ = [
    # 会话管理
    "SessionCreate", "SessionResponse", "SessionListResponse", "SessionArchive",
    # 统一对话
    "ChatRequest", "ChatResponse", "TierSuggestRequest", "TierSuggestResponse", "ForceModeRequest",
    # 上下文与追溯
    "ContextMemoryItem", "ContextResponse", "TraceStep", "TraceResponse",
    "TraceTreeResponse", "CostBreakdownResponse", "DecisionChainResponse",
    # 证据收集与分析
    "EvidenceCollectRequest", "EvidenceSourceItem", "EvidenceResponse",
    "AnalysisInterpretRequest", "AnalysisInterpretResponse",
    "DatasetInterpretRequest",
    # 多模态与规则引擎
    "MultimodalNormalizeRequest", "MultimodalNormalizeResponse",
    "VisionAnalyzeRequest", "VisionAnalyzeResponse",
    "RuleResponse", "RuleSetResponse", "RuleListResponse",
    "RuleExecuteRequest", "RuleExecuteResponse",
    "RuleValidateRequest", "RuleValidateResponse",
]
