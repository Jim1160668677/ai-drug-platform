"""BaseAgent — Co-Scientist 智能体基类

职责：
- 包装 LLM 客户端（FallbackLLMClient），提供 quick(prompt, system=) 便捷接口
- 适配返回值：LLM 客户端返回 {content, usage, model}，算法层期望 {content, token_usage, cost_usd}
- 统一 token/cost 累计统计
- 统一超时、错误处理、日志
- 提供 JSON 解析工具方法

子类只需实现 run() 方法。

参考论文：Section "Multi-agent architecture" + Extended Data Fig. 2
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.llm.cache import llm_cache

logger = logging.getLogger(__name__)


class BaseAgent:
    """Co-Scientist 智能体基类

    用法：
        class MyAgent(BaseAgent):
            async def run(self, research_goal, **kwargs):
                result = await self.quick(prompt, system=system_prompt)
                return self._parse_json(result["content"])

        agent = MyAgent(llm_client)
        output = await agent.run("研究目标")
    """

    # 子类可覆盖：智能体名称（用于日志）
    agent_name: str = "base"

    def __init__(
        self,
        llm_client: Any,
        semaphore: Optional[asyncio.Semaphore] = None,
        timeout: float = 60.0,
        temperature: float = 0.7,
        agent_name: Optional[str] = None,
    ):
        """
        Args:
            llm_client: LLM 客户端实例（需有 async chat(messages) -> dict 方法）
            semaphore: 并发控制信号量（None 则不限制）
            timeout: 单次 LLM 调用超时（秒）
            temperature: 采样温度
            agent_name: 智能体名称（覆盖类属性，用于日志）
        """
        self.llm_client = llm_client
        self.semaphore = semaphore
        self.timeout = timeout
        if agent_name is not None:
            self.agent_name = agent_name
        self.temperature = temperature

        # 累计统计
        self.total_token_usage: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        self.total_cost_usd: float = 0.0
        self.call_count: int = 0
        self.error_count: int = 0

    async def quick(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """便捷 LLM 调用 — 适配算法层接口

        将 prompt + system 转为 messages，调用 llm_client.chat()，
        适配返回值为 {content, token_usage, cost_usd, model}。

        Args:
            prompt: 用户 prompt
            system: 系统 prompt（可选）
            temperature: 采样温度（覆盖默认值）
        Returns:
            {"content": str, "token_usage": {"prompt", "completion", "total"},
             "cost_usd": float, "model": str, "error": Optional[str]}
        """
        messages: List[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async def _call():
            # FallbackLLMClient.chat 接受 messages 列表
            kwargs = {}
            if temperature is not None:
                kwargs["temperature"] = temperature
            elif self.temperature != 0.7:
                kwargs["temperature"] = self.temperature

            return await self.llm_client.chat(messages, **kwargs)

        # Phase C 性能优化：LLM 响应缓存（仅 temperature<=0 或显式启用时缓存）
        actual_temp = temperature if temperature is not None else self.temperature
        should_cache = use_cache if use_cache is not None else (actual_temp <= 0.0)

        async def _cached_call():
            return await llm_cache.get_or_call(
                prompt=prompt,
                call_fn=_call,
                system=system,
                temperature=actual_temp,
                use_cache=should_cache,
            )

        try:
            if self.semaphore:
                async with self.semaphore:
                    response = await asyncio.wait_for(_cached_call(), timeout=self.timeout)
            else:
                response = await asyncio.wait_for(_cached_call(), timeout=self.timeout)
        except asyncio.TimeoutError:
            self.error_count += 1
            logger.warning("[%s] LLM 调用超时（%ss）", self.agent_name, self.timeout)
            return {
                "content": "",
                "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                "cost_usd": 0.0,
                "model": "",
                "error": "timeout",
            }
        except Exception as e:
            self.error_count += 1
            logger.exception("[%s] LLM 调用失败: %s", self.agent_name, e)
            return {
                "content": "",
                "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                "cost_usd": 0.0,
                "model": "",
                "error": str(e),
            }

        # 适配返回值
        content = response.get("content", "") or ""
        usage = response.get("usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = prompt_tokens + completion_tokens

        token_usage = {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
        }
        cost_usd = self._estimate_cost(prompt_tokens, completion_tokens, response.get("model", ""))
        model = response.get("model", "")

        # 累计统计
        self.total_token_usage["prompt"] += prompt_tokens
        self.total_token_usage["completion"] += completion_tokens
        self.total_token_usage["total"] += total_tokens
        self.total_cost_usd += cost_usd
        self.call_count += 1

        return {
            "content": content,
            "token_usage": token_usage,
            "cost_usd": cost_usd,
            "model": model,
            "error": None,
        }

    def _estimate_cost(
        self, prompt_tokens: int, completion_tokens: int, model: str = ""
    ) -> float:
        """粗略估算成本（USD）

        基于 Agnes/智谱/GLM 的常见定价：
        - 输入: $0.001 / 1K tokens
        - 输出: $0.002 / 1K tokens
        """
        return (prompt_tokens / 1000.0) * 0.001 + (completion_tokens / 1000.0) * 0.002

    def _parse_json(self, content: str, default: Any = None) -> Any:
        """解析 LLM 响应为 JSON（容错处理）

        支持以下格式：
        - 纯 JSON 字符串
        - ```json ... ``` 代码块
        - ``` ... ``` 代码块
        - JSON 前后有额外文本（提取第一个 { 到最后一个 }）

        Args:
            content: LLM 响应文本
            default: 解析失败时的默认返回值
        Returns:
            解析后的 dict/list，或 default
        """
        if not content:
            return default if default is not None else {}

        text = content.strip()

        # 1. 尝试直接解析
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. 提取 ```json ... ``` 代码块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        # 3. 提取 ``` ... ``` 代码块
        if "```" in text:
            start = text.find("```") + 3
            # 跳过可能的语言标识符行
            newline = text.find("\n", start)
            if newline > start:
                start = newline + 1
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        # 4. 提取第一个 { 到最后一个 }（或 [ 到 ]）
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")

        # 选择更靠前的起始符
        candidates = []
        if brace_start >= 0 and brace_end > brace_start:
            candidates.append((brace_start, brace_end + 1))
        if bracket_start >= 0 and bracket_end > bracket_start:
            candidates.append((bracket_start, bracket_end + 1))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            start, end = candidates[0]
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug("[%s] JSON 解析失败: %s", self.agent_name, e)

        logger.debug("[%s] 无法解析 JSON，返回默认值。内容前100字符: %s", self.agent_name, text[:100])
        return default if default is not None else {}

    def get_stats(self) -> Dict[str, Any]:
        """获取智能体累计统计"""
        return {
            "agent_name": self.agent_name,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "total_tokens": self.total_token_usage["total"],
            "total_cost_usd": round(self.total_cost_usd, 6),
        }

    def reset_stats(self) -> None:
        """重置统计"""
        self.total_token_usage = {"prompt": 0, "completion": 0, "total": 0}
        self.total_cost_usd = 0.0
        self.call_count = 0
        self.error_count = 0

    async def run(self, *args, **kwargs) -> Any:
        """子类实现 — 执行智能体任务"""
        raise NotImplementedError(f"{self.agent_name} 未实现 run() 方法")