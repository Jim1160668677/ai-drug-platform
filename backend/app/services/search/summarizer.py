"""搜索结果摘要器（MapReduce 风格）+ 全局 LRU 缓存。

算法参考 LangChain MapReduceDocumentsChain 的简化版：
  Map: 每条 result → (title 前 30 字) + (snippet 前 90 字) 组成一条"要点句子"
  Reduce: 去重 + 按领域去重合并 → 编号输出 ≤ max_characters
不调 LLM（避免把 D 瓶颈转移到 LLM 调用延迟上）——纯文本规则即可把 10 条搜索摘要压到 400 字以内核心信息。
"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from app.services.search.base import SearchResult

logger = logging.getLogger(__name__)


class _SearchLRU:
    def __init__(self, maxsize: int = 512, ttl_seconds: int = 86400):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        import time as _t
        self._t = _t
        self._d: "OrderedDict[Tuple, Tuple[float, List[Any]]]" = OrderedDict()

    def get(self, key):
        if key not in self._d:
            return None
        ts, val = self._d[key]
        if self._t.time() - ts > self.ttl:
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return val

    def put(self, key, value) -> None:
        import time
        if key in self._d:
            self._d.move_to_end(key)
        self._d[key] = (time.time(), list(value))
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)


_global_search_cache = _SearchLRU(maxsize=512, ttl_seconds=86400)


_NOISE_RE = re.compile(
    r"(copyright\s*©?\s*\d{4}|all\s+rights\s+reserved|doi:\s*\S+|pmid\s*\d+)",
    re.IGNORECASE,
)


class SearchSummarizer:
    """把 SearchResult 列表压成 3~5 条要点短摘要。"""

    _IMPORTANT_KWS = re.compile(
        r"(phase\s*[iI]{1,3}|clinical\s+trial|pfs|os|hr\s*[<>=]|p\s*[<>=]\s*0\.0|objective\s+response|"
        r"or\s*[=:]\s*\d|resistance|mutation|sensitivity|specificity|biomarker|"
        r"approved|fda|breakthrough|orrc|ic50|kd\s*[<=])",
        re.IGNORECASE,
    )

    def summarize(self, results: List["SearchResult"], max_characters: int = 400) -> str:
        if not results:
            return ""
        sentences: List[str] = []
        for r in results:
            title = (r.title or "").strip()
            snippet = (r.snippet or "").strip()
            snippet = _NOISE_RE.sub(" ", snippet)
            snippet = re.sub(r"\s+", " ", snippet).strip()
            head = title[:35] + ("…" if len(title) > 35 else "")
            body = snippet[:110] + ("…" if len(snippet) > 110 else "")
            if head and body:
                line = f"{head}: {body}"
            else:
                line = head or body
            sentences.append(line)

        def _score(s: str) -> int:
            return len(self._IMPORTANT_KWS.findall(s))

        sentences = [s for s in sentences if s]
        sentences.sort(key=_score, reverse=True)
        seen_norm = set()
        uniq: List[str] = []
        for s in sentences:
            n = re.sub(r"\W+", " ", s.lower()).strip()
            if n in seen_norm:
                continue
            seen_norm.add(n)
            uniq.append(s)

        out_parts: List[str] = ["搜索结果核心摘要："]
        used = len(out_parts[0]) + 2
        for i, s in enumerate(uniq, 1):
            item = f"{i}. {s}"
            if used + len(item) + 1 > max_characters:
                break
            out_parts.append(item)
            used += len(item) + 1
        return "\n- ".join(out_parts) if len(out_parts) > 1 else out_parts[0]
