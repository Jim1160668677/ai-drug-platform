"""DuckDuckGo 搜索引擎 — 免费、无需 API Key

使用 duckduckgo_search 库（AsyncDDGS），无 Key 限制。
速率限制：1 req/s（DuckDuckGo 官方建议）。

文档：https://pypi.org/project/duckduckgo-search/
"""
import asyncio
import logging
from typing import List

from app.services.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)


class DuckDuckGoEngine(SearchEngine):
    """DuckDuckGo 搜索引擎

    无 API Key，免费使用。Mock 模式（USE_MOCK=true）返回预置结果。
    """

    name = "duckduckgo"

    def __init__(self, use_mock: bool = False):
        """初始化

        Args:
            use_mock: True 时返回预置结果（用于测试环境）
        """
        from app.core.config import settings
        self.use_mock = use_mock or settings.is_mock
        self._semaphore = asyncio.Semaphore(1)  # 1 req/s
        self._last_call_time = 0.0

    @property
    def is_available(self) -> bool:
        """DuckDuckGo 始终可用"""
        return True

    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """执行 DuckDuckGo 搜索"""
        if not query.strip():
            return []

        if self.use_mock:
            return self._mock_search(query, max_results)

        async with self._semaphore:
            # 速率限制：距上次调用至少 1s
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_call_time
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
            self._last_call_time = asyncio.get_event_loop().time()

            try:
                from duckduckgo_search import AsyncDDGS

                results: List[SearchResult] = []
                async with AsyncDDGS() as ddgs:
                    async for r in ddgs.atext(query, max_results=max_results):
                        results.append(SearchResult(
                            title=r.get("title", ""),
                            url=r.get("href") or r.get("link", ""),
                            snippet=r.get("body") or r.get("snippet", ""),
                            source=self.name,
                            position=len(results) + 1,
                        ))
                logger.info(f"DuckDuckGo 搜索 '{query}': 返回 {len(results)} 条")
                return results
            except ImportError:
                logger.warning("duckduckgo_search 未安装，降级到 Mock")
                return self._mock_search(query, max_results)
            except Exception as e:
                logger.error(f"DuckDuckGo 搜索失败: {e}")
                return self._mock_search(query, max_results)

    def _mock_search(self, query: str, max_results: int) -> List[SearchResult]:
        """Mock 模式预置结果"""
        query_lower = query.lower()
        mock_results = [
            SearchResult(
                title=f"{query} - 最新研究进展",
                url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/",
                snippet=f"关于 {query} 的最新研究综述，涵盖分子机制、临床试验和治疗进展。",
                source=self.name,
                position=1,
            ),
            SearchResult(
                title=f"{query} - Nature Reviews Cancer",
                url="https://www.nature.com/articles/s41568-024-00045-6",
                snippet=f"Nature 综述：{query} 的生物学意义与临床应用前景。",
                source=self.name,
                position=2,
            ),
            SearchResult(
                title=f"{query} - ClinicalTrials.gov",
                url="https://clinicaltrials.gov/ct2/show/NCT01234567",
                snippet=f"正在进行的 {query} 相关临床试验，Phase III，招募中。",
                source=self.name,
                position=3,
            ),
            SearchResult(
                title=f"{query} - FDA 批准药物",
                url="https://www.fda.gov/drugs/postmarket-drug-safety-information",
                snippet=f"FDA 关于 {query} 靶向治疗的审批信息和安全性更新。",
                source=self.name,
                position=4,
            ),
            SearchResult(
                title=f"{query} - Wikipedia",
                url="https://en.wikipedia.org/wiki/EGFR_inhibitor",
                snippet=f"维基百科：{query} 的基础知识介绍。",
                source=self.name,
                position=5,
            ),
        ]
        # 过滤相关结果（简单子串匹配）
        if any(kw in query_lower for kw in ("egfr", "kras", "tp53", "cancer", "drug", "inhibitor")):
            return mock_results[:max_results]
        # 默认返回前 3 条
        return mock_results[: min(3, max_results)]
