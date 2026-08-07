"""用户级 LLM 配置模型 — BYO Key 模式

设计来源：参照 Trae 论坛方案，用户可在个人中心绑定自有 API Key
选择不同 LLM（豆包/DeepSeek/OpenAI 等），用于个人基因组解读。
系统默认激活配置保持 Agnes；用户激活配置优先，调用失败降级到系统。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserLLMConfig(UUIDMixin, TimestampMixin, Base):
    """用户级 LLM 配置 — 每个用户独立维护

    一个用户可有多个配置，仅一个 is_active=True。
    API Key 通过 app.core.encryption.encrypt() 加密存储。
    """

    __tablename__ = "user_llm_configs"

    owner_id: Mapped[UUIDType] = mapped_column(ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="配置名称，如「豆包」「DeepSeek」")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible", comment="提供商标识")

    base_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="基础 URL")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, comment="API 密钥（加密存储）")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="模型名")

    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False, comment="温度")
    max_tokens: Mapped[int] = mapped_column(default=2000, nullable=False, comment="最大 token 数")
    timeout_sec: Mapped[int] = mapped_column(default=60, nullable=False, comment="超时秒数")

    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True, comment="是否当前激活")

    last_test_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_test_success: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_test_message: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<UserLLMConfig {self.name} provider={self.provider} active={self.is_active}>"


__all__ = ["UserLLMConfig"]
