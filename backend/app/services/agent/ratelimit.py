"""Agent 限流器 — Redis 令牌桶 + 内存降级

设计来源：2026-07-18-agent-functional-design.md §9

两个维度：
- RPM（每分钟请求数）：固定窗口计数器
- 并发任务数：原子 INCR/DECR

Redis 不可用时降级到进程内字典计数器（仅单实例有效）。
"""
import logging
import time
from collections import defaultdict
from typing import Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis 限流器，内存降级

    Usage:
        limiter = RateLimiter(redis_client)
        ok, retry_after = await limiter.check_rpm(user_id)
        if not ok:
            raise RateLimitedError(retry_after=retry_after)
        try:
            ok, _ = await limiter.acquire_concurrency(user_id)
            ...  # 执行任务
        finally:
            await limiter.release_concurrency(user_id)
    """

    def __init__(self, redis_client=None):
        """Args:
            redis_client: 可选的 redis.asyncio.Redis 实例；None 时降级到内存
        """
        self._redis = redis_client
        self._fallback_rpm: dict[str, list[float]] = defaultdict(list)
        self._fallback_conc: dict[str, int] = defaultdict(int)
        self._fallback_locks: dict[str, bool] = defaultdict(bool)

    @property
    def is_redis_available(self) -> bool:
        return self._redis is not None

    async def check_rpm(self, user_id: str) -> Tuple[bool, Optional[int]]:
        """检查每分钟请求数限制

        Returns:
            (是否通过, retry_after_seconds)
        """
        key = f"agent:rpm:{user_id}"
        limit = settings.AGENT_RATE_LIMIT_RPM
        window_sec = 60

        if self.is_redis_available:
            try:
                return await self._check_rpm_redis(key, limit, window_sec)
            except Exception as e:
                logger.warning(f"Redis 限流降级到内存: {e}")
                self._redis = None  # 后续直接走内存

        return self._check_rpm_memory(user_id, limit, window_sec)

    async def _check_rpm_redis(
        self, key: str, limit: int, window_sec: int
    ) -> Tuple[bool, Optional[int]]:
        """Redis 实现：INCR + EXPIRE 固定窗口"""
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_sec, nx=True)  # 仅首次设置过期
        count, _ = await pipe.execute()
        if count > limit:
            ttl = await self._redis.ttl(key)
            retry_after = max(ttl, 1) if ttl > 0 else window_sec
            return False, retry_after
        return True, None

    def _check_rpm_memory(
        self, user_id: str, limit: int, window_sec: int
    ) -> Tuple[bool, Optional[int]]:
        """内存降级实现：滑动窗口"""
        now = time.time()
        cutoff = now - window_sec
        # 清理过期记录
        self._fallback_rpm[user_id] = [
            t for t in self._fallback_rpm[user_id] if t > cutoff
        ]
        if len(self._fallback_rpm[user_id]) >= limit:
            retry_after = int(window_sec - (now - self._fallback_rpm[user_id][0]))
            return False, max(retry_after, 1)
        self._fallback_rpm[user_id].append(now)
        return True, None

    async def acquire_concurrency(self, user_id: str) -> Tuple[bool, Optional[int]]:
        """获取并发槽位

        Returns:
            (是否获取成功, 当前并发数)
        """
        key = f"agent:conc:{user_id}"
        limit = settings.AGENT_RATE_LIMIT_CONCURRENT

        if self.is_redis_available:
            try:
                current = await self._redis.incr(key)
                if current > limit:
                    await self._redis.decr(key)
                    return False, current - 1
                # 设置过期防止泄漏（5 分钟兜底）
                await self._redis.expire(key, 300)
                return True, current
            except Exception as e:
                logger.warning(f"Redis 并发限流降级到内存: {e}")
                self._redis = None

        if self._fallback_conc[user_id] >= limit:
            return False, self._fallback_conc[user_id]
        self._fallback_conc[user_id] += 1
        return True, self._fallback_conc[user_id]

    async def release_concurrency(self, user_id: str) -> None:
        """释放并发槽位"""
        key = f"agent:conc:{user_id}"

        if self.is_redis_available:
            try:
                current = await self._redis.decr(key)
                if current < 0:
                    # 防止计数器变负
                    await self._redis.set(key, 0)
                return
            except Exception as e:
                logger.warning(f"Redis 释放并发降级: {e}")
                self._redis = None

        if self._fallback_conc[user_id] > 0:
            self._fallback_conc[user_id] -= 1


# 模块级单例（不持有 redis，由端点注入）
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(redis_client=None) -> RateLimiter:
    """获取限流器单例

    首次调用时若提供 redis_client 则注入；后续调用忽略 redis_client 参数。
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(redis_client)
    elif redis_client is not None and not _rate_limiter.is_redis_available:
        _rate_limiter._redis = redis_client
    return _rate_limiter
