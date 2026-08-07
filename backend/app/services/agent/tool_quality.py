"""工具质量跟踪器 — 记录工具调用指标并推荐最优工具

设计来源：2026-07-28 Agent 增强（工具质量评估与动态选择）

核心职责：
1. 记录每次工具调用的指标：成功/失败、耗时、调用次数
2. 计算工具质量评分（成功率 × 速度评分 × 稳定性评分）
3. 提供工具推荐：给定候选工具列表，返回按质量评分排序的推荐
4. TTL 过期清理（防止内存泄漏）

存储：内存字典（默认）+ 可选 DB 持久化
线程安全：使用 asyncio.Lock 保护写入（单进程内）

集成点：
- AgentEngine 工具调用后调用 tracker.record()
- Planner 生成计划前可查询 tracker 获取工具推荐
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ToolMetrics:
    """单个工具的质量指标"""

    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    # 最近的调用记录（用于稳定性分析，最多保留 20 条）
    recent_results: List[bool] = field(default_factory=list)
    recent_durations_ms: List[float] = field(default_factory=list)
    last_called_at: Optional[datetime] = None
    last_error: Optional[str] = None

    @property
    def success_rate(self) -> float:
        """成功率（0.0-1.0）"""
        if self.total_calls == 0:
            return 0.0
        return self.success_count / self.total_calls

    @property
    def avg_duration_ms(self) -> float:
        """平均耗时（毫秒）"""
        if self.total_calls == 0:
            return 0.0
        return self.total_duration_ms / self.total_calls

    @property
    def stability_score(self) -> float:
        """稳定性评分（0.0-1.0）

        基于最近 20 次调用的成功率波动。
        成功率稳定（全成功或全失败）→ 高分；频繁波动 → 低分。
        """
        if not self.recent_results:
            return 0.5  # 无数据时中等
        if len(self.recent_results) < 3:
            return 0.6  # 数据不足时略高于中等
        # 计算最近调用的成功率
        recent_success_rate = sum(self.recent_results) / len(self.recent_results)
        # 与历史成功率对比，差异越小越稳定
        if self.total_calls > 0:
            historical_rate = self.success_rate
            diff = abs(recent_success_rate - historical_rate)
            return max(0.0, 1.0 - diff * 2)
        return recent_success_rate

    @property
    def speed_score(self) -> float:
        """速度评分（0.0-1.0）

        基于平均耗时：
        - < 500ms → 1.0
        - < 2s → 0.8
        - < 5s → 0.6
        - < 10s → 0.4
        - >= 10s → 0.2
        """
        avg = self.avg_duration_ms
        if avg == 0:
            return 0.5  # 无数据
        if avg < 500:
            return 1.0
        elif avg < 2000:
            return 0.8
        elif avg < 5000:
            return 0.6
        elif avg < 10000:
            return 0.4
        else:
            return 0.2

    @property
    def quality_score(self) -> float:
        """综合质量评分（0.0-1.0）

        权重：成功率 50% + 速度 25% + 稳定性 25%
        """
        if self.total_calls == 0:
            return 0.5  # 无数据时给中等分（不惩罚新工具）
        return (
            self.success_rate * 0.5
            + self.speed_score * 0.25
            + self.stability_score * 0.25
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "min_duration_ms": round(self.min_duration_ms, 2) if self.min_duration_ms != float("inf") else 0,
            "max_duration_ms": round(self.max_duration_ms, 2),
            "quality_score": round(self.quality_score, 4),
            "speed_score": round(self.speed_score, 4),
            "stability_score": round(self.stability_score, 4),
            "last_called_at": self.last_called_at.isoformat() if self.last_called_at else None,
            "last_error": self.last_error,
        }


class ToolQualityTracker:
    """工具质量跟踪器（单例）

    Usage:
        tracker = ToolQualityTracker()

        # 记录调用
        await tracker.record(
            tool_name="discover_targets",
            success=True,
            duration_ms=1234,
        )

        # 获取推荐
        ranked = await tracker.rank_tools(["discover_targets", "search_ncbi"])
        # ranked = [{"tool_name": "discover_targets", "quality_score": 0.85}, ...]
    """

    _instance: Optional["ToolQualityTracker"] = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, ttl_days: Optional[int] = None):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._metrics: Dict[str, ToolMetrics] = {}
            self._data_lock = asyncio.Lock()
            self._ttl_days = ttl_days or getattr(
                settings, "AGENT_TOOL_QUALITY_TTL_DAYS", 7
            )
            self._last_cleanup = datetime.now(timezone.utc)
            logger.info(
                f"ToolQualityTracker 初始化（TTL={self._ttl_days}天）"
            )

    async def record(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """记录一次工具调用

        Args:
            tool_name: 工具名
            success: 是否成功
            duration_ms: 耗时（毫秒）
            error: 失败时的错误信息
        """
        async with self._data_lock:
            if tool_name not in self._metrics:
                self._metrics[tool_name] = ToolMetrics(tool_name=tool_name)

            m = self._metrics[tool_name]
            m.total_calls += 1
            if success:
                m.success_count += 1
            else:
                m.failure_count += 1
                m.last_error = (error or "")[:500]

            m.total_duration_ms += duration_ms
            m.min_duration_ms = min(m.min_duration_ms, duration_ms)
            m.max_duration_ms = max(m.max_duration_ms, duration_ms)
            m.last_called_at = datetime.now(timezone.utc)

            # 保留最近 20 条记录
            m.recent_results.append(success)
            if len(m.recent_results) > 20:
                m.recent_results.pop(0)
            m.recent_durations_ms.append(duration_ms)
            if len(m.recent_durations_ms) > 20:
                m.recent_durations_ms.pop(0)

        # 定期清理过期数据
        await self._maybe_cleanup()

    async def get_metrics(self, tool_name: str) -> Optional[ToolMetrics]:
        """获取单个工具的指标"""
        async with self._data_lock:
            return self._metrics.get(tool_name)

    async def get_all_metrics(self) -> Dict[str, ToolMetrics]:
        """获取所有工具指标"""
        async with self._data_lock:
            return dict(self._metrics)

    async def rank_tools(
        self,
        candidate_tools: List[str],
        min_calls: int = 0,
    ) -> List[Dict[str, Any]]:
        """按质量评分排序候选工具

        Args:
            candidate_tools: 候选工具名列表
            min_calls: 最低调用次数阈值（低于此值不纳入排序，但仍返回）

        Returns:
            排序后的工具列表（高质量在前），每项含 quality_score
        """
        async with self._data_lock:
            ranked: List[Tuple[float, str, ToolMetrics]] = []
            for tool_name in candidate_tools:
                m = self._metrics.get(tool_name)
                if m is None:
                    # 无数据的新工具，给中等分
                    ranked.append((0.5, tool_name, ToolMetrics(tool_name=tool_name)))
                elif m.total_calls < min_calls:
                    # 数据不足，给略低于中等的分
                    ranked.append((0.45, tool_name, m))
                else:
                    ranked.append((m.quality_score, tool_name, m))

            # 按分数降序
            ranked.sort(key=lambda x: x[0], reverse=True)

            return [
                {
                    "tool_name": name,
                    "quality_score": round(score, 4),
                    "total_calls": m.total_calls,
                    "success_rate": round(m.success_rate, 4),
                    "avg_duration_ms": round(m.avg_duration_ms, 2),
                }
                for score, name, m in ranked
            ]

    async def recommend_best(
        self,
        candidate_tools: List[str],
        min_calls: int = 3,
    ) -> Optional[str]:
        """推荐最优工具

        Args:
            candidate_tools: 候选工具名列表
            min_calls: 最低调用次数阈值

        Returns:
            推荐的工具名，若无足够数据返回 None
        """
        ranked = await self.rank_tools(candidate_tools, min_calls=min_calls)
        if not ranked:
            return None

        # 若所有工具都无数据（quality_score=0.5），返回 None 让 LLM 自行决策
        if all(r["total_calls"] == 0 for r in ranked):
            return None

        return ranked[0]["tool_name"]

    async def get_summary(self) -> Dict[str, Any]:
        """获取工具质量摘要（用于调试和监控）"""
        async with self._data_lock:
            total_calls = sum(m.total_calls for m in self._metrics.values())
            total_success = sum(m.success_count for m in self._metrics.values())
            return {
                "total_tools": len(self._metrics),
                "total_calls": total_calls,
                "overall_success_rate": (
                    round(total_success / total_calls, 4) if total_calls > 0 else 0.0
                ),
                "tools": {
                    name: m.to_dict() for name, m in self._metrics.items()
                },
                "last_cleanup": self._last_cleanup.isoformat(),
            }

    async def reset(self, tool_name: Optional[str] = None) -> int:
        """重置指标（用于测试）

        Args:
            tool_name: 指定工具名，None 则重置全部

        Returns:
            重置的工具数
        """
        async with self._data_lock:
            if tool_name:
                if tool_name in self._metrics:
                    del self._metrics[tool_name]
                    return 1
                return 0
            else:
                count = len(self._metrics)
                self._metrics.clear()
                return count

    async def _maybe_cleanup(self) -> None:
        """定期清理过期数据（每 24 小时一次）"""
        now = datetime.now(timezone.utc)
        if (now - self._last_cleanup) < timedelta(hours=24):
            return

        async with self._data_lock:
            cutoff = now - timedelta(days=self._ttl_days)
            expired = [
                name for name, m in self._metrics.items()
                if m.last_called_at and m.last_called_at < cutoff
            ]
            for name in expired:
                del self._metrics[name]
            if expired:
                logger.info(f"ToolQualityTracker 清理 {len(expired)} 个过期工具指标")
            self._last_cleanup = now


# 模块级单例
_tracker: Optional[ToolQualityTracker] = None


def get_tool_quality_tracker() -> ToolQualityTracker:
    """获取工具质量跟踪器单例"""
    global _tracker
    if _tracker is None:
        _tracker = ToolQualityTracker()
    return _tracker


__all__ = [
    "ToolQualityTracker",
    "ToolMetrics",
    "get_tool_quality_tracker",
]
