"""LLM 成本追踪器 — 按日预算 + 用量统计

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/LLM服务层.md

按日重置预算追踪，支持内存态或 Redis 持久化（通过 LLM_COST_TRACKER_REDIS_URL 配置）。
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# 模型定价表（USD / 1M tokens）— (input, output)
_MODEL_PRICING: Dict[str, tuple] = {
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-opus": (15.0, 75.0),
    "claude-3-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
}


class CostTracker:
    """LLM 成本追踪器 — 按日预算控制

    内存态实现，每日 00:00 UTC 重置。
    生产环境可通过 LLM_COST_TRACKER_REDIS_URL 切换为 Redis 持久化。
    """

    def __init__(self, daily_budget_usd: Optional[float] = None):
        self.daily_budget = daily_budget_usd or settings.LLM_DAILY_BUDGET_USD
        self._lock = threading.Lock()
        self._today: str = self._today_key()
        self._spent: float = 0.0
        self._calls: int = 0
        self._by_model: Dict[str, float] = {}
        self._redis = self._init_redis()

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _init_redis(self):
        """可选 Redis 持久化"""
        url = getattr(settings, "LLM_COST_TRACKER_REDIS_URL", "") or ""
        if not url:
            return None
        try:
            import redis

            client = redis.from_url(url)
            client.ping()
            logger.info("CostTracker Redis 持久化已启用")
            return client
        except Exception as e:
            logger.warning(f"Redis 连接失败，降级为内存追踪: {e}")
            return None

    def _maybe_reset(self) -> None:
        """跨日时重置计数"""
        today = self._today_key()
        if today != self._today:
            self._today = today
            self._spent = 0.0
            self._calls = 0
            self._by_model = {}
            logger.info(f"CostTracker 跨日重置: {today}")

    def estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """估算单次调用成本

        Args:
            model: 模型名（如 gpt-4o-mini）
            prompt_tokens: 输入 token 数
            completion_tokens: 输出 token 数
        Returns:
            成本（USD，4 位小数）
        """
        pricing = _MODEL_PRICING.get(model, (0.50, 1.50))  # 默认用 gpt-3.5 价格
        input_cost = prompt_tokens * pricing[0] / 1_000_000
        output_cost = completion_tokens * pricing[1] / 1_000_000
        return round(input_cost + output_cost, 4)

    def can_spend(self, amount: float) -> bool:
        """检查是否还能支出"""
        with self._lock:
            self._maybe_reset()
            return (self._spent + amount) <= self.daily_budget

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """记录一次调用

        Args:
            model: 模型名
            prompt_tokens: 输入 token 数
            completion_tokens: 输出 token 数
        Returns:
            本次成本（USD）
        """
        cost = self.estimate_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            self._maybe_reset()
            self._spent += cost
            self._calls += 1
            self._by_model[model] = self._by_model.get(model, 0.0) + cost
        logger.debug(
            f"CostTracker record: model={model} cost=${cost:.4f} "
            f"today_total=${self._spent:.4f}/{self.daily_budget}"
        )
        return cost

    def today_summary(self) -> Dict[str, Any]:
        """今日汇总"""
        with self._lock:
            self._maybe_reset()
            return {
                "date": self._today,
                "spent_usd": round(self._spent, 4),
                "budget_usd": self.daily_budget,
                "remaining_usd": round(max(0.0, self.daily_budget - self._spent), 4),
                "utilization": round(self._spent / self.daily_budget, 4) if self.daily_budget else 0,
                "calls": self._calls,
                "by_model": {k: round(v, 4) for k, v in self._by_model.items()},
            }


# 模块级单例
_cost_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """获取 CostTracker 单例"""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker
