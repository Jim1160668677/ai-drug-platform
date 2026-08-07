"""模型切换日志 ORM 模型

记录每一次大模型自动降级/切换事件，满足需求：
- 保留完整的切换日志，记录切换时间、原因及模型性能指标
- 支持按时间/模型/触发类型查询，用于性能监控与触发条件优化
"""
import enum
import uuid
from typing import Any, Optional

from sqlalchemy import Enum, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin, UUIDMixin


class SwitchTriggerType(str, enum.Enum):
    """切换触发类型"""

    QUALITY_LOW = "quality_low"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    EMPTY_CONTENT = "empty_content"
    NETWORK_ERROR = "network_error"
    HEALTH_CHECK = "health_check"
    MANUAL = "manual"


class ModelSwitchLog(Base, UUIDMixin, TimestampMixin):
    """模型切换日志 — 每条记录代表一次自动降级事件"""

    __tablename__ = "model_switch_logs"

    from_model: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="切换前模型（主模型）"
    )
    to_model: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="切换后模型（备用模型）"
    )
    trigger_type: Mapped[SwitchTriggerType] = mapped_column(
        Enum(SwitchTriggerType, name="switch_trigger_type"),
        nullable=False,
        index=True,
        comment="触发类型",
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="人类可读的切换原因"
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="主模型响应耗时（毫秒）"
    )
    content_length: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="主模型返回内容长度（字符数）"
    )
    success_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="切换时的滚动成功率（0.0-1.0）"
    )
    http_status: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="主模型 HTTP 状态码（如适用）"
    )
    fallback_succeeded: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="备用模型是否成功响应"
    )
    fallback_latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="备用模型响应耗时（毫秒）"
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        nullable=True, index=True, comment="触发切换的用户 ID"
    )
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="请求追踪 ID"
    )
    performance_metrics: Mapped[Optional[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
        comment="完整的性能指标快照（滚动窗口、P95 延迟等）",
    )

    def __repr__(self) -> str:
        return (
            f"<ModelSwitchLog {self.from_model}->{self.to_model} "
            f"trigger={self.trigger_type} succeeded={self.fallback_succeeded}>"
        )
