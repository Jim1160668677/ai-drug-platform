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


def _guardrail_to_dict(result: GuardrailResult) -> Dict[str, Any]:
    """GuardrailResult → dict"""
    return {
        "passed": result.passed,
        "blocked": result.blocked,
        "reasons": result.reasons,
        "sanitized": result.sanitized_text is not None,
    }
