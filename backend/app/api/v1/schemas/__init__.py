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
    target_id: Optional[UUID] = None
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


# ========== 用户级 LLM 配置（BYO Key）==========

class UserLLMConfigCreate(BaseModel):
    """创建用户级 LLM 配置"""
    name: str = Field(..., description="配置名称，如 豆包/DeepSeek/OpenAI")
    provider: str = Field("openai_compatible", description="提供商标识")
    base_url: str = Field(..., description="基础 URL")
    api_key: str = Field(..., description="API 密钥")
    model_name: str = Field(..., description="模型名")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(2000, ge=1, le=32000)
    timeout_sec: int = Field(60, ge=1, le=600)
    is_active: bool = Field(False, description="是否设为当前激活")


class UserLLMConfigUpdate(BaseModel):
    """更新用户级 LLM 配置"""
    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    timeout_sec: Optional[int] = Field(None, ge=1, le=600)
    is_active: Optional[bool] = None


class UserLLMConfigResponse(BaseSchema):
    """用户级 LLM 配置响应（API key 脱敏）"""
    id: UUID
    name: str
    provider: str
    base_url: str
    api_key_masked: str
    model_name: str
    temperature: float
    max_tokens: int
    timeout_sec: int
    is_active: bool
    last_test_at: Optional[datetime]
    last_test_success: Optional[bool]
    last_test_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class UserLLMTestRequest(BaseModel):
    """测试用户级 LLM 配置连通性"""
    config_id: Optional[UUID] = Field(None, description="不传则测试当前激活配置")
    custom_message: Optional[str] = Field(None, description="自定义测试消息，默认 ping")


class UserLLMTestResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None
    response_text: Optional[str] = None
    duration_sec: Optional[float] = None


# ========== 个人基因组解读模块 ==========

class TraitCreate(BaseModel):
    """创建性状"""
    name: str = Field(..., description="性状名，如 过敏易感")
    category: str = Field(..., description="性状分类")
    description: Optional[str] = None
    icon: Optional[str] = None


class TraitResponse(BaseSchema):
    """性状响应"""
    id: UUID
    name: str
    category: str
    description: Optional[str]
    icon: Optional[str]
    created_at: datetime


class SnpLocusResponse(BaseSchema):
    """SNP 位点响应"""
    id: UUID
    rsid: str
    chromosome: str
    position_grch37: Optional[int]
    position_grch38: Optional[int]
    ref_allele: Optional[str]
    alt_allele: Optional[str]
    gene_symbol: Optional[str]
    trait_id: UUID
    effect_allele: Optional[str]
    risk_genotype: Optional[str]
    effect_size: Optional[float]
    weight: float
    locus_tier: str
    population: str
    evidence_source: str
    evidence_level: str
    pmid: Optional[str]
    is_approved: bool
    created_at: datetime


class PersonalGenomeResponse(BaseSchema):
    """个人基因组文件响应"""
    id: UUID
    owner_id: UUID
    project_id: Optional[UUID]
    file_name: str
    genome_build: str
    source_format: str
    total_variants: Optional[int]
    parsed_summary: Optional[dict]
    quality_metrics: Optional[dict]
    created_at: datetime


class GenotypeMatchResponse(BaseSchema):
    """基因型匹配响应"""
    id: UUID
    personal_genome_id: UUID
    snp_locus_id: UUID
    rsid: Optional[str] = None
    gene_symbol: Optional[str] = None
    user_genotype: str
    is_risk: bool
    risk_score: float
    note: Optional[str] = None


class RiskAssessmentResponse(BaseSchema):
    """风险评估响应"""
    id: UUID
    personal_genome_id: UUID
    trait_id: UUID
    trait_name: Optional[str] = None
    overall_risk_score: float
    risk_level: str
    core_loci_matched: int
    auxiliary_loci_matched: int
    matched_loci_ids: Optional[list] = None
    interpretation: Optional[dict] = None
    llm_model: Optional[str] = None
    created_at: datetime


class LifestyleRecommendationResponse(BaseSchema):
    """生活建议响应"""
    id: UUID
    risk_assessment_id: UUID
    category: str
    content: str
    priority: str
    evidence: Optional[str] = None


class LociSearchRequest(BaseModel):
    """AI 检索位点请求"""
    genome_build: str = Field("GRCh37", description="基因组版本 GRCh37/GRCh38/unknown")
    use_external_sources: bool = Field(True, description="是否交叉验证 GWAS Catalog/ClinVar/OMIM")


class InterpretRequest(BaseModel):
    """生成解读报告请求"""
    trait_id: Optional[UUID] = Field(None, description="性状 ID（可选，端点已通过 assessment_id 隐式确定）")
    use_llm: bool = Field(True, description="是否调用 LLM 生成解读")
    user_llm_config_id: Optional[UUID] = Field(None, description="用户级 LLM配置 ID（不传则用系统激活）")


class GenomeExportRequest(BaseModel):
    """基因组解读报告导出请求"""
    personal_genome_id: UUID
    format: str = Field("both", description="导出格式：markdown / json / both")
    user_llm_config_id: Optional[UUID] = Field(None, description="用户级 LLM 配置 ID（可选）")


class KbExpandRequest(BaseModel):
    """知识库扩充请求"""
    trait_ids: Optional[List[UUID]] = Field(None, description="指定性状 ID 列表（不传则全部）")
    user_llm_config_id: Optional[UUID] = None


class PromptTemplateResponse(BaseSchema):
    """Prompt 模板响应"""
    id: UUID
    name: str
    template_type: str
    genome_build: Optional[str]
    trait_category: Optional[str]
    content: str
    description: Optional[str]
    is_active: bool
    created_at: datetime


class PromptTemplateCreate(BaseModel):
    """创建 Prompt 模板"""
    name: str
    template_type: str = Field(..., description="trait_search/interpretation/recommendation/general")
    genome_build: Optional[str] = None
    trait_category: Optional[str] = None
    content: str
    description: Optional[str] = None
    is_active: bool = True


class PersonalizedTreatmentRequest(BaseModel):
    """个性化治疗推荐请求"""
    personal_genome_id: UUID
    project_id: Optional[UUID] = Field(None, description="项目 ID（可选）")
    disease: Optional[str] = Field(None, description="疾病名（用于推荐靶向药）")
    user_llm_config_id: Optional[UUID] = Field(
        None, description="用户级 LLM 配置 ID（不传则用激活配置或系统默认）"
    )


# 导出新增 schemas
__all__ = [
    # 既有（部分保留）
    "BaseSchema", "TokenResponse", "UserCreate", "UserResponse", "UserUpdateRole",
    "UserUpdateStatus", "UserListResponse", "ProjectCreate", "ProjectResponse",
    "StandardResponse", "ApiResponse", "PagedResponse", "success_response", "paged_response",
    "LLMConfigCreate", "LLMConfigUpdate", "LLMConfigResponse", "LLMTestRequest", "LLMTestResponse",
    # 用户级 LLM
    "UserLLMConfigCreate", "UserLLMConfigUpdate", "UserLLMConfigResponse",
    "UserLLMTestRequest", "UserLLMTestResponse",
    # 个人基因组解读
    "TraitCreate", "TraitResponse", "SnpLocusResponse", "PersonalGenomeResponse",
    "GenotypeMatchResponse", "RiskAssessmentResponse", "LifestyleRecommendationResponse",
    "LociSearchRequest", "InterpretRequest", "KbExpandRequest",
    "PromptTemplateResponse", "PromptTemplateCreate", "PersonalizedTreatmentRequest",
    "GenomeExportRequest",
]
