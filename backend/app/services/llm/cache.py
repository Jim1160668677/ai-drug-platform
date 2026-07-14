"""LLM 响应缓存 — 内存 LRU + 可选 Redis

按 prompt hash + tier 缓存 LLM 响应，避免重复调用相同提示。
仅缓存 fast_screen 层（deep_insight 通常包含 RAG 上下文，不宜缓存）。
"""
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 缓存默认配置
_DEFAULT_MAX_SIZE = 512
_DEFAULT_TTL_SEC = 3600  # 1 小时


class LLMResponseCache:
    """两阶缓存：内存 LRU（热数据）+ Redis（跨进程，可选）

    Usage:
        cache = get_cache()
        cached = await cache.get(prompt, tier="fast_screen")
        if cached:
            return cached  # 命中
        # ... 调用 LLM ...
        await cache.set(prompt, tier, response, ttl=3600)
    """

    def __init__(
        self,
        max_size: int = _DEFAULT_MAX_SIZE,
        default_ttl: int = _DEFAULT_TTL_SEC,
        redis_client=None,
    ):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._redis = redis_client
        # 统计
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _hash_key(prompt: str, tier: str, system: Optional[str] = None) -> str:
        """生成缓存键 — prompt + tier + system 的 SHA256"""
        raw = f"{tier}|{system or ''}|{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(
        self,
        prompt: str,
        tier: str = "fast_screen",
        system: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """查询缓存

        Returns:
            缓存的响应 dict（含 _cache_hit=True），或 None
        """
        key = self._hash_key(prompt, tier, system)

        # 1. 内存缓存
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                if time.time() < entry["expires_at"]:
                    self._hits += 1
                    result = dict(entry["response"])
                    result["_cache_hit"] = True
                    logger.debug(f"LLMCache HIT (memory): {key[:12]}...")
                    return result
                else:
                    del self._store[key]

        # 2. Redis 缓存
        if self._redis is not None:
            try:
                import json

                raw = await self._redis.get(f"llm_cache:{key}")
                if raw:
                    self._hits += 1
                    result = json.loads(raw)
                    result["_cache_hit"] = True
                    logger.debug(f"LLMCache HIT (redis): {key[:12]}...")
                    return result
            except Exception as e:
                logger.warning(f"LLMCache redis get 失败: {e}")

        self._misses += 1
        return None

    async def set(
        self,
        prompt: str,
        tier: str,
        response: Dict[str, Any],
        system: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """写入缓存

        Args:
            prompt: 原始提示
            tier: 模型层级
            response: LLM 响应 dict
            system: 系统提示词（可选）
            ttl: 过期秒数（默认 1 小时）
        """
        # deep_insight 含 RAG 上下文，默认不缓存
        if tier == "deep_insight" and ttl is None:
            logger.debug("LLMCache 跳过 deep_insight（含 RAG 上下文）")
            return

        key = self._hash_key(prompt, tier, system)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl

        # 移除缓存标记
        clean = {k: v for k, v in response.items() if k != "_cache_hit"}

        # 1. 写入内存
        with self._lock:
            self._store[key] = {"response": clean, "expires_at": expires_at}
            self._store.move_to_end(key)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

        # 2. 写入 Redis
        if self._redis is not None:
            try:
                import json

                await self._redis.setex(
                    f"llm_cache:{key}",
                    ttl or self._default_ttl,
                    json.dumps(clean, default=str),
                )
            except Exception as e:
                logger.warning(f"LLMCache redis set 失败: {e}")

    async def invalidate(self, pattern: Optional[str] = None) -> int:
        """失效缓存

        Args:
            pattern: 按前缀匹配失效（None = 清空全部）
        Returns:
            失效条目数
        """
        count = 0
        with self._lock:
            if pattern is None:
                count = len(self._store)
                self._store.clear()
            else:
                keys_to_del = [k for k in self._store if k.startswith(pattern)]
                for k in keys_to_del:
                    del self._store[k]
                    count += 1

        if self._redis is not None:
            try:
                if pattern is None:
                    await self._redis.flushdb()
                else:
                    # 简化：用 keys + delete
                    keys = await self._redis.keys(f"llm_cache:{pattern}*")
                    if keys:
                        await self._redis.delete(*keys)
                        count += len(keys)
            except Exception as e:
                logger.warning(f"LLMCache redis invalidate 失败: {e}")

        logger.info(f"LLMCache 失效 {count} 条")
        return count

    def stats(self) -> Dict[str, Any]:
        """缓存统计"""
        total = self._hits + self._misses
        hit_rate = round(self._hits / total, 4) if total > 0 else 0.0
        with self._lock:
            return {
                "memory_entries": len(self._store),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "redis_enabled": self._redis is not None,
                "default_ttl_sec": self._default_ttl,
            }


# 模块级单例
_cache: Optional[LLMResponseCache] = None


def get_cache() -> LLMResponseCache:
    """获取 LLMResponseCache 单例"""
    global _cache
    if _cache is None:
        _cache = LLMResponseCache()
    return _cache
