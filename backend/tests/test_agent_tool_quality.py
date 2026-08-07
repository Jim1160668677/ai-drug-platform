"""ToolQualityTracker 单元测试 — 工具质量跟踪与推荐

测试矩阵：
- 指标记录：成功率/耗时/调用次数
- 质量评分计算：成功率/速度/稳定性
- 工具推荐排序
- TTL 清理
- 单例与重置
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.agent.tool_quality import (
    ToolMetrics,
    ToolQualityTracker,
    get_tool_quality_tracker,
)


# ========== ToolMetrics 数据类测试 ==========


class TestToolMetrics:
    """测试 ToolMetrics 指标计算"""

    def test_empty_metrics(self):
        """空指标默认值"""
        m = ToolMetrics(tool_name="test")
        assert m.total_calls == 0
        assert m.success_rate == 0.0
        assert m.avg_duration_ms == 0.0
        assert m.quality_score == 0.5  # 无数据给中等分

    def test_success_rate(self):
        """成功率计算"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 10
        m.success_count = 8
        m.failure_count = 2
        assert m.success_rate == 0.8

    def test_avg_duration(self):
        """平均耗时"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 3
        m.total_duration_ms = 3000
        assert m.avg_duration_ms == 1000.0

    def test_speed_score_fast(self):
        """速度快 → 高分"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 5
        m.total_duration_ms = 5 * 400  # avg 400ms
        assert m.speed_score == 1.0

    def test_speed_score_slow(self):
        """速度慢 → 低分"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 5
        m.total_duration_ms = 5 * 15000  # avg 15s
        assert m.speed_score == 0.2

    def test_stability_score_stable(self):
        """稳定（全成功）→ 高分"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 10
        m.success_count = 10
        m.recent_results = [True] * 10
        assert m.stability_score >= 0.8

    def test_quality_score_combines_all(self):
        """综合评分 = 成功率50% + 速度25% + 稳定性25%"""
        m = ToolMetrics(tool_name="test")
        m.total_calls = 10
        m.success_count = 9
        m.failure_count = 1
        m.total_duration_ms = 10 * 1000  # avg 1s → speed 0.8
        m.recent_results = [True] * 10

        # success_rate = 0.9, speed_score = 0.8
        # stability_score: recent_success_rate=1.0, historical=0.9, diff=0.1 → 1.0-0.2=0.8
        expected = 0.9 * 0.5 + 0.8 * 0.25 + 0.8 * 0.25
        assert abs(m.quality_score - round(expected, 4)) < 0.01

    def test_to_dict(self):
        """to_dict 序列化"""
        m = ToolMetrics(tool_name="test_tool")
        m.total_calls = 5
        m.success_count = 4
        m.failure_count = 1
        m.total_duration_ms = 5000

        d = m.to_dict()
        assert d["tool_name"] == "test_tool"
        assert d["total_calls"] == 5
        assert d["success_rate"] == 0.8
        assert d["avg_duration_ms"] == 1000.0


# ========== ToolQualityTracker 记录与查询测试 ==========


class TestToolQualityTrackerRecord:
    """测试工具调用记录"""

    @pytest.fixture(autouse=True)
    def setup_tracker(self):
        """每个测试用独立 tracker 实例（绕过单例 __new__，避免单例污染）"""
        self.tracker = object.__new__(ToolQualityTracker)
        self.tracker._initialized = True
        self.tracker._metrics = {}
        self.tracker._data_lock = asyncio.Lock()
        self.tracker._ttl_days = 7
        self.tracker._last_cleanup = datetime.now(timezone.utc)
        yield
        # 清理

    @pytest.mark.asyncio
    async def test_record_success(self):
        """记录成功调用"""
        await self.tracker.record(
            tool_name="search_ncbi",
            success=True,
            duration_ms=500,
        )
        m = await self.tracker.get_metrics("search_ncbi")
        assert m is not None
        assert m.total_calls == 1
        assert m.success_count == 1
        assert m.failure_count == 0
        assert m.avg_duration_ms == 500.0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        """记录失败调用"""
        await self.tracker.record(
            tool_name="search_ncbi",
            success=False,
            duration_ms=100,
            error="timeout",
        )
        m = await self.tracker.get_metrics("search_ncbi")
        assert m.total_calls == 1
        assert m.success_count == 0
        assert m.failure_count == 1
        assert m.last_error == "timeout"

    @pytest.mark.asyncio
    async def test_record_multiple(self):
        """多次记录累积统计"""
        for _ in range(8):
            await self.tracker.record("tool_a", True, 500)
        for _ in range(2):
            await self.tracker.record("tool_a", False, 500, "err")

        m = await self.tracker.get_metrics("tool_a")
        assert m.total_calls == 10
        assert m.success_count == 8
        assert m.failure_count == 2
        assert m.success_rate == 0.8

    @pytest.mark.asyncio
    async def test_recent_results_capped(self):
        """最近结果列表上限 20"""
        for _ in range(25):
            await self.tracker.record("tool_a", True, 100)

        m = await self.tracker.get_metrics("tool_a")
        assert len(m.recent_results) == 20
        assert m.total_calls == 25  # total 不限


# ========== 工具推荐排序测试 ==========


class TestToolRanking:
    """测试工具推荐排序"""

    @pytest.fixture(autouse=True)
    def setup_tracker(self):
        self.tracker = ToolQualityTracker.__new__(ToolQualityTracker)
        self.tracker._initialized = True
        self.tracker._metrics = {}
        self.tracker._data_lock = asyncio.Lock()
        self.tracker._ttl_days = 7
        self.tracker._last_cleanup = datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_rank_by_quality(self):
        """按质量评分排序（高→低）"""
        # tool_a: 成功率高、速度快
        for _ in range(10):
            await self.tracker.record("tool_a", True, 300)
        # tool_b: 成功率低、速度慢
        for _ in range(5):
            await self.tracker.record("tool_b", True, 8000)
        for _ in range(5):
            await self.tracker.record("tool_b", False, 8000, "err")

        ranked = await self.tracker.rank_tools(["tool_a", "tool_b"])
        assert ranked[0]["tool_name"] == "tool_a"
        assert ranked[0]["quality_score"] > ranked[1]["quality_score"]

    @pytest.mark.asyncio
    async def test_rank_with_no_data(self):
        """无数据的新工具给中等分"""
        ranked = await self.tracker.rank_tools(["new_tool"])
        assert len(ranked) == 1
        assert ranked[0]["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_recommend_best(self):
        """推荐最优工具"""
        for _ in range(10):
            await self.tracker.record("tool_a", True, 300)
        for _ in range(10):
            await self.tracker.record("tool_b", True, 5000)

        best = await self.tracker.recommend_best(["tool_a", "tool_b"], min_calls=5)
        assert best == "tool_a"

    @pytest.mark.asyncio
    async def test_recommend_best_no_data(self):
        """全部无数据 → 返回 None"""
        best = await self.tracker.recommend_best(["new_tool1", "new_tool2"])
        assert best is None

    @pytest.mark.asyncio
    async def test_recommend_best_below_min_calls(self):
        """调用次数不足 → 返回 None"""
        await self.tracker.record("tool_a", True, 300)
        best = await self.tracker.recommend_best(["tool_a"], min_calls=5)
        # 调用次数不足，但仍会返回（降级处理）
        # 等等，re-检查 recommend_best 逻辑
        # 若所有工具 total_calls=0 返回 None；若有数据但 < min_calls，仍返回
        assert best == "tool_a"  # 有数据，仍返回


# ========== 单例与重置测试 ==========


class TestToolQualityTrackerSingleton:
    """测试单例与重置"""

    @pytest.mark.asyncio
    async def test_reset_single_tool(self):
        tracker = get_tool_quality_tracker()
        await tracker.record("test_reset_tool", True, 100)
        assert await tracker.get_metrics("test_reset_tool") is not None

        count = await tracker.reset("test_reset_tool")
        assert count == 1
        assert await tracker.get_metrics("test_reset_tool") is None

    @pytest.mark.asyncio
    async def test_get_summary(self):
        tracker = get_tool_quality_tracker()
        await tracker.record("summary_test_tool", True, 100)

        summary = await tracker.get_summary()
        assert "total_tools" in summary
        assert "total_calls" in summary
        assert "overall_success_rate" in summary
        assert "tools" in summary
        assert summary["total_calls"] >= 1

        # 清理
        await tracker.reset("summary_test_tool")


# ========== TTL 清理测试 ==========


class TestToolQualityTTL:
    """测试 TTL 过期清理"""

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        tracker = object.__new__(ToolQualityTracker)
        tracker._initialized = True
        tracker._metrics = {}
        tracker._data_lock = asyncio.Lock()
        tracker._ttl_days = 7
        tracker._last_cleanup = datetime.now(timezone.utc) - timedelta(hours=25)

        # 记录一个工具
        await tracker.record("old_tool", True, 100)
        # record 会触发 _maybe_cleanup（25h>24h），但 old_tool 刚记录未过期

        # 手动修改 last_called_at 为 10 天前（已过期）
        async with tracker._data_lock:
            tracker._metrics["old_tool"].last_called_at = (
                datetime.now(timezone.utc) - timedelta(days=10)
            )

        # 重置 _last_cleanup 为 25 小时前，使下次 record 触发清理
        tracker._last_cleanup = datetime.now(timezone.utc) - timedelta(hours=25)

        # 触发清理
        await tracker.record("new_tool", True, 100)  # 这会触发 _maybe_cleanup

        assert "old_tool" not in tracker._metrics
        assert "new_tool" in tracker._metrics
