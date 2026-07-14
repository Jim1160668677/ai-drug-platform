"""LLM 配置模型 — 多 LLM 提供商动态切换"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AccessMode(str, enum.Enum):
    """访问模式"""
    API_ONLY = "api_only"
    LOCAL_DEPLOY = "local_deploy"
    PROXY = "proxy"


class UpstreamProtocol(str, enum.Enum):
    """上游协议"""
    CHAT_COMPLETIONS = "chat_completions"  # OpenAI 兼容
    COMPLETIONS = "completions"  # 旧版 completions
    ANTHROPIC = "anthropic"  # Anthropic Messages API


class LLMConfig(UUIDMixin, TimestampMixin, Base):
    """LLM 提供商配置

    支持多 provider 多配置，仅一个 is_active=True。
    运行时由 get_active_llm_config() 读取激活配置。
    """
    __tablename__ = "llm_configs"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="配置名称，如 Agnes、OpenAI、Azure")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible", comment="提供商标识")

    # 访问与协议
    access_mode: Mapped[AccessMode] = mapped_column(
        Enum(AccessMode, native_enum=False, length=32),
        default=AccessMode.API_ONLY,
        nullable=False,
        comment="访问模式: api_only/local_deploy/proxy",
    )
    upstream_protocol: Mapped[UpstreamProtocol] = mapped_column(
        Enum(UpstreamProtocol, native_enum=False, length=32),
        default=UpstreamProtocol.CHAT_COMPLETIONS,
        nullable=False,
        comment="上游协议: chat_completions/completions/anthropic",
    )

    # 连接配置
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="基础 URL，如 https://apihub.agnes-ai.com/v1")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, comment="API 密钥（加密存储建议生产环境改进）")

    # 模型配置
    test_model: Mapped[str] = mapped_column(String(128), nullable=False, comment="测试用模型名，如 agnes-2.0-flash")
    fast_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="快速筛查模型")
    deep_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="深度洞察模型")

    # 版本管理
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False, comment="配置版本号")
    parent_config_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, comment="前一版本配置 ID（版本链）")

    # 参数
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False, comment="温度")
    max_tokens: Mapped[int] = mapped_column(default=2000, nullable=False, comment="最大 token 数")
    timeout_sec: Mapped[int] = mapped_column(default=60, nullable=False, comment="超时秒数")

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True, comment="是否当前激活")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述")

    # 最后测试状态
    last_test_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


__all__ = ["LLMConfig", "AccessMode", "UpstreamProtocol"]
