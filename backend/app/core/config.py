"""应用配置 — Mock/Real 切换的枢纽"""
import logging
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 已知不安全的默认密钥占位符（出现在源码中，不可用于生产）
_INSECURE_DEFAULT_SECRETS = {
    "change-this-to-a-random-secret-key-in-production",
    "dev-secret-key-change-in-production",
    "",
}


class Settings(BaseSettings):
    """应用配置，从环境变量读取"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    # ========== 运行环境 ==========
    APP_ENV: str = "development"
    USE_MOCK: bool = True

    # ========== 后端 ==========
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    JWT_SECRET_KEY: str = "change-this-to-a-random-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # access token 30 分钟过期
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7     # refresh token 7 天过期
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost"
    # Fernet 加密密钥（用于加密 LLM API Key 等敏感数据）
    # 生产环境必须设置为 32 字节 base64 字符串：Fernet.generate_key()
    API_KEY_ENCRYPTION_KEY: str = ""

    # ========== 数据库 ==========
    # 生产环境必须通过环境变量设置 DATABASE_URL
    DATABASE_URL: str = ""

    # ========== Redis ==========
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    # ========== ChromaDB ==========
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8000

    # ========== Neo4j ==========
    NEO4J_HOST: str = "neo4j"
    NEO4J_BOLT_PORT: int = 7687
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ========== MinIO ==========
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_BUCKET: str = "pdd-data"

    # ========== 大模型 ==========
    OPENAI_API_KEY: str = ""
    AGNES_API_KEY: str = ""
    LLM_BASE_URL: str = "https://apihub.agnes-ai.com/v1"
    LLM_MODEL_FAST: str = "agnes-2.5-flash"
    LLM_MODEL_DEEP: str = "agnes-2.5-flash"
    FAST_SCREEN_MAX_COST_USD: float = 5.0
    FAST_SCREEN_MAX_DURATION_SEC: int = 300
    DEEP_INSIGHT_MAX_COST_USD: float = 20.0
    DEEP_INSIGHT_MAX_DURATION_SEC: int = 1800

    # ========== 降级与多模型冗余 ==========
    # Agnes 2.0 Flash — 作为 agnes-2.5-flash 的备用模型（同 API，不同模型名）
    # 当 agnes-2.5-flash 不可用/低质量时自动切换到 agnes-2.0-flash
    AGNES_FALLBACK_MODEL: str = "agnes-2.0-flash"
    AGNES_FALLBACK_TIMEOUT_SEC: int = 60
    # 智谱 GLM-4.7-Flash（OpenAI 兼容，免费，作为 Agnes 的第三级备用模型）
    # 文档：https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash
    ZHIPU_API_KEY: str = ""                                      # 智谱 API Key（id.secret 格式），环境变量注入
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    ZHIPU_MODEL: str = "glm-4.7-flash"
    ZHIPU_TIMEOUT_SEC: int = 60

    # 降级总开关（False 时 get_llm_client_with_config 返回原始 client，行为不变）
    LLM_FALLBACK_ENABLED: bool = True

    # 质量阈值 — 触发降级的条件
    LLM_FALLBACK_MIN_CONTENT_CHARS: int = 20        # 主响应内容 < 此长度视为低质量
    LLM_FALLBACK_RETRY_ON_HTTP_ERROR: bool = True   # 主响应 HTTP 4xx/5xx 时切换
    LLM_FALLBACK_RETRY_ON_TIMEOUT: bool = True      # 主响应超时时切换
    LLM_FALLBACK_RETRY_ON_EMPTY: bool = True        # 主响应空内容时切换

    # 性能监控 — 滚动窗口指标驱动触发条件优化
    LLM_HEALTH_ROLLING_WINDOW: int = 50             # 滚动窗口样本数
    LLM_HEALTH_SUCCESS_RATE_THRESHOLD: float = 0.7  # 滚动成功率低于此值自动启用降级
    LLM_HEALTH_LATENCY_P95_THRESHOLD_SEC: float = 20.0  # P95 延迟高于此值标记不健康

    # ========== 外部生物医学 API ==========
    MYGENE_BASE_URL: str = "https://mygene.info/v3"
    MYVARIANT_BASE_URL: str = "https://myvariant.info/v1"
    CHEMBL_BASE_URL: str = "https://www.ebi.ac.uk/chembl/api/data"
    CLINICALTRIALS_BASE_URL: str = "https://clinicaltrials.gov/api/v2"

    # ========== NCBI E-utilities ==========
    # 文档：https://www.ncbi.nlm.nih.gov/books/NBK25499/
    # 无 API Key 限速 3 req/s，有 API Key 限速 10 req/s
    NCBI_BASE_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    NCBI_API_KEY: str = ""                       # 可选，提升速率限制到 10 req/s
    NCBI_RATE_LIMIT_RPS: int = 3                 # 无 API Key 时的速率限制
    NCBI_CACHE_TTL_DAYS: int = 7                 # 缓存有效期
    NCBI_MAX_RETRIES: int = 3                    # 最大重试次数（指数退避 1s/2s/4s）
    NCBI_TIMEOUT_SEC: int = 30                   # 请求超时

    # ========== 学术资源客户端（bioRxiv/arXiv/Semantic Scholar/CrossRef）==========
    # 用于科学推理助手的学术文献自动发现,统一遵循 USE_MOCK 开关
    # bioRxiv 无需 API Key;arXiv 无需 API Key
    SEMANTIC_SCHOLAR_API_KEY: str = ""           # https://www.semanticscholar.org/product/api (可选,无 Key 限 100 req/5min)
    CROSSREF_MAILTO: str = ""                    # CrossRef polite pool 邮箱(可选,提供后 50 req/s,否则 2 req/s)
    ACADEMIC_CACHE_TTL_DAYS: int = 7             # 学术文献缓存有效期(天)
    ACADEMIC_TIMEOUT_SEC: int = 30               # 学术 API 请求超时
    ACADEMIC_MAX_RETRIES: int = 3                # 指数退避重试次数

    # ========== 网络搜索 ==========
    # 多引擎聚合：DuckDuckGo（免费）+ Serper（Google 代理）+ Brave
    WEB_SEARCH_ENGINE: str = "auto"              # auto / duckduckgo / serper / brave
    SERPER_API_KEY: str = ""                      # https://serper.dev（免费 2500 次/月）
    BRAVE_SEARCH_API_KEY: str = ""                # https://api.search.brave.com（免费 2000 次/月）
    WEB_SEARCH_MAX_RESULTS: int = 10              # 单次搜索最大返回数
    WEB_SEARCH_CACHE_TTL_HOURS: int = 24         # 搜索结果缓存时长
    WEB_SEARCH_TIMEOUT_SEC: int = 15             # 搜索请求超时
    WEB_FETCH_MAX_CHARS: int = 5000              # 网页抓取最大字符数
    WEB_FETCH_TIMEOUT_SEC: int = 15              # 网页抓取超时

    # ========== Agent 增强 ==========
    AGENT_USE_DAG_EXECUTOR: bool = False          # DAG 并行执行开关（默认关闭，逐步启用）
    AGENT_USE_REFLECTION: bool = True             # 工具失败反思重试
    AGENT_REFLECTION_MAX_RETRIES: int = 2         # 反思最大重试次数（防死循环）
    AGENT_USE_KNOWLEDGE_GAP_DETECTION: bool = True  # 知识盲区自动触发网络搜索
    AGENT_KNOWLEDGE_GAP_THRESHOLD: int = 2         # 连续无结果步数触发阈值
    AGENT_TOOL_QUALITY_TRACKING: bool = True      # 工具质量跟踪开关
    AGENT_TOOL_QUALITY_TTL_DAYS: int = 7          # 工具质量数据保留时长

    # ========== DiffDock ==========
    NVIDIA_NIM_API_KEY: str = ""
    DIFFDOCK_NIM_URL: str = "https://integrate.api.nvidia.com/v1/genai/biology/mit/diffdock"

    # ========== Protenix（字节跳动蛋白-配体复合物结构预测）==========
    # GitHub: https://github.com/bytedance/Protenix
    # 配置 Protenix HTTP 服务地址后启用真实模式；未配置时使用 Mock（生成演示用 PDB + 结合位点）
    PROTENIX_API_URL: str = ""
    PROTENIX_USE_MOCK: bool = True    # 兼容统一开关；为 True 且未配置 API_URL 时走 Mock
    PROTENIX_MODEL_NAME: str = "protenix_v1"
    PROTENIX_TIMEOUT_SEC: int = 300   # 单次推断超时（秒）

    # ========== 计算引擎（Phase 1：集成 6 个开源 GitHub 项目）==========
    # 统一遵循 USE_MOCK 开关：True=Mock 伪造结果（测试默认），False=调用真实引擎（需 GPU+模型）
    ESMFOLD_USE_MOCK: bool = True      # ESMFold 蛋白结构预测（facebookresearch/esm）
    ESMFOLD_MODEL_NAME: str = "esmfold_v1"
    UNIMOL_USE_MOCK: bool = True      # Uni-Mol 分子对接（dp-tech/Uni-Mol）
    VINA_USE_MOCK: bool = True        # AutoDock Vina 分子对接（ccsb-scripps/AutoDock-Vina）
    VINA_EXE_PATH: str = "vina"       # Vina 可执行文件路径
    SCGPT_USE_MOCK: bool = True       # scGPT 单细胞扰动预测（bowang-lab/scGPT）
    MHCFLURRY_USE_MOCK: bool = True   # MHCflurry MHC-I 结合亲和力预测(OpenVaccine/mhcflurry)
    AIZYNTH_USE_MOCK: bool = True     # AiZynthFinder 合成路线搜索（MolecularAI/aizynthfinder）

    # ========== 联邦学习 ==========
    FL_NUM_ROUNDS_DEFAULT: int = 10
    FL_MIN_CLIENTS_DEFAULT: int = 3
    FL_MAD_THRESHOLD: float = 3.0  # 中位数绝对偏差阈值（恶意客户端检测）

    # ========== LLM 预算与护栏 ==========
    LLM_DAILY_BUDGET_USD: float = 50.0
    LLM_USER_DAILY_BUDGET_USD: float = 10.0  # 单用户日预算
    GUARDRAIL_ENABLED: bool = True
    GUARDRAIL_MAX_DOSE_MG: float = 1000.0  # 剂量上限（mg）
    GUARDRAIL_BLOCK_PATTERNS: str = "绝对治愈,100%有效,包治百病,特效药"
    # 医学红线规则（v3.0 文档 11.3 节）
    GUARDRAIL_MEDICAL_REDLINES_ENABLED: bool = True
    CONSENT_CHECK_ENABLED: bool = True  # 知情同意校验（功能 7）

    # ========== LLM 推理档位（成本感知分级推理）==========
    # 三档推理配置：turbo(快速筛查) / standard(标准分析) / deep(深度推理)
    # IntentRouter.auto 模式下根据问题复杂度自动选择档位
    LLM_TIERS: dict = {
        "turbo": {
            "max_rounds": 2,
            "max_initial_count": 3,
            "evidence_level": "summary",
            "timeout_sec": 60,
            "description": "快速筛查",
        },
        "standard": {
            "max_rounds": 3,
            "max_initial_count": 5,
            "evidence_level": "compact",
            "timeout_sec": 300,
            "description": "标准分析",
        },
        "deep": {
            "max_rounds": 3,
            "max_initial_count": 4,
            "evidence_level": "full",
            "timeout_sec": 600,
            "description": "深度推理",
        },
    }
    DEFAULT_LLM_TIER: str = "standard"

    # ========== 限流 ==========
    # 登录端点限流（防暴力破解，始终启用）
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5

    # ========== Agent / ReAct 引擎 ==========
    AGENT_MAX_STEPS: int = 8                  # 单任务 ReAct 最大循环步数（优化：15→8，减少延迟）
    AGENT_MAX_TOKENS: int = 8000              # 单任务上下文 token 上限（超出触发压缩）
    AGENT_TASK_TIMEOUT_SEC: int = 180         # 单任务总超时（秒）（优化：300→180）
    AGENT_WS_MAX_CONN_SEC: int = 1800         # WebSocket 最大连接时长（秒）
    AGENT_RATE_LIMIT_RPM: int = 60            # 每用户每分钟请求数
    # 简单问答跳过 Planner，直接进 ReAct（节省一次 LLM 调用，加速响应）
    AGENT_SKIP_PLANNER_FOR_SIMPLE_Q: bool = True
    AGENT_RATE_LIMIT_CONCURRENT: int = 5      # 每用户并发任务数
    AGENT_CACHE_TTL_SEC: int = 3600           # L2 Redis 缓存 TTL
    AGENT_CONTEXT_COMPRESS_THRESHOLD: int = 6000  # 上下文压缩触发阈值（token）


    # ========== Co-Scientist 多智能体科学推理引擎 ==========
    # 基于 Nature 论文 Co-Scientist，Real 优先，失败降级 Mock（复用 FallbackLLMClient）
    COSCIENTIST_USE_MOCK: bool = False
    COSCIENTIST_INITIAL_HYPOTHESES: int = 5
    COSCIENTIST_DEBATE_ROUNDS: int = 3
    COSCIENTIST_DEBATE_CONVERGENCE_THRESHOLD: float = 0.85
    COSCIENTIST_DEBATE_TOP_K: int = 5
    COSCIENTIST_ELO_INITIAL: float = 1000.0
    COSCIENTIST_ELO_K_FACTOR: int = 32
    COSCIENTIST_ELO_K_PROVISIONAL: int = 40
    COSCIENTIST_ELO_K_STABLE: int = 24
    COSCIENTIST_ELO_PROVISIONAL_GAMES: int = 10
    COSCIENTIST_EVOLUTION_MAX_ITERATIONS: int = 5
    COSCIENTIST_MAX_COST_USD: float = 5.0
    COSCIENTIST_MAX_DURATION_SEC: int = 1800
    # 推理模式超时配置（按模式分级）
    COSCIENTIST_FAST_ROUND_TIMEOUT_SEC: float = 120.0       # fast: 每轮 2min
    COSCIENTIST_STANDARD_ROUND_TIMEOUT_SEC: float = 300.0   # standard: 每轮 5min
    COSCIENTIST_DEEP_ROUND_TIMEOUT_SEC: float = 600.0       # deep: 每轮 10min
    COSCIENTIST_AUTO_EXPERIMENT_DESIGN: bool = False
    COSCIENTIST_FAST_MAX_ROUNDS: int = 2
    COSCIENTIST_STANDARD_MAX_ROUNDS: int = 3
    COSCIENTIST_DEEP_MAX_ROUNDS: int = 5
    COSCIENTIST_FAST_DEBATE_ROUNDS: int = 1
    COSCIENTIST_STANDARD_DEBATE_ROUNDS: int = 2
    COSCIENTIST_PARALLEL_AGENTS: bool = True
    COSCIENTIST_PARALLEL_SEMAPHORE: int = 3
    COSCIENTIST_PROXIMITY_JACCARD_THRESHOLD: float = 0.6
    COSCIENTIST_EVOLUTION_SIMILARITY_THRESHOLD: float = 0.7
    COSCIENTIST_EVOLUTION_SEVERITY_THRESHOLD: int = 7
    COSCIENTIST_EVOLUTION_COMPLEXITY_LEN_THRESHOLD: int = 500
    COSCIENTIST_FEEDBACK_ELO_BONUS: float = 50.0

    # ========== 统一智能系统（融合 AI 问答 / 科学推理 / Agent 工作台）==========
    # 基于 Nature Co-Scientist 论文 + karpathy/autoresearch 自主实验循环理念
    # 灰度开关：False 时旧端点（/chat /agent/* /coscientist/*）走原路径，True 时委托 UnifiedOrchestrator
    INTELLIGENCE_USE_UNIFIED_ORCHESTRATOR: bool = True
    # 原生多模态 LLM 模型（病理图像 / 蛋白结构图分析），不硬编码，通过 settings 注入
    LLM_MODEL_VISION: str = "agnes-2.0-vision"
    # 上下文记忆 TTL（天）：消息类默认 30 天，快照类默认 7 天
    INTELLIGENCE_CONTEXT_MEMORY_TTL_DAYS: int = 30
    INTELLIGENCE_SNAPSHOT_TTL_DAYS: int = 7
    # 推理追溯最大事件数（查询限制）
    INTELLIGENCE_TRACE_MAX_EVENTS: int = 5000
    # IntentRouter LLM 二级分类置信度阈值（低于此值降级为 chat）
    INTELLIGENCE_INTENT_LLM_THRESHOLD: float = 0.7
    # 连续追问轮数阈值（超过后自动建议升级 reasoning）
    INTELLIGENCE_CHAT_UPGRADE_THRESHOLD: int = 3
    # 单会话上下文内存上限（MB）
    INTELLIGENCE_SESSION_MEMORY_LIMIT_MB: int = 4

    # ========== 沙箱 ==========
    AGENT_SANDBOX_IMAGE: str = "ai-drug-sandbox:latest"
    AGENT_SANDBOX_TIMEOUT_SEC: int = 30       # 单次代码执行超时
    AGENT_SANDBOX_MEMORY_MB: int = 512        # 容器内存上限
    AGENT_SANDBOX_CPU_LIMIT: float = 1.0      # 容器 CPU 核数上限
    AGENT_SANDBOX_ENABLED: bool = False       # 沙箱总开关（生产环境启用）

    # ========== 信封中间件 ==========
    ENVELOPE_MIDDLEWARE_ENABLED: bool = True
    ENVELOPE_MAX_BODY_SIZE: int = 1048576  # 1 MB — 超过此大小的响应不注入 duration_ms

    # ========== 日志 ==========
    LOG_LEVEL: str = "INFO"
    LOG_FILE_PATH: str = "logs"
    LOG_JSON_FORMAT: bool = False  # Phase F: 生产环境启用 JSON 结构化日志

    # ========== 可观测性（Phase F）==========
    METRICS_ENABLED: bool = True          # 启用 Prometheus 指标采集
    METRICS_PATH: str = "/api/v1/metrics"  # 指标端点路径

    # ========== 混合架构参数 ==========
    HYBRID_LLM_RANK_TOP_K: int = 20        # LLM 重排序候选数
    HYBRID_VINA_REFINE_TOP_K: int = 5     # Vina 精修数量
    DUAL_CONTEXT_AMPLIFIER_THRESHOLD: float = 0.2  # 条件放大器阈值
    DUAL_CONTEXT_NUM_CONTEXTS: int = 2    # 双上下文数量
    HYBRID_MAX_COST_USD: float = 50.0      # 混合编排单次最大成本
    HYBRID_MAX_DURATION_SEC: int = 600    # 混合编排最大耗时
    # 性能优化参数（v2 — 防止 hybrid 对接超时）
    HYBRID_MAX_CANDIDATES: int = 10        # 候选分子上限（防止 LLM 上下文爆炸 + 减少 N 次对接）
    HYBRID_CONCURRENCY: int = 5            # 单批次并发对接数（asyncio.gather 并发度）
    HYBRID_PER_MOL_TIMEOUT_SEC: int = 30  # 单分子对接超时（秒，防卡死）
    HYBRID_LLM_TIMEOUT_SEC: int = 45       # 单次 LLM 调用超时（秒，超时降级）

    # ========== 基准评测参数 ==========
    BENCHMARK_CPU_WATTS: float = 350.0     # CPU 功耗（瓦）
    BENCHMARK_GPU_WATTS: float = 400.0     # GPU 功耗
    BENCHMARK_PUE: float = 1.5              # 数据中心 PUE
    BENCHMARK_TRADITIONAL_GPU_HOURS: float = 24.0  # 传统超算基准 GPU 小时数
    BENCHMARK_LLM_ONLY_MAX_COST_USD: float = 10.0

    # ========== 合成参数 ==========
    SYNTHESIS_MAX_ROUTES: int = 5
    SYNTHESIS_COST_PER_STEP_USD: float = 150.0
    SYNTHESIS_LABOR_RATE_USD_PER_HR: float = 80.0
    SYNTHESIS_HOURS_PER_STEP: float = 4.0
    SYNTHESIS_REAGENT_DB_PATH: str = "data/reagents.json"
    SYNTHESIS_MAX_COST_USD: float = 100.0

    # ========== 新抗原与疫苗 ==========
    VACCINE_MAX_PEPTIDE_LENGTH: int = 11
    VACCINE_MIN_BINDING_NM: float = 500.0  # IC50 < 500nM 视为强结合
    VACCINE_GC_CONTENT_MIN: float = 0.30
    VACCINE_GC_CONTENT_MAX: float = 0.70

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """JWT 密钥安全校验

        生产环境（APP_ENV 不是 development/testing）拒绝默认占位符密钥。
        开发/测试环境允许但记录警告。
        """
        from os import environ
        app_env = environ.get("APP_ENV", "development")
        if v in _INSECURE_DEFAULT_SECRETS:
            if app_env in ("production", "staging", "prod"):
                raise ValueError(
                    "JWT_SECRET_KEY 不能使用默认占位符，请设置至少 32 字节的随机密钥"
                )
            logger.warning(
                "JWT_SECRET_KEY 使用默认占位符，仅适用于开发环境。生产环境必须设置强密钥。"
            )
        elif len(v) < 32:
            if app_env in ("production", "staging", "prod"):
                raise ValueError("JWT_SECRET_KEY 至少 32 字节")
            logger.warning("JWT_SECRET_KEY 长度不足 32 字节，建议使用更强的密钥")
        return v

    @field_validator("API_KEY_ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """加密密钥安全校验

        生产环境强制配置 Fernet 密钥，防止敏感数据明文存储。
        """
        from os import environ
        app_env = environ.get("APP_ENV", "development")
        if not v and app_env in ("production", "staging", "prod"):
            raise ValueError(
                "API_KEY_ENCRYPTION_KEY 在生产环境必须设置（使用 Fernet.generate_key() 生成）"
            )
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_mock(self) -> bool:
        return self.USE_MOCK

    @property
    def neo4j_uri(self) -> str:
        return f"bolt://{self.NEO4J_HOST}:{self.NEO4J_BOLT_PORT}"

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
