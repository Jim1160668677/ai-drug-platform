"""LLM 降级包装器 — Agnes 主模型故障/低质量时无缝切换到智谱 GLM-4.7-Flash

设计要点：
- FallbackLLMClient 实现 LLMClient 接口，对上层完全透明
- QualityAssessor 评估主模型响应质量，判定是否需要降级
- 降级链路：primary.chat() → 质量评估 → (不达标) → fallback.chat() → 记录日志
- 性能监控：每次调用都记录到 ModelPerformanceMonitor，驱动触发条件优化
- 切换透明：用户无感知，返回值结构与主模型一致
"""
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from app.clients.base import LLMClient
from app.core.config import settings
from app.core.llm.performance import ModelPerformanceMonitor, get_performance_monitor
from app.core.llm.switch_logger import SwitchLogger
from app.models.model_switch_log import SwitchTriggerType
from app.core.observability.metrics import record_llm_call

logger = logging.getLogger(__name__)

# 错误前缀模式 — RealLLMClient.chat() 在异常时返回带前缀的 content
_HTTP_ERROR_RE = re.compile(r"\[LLM\s+HTTP\s+(\d+)\]")
_TIMEOUT_PREFIX = "[LLM 调用超时]"
_NETWORK_ERROR_PREFIX = "[LLM 调用失败]"
_STREAM_ERROR_PREFIX = "[LLM stream"


@dataclass
class AssessmentResult:
    """质量评估结果"""

    is_low_quality: bool
    reason: str
    trigger_type: Optional[SwitchTriggerType] = None
    http_status: Optional[int] = None


class QualityAssessor:
    """主模型响应质量评估器

    根据 settings 中的阈值和开关，判断响应是否需要触发降级。
    """

    def __init__(
        self,
        min_content_chars: int = None,
        retry_on_http_error: bool = None,
        retry_on_timeout: bool = None,
        retry_on_empty: bool = None,
    ):
        self.min_content_chars = (
            min_content_chars if min_content_chars is not None
            else settings.LLM_FALLBACK_MIN_CONTENT_CHARS
        )
        self.retry_on_http_error = (
            retry_on_http_error if retry_on_http_error is not None
            else settings.LLM_FALLBACK_RETRY_ON_HTTP_ERROR
        )
        self.retry_on_timeout = (
            retry_on_timeout if retry_on_timeout is not None
            else settings.LLM_FALLBACK_RETRY_ON_TIMEOUT
        )
        self.retry_on_empty = (
            retry_on_empty if retry_on_empty is not None
            else settings.LLM_FALLBACK_RETRY_ON_EMPTY
        )

    def assess(self, response: dict) -> AssessmentResult:
        """评估主模型响应质量

        Returns:
            AssessmentResult — is_low_quality=True 时需要降级
        """
        content = response.get("content", "") or ""
        content_stripped = content.strip()

        # 1. 空内容
        if not content_stripped:
            if self.retry_on_empty:
                return AssessmentResult(
                    is_low_quality=True,
                    reason="主模型返回空内容",
                    trigger_type=SwitchTriggerType.EMPTY_CONTENT,
                )
            return AssessmentResult(is_low_quality=False, reason="")

        # 2. HTTP 错误（content 包含 "[LLM HTTP xxx]"）
        http_match = _HTTP_ERROR_RE.search(content)
        if http_match:
            status_code = int(http_match.group(1))
            if self.retry_on_http_error:
                return AssessmentResult(
                    is_low_quality=True,
                    reason=f"主模型返回 HTTP {status_code} 错误",
                    trigger_type=SwitchTriggerType.HTTP_ERROR,
                    http_status=status_code,
                )
            return AssessmentResult(is_low_quality=False, reason="")

        # 3. 超时
        if content.startswith(_TIMEOUT_PREFIX):
            if self.retry_on_timeout:
                return AssessmentResult(
                    is_low_quality=True,
                    reason=f"主模型请求超时: {content[:100]}",
                    trigger_type=SwitchTriggerType.TIMEOUT,
                )
            return AssessmentResult(is_low_quality=False, reason="")

        # 4. 网络错误
        if content.startswith(_NETWORK_ERROR_PREFIX) or content.startswith(_STREAM_ERROR_PREFIX):
            return AssessmentResult(
                is_low_quality=True,
                reason=f"主模型网络异常: {content[:100]}",
                trigger_type=SwitchTriggerType.NETWORK_ERROR,
            )

        # 5. 内容过短（质量不达标）
        if len(content_stripped) < self.min_content_chars:
            return AssessmentResult(
                is_low_quality=True,
                reason=(
                    f"主模型响应内容过短（{len(content_stripped)} 字符 < "
                    f"阈值 {self.min_content_chars}）"
                ),
                trigger_type=SwitchTriggerType.QUALITY_LOW,
            )

        return AssessmentResult(is_low_quality=False, reason="")


class FallbackLLMClient(LLMClient):
    """降级 LLM 客户端 — 包装主模型 + 备用模型

    对上层完全透明：实现 LLMClient 接口，调用方无需感知降级逻辑。
    主模型故障/低质量时自动切换到备用模型（智谱 GLM-4.7-Flash）。

    用法：
        client = FallbackLLMClient(primary, fallback)
        result = await client.chat(messages)  # 自动降级，对调用方透明
    """

    def __init__(
        self,
        primary_client: LLMClient,
        fallback_client: LLMClient,
        assessor: Optional[QualityAssessor] = None,
        switch_logger: Optional[SwitchLogger] = None,
        performance_monitor: Optional[ModelPerformanceMonitor] = None,
        fallback_enabled: bool = None,
    ):
        self.primary = primary_client
        self.fallback = fallback_client
        self.assessor = assessor or QualityAssessor()
        self.switch_logger = switch_logger or SwitchLogger()
        self.monitor = performance_monitor or get_performance_monitor()
        self.fallback_enabled = (
            fallback_enabled if fallback_enabled is not None
            else settings.LLM_FALLBACK_ENABLED
        )
        # 主模型/备用模型名称（从客户端属性推断，用于日志记录）
        self.primary_model_name = getattr(
            primary_client, "default_model", None
        ) or settings.LLM_MODEL_DEEP
        self.fallback_model_name = getattr(
            fallback_client, "default_model", None
        ) or settings.ZHIPU_MODEL

    def _get_model_name(self, client: LLMClient, response: dict) -> str:
        """从响应中提取模型名称"""
        return response.get("model") or getattr(
            client, "default_model", ""
        ) or "unknown"

    async def chat(
        self,
        messages: List[dict],
        model: str = None,
        user_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """对话补全 — 主模型不达标时自动降级到备用模型

        降级流程对用户透明：返回值结构与主模型一致。
        """
        if not self.fallback_enabled:
            # 降级关闭 — 直接返回主模型结果
            return await self.primary.chat(messages, model=model, **kwargs)

        # 1. 调用主模型（含异常保护，确保降级链路不中断）
        start = time.time()
        try:
            primary_response = await self.primary.chat(messages, model=model, **kwargs)
        except Exception as e:
            logger.error(
                "主模型 %s 调用异常: %s %s，构造降级响应",
                self.primary_model_name, type(e).__name__, e,
            )
            primary_response = {
                "content": f"[LLM 调用失败] {type(e).__name__}: {e}",
                "model": getattr(self.primary, "default_model", "unknown"),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "duration_sec": round(time.time() - start, 3),
                "references": [],
                "code": None,
            }
        primary_latency = time.time() - start

        primary_model = self._get_model_name(self.primary, primary_response)

        # 2. 评估主模型响应质量
        assessment = self.assessor.assess(primary_response)

        # 3. 记录主模型性能
        self.monitor.record(
            model_name=primary_model,
            success=not assessment.is_low_quality,
            latency_sec=primary_latency,
            error=assessment.reason if assessment.is_low_quality else None,
        )

        # 4. 质量达标 — 直接返回
        if not assessment.is_low_quality:
            # Phase F: 记录主模型成功调用指标
            record_llm_call(
                model=primary_model,
                tier=kwargs.get("tier", "default"),
                status="success",
                duration_sec=primary_latency,
                cost_usd=primary_response.get("cost_usd", 0.0) or 0.0,
            )
            return primary_response

        # 5. 质量不达标 — 降级到备用模型
        logger.warning(
            "主模型 %s 响应不达标，降级到备用模型 %s: %s",
            primary_model, self.fallback_model_name, assessment.reason,
        )

        # 5a. 如主模型与备用模型相同（或同类），跳过回退直接返回空响应标记
        if primary_model == self.fallback_model_name or not self.fallback_model_name:
            logger.warning("主备模型相同 (%s)，跳过回退，返回主模型结果", primary_model)
            return primary_response

        # 5b. 空内容时优先用短 prompt 重试一次（降低 max_tokens）
        if assessment.trigger_type == SwitchTriggerType.EMPTY_CONTENT:
            try:
                retry_kwargs = dict(kwargs)
                retry_kwargs["max_tokens"] = min(
                    retry_kwargs.get("max_tokens", 2000), 500
                )
                retry_messages = messages
                # 尝试简化最后一条消息
                if retry_messages and retry_messages[-1].get("role") == "user":
                    last_content = retry_messages[-1].get("content", "")
                    if len(last_content) > 500:
                        retry_messages = list(retry_messages)
                        retry_messages[-1] = {
                            **retry_messages[-1],
                            "content": last_content[:500] + "...",
                        }
                retry_response = await self.primary.chat(
                    retry_messages, model=model, **retry_kwargs
                )
                retry_assessment = self.assessor.assess(retry_response)
                if not retry_assessment.is_low_quality:
                    logger.info("空内容重试成功 (简化prompt)")
                    return retry_response
            except Exception as e:
                logger.warning("空内容重试失败: %s", e)

        fallback_start = time.time()
        try:
            fallback_response = await self.fallback.chat(
                messages, model=model, **kwargs
            )
            fallback_latency = time.time() - fallback_start
            fallback_succeeded = True

            # 检查备用模型是否也返回了错误
            fallback_assessment = self.assessor.assess(fallback_response)
            if fallback_assessment.is_low_quality:
                fallback_succeeded = False
                logger.error(
                    "备用模型 %s 也返回低质量响应: %s",
                    self.fallback_model_name, fallback_assessment.reason,
                )
        except Exception as e:
            fallback_latency = time.time() - fallback_start
            fallback_succeeded = False
            logger.error("备用模型 %s 调用异常: %s", self.fallback_model_name, e)
            # 备用模型也失败 — 返回主模型的原始响应（至少有内容）
            return primary_response

        # 6. 记录备用模型性能
        self.monitor.record(
            model_name=self.fallback_model_name,
            success=fallback_succeeded,
            latency_sec=fallback_latency,
        )
        # Phase F: 记录 LLM 指标 — 主模型失败 + 备用模型结果
        record_llm_call(
            model=primary_model,
            tier=kwargs.get("tier", "default"),
            status="fallback",
            duration_sec=primary_latency,
        )
        if fallback_succeeded:
            record_llm_call(
                model=self.fallback_model_name,
                tier=kwargs.get("tier", "default"),
                status="success",
                duration_sec=fallback_latency,
                cost_usd=fallback_response.get("cost_usd", 0.0) or 0.0,
            )
        else:
            record_llm_call(
                model=self.fallback_model_name,
                tier=kwargs.get("tier", "default"),
                status="failed",
                duration_sec=fallback_latency,
            )

        # 7. 记录切换日志（异步，不阻塞返回）
        try:
            await self.switch_logger.log_switch(
                from_model=primary_model,
                to_model=self.fallback_model_name,
                trigger_type=assessment.trigger_type,
                reason=assessment.reason,
                latency_ms=int(primary_latency * 1000),
                content_length=len(primary_response.get("content", "") or ""),
                success_rate=(self.monitor.get_metrics(primary_model) or {}).get("success_rate"),
                http_status=assessment.http_status,
                fallback_succeeded=fallback_succeeded,
                fallback_latency_ms=int(fallback_latency * 1000),
                user_id=user_id,
                request_id=request_id,
                performance_metrics=self.monitor.get_health_snapshot(),
            )
        except Exception as e:
            logger.warning("切换日志记录失败（不影响主流程）: %s", e)

        # 8. 返回备用模型响应（对用户透明）
        return fallback_response

    async def stream_chat(
        self,
        messages: List[dict],
        model: str = None,
        user_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式对话 — 主模型流式出错时降级到备用模型

        策略：先尝试主模型流式，若首个事件即为 error，则切换到备用模型。
        """
        if not self.fallback_enabled:
            async for chunk in self.primary.stream_chat(messages, model=model, **kwargs):
                yield chunk
            return

        primary_model = getattr(self.primary, "default_model", "") or self.primary_model_name
        start = time.time()
        got_token = False
        error_chunk = None

        try:
            async for chunk in self.primary.stream_chat(messages, model=model, **kwargs):
                if chunk.get("type") == "error":
                    error_chunk = chunk
                    # 继续收集，不立即 break
                else:
                    if chunk.get("type") == "token":
                        got_token = True
                    yield chunk
        except Exception as e:
            error_chunk = {"type": "error", "content": str(e)}

        primary_latency = time.time() - start

        # 如果主模型有 token 输出，说明基本正常，记录性能后返回
        if got_token:
            self.monitor.record(
                model_name=primary_model,
                success=True,
                latency_sec=primary_latency,
            )
            return

        # 主模型没有 token 输出 — 降级到备用模型
        assessment = AssessmentResult(
            is_low_quality=True,
            reason=f"主模型流式无输出: {error_chunk.get('content', '')[:100]}" if error_chunk else "主模型流式无输出",
            trigger_type=SwitchTriggerType.NETWORK_ERROR,
        )

        self.monitor.record(
            model_name=primary_model,
            success=False,
            latency_sec=primary_latency,
            error=assessment.reason,
        )

        logger.warning(
            "主模型 %s 流式失败，降级到备用模型 %s",
            primary_model, self.fallback_model_name,
        )

        # 降级到备用模型的非流式调用（保证可靠性）
        fallback_start = time.time()
        try:
            fallback_response = await self.fallback.chat(messages, model=model, **kwargs)
            fallback_latency = time.time() - fallback_start
            fallback_succeeded = True

            # 逐段 yield 备用模型响应
            content = fallback_response.get("content", "")
            if content:
                yield {"type": "token", "content": content}
            yield {
                "type": "done",
                "content": content,
                "usage": fallback_response.get("usage", {}),
                "model": fallback_response.get("model", self.fallback_model_name),
            }
        except Exception as e:
            fallback_latency = time.time() - fallback_start
            fallback_succeeded = False
            logger.error("备用模型流式降级也失败: %s", e)
            yield {"type": "error", "content": str(e)}
        finally:
            self.monitor.record(
                model_name=self.fallback_model_name,
                success=fallback_succeeded,
                latency_sec=fallback_latency,
            )
            try:
                await self.switch_logger.log_switch(
                    from_model=primary_model,
                    to_model=self.fallback_model_name,
                    trigger_type=assessment.trigger_type,
                    reason=assessment.reason,
                    latency_ms=int(primary_latency * 1000),
                    fallback_succeeded=fallback_succeeded,
                    fallback_latency_ms=int(fallback_latency * 1000),
                    user_id=user_id,
                    request_id=request_id,
                    performance_metrics=self.monitor.get_health_snapshot(),
                )
            except Exception as e:
                logger.warning("切换日志记录失败: %s", e)

    async def embed(self, text: str) -> List[float]:
        """文本向量化 — 直接委托主模型（嵌入不需要降级）"""
        return await self.primary.embed(text)
