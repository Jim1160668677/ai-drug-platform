"""RateLimiter 单元测试 — Redis 令牌桶 + 内存降级"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.services.agent.ratelimit import (
    RateLimiter,
    get_rate_limiter,
    _rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置模块级单例，避免相互污染"""
    import app.services.agent.ratelimit as mod
    saved = mod._rate_limiter
    mod._rate_limiter = None
    yield
    mod._rate_limiter = saved


# ========== check_rpm 内存模式 ==========


@pytest.mark.asyncio
async def test_check_rpm_under_limit_memory():
    limiter = RateLimiter(redis_client=None)
    ok, retry_after = await limiter.check_rpm("user-1")
    assert ok is True
    assert retry_after is None


@pytest.mark.asyncio
async def test_check_rpm_over_limit_memory():
    limiter = RateLimiter(redis_client=None)
    limit = settings.AGENT_RATE_LIMIT_RPM
    # 前 limit 次通过
    for _ in range(limit):
        ok, _ = await limiter.check_rpm("user-2")
        assert ok is True
    # 第 limit+1 次被拒
    ok, retry_after = await limiter.check_rpm("user-2")
    assert ok is False
    assert retry_after is not None
    assert retry_after > 0


# ========== check_rpm Redis 模式 ==========


@pytest.mark.asyncio
async def test_check_rpm_redis_mock_success():
    """Redis 模式：incr 返回 ≤ limit，通过"""
    redis = MagicMock()
    pipe = MagicMock()
    pipe.incr = MagicMock(return_value=MagicMock())
    pipe.expire = MagicMock(return_value=MagicMock())
    # pipeline.execute() 返回 [count, _]
    pipe.execute = AsyncMock(return_value=[1, True])
    redis.pipeline.return_value = pipe
    redis.ttl = AsyncMock(return_value=60)

    limiter = RateLimiter(redis_client=redis)
    ok, retry_after = await limiter.check_rpm("user-3")
    assert ok is True
    assert retry_after is None


@pytest.mark.asyncio
async def test_check_rpm_redis_mock_exceeded():
    """Redis 模式：incr 返回 > limit，被拒并返回 ttl"""
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[settings.AGENT_RATE_LIMIT_RPM + 1, True])
    redis.pipeline.return_value = pipe
    redis.ttl = AsyncMock(return_value=30)

    limiter = RateLimiter(redis_client=redis)
    ok, retry_after = await limiter.check_rpm("user-4")
    assert ok is False
    assert retry_after == 30


@pytest.mark.asyncio
async def test_check_rpm_redis_failure_fallback():
    """Redis 异常时降级到内存模式，_redis 被置 None"""
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=ConnectionError("redis down"))
    redis.pipeline.return_value = pipe

    limiter = RateLimiter(redis_client=redis)
    # 第一次：Redis 异常 → 降级内存
    ok, _ = await limiter.check_rpm("user-5")
    assert ok is True  # 内存模式首次通过
    assert limiter.is_redis_available is False  # 已降级


# ========== acquire_concurrency 内存模式 ==========


@pytest.mark.asyncio
async def test_acquire_concurrency_under_limit_memory():
    limiter = RateLimiter(redis_client=None)
    limit = settings.AGENT_RATE_LIMIT_CONCURRENT
    for i in range(limit):
        ok, current = await limiter.acquire_concurrency("user-c1")
        assert ok is True
        assert current == i + 1


@pytest.mark.asyncio
async def test_acquire_concurrency_over_limit_memory():
    limiter = RateLimiter(redis_client=None)
    limit = settings.AGENT_RATE_LIMIT_CONCURRENT
    for _ in range(limit):
        await limiter.acquire_concurrency("user-c2")
    ok, current = await limiter.acquire_concurrency("user-c2")
    assert ok is False
    assert current == limit


@pytest.mark.asyncio
async def test_release_concurrency_memory():
    limiter = RateLimiter(redis_client=None)
    await limiter.acquire_concurrency("user-c3")
    await limiter.release_concurrency("user-c3")
    # 释放后可再次获取
    ok, current = await limiter.acquire_concurrency("user-c3")
    assert ok is True
    assert current == 1


@pytest.mark.asyncio
async def test_release_concurrency_below_zero_protected():
    """多次 release 不会使计数变负"""
    limiter = RateLimiter(redis_client=None)
    await limiter.acquire_concurrency("user-c4")
    await limiter.release_concurrency("user-c4")
    await limiter.release_concurrency("user-c4")  # 多释放一次
    await limiter.release_concurrency("user-c4")
    # 计数不应为负
    assert limiter._fallback_conc["user-c4"] >= 0


# ========== acquire_concurrency Redis 模式 ==========


@pytest.mark.asyncio
async def test_acquire_concurrency_redis_mock_success():
    redis = MagicMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)

    limiter = RateLimiter(redis_client=redis)
    ok, current = await limiter.acquire_concurrency("user-r1")
    assert ok is True
    assert current == 1
    redis.expire.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_concurrency_redis_mock_exceeded():
    redis = MagicMock()
    redis.incr = AsyncMock(return_value=settings.AGENT_RATE_LIMIT_CONCURRENT + 1)
    redis.decr = AsyncMock(return_value=settings.AGENT_RATE_LIMIT_CONCURRENT)
    redis.expire = AsyncMock(return_value=True)

    limiter = RateLimiter(redis_client=redis)
    ok, current = await limiter.acquire_concurrency("user-r2")
    assert ok is False
    assert current == settings.AGENT_RATE_LIMIT_CONCURRENT
    redis.decr.assert_awaited()


@pytest.mark.asyncio
async def test_release_concurrency_redis_mock():
    redis = MagicMock()
    redis.decr = AsyncMock(return_value=0)

    limiter = RateLimiter(redis_client=redis)
    await limiter.release_concurrency("user-r3")
    redis.decr.assert_awaited()


@pytest.mark.asyncio
async def test_release_concurrency_redis_negative_reset():
    """Redis decr 返回负数时，调用 set(key, 0) 重置"""
    redis = MagicMock()
    redis.decr = AsyncMock(return_value=-1)
    redis.set = AsyncMock(return_value=True)

    limiter = RateLimiter(redis_client=redis)
    await limiter.release_concurrency("user-r4")
    redis.set.assert_awaited()
    args = redis.set.call_args
    assert args[0][1] == 0  # 第二个位置参数 = 0


# ========== 单例 get_rate_limiter ==========


def test_get_rate_limiter_singleton():
    a = get_rate_limiter()
    b = get_rate_limiter()
    assert a is b


def test_get_rate_limiter_inject_redis_later():
    """首次 None 创建，二次传 redis 注入到原实例"""
    a = get_rate_limiter()
    assert a.is_redis_available is False
    fake_redis = MagicMock()
    b = get_rate_limiter(redis_client=fake_redis)
    assert b is a
    assert a.is_redis_available is True
