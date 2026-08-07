"""Brave Search 引擎 — 隐私优先的搜索引擎 API

调用 https://api.search.brave.com/res/v1/web/search，免费 2000 次/月。
需配置 BRAVE_SEARCH_API_KEY。

文档：https://api.search.brave.com/
"""
import logging
from typing import List, Optional

import httpx

from app.services.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchEngine(SearchEngine):
    """Brave Search API 客户端"""

    name = "brave"

    def __init__(self, api_key: Optional[str] = None):
        """初始化

        Args:
            api_key: Brave API Key（默认从 settings.BRAVE_SEARCH_API_KEY 读取）
        """
        from app.core.config import settings
        self.api_key = api_key or settings.BRAVE_SEARCH_API_KEY.strip()
        self.timeout = settings.WEB_SEARCH_TIMEOUT_SEC
        self.use_mock = settings.is_mock

    @property
    def is_available(self) -> bool:
        """可用性：非 Mock 模式且 API Key 已配置"""
        return self.use_mock or bool(self.api_key)

    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """执行 Brave 搜索"""
        if not query.strip():
            return []

        if self.use_mock:
            return self._mock_search(query, max_results)

        if not self.api_key:
            logger.warning("Brave API Key 未配置，跳过")
            return []

        try:
            headers = {
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            }
            params = {
                "q": query,
                "count": min(max_results, 20),
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(BRAVE_API_URL, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Brave HTTP {resp.status_code}: {resp.text[:200]}")
                    return []
                data = resp.json()

            results: List[SearchResult] = []
            # Brave 返回 web.results 数组
            web_data = data.get("web", {}) or {}
            for i, item in enumerate(web_data.get("results", [])[:max_results]):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    source=self.name,
                    position=i + 1,
                    published_at=item.get("age"),
                ))

            logger.info(f"Brave 搜索 '{query}': 返回 {len(results)} 条")
            return results

        except httpx.TimeoutException:
            logger.warning(f"Brave 搜索超时: {query}")
            return []
        except Exception as e:
            logger.error(f"Brave 搜索失败: {e}")
            return []

    def _mock_search(self, query: str, max_results: int) -> List[SearchResult]:
        """Mock 模式预置结果"""
        return [
            SearchResult(
                title=f"{query} - Brave 搜索结果 1",
                url="https://www.example.org/brave1",
                snippet=f"Brave Mock 结果：{query} 的第一条搜索结果。",
                source=self.name,
                position=1,
            ),
            SearchResult(
                title=f"{query} - Brave 搜索结果 2",
                url="https://www.example.org/brave2",
                snippet=f"Brave Mock 结果：{query} 的第二条搜索结果。",
                source=self.name,
                position=2,
            ),
        ][:max_results]
