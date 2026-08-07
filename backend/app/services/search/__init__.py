"""网络搜索模块 — 多引擎聚合 + 网页抓取

模块组成：
- base:           SearchEngine ABC + SearchResult 数据类
- duckduckgo:     DuckDuckGo 引擎（免费）
- serper:         Serper.dev 引擎（Google 代理）
- brave:          Brave Search 引擎
- aggregator:     多引擎聚合器
- fetcher:        网页抓取器
"""
from app.services.search.aggregator import MultiEngineAggregator, get_aggregator
from app.services.search.base import (
    SearchEngine,
    SearchResult,
    get_domain_authority,
    normalize_url,
)
from app.services.search.fetcher import WebPageFetcher

__all__ = [
    "SearchEngine",
    "SearchResult",
    "MultiEngineAggregator",
    "get_aggregator",
    "WebPageFetcher",
    "normalize_url",
    "get_domain_authority",
]
