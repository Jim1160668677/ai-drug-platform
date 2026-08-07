"""多引擎聚合器 — 并发调用 + 去重 + 重排序

策略：
1. 并发调用所有可用引擎（asyncio.gather + return_exceptions=True）
2. URL 归一化去重（同 URL 多源命中 → score 加权）
3. 综合评分 = 来源权重(0.4) + 域名权威性(0.4) + 原始排名(0.2)
4. 按综合评分降序返回

来源权重（基于经验设定）：
- serper: 1.0（Google 算法最权威）
- brave: 0.9（隐私优先，结果略逊 Google）
- duckduckgo: 0.8（免费，结果质量稳定）
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.services.search.base import (
    SearchEngine,
    SearchResult,
    get_domain_authority,
    normalize_url,
)

logger = logging.getLogger(__name__)

# 引擎来源权重
SOURCE_WEIGHTS: Dict[str, float] = {
    "serper": 1.0,
    "brave": 0.9,
    "duckduckgo": 0.8,
}


class MultiEngineAggregator:
    """多引擎聚合搜索

    Usage:
        agg = MultiEngineAggregator([DuckDuckGoEngine(), SerperEngine(), BraveSearchEngine()])
        results = await agg.search("EGFR inhibitor NSCLC")
    """

    def __init__(self, engines: Optional[List[SearchEngine]] = None):
        """初始化

        Args:
            engines: 引擎列表；None 时按 settings.WEB_SEARCH_ENGINE 自动配置
        """
        if engines is not None:
            self.engines = engines
        else:
            self.engines = self._build_default_engines()

    def _build_default_engines(self) -> List[SearchEngine]:
        """根据 settings.WEB_SEARCH_ENGINE 构建引擎列表"""
        from app.core.config import settings

        mode = settings.WEB_SEARCH_ENGINE.lower().strip()
        engines: List[SearchEngine] = []

        # 按 mode 选择引擎
        if mode in ("auto", "all"):
            # auto: 加载所有可用引擎（按优先级顺序）
            from app.services.search.duckduckgo import DuckDuckGoEngine
            from app.services.search.serper import SerperEngine
            from app.services.search.brave import BraveSearchEngine

            duckduckgo = DuckDuckGoEngine()
            serper = SerperEngine()
            brave = BraveSearchEngine()

            # 始终包含 DuckDuckGo（免费可用）
            engines.append(duckduckgo)
            # 仅添加已配置 Key 的引擎
            if serper.is_available and not serper.use_mock:
                engines.append(serper)
            if brave.is_available and not brave.use_mock:
                engines.append(brave)

        elif mode == "duckduckgo":
            from app.services.search.duckduckgo import DuckDuckGoEngine
            engines.append(DuckDuckGoEngine())
        elif mode == "serper":
            from app.services.search.serper import SerperEngine
            engines.append(SerperEngine())
        elif mode == "brave":
            from app.services.search.brave import BraveSearchEngine
            engines.append(BraveSearchEngine())
        else:
            logger.warning(f"未知 WEB_SEARCH_ENGINE={mode}，降级到 DuckDuckGo")
            from app.services.search.duckduckgo import DuckDuckGoEngine
            engines.append(DuckDuckGoEngine())

        return engines

    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """并发调用所有引擎并聚合结果

        Args:
            query: 搜索查询词
            max_results: 最大返回数
        Returns:
            去重 + 重排序后的结果列表
        """
        if not query.strip():
            return []

        # 过滤可用引擎
        available = [e for e in self.engines if e.is_available]
        if not available:
            logger.warning("无可用搜索引擎")
            return []

        # ========= 瓶颈 D：LRU 命中直接返回 =========
        from app.services.search.summarizer import _global_search_cache

        engine_names = sorted(getattr(e, "name", "") for e in available)
        cache_key = (query.strip().lower(), max_results, tuple(engine_names))
        cached = _global_search_cache.get(cache_key)
        if cached is not None:
            logger.info("[aggregator] cache hit for query=%s", query[:50])
            return cached[:max_results]

        # 并发调用
        tasks = [e.search(query, max_results=max_results) for e in available]
        # 每个引擎单独加超时（避免单个引擎慢导致整体等待）
        # return_exceptions=True 避免单引擎失败/超时影响整体
        tasks_with_timeout = [
            asyncio.wait_for(t, timeout=10.0) for t in tasks
        ]
        raw_results = await asyncio.gather(*tasks_with_timeout, return_exceptions=True)

        # 合并结果
        all_results: List[SearchResult] = []
        for engine, result in zip(available, raw_results):
            if isinstance(result, Exception):
                if isinstance(result, asyncio.TimeoutError):
                    logger.warning(f"引擎 {engine.name} 调用超时 (10s)")
                else:
                    logger.warning(f"引擎 {engine.name} 调用失败: {result}")
                continue
            if isinstance(result, list):
                all_results.extend(result)

        if not all_results:
            return []

        # 去重 + 评分 + 重排序
        aggregated = self._aggregate(all_results)

        # ========= 瓶颈 D：域名去重 Top-5 =========
        aggregated = apply_domain_limit_and_truncate(
            aggregated, per_domain=2, total=min(5, max_results)
        )
        from app.services.search.summarizer import _global_search_cache

        engine_names = sorted(getattr(e, "name", "") for e in available)
        cache_key = (query.strip().lower(), max_results, tuple(engine_names))
        _global_search_cache.put(cache_key, aggregated)
        return aggregated

    def _aggregate(self, results: List[SearchResult]) -> List[SearchResult]:
        """去重 + 评分 + 重排序

        1. URL 归一化
        2. 同 URL 多源命中 → 合并，来源权重取最大
        3. 综合评分 = 来源权重(0.4) + 域名权威性(0.4) + 原始排名(0.2)
        """
        # URL 归一化 + 按 URL 分组
        url_map: Dict[str, List[SearchResult]] = {}
        for r in results:
            normalized = normalize_url(r.url)
            if not normalized:
                continue
            r.url = normalized
            url_map.setdefault(normalized, []).append(r)

        aggregated: List[SearchResult] = []
        for url, group in url_map.items():
            # 取第一条作为基准（保留原始字段）
            best = group[0]
            # 多源命中时 score 加权
            source_bonus = max(
                SOURCE_WEIGHTS.get(r.source, 0.5) for r in group
            )
            # 多源命中本身是质量信号 +0.1
            if len(group) > 1:
                source_bonus = min(1.0, source_bonus + 0.1)

            # 综合评分
            domain_score = get_domain_authority(url) / 10.0  # 0-1
            # 原始排名评分：第 1 名 1.0，第 10 名 0.1
            position_score = 0.0
            if best.position and best.position > 0:
                position_score = max(0.0, 1.0 - (best.position - 1) * 0.1)

            # 加权综合
            total_score = (
                source_bonus * 0.4
                + domain_score * 0.4
                + position_score * 0.2
            )

            best.score = round(total_score, 4)
            aggregated.append(best)

        # 按综合评分降序
        aggregated.sort(key=lambda r: r.score or 0, reverse=True)

        # 域名级去重：同域只保留评分最高的 1 条（每域取 Top-1）
        seen_domain = set()
        deduped: List[SearchResult] = []
        for r in aggregated:
            try:
                host = urlparse(r.url).netloc.lower()
                if host.startswith("www."):
                    host = host[4:]
            except Exception:
                host = ""
            if host and host in seen_domain:
                continue
            if host:
                seen_domain.add(host)
            deduped.append(r)
        aggregated = deduped

        # 重新分配 position
        for i, r in enumerate(aggregated, 1):
            r.position = i

        return aggregated


# 模块级单例
_aggregator: Optional[MultiEngineAggregator] = None


def get_aggregator() -> MultiEngineAggregator:
    """获取聚合器单例"""
    global _aggregator
    if _aggregator is None:
        _aggregator = MultiEngineAggregator()
    return _aggregator


def reset_aggregator() -> None:
    """重置单例（测试用）"""
    global _aggregator
    _aggregator = None


# ========== 搜索结果域名级去重 + 全局 Top-N 截断（瓶颈 D）==========
import re as _re
from urllib.parse import urlparse as _urlparse


def _domain(url: str) -> str:
    try:
        host = _urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def apply_domain_limit_and_truncate(
    results: List["SearchResult"],
    per_domain: int = 2,
    total: int = 5,
) -> List["SearchResult"]:
    """每域名最多 per_domain 条 + 全局 total 条（默认 2/5，把搜索体积降到 30%~50%）

    保留优先级：按传入顺序（_aggregate 已经按综合评分排好），所以取前 N 稳定。
    """
    seen: Dict[str, int] = {}
    out: List[SearchResult] = []
    for r in results:
        d = _domain(r.url)
        if d and seen.get(d, 0) >= per_domain:
            continue
        seen[d] = seen.get(d, 0) + 1
        out.append(r)
        if len(out) >= total:
            break
    return out
