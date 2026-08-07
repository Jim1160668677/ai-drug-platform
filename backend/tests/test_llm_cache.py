"""LLM 响应缓存测试 — Phase C 性能优化

验证 app.core.llm.cache.LLMResponseCache 的核心功能：
- 缓存命中/未命中
- TTL 过期
- LRU 淘汰
- temperature<=0 自动缓存
- 统计准确性
- 线程安全
"""
import asyncio
import time
import pytest

from app.core.llm.cache import LLMResponseCache


@pytest.fixture
def cache():
    """每个测试用独立缓存实例"""
    return LLMResponseCache(max_entries=3, ttl_seconds=2, enabled=True)


class TestCacheBasic:
    """基础缓存功能"""

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(self, cache):
        """首次未命中 → 执行调用 → 第二次命中"""
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": "test response", "error": None}

        # 首次调用 — 未命中
        result1 = await cache.get_or_call("prompt1", call_fn, temperature=0.0)
        assert result1["content"] == "test response"
        assert call_count == 1

        # 第二次调用 — 命中缓存
        result2 = await cache.get_or_call("prompt1", call_fn, temperature=0.0)
        assert result2["content"] == "test response"
        assert call_count == 1  # 未再次执行 call_fn

    @pytest.mark.asyncio
    async def test_different_prompts_no_collision(self, cache):
        """不同 prompt 不冲突"""
        results = []

        async def call_fn_a():
            return {"content": "A"}
        async def call_fn_b():
            return {"content": "B"}

        r1 = await cache.get_or_call("promptA", call_fn_a, temperature=0.0)
        r2 = await cache.get_or_call("promptB", call_fn_b, temperature=0.0)
        assert r1["content"] == "A"
        assert r2["content"] == "B"

    @pytest.mark.asyncio
    async def test_system_prompt_affects_key(self, cache):
        """不同 system prompt 生成不同缓存键"""
        count = 0

        async def call_fn():
            nonlocal count
            count += 1
            return {"content": f"resp{count}"}

        r1 = await cache.get_or_call("same prompt", call_fn, system="sys1", temperature=0.0)
        r2 = await cache.get_or_call("same prompt", call_fn, system="sys2", temperature=0.0)
        assert r1["content"] == "resp1"
        assert r2["content"] == "resp2"
        assert count == 2


class TestCacheTTL:
    """TTL 过期机制"""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache):
        """TTL 过期后重新调用"""
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": f"resp{call_count}", "error": None}

        # 首次调用
        await cache.get_or_call("prompt", call_fn, temperature=0.0)
        assert call_count == 1

        # 等待 TTL 过期（ttl_seconds=2）
        await asyncio.sleep(2.1)

        # 再次调用 — 应重新执行
        await cache.get_or_call("prompt", call_fn, temperature=0.0)
        assert call_count == 2


class TestCacheLRU:
    """LRU 淘汰策略"""

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache):
        """max_entries=3 时，第 4 个条目淘汰最旧的"""
        async def call_fn(key):
            return {"content": key, "error": None}

        # 填满 3 个条目
        await cache.get_or_call("p1", lambda: call_fn("p1"), temperature=0.0)
        await cache.get_or_call("p2", lambda: call_fn("p2"), temperature=0.0)
        await cache.get_or_call("p3", lambda: call_fn("p3"), temperature=0.0)

        stats = cache.stats()
        assert stats["entries"] == 3

        # 第 4 个条目 — 淘汰 p1（最旧）
        await cache.get_or_call("p4", lambda: call_fn("p4"), temperature=0.0)
        stats = cache.stats()
        assert stats["entries"] == 3
        assert stats["evictions"] == 1

    @pytest.mark.asyncio
    async def test_lru_access_refreshes(self, cache):
        """访问条目会刷新其 LRU 位置"""
        async def call_fn(key):
            return {"content": key, "error": None}

        await cache.get_or_call("p1", lambda: call_fn("p1"), temperature=0.0)
        await cache.get_or_call("p2", lambda: call_fn("p2"), temperature=0.0)
        await cache.get_or_call("p3", lambda: call_fn("p3"), temperature=0.0)

        # 访问 p1（刷新其位置）
        await cache.get_or_call("p1", lambda: call_fn("p1_NEW"), temperature=0.0)

        # 添加 p4 — 应淘汰 p2（而非 p1）
        await cache.get_or_call("p4", lambda: call_fn("p4"), temperature=0.0)

        # p1 应仍在缓存中（命中）
        hit_count_before = cache.stats()["hits"]
        await cache.get_or_call("p1", lambda: call_fn("p1_MISS"), temperature=0.0)
        hit_count_after = cache.stats()["hits"]
        assert hit_count_after > hit_count_before


class TestCacheTemperature:
    """温度相关的缓存策略"""

    @pytest.mark.asyncio
    async def test_high_temperature_not_cached(self, cache):
        """temperature > 0 默认不缓存"""
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": "resp", "error": None}

        await cache.get_or_call("prompt", call_fn, temperature=0.7)
        await cache.get_or_call("prompt", call_fn, temperature=0.7)
        assert call_count == 2  # 两次都执行

    @pytest.mark.asyncio
    async def test_force_cache_high_temperature(self, cache):
        """use_cache=True 强制缓存高温度响应"""
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": "resp", "error": None}

        await cache.get_or_call("prompt", call_fn, temperature=0.7, use_cache=True)
        await cache.get_or_call("prompt", call_fn, temperature=0.7, use_cache=True)
        assert call_count == 1  # 第二次命中缓存


class TestCacheStats:
    """统计功能"""

    @pytest.mark.asyncio
    async def test_stats_accuracy(self, cache):
        """命中率统计准确"""
        async def call_fn():
            return {"content": "resp", "error": None}

        # 1 次未命中
        await cache.get_or_call("p1", call_fn, temperature=0.0)
        # 2 次命中
        await cache.get_or_call("p1", call_fn, temperature=0.0)
        await cache.get_or_call("p1", call_fn, temperature=0.0)
        # 1 次未命中
        await cache.get_or_call("p2", call_fn, temperature=0.0)

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_disabled_cache_passthrough(self):
        """enabled=False 时完全透传"""
        cache = LLMResponseCache(enabled=False)
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": "resp", "error": None}

        await cache.get_or_call("p1", call_fn, temperature=0.0)
        await cache.get_or_call("p1", call_fn, temperature=0.0)
        assert call_count == 2
        assert cache.stats()["entries"] == 0

    @pytest.mark.asyncio
    async def test_error_response_not_cached(self, cache):
        """错误响应不被缓存"""
        call_count = 0

        async def call_fn():
            nonlocal call_count
            call_count += 1
            return {"content": "", "error": "API error"}

        await cache.get_or_call("p1", call_fn, temperature=0.0)
        await cache.get_or_call("p1", call_fn, temperature=0.0)
        assert call_count == 2  # 错误响应未缓存，两次都执行


class TestCacheCleanup:
    """清理功能"""

    @pytest.mark.asyncio
    async def test_clear_cache(self, cache):
        """clear() 清空所有条目"""
        async def call_fn():
            return {"content": "resp", "error": None}

        await cache.get_or_call("p1", call_fn, temperature=0.0)
        await cache.get_or_call("p2", call_fn, temperature=0.0)
        assert cache.stats()["entries"] == 2

        cleared = await cache.clear()
        assert cleared == 2
        assert cache.stats()["entries"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """cleanup_expired 清理过期条目"""
        cache = LLMResponseCache(ttl_seconds=0.5, enabled=True)

        async def call_fn():
            return {"content": "resp", "error": None}

        await cache.get_or_call("p1", call_fn, temperature=0.0)
        await asyncio.sleep(0.6)

        expired = await cache.cleanup_expired()
        assert expired == 1
        assert cache.stats()["entries"] == 0