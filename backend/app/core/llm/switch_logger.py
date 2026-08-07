"""切换日志记录器 — 持久化每一次模型切换事件到数据库

设计要点：
- 异步写入，不阻塞主调用链路（写入失败时降级到 logging.warning）
- 自管理 DB 会话（从全局引擎创建独立 session，避免干扰调用方的事务）
- 记录完整指标快照（performance_metrics JSON 字段）
- 满足需求：保留完整的切换日志，记录切换时间、原因及模型性能指标
"""
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class SwitchLogger:
    """模型切换日志记录器

    用法：
        switch_logger = SwitchLogger()
        await switch_logger.log_switch(
            from_model="agnes-2.0-flash",
            to_model="glm-4.7-flash",
            trigger_type=SwitchTriggerType.QUALITY_LOW,
            reason="响应内容过短（15字符 < 阈值20）",
            fallback_succeeded=True,
        )
    """

    def __init__(self) -> None:
        self._enabled = True

    async def log_switch(
        self,
        from_model: str,
        to_model: str,
        trigger_type,
        reason: str,
        latency_ms: Optional[int] = None,
        content_length: Optional[int] = None,
        success_rate: Optional[float] = None,
        http_status: Optional[int] = None,
        fallback_succeeded: bool = False,
        fallback_latency_ms: Optional[int] = None,
        user_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
        performance_metrics: Optional[dict] = None,
    ) -> None:
        """异步记录一次模型切换事件

        写入失败时降级到 logging.warning，不抛异常（不影响主调用链路）。
        """
        if not self._enabled:
            return

        try:
            await self._persist(
                from_model=from_model,
                to_model=to_model,
                trigger_type=trigger_type,
                reason=reason,
                latency_ms=latency_ms,
                content_length=content_length,
                success_rate=success_rate,
                http_status=http_status,
                fallback_succeeded=fallback_succeeded,
                fallback_latency_ms=fallback_latency_ms,
                user_id=user_id,
                request_id=request_id,
                performance_metrics=performance_metrics,
            )
        except Exception as e:
            logger.warning(
                "模型切换日志写入失败（降级到日志记录）: %s -> %s, "
                "trigger=%s, reason=%s, error=%s",
                from_model, to_model, trigger_type, reason, e,
            )

    async def _persist(self, **kwargs) -> None:
        """持久化到数据库 — 自管理 session"""
        from app.db.session import async_session_factory
        from app.models.model_switch_log import ModelSwitchLog, SwitchTriggerType

        trigger = kwargs.pop("trigger_type")
        if isinstance(trigger, str):
            try:
                trigger = SwitchTriggerType(trigger)
            except ValueError:
                trigger = SwitchTriggerType.MANUAL

        log_entry = ModelSwitchLog(
            from_model=kwargs["from_model"],
            to_model=kwargs["to_model"],
            trigger_type=trigger,
            reason=kwargs["reason"],
            latency_ms=kwargs.get("latency_ms"),
            content_length=kwargs.get("content_length"),
            success_rate=kwargs.get("success_rate"),
            http_status=kwargs.get("http_status"),
            fallback_succeeded=kwargs.get("fallback_succeeded", False),
            fallback_latency_ms=kwargs.get("fallback_latency_ms"),
            user_id=kwargs.get("user_id"),
            request_id=kwargs.get("request_id"),
            performance_metrics=kwargs.get("performance_metrics"),
        )

        async with async_session_factory() as db:
            db.add(log_entry)
            await db.commit()

        logger.info(
            "模型切换已记录: %s -> %s (trigger=%s, reason=%s, fallback_succeeded=%s)",
            kwargs["from_model"], kwargs["to_model"],
            trigger.value, kwargs["reason"],
            kwargs.get("fallback_succeeded", False),
        )

    def disable(self) -> None:
        """禁用日志记录（供测试使用）"""
        self._enabled = False

    def enable(self) -> None:
        """启用日志记录"""
        self._enabled = True
