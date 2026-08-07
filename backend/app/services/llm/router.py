"""LLM 路由器 — 多模型分级路由

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/LLM服务层.md

将 LLMOrchestrator 中的模型选择和调用逻辑拆分为独立路由器：
- quick(prompt) → 轻量模型（gpt-4o-mini 等）用于 fast_screen
- deep(prompt) → 重型模型（gpt-4o 等）用于 deep_insight
- complete(prompt, tier) → 根据 tier 路由

集成了 CostTracker（预算控制）和 Guardrail（安全护栏）。
"""
import logging
import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.models.analysis_job import AnalysisTier
from app.services.llm.cache import LLMResponseCache, get_cache
from app.services.llm.cost_tracker import CostTracker, get_cost_tracker
from app.services.llm.guardrail import Guardrail, GuardrailResult, get_guardrail

logger = logging.getLogger(__name__)


class LLMRouter:
    """LLM 多模型路由器

    根据 tier 路由到不同模型，集成成本追踪、安全护栏和响应缓存。

    Usage:
        router = LLMRouter(llm_client, llm_config=db_config)
        result = await router.complete("用户问题", tier="fast_screen")
    """

    def __init__(
        self,
        llm_client,
        llm_config=None,
        cost_tracker: Optional[CostTracker] = None,
        guardrail: Optional[Guardrail] = None,
        cache: Optional[LLMResponseCache] = None,
    ):
        """
        Args:
            llm_client: LLM 客户端实例（Mock 或 Real）
            llm_config: 数据库激活的 LLMConfig（可选）
            cost_tracker: 成本追踪器（默认使用单例）
            guardrail: 安全护栏（默认使用单例）
            cache: 响应缓存（默认使用单例）
        """
        self.llm_client = llm_client
        self.llm_config = llm_config
        self.cost_tracker = cost_tracker or get_cost_tracker()
        self.guardrail = guardrail or get_guardrail()
        self.cache = cache or get_cache()

    def select_model(self, tier: str) -> str:
        """根据 tier 选择模型

        优先使用数据库激活配置，回退到 settings 默认值。
        """
        if self.llm_config is not None:
            if tier == AnalysisTier.FAST_SCREEN:
                return self.llm_config.fast_model or self.llm_config.test_model
            return self.llm_config.deep_model or self.llm_config.test_model
        if tier == AnalysisTier.FAST_SCREEN:
            return settings.LLM_MODEL_FAST
        return settings.LLM_MODEL_DEEP

    async def quick(self, prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
        """快速路由 — 使用轻量模型

        Args:
            prompt: 用户提示
            system: 系统提示词（可选）
        Returns:
            {content, model, usage, cost_usd, guardrail}
        """
        return await self.complete(prompt, tier=AnalysisTier.FAST_SCREEN, system=system)

    async def deep(self, prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
        """深度路由 — 使用重型模型

        Args:
            prompt: 用户提示
            system: 系统提示词（可选）
        Returns:
            {content, model, usage, cost_usd, guardrail}
        """
        return await self.complete(prompt, tier=AnalysisTier.DEEP_INSIGHT, system=system)

    async def complete(
        self,
        prompt: str,
        tier: str = AnalysisTier.FAST_SCREEN,
        system: Optional[str] = None,
        bypass_guardrail: bool = False,
    ) -> Dict[str, Any]:
        """主路由入口

        Args:
            prompt: 用户提示
            tier: fast_screen / deep_insight
            system: 系统提示词（可选）
            bypass_guardrail: 是否跳过护栏（仅内部调用）
        Returns:
            {content, model, usage, cost_usd, guardrail, references, code}
        """
        start = time.time()
        model = self.select_model(tier)
        guardrail_result = GuardrailResult(passed=True)

        # 1. 输入护栏检查
        if not bypass_guardrail:
            guardrail_result = self.guardrail.check_input(prompt)
            if guardrail_result.blocked:
                logger.warning(f"LLMRouter 输入被护栏拦截: {guardrail_result.reasons}")
                return {
                    "content": f"输入被安全护栏拦截：{', '.join(guardrail_result.reasons)}",
                    "model": model,
                    "usage": {},
                    "cost_usd": 0.0,
                    "guardrail": _guardrail_to_dict(guardrail_result),
                    "references": [],
                    "code": None,
                    "blocked": True,
                }
            # 使用脱敏后的文本
            effective_prompt = guardrail_result.sanitized_text or prompt
        else:
            effective_prompt = prompt

        # 2. 查询缓存（仅 fast_screen 层）
        cached = await self.cache.get(prompt, tier, system)
        if cached is not None:
            logger.info(f"LLMRouter 缓存命中，跳过 LLM 调用")
            return cached

        # 3. 调用 LLM
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": effective_prompt})

        try:
            response = await self.llm_client.chat(messages, model=model)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return {
                "content": f"LLM 调用失败: {e}",
                "model": model,
                "usage": {},
                "cost_usd": 0.0,
                "guardrail": _guardrail_to_dict(guardrail_result),
                "references": [],
                "code": None,
                "error": str(e),
            }

        # 3. 输出护栏检查
        content = response.get("content", "")
        if not bypass_guardrail:
            output_check = self.guardrail.check_output(content)
            if output_check.blocked:
                logger.warning(f"LLMRouter 输出被护栏拦截: {output_check.reasons}")
                return {
                    "content": f"输出被安全护栏拦截：{', '.join(output_check.reasons)}",
                    "model": model,
                    "usage": response.get("usage", {}),
                    "cost_usd": 0.0,
                    "guardrail": _guardrail_to_dict(output_check),
                    "references": response.get("references", []),
                    "code": response.get("code"),
                    "blocked": True,
                }

        # 4. 成本追踪
        usage = response.get("usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost_usd = 0.0
        if self.cost_tracker.can_spend(0.01):  # 预检
            cost_usd = self.cost_tracker.record(model, prompt_tokens, completion_tokens)
        else:
            logger.warning("LLM 日预算已耗尽，本次不计费但已调用")

        duration_sec = round(time.time() - start, 3)
        result = {
            "content": content,
            "model": model,
            "usage": usage,
            "cost_usd": cost_usd,
            "guardrail": _guardrail_to_dict(guardrail_result),
            "references": response.get("references", []),
            "code": response.get("code"),
            "duration_sec": duration_sec,
        }

        # 5. 写入缓存
        await self.cache.set(prompt, tier, result, system)

        return result

    async def stream_complete(
        self,
        prompt: str,
        tier: str = AnalysisTier.FAST_SCREEN,
        system: Optional[str] = None,
        bypass_guardrail: bool = False,
    ):
        """流式主路由入口 — 逐 token yield

        让 Agent 引擎能在 LLM 生成时就推送 token 到前端，显著降低首字延迟。

        流程：
        1. 输入护栏检查（同步）
        2. 调用 LLM stream_chat
        3. 逐 token yield 给调用方
        4. 完成后输出护栏检查（仅对完整内容做检查，若被拦截则追加提示）
        5. 成本追踪

        Yields:
            {"type": "token", "content": "..."} — 增量 token
            {"type": "done", "content": "...", "model": "...", "usage": {...},
             "guardrail": {...}, "cost_usd": float} — 完整响应结束
            {"type": "error", "content": "..."} — 错误信息
        """
        import time as _time

        start = _time.time()
        model = self.select_model(tier)
        guardrail_result = GuardrailResult(passed=True)

        # 1. 输入护栏检查
        if not bypass_guardrail:
            guardrail_result = self.guardrail.check_input(prompt)
            if guardrail_result.blocked:
                logger.warning(
                    f"LLMRouter.stream_complete 输入被护栏拦截: {guardrail_result.reasons}"
                )
                yield {
                    "type": "error",
                    "content": f"输入被安全护栏拦截：{', '.join(guardrail_result.reasons)}",
                    "blocked": True,
                }
                return
            effective_prompt = guardrail_result.sanitized_text or prompt
        else:
            effective_prompt = prompt

        # 2. 构造 messages
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": effective_prompt})

        # 3. 流式调用 LLM
        full_content: str = ""
        usage: Dict[str, Any] = {}
        final_model = model
        has_stream = hasattr(self.llm_client, "stream_chat")

        if has_stream:
            try:
                async for chunk in self.llm_client.stream_chat(
                    messages, model=model
                ):
                    chunk_type = chunk.get("type")
                    if chunk_type == "token":
                        token = chunk.get("content", "")
                        if token:
                            full_content += token
                            yield {"type": "token", "content": token}
                    elif chunk_type == "done":
                        full_content = chunk.get("content", "") or full_content
                        usage = chunk.get("usage", {}) or {}
                        final_model = chunk.get("model", model)
                    elif chunk_type == "error":
                        yield {
                            "type": "error",
                            "content": chunk.get("content", "LLM 流式调用失败"),
                        }
                        return
            except Exception as e:
                logger.error(f"LLM stream 调用失败: {e}", exc_info=True)
                yield {
                    "type": "error",
                    "content": f"LLM stream 调用失败: {e}",
                }
                return
        else:
            # 客户端不支持流式：回退到非流式调用，整段作为单 token
            try:
                response = await self.llm_client.chat(messages, model=model)
                full_content = response.get("content", "")
                usage = response.get("usage", {}) or {}
                final_model = response.get("model", model)
                if full_content:
                    yield {"type": "token", "content": full_content}
            except Exception as e:
                logger.error(f"LLM 非流式调用失败: {e}", exc_info=True)
                yield {
                    "type": "error",
                    "content": f"LLM 调用失败: {e}",
                }
                return

        # 4. 输出护栏检查（对完整内容）
        if not bypass_guardrail:
            output_check = self.guardrail.check_output(full_content)
            if output_check.blocked:
                logger.warning(
                    f"LLMRouter.stream_complete 输出被护栏拦截: {output_check.reasons}"
                )
                # 用拦截提示替换内容
                full_content = (
                    f"输出被安全护栏拦截：{', '.join(output_check.reasons)}\n\n"
                    + full_content
                )
            elif output_check.annotations:
                full_content += "\n\n" + "\n".join(output_check.annotations)

        # 5. 成本追踪
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost_usd = 0.0
        if self.cost_tracker.can_spend(0.01):
            cost_usd = self.cost_tracker.record(
                final_model, prompt_tokens, completion_tokens
            )

        duration_sec = round(_time.time() - start, 3)
        yield {
            "type": "done",
            "content": full_content,
            "model": final_model,
            "usage": usage,
            "guardrail": _guardrail_to_dict(guardrail_result),
            "cost_usd": cost_usd,
            "duration_sec": duration_sec,
        }


def _guardrail_to_dict(result: GuardrailResult) -> Dict[str, Any]:
    """GuardrailResult → dict"""
    return {
        "passed": result.passed,
        "blocked": result.blocked,
        "reasons": result.reasons,
        "sanitized": result.sanitized_text is not None,
    }
