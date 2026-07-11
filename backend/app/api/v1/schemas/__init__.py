"""API 请求/响应模型"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List
from datetime import datetime
from uuid import UUID

# 统一响应信封（repowiki 设计规范要求）
from app.schemas.common import (
    ApiResponse,
    PagedResponse,
    ResponseMeta,
    PagedMeta,
    ErrorDetail,
    ErrorResponse,
    success_response,
    paged_response,
    error_response,
)


class BaseSchema(BaseModel):
    """基础响应模型"""
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class TokenResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    name: str
    email: str


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: str = "researcher"
    organization: Optional[str] = None


class UserResponse(BaseSchema):
    id: UUID
    email: str
    name: str
    role: str
    organization: Optional[str]
    is_active: bool
    created_at: datetime


class UserUpdateRole(BaseModel):
    role: str = Field(..., description="新角色：founder/chief_researcher/researcher/doctor/data_engineer")


class UserUpdateStatus(BaseModel):
    is_active: bool = Field(..., description="启用/禁用")


class UserListResponse(BaseSchema):
    items: List[UserResponse]
    total: int
    skip: int
    limit: int


class ProjectCreate(BaseModel):
    name: str
    patient_pseudonym: Optional[str] = None
    cancer_type: Optional[str] = None
    stage: Optional[str] = None
    description: Optional[str] = None


class ProjectResponse(BaseSchema):
    id: UUID
    name: str
    patient_pseudonym: Optional[str]
    cancer_type: Optional[str]
    stage: Optional[str]
    description: Optional[str]
    status: str
    owner_id: UUID
    created_at: datetime


class DatasetResponse(BaseSchema):
    id: UUID
    project_id: UUID
    name: str
    data_type: str
    source: Optional[str]
    file_format: Optional[str]
    file_size: Optional[int]
    parse_status: str
    quality_metrics: Optional[dict]
    parsed_summary: Optional[dict]
    created_at: datetime


class TargetResponse(BaseSchema):
    id: UUID
    project_id: UUID
    gene_symbol: str
    gene_name: Optional[str]
    evidence_grade: str
    confidence_score: Optional[float]
    source: Optional[str]
    annotation: Optional[dict]
    pathway: Optional[dict]
    approved_drugs: Optional[list]
    evidence_chain: Optional[dict]
    analysis_tier: Optional[str]
    created_at: datetime


class MoleculeResponse(BaseSchema):
    id: UUID
    smiles: str
    name: Optional[str]
    chembl_id: Optional[str]
    molecular_weight: Optional[float]
    logp: Optional[float]
    properties: Optional[dict]
    docking_result: Optional[dict]
    is_approved: Optional[bool]
    designed_by: Optional[str]


class HypothesisCreate(BaseModel):
    name: str
    description: Optional[str] = None
    mechanism: Optional[str] = None
    strategy: Optional[str] = None
    analysis_config: Optional[dict] = None


class HypothesisResponse(BaseSchema):
    id: UUID
    project_id: UUID
    name: str
    description: Optional[str]
    mechanism: Optional[str]
    strategy: Optional[str]
    status: str
    analysis_result: Optional[dict]
    target_list: Optional[list]
    forced_deep_analysis: Optional[bool]
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户问题")
    project_id: Optional[str] = None
    tier: str = Field("fast_screen", description="分析层级: fast_screen / deep_insight")


class ChatResponse(BaseModel):
    answer: str
    tier: str
    cost_usd: float
    duration_sec: float
    model: str
    references: Optional[List[dict]] = None
    code: Optional[str] = None


class StandardResponse(BaseModel):
    """统一响应（兼容别名 — 等价于 ApiResponse[Any]）

    注意：新代码应直接使用 ApiResponse[T]。
    本类保留是为了平滑迁移现有 16 个端点的 response_model 引用。
    """
    success: bool = True
    message: str = ""
    data: Any = None
    meta: Optional[dict] = None


# ========== LLM 配置 ==========

class LLMConfigCreate(BaseModel):
    """创建 LLM 配置"""
    name: str = Field(..., description="配置名称，如 Agnes、OpenAI、Azure")
    provider: str = Field("openai_compatible", description="提供商标识")
    access_mode: str = Field("api_only", description="访问模式: api_only/local_deploy/proxy")
    upstream_protocol: str = Field("chat_completions", description="上游协议: chat_completions/completions/anthropic")
    base_url: str = Field(..., description="基础 URL，如 https://apihub.agnes-ai.com/v1")
    api_key: str = Field(..., description="API 密钥")
    test_model: str = Field(..., description="测试用模型名，如 agnes-2.0-flash")
    fast_model: Optional[str] = Field(None, description="快速筛查模型")
    deep_model: Optional[str] = Field(None, description="深度洞察模型")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度")
    max_tokens: int = Field(2000, ge=1, le=32000, description="最大 token 数")
    timeout_sec: int = Field(60, ge=1, le=600, description="超时秒数")
    description: Optional[str] = None
    is_active: bool = Field(False, description="是否设为当前激活")


class LLMConfigUpdate(BaseModel):
    """更新 LLM 配置（部分字段）"""
    name: Optional[str] = None
    provider: Optional[str] = None
    access_mode: Optional[str] = None
    upstream_protocol: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    test_model: Optional[str] = None
    fast_model: Optional[str] = None
    deep_model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    timeout_sec: Optional[int] = Field(None, ge=1, le=600)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class LLMConfigResponse(BaseSchema):
    """LLM 配置响应（API key 脱敏）"""
    id: UUID
    name: str
    provider: str
    access_mode: str
    upstream_protocol: str
    base_url: str
    api_key_masked: str = Field(..., description="API key 脱敏后显示")
    test_model: str
    fast_model: Optional[str]
    deep_model: Optional[str]
    temperature: float
    max_tokens: int
    timeout_sec: int
    is_active: bool
    description: Optional[str]
    last_test_at: Optional[datetime]
    last_test_success: Optional[bool]
    last_test_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class LLMTestRequest(BaseModel):
    """测试 LLM 配置连通性请求"""
    config_id: Optional[UUID] = Field(None, description="不传则测试当前激活配置")
    custom_message: Optional[str] = Field(None, description="自定义测试消息，默认 ping")


class LLMTestResponse(BaseModel):
    """测试 LLM 配置连通性响应"""
    success: bool
    message: str
    model: Optional[str] = None
    response_text: Optional[str] = None
    duration_sec: Optional[float] = None
