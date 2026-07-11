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
    DATABASE_URL: str = "postgresql+asyncpg://pdd:pdd_secret@postgres:5432/precision_drug"

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
    NEO4J_PASSWORD: str = "neo4j_secret"

    # ========== MinIO ==========
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_BUCKET: str = "pdd-data"

    # ========== 大模型 ==========
    OPENAI_API_KEY: str = ""
    LLM_MODEL_FAST: str = "gpt-4o-mini"
    LLM_MODEL_DEEP: str = "gpt-4o"
    FAST_SCREEN_MAX_COST_USD: float = 5.0
    FAST_SCREEN_MAX_DURATION_SEC: int = 300
    DEEP_INSIGHT_MAX_COST_USD: float = 20.0
    DEEP_INSIGHT_MAX_DURATION_SEC: int = 1800

    # ========== 外部生物医学 API ==========
    MYGENE_BASE_URL: str = "https://mygene.info/v3"
    MYVARIANT_BASE_URL: str = "https://myvariant.info/v1"
    CHEMBL_BASE_URL: str = "https://www.ebi.ac.uk/chembl/api/data"
    CLINICALTRIALS_BASE_URL: str = "https://clinicaltrials.gov/api/v2"

    # ========== DiffDock ==========
    NVIDIA_NIM_API_KEY: str = ""
    DIFFDOCK_NIM_URL: str = "https://integrate.api.nvidia.com/v1/genai/biology/mit/diffdock"

    # ========== 联邦学习 ==========
    FL_NUM_ROUNDS_DEFAULT: int = 10
    FL_MIN_CLIENTS_DEFAULT: int = 3
    FL_MAD_THRESHOLD: float = 3.0  # 中位数绝对偏差阈值（恶意客户端检测）

    # ========== LLM 预算与护栏 ==========
    LLM_DAILY_BUDGET_USD: float = 50.0
    GUARDRAIL_ENABLED: bool = True
    GUARDRAIL_MAX_DOSE_MG: float = 1000.0  # 剂量上限（mg）
    GUARDRAIL_BLOCK_PATTERNS: str = "绝对治愈,100%有效,包治百病,特效药"

    # ========== 限流 ==========
    # 登录端点限流（防暴力破解，始终启用）
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5

    # ========== 信封中间件 ==========
    ENVELOPE_MIDDLEWARE_ENABLED: bool = True
    ENVELOPE_MAX_BODY_SIZE: int = 1048576  # 1 MB — 超过此大小的响应不注入 duration_ms

    # ========== 日志 ==========
    LOG_LEVEL: str = "INFO"
    LOG_FILE_PATH: str = "logs"

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
