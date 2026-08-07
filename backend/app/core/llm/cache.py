"""LLM 响应缓存 — Phase C 性能优化

减少 Co-Scientist 多智能体协作中的重复 LLM 调用，降低成本和延迟。

设计：
- 基于 (prompt + system + temperature + model) 哈希的内存缓存
- TTL 过期机制（默认 1 小时）
- 仅缓存确定性响应（temperature=0 或显式启用）
- 线程安全 + 异步友好（asyncio.Lock）
- LRU 淘汰策略（默认 max_entries=512）
- 命中率统计

使用方式：
    from app.core.llm.cache import llm_cache

    # 显式启用缓存
    result = await llm_cache.get_or_call(
        prompt="分析 TP53 的作用",
        system="你是生物学家",
        temperature=0.0,
        call_fn=lambda: llm_client.chat(messages),
    )

    # 统计
    stats = llm_cache.stats()
"""
import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class LLMResponseCache:
    """LLM 响应内存缓存（LRU + TTL）

    线程安全：使用 asyncio.Lock 保护内部 OrderedDict。
    异步友好：get_or_call 接受 async callable。
    """

    def __init__(
        self,
        max_entries: int = 512,
        ttl_seconds: int = 3600,
        enabled: bool = True,
    ):
        """
        Args:
            max_entries: 最大缓存条目数（LRU 淘汰）
            ttl_seconds: 单条目存活时间（秒）
            enabled: 全局开关（False 则完全透传）
        """
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._lock = asyncio.Lock()
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled

        # 统计
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _make_key(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        model: str = "",
    ) -> str:
        """生成缓存键 — 基于内容哈希"""
        raw = f"{system or ''}|{prompt}|{temperature}|{model}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _is_expired(self, entry: dict) -> bool:
        """检查条目是否过期"""
        return time.time() - entry["timestamp"] > self.ttl_seconds

    async def get(self, key: str) -> Optional[dict]:
        """异步获取缓存条目"""
        if not self.enabled:
            return None
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._is_expired(entry):
                del self._store[key]
                self._misses += 1
                return None
            # LRU：移到末尾（最近使用）
            self._store.move_to_end(key)
            self._hits += 1
            # 返回深拷贝避免外部修改
            import copy
            return copy.deepcopy(entry["value"])

    async def set(self, key: str, value: dict) -> None:
        """异步设置缓存条目"""
        if not self.enabled:
            return
        async with self._lock:
            # LRU 淘汰
            while len(self._store) >= self.max_entries:
                self._store.popitem(last=False)
                self._evictions += 1

            self._store[key] = {
                "value": value,
                "timestamp": time.time(),
            }

    async def get_or_call(
        self,
        prompt: str,
        call_fn: Callable[[], Awaitable[dict]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        model: str = "",
        use_cache: Optional[bool] = None,
    ) -> dict:
        """获取缓存或执行调用

        Args:
            prompt: 用户 prompt
            call_fn: 异步调用函数（未命中时执行）
            system: 系统 prompt
            temperature: 采样温度
            model: 模型名称
            use_cache: 是否使用缓存（None=仅 temperature<=0 时缓存）
        Returns:
            LLM 响应 dict
        """
        # 决定是否缓存
        should_cache = use_cache if use_cache is not None else (temperature <= 0.0)
        if not should_cache or not self.enabled:
            return await call_fn()

        key = self._make_key(prompt, system, temperature, model)
        cached = await self.get(key)
        if cached is not None:
            logger.debug("[llm_cache] 命中缓存 key=%s", key[:8])
            return cached

        # 未命中 — 执行调用
        result = await call_fn()
        # 仅缓存成功响应
        if result and not result.get("error"):
            await self.set(key, result)
        return result

    def stats(self) -> Dict[str, Any]:
        """返回缓存统计"""
        total = self._hits + self._misses
        return {
            "enabled": self.enabled,
            "entries": len(self._store),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
            "evictions": self._evictions,
            "ttl_seconds": self.ttl_seconds,
        }

    async def clear(self) -> int:
        """清空缓存，返回清除的条目数"""
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    async def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        if not self.enabled:
            return 0
        async with self._lock:
            expired_keys = [
                k for k, v in self._store.items() if self._is_expired(v)
            ]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)


# 全局单例
llm_cache = LLMResponseCache(
    max_entries=512,
    ttl_seconds=3600,
    enabled=True,
)