"""LLM 响应 LRU 缓存（相同 prompt 命中直接复用）

参考 LangChain 缓存策略的极简实现：OrderedDict + 规范化 key + maxsize LRU 淘汰。
只在相同 run_id 内有效，避免跨研究项目命中错误答案。
不引入任何新依赖。
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ResponseCache:
    """线程不安全的 LRU。asyncio 单协程使用是安全的。

    用法：
        cache = ResponseCache(maxsize=128, run_id="run_123")
        key = cache.build_key("reflection", system=..., user=...)
        cached = cache.get(key)
        if cached is None:
            resp = await llm.call(...)
            cache.put(key, resp)
    """

    def __init__(self, maxsize: int = 256, run_id: str = ""):
        self.maxsize = max(1, int(maxsize))
        self.run_id = str(run_id)
        self._store: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        t = text.strip()
        t = re.sub(r"\s+", " ", t)
        return t

    def build_key(self, agent_name: str, **parts: Any) -> str:
        merged = [self.run_id, agent_name]
        for k in sorted(parts.keys()):
            v = parts[k]
            if isinstance(v, str):
                merged.append(f"{k}={self._normalize(v)}")
            else:
                merged.append(f"{k}={repr(v)}")
        raw = "||".join(merged).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        k = self._normalize(key)
        if k in self._store:
            self._store.move_to_end(k)
            self.hits += 1
            return self._store[k]
        self.misses += 1
        return None

    def put(self, key: str, value: Dict[str, Any]) -> None:
        k = self._normalize(key)
        if k in self._store:
            self._store.move_to_end(k)
        self._store[k] = dict(value)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def stats(self) -> Dict[str, Any]:
        return {
            "size": len(self._store),
            "maxsize": self.maxsize,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate(), 4),
        }
