"""LLM 响应缓存单元测试"""
import asyncio
import time

import pytest

from app.services.llm.cache import LLMResponseCache


@pytest.fixture
def cache():
    return LLMResponseCache(max_size=5, default_ttl=2)


class TestLLMResponseCache:

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """写入后能命中"""
        await cache.set("hello", "fast_screen", {"content": "world"})
        result = await cache.get("hello", "fast_screen")
        assert result is not None
        assert result["content"] == "world"
        assert result["_cache_hit"] is True

    @pytest.mark.asyncio
    async def test_miss(self, cache):
        """未写入的 key 返回 None"""
        result = await cache.get("nonexistent", "fast_screen")
        assert result is None

    @pytest.mark.asyncio
    async def test_tier_difference(self, cache):
        """不同 tier 的缓存独立"""
        await cache.set("prompt", "fast_screen", {"content": "fast"})
        await cache.set("prompt", "deep_insight", {"content": "deep"}, ttl=60)
        fast = await cache.get("prompt", "fast_screen")
        deep = await cache.get("prompt", "deep_insight")
        assert fast["content"] == "fast"
        assert deep["content"] == "deep"

    @pytest.mark.asyncio
    async def test_system_difference(self, cache):
        """不同 system prompt 的缓存独立"""
        await cache.set("prompt", "fast_screen", {"content": "a"}, system="sys1")
        await cache.set("prompt", "fast_screen", {"content": "b"}, system="sys2")
        a = await cache.get("prompt", "fast_screen", system="sys1")
        b = await cache.get("prompt", "fast_screen", system="sys2")
        assert a["content"] == "a"
        assert b["content"] == "b"

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, cache):
        """TTL 过期后不命中"""
        await cache.set("prompt", "fast_screen", {"content": "data"}, ttl=1)
        await asyncio.sleep(2)
        result = await cache.get("prompt", "fast_screen")
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache):
        """超出 max_size 时淘汰最旧"""
        for i in range(6):
            await cache.set(f"prompt_{i}", "fast_screen", {"content": str(i)})
        # prompt_0 应被淘汰
        result = await cache.get("prompt_0", "fast_screen")
        assert result is None
        # prompt_5 应存在
        result = await cache.get("prompt_5", "fast_screen")
        assert result is not None

    @pytest.mark.asyncio
    async def test_invalidate_all(self, cache):
        """清空全部缓存"""
        await cache.set("a", "fast_screen", {"content": "1"})
        await cache.set("b", "fast_screen", {"content": "2"})
        count = await cache.invalidate()
        assert count >= 2
        assert await cache.get("a", "fast_screen") is None
        assert await cache.get("b", "fast_screen") is None

    @pytest.mark.asyncio
    async def test_hit_miss_stats(self, cache):
        """命中/未命中统计"""
        await cache.set("hit", "fast_screen", {"content": "data"})
        await cache.get("hit", "fast_screen")  # hit
        await cache.get("miss", "fast_screen")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_deep_insight_not_cached_by_default(self, cache):
        """deep_insight 层默认不缓存"""
        await cache.set("prompt", "deep_insight", {"content": "deep"})
        result = await cache.get("prompt", "deep_insight")
        assert result is None

    @pytest.mark.asyncio
    async def test_deep_insight_cached_with_explicit_ttl(self, cache):
        """deep_insight 层显式 TTL 可缓存"""
        await cache.set("prompt", "deep_insight", {"content": "deep"}, ttl=60)
        result = await cache.get("prompt", "deep_insight")
        assert result is not None
        assert result["content"] == "deep"

    @pytest.mark.asyncio
    async def test_cache_hit_mark(self, cache):
        """缓存命中响应包含 _cache_hit 标记"""
        await cache.set("prompt", "fast_screen", {"content": "data"})
        result = await cache.get("prompt", "fast_screen")
        assert result["_cache_hit"] is True

    def test_stats_structure(self, cache):
        """stats 返回正确结构"""
        stats = cache.stats()
        assert "memory_entries" in stats
        assert "max_size" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert "redis_enabled" in stats
        assert "default_ttl_sec" in stats
