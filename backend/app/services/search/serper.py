"""Serper.dev 搜索引擎 — Google 搜索 API 代理

调用 https://google.serper.dev/search（POST JSON），免费 2500 次/月。
需配置 SERPER_API_KEY。

文档：https://serper.dev/
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.services.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

SERPER_API_URL = "https://google.serper.dev/search"


class SerperEngine(SearchEngine):
    """Serper.dev Google 搜索代理"""

    name = "serper"

    def __init__(self, api_key: Optional[str] = None):
        """初始化

        Args:
            api_key: Serper API Key（默认从 settings.SERPER_API_KEY 读取）
        """
        from app.core.config import settings
        self.api_key = api_key or settings.SERPER_API_KEY.strip()
        self.timeout = settings.WEB_SEARCH_TIMEOUT_SEC
        self.use_mock = settings.is_mock

    @property
    def is_available(self) -> bool:
        """可用性：非 Mock 模式且 API Key 已配置"""
        return self.use_mock or bool(self.api_key)

    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """执行 Serper 搜索"""
        if not query.strip():
            return []

        if self.use_mock:
            return self._mock_search(query, max_results)

        if not self.api_key:
            logger.warning("Serper API Key 未配置，跳过")
            return []

        try:
            payload = {
                "q": query,
                "num": max_results,
            }
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(SERPER_API_URL, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Serper HTTP {resp.status_code}: {resp.text[:200]}")
                    return []
                data = resp.json()

            results: List[SearchResult] = []
            # Serper 返回 organic 数组
            for i, item in enumerate(data.get("organic", [])[:max_results]):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source=self.name,
                    position=i + 1,
                    published_at=item.get("date"),
                ))

            # 知识图谱（如有）
            kg = data.get("knowledgeGraph")
            if kg:
                results.insert(0, SearchResult(
                    title=kg.get("title", ""),
                    url=kg.get("website", ""),
                    snippet=kg.get("description", ""),
                    source=self.name,
                    position=0,
                ))

            logger.info(f"Serper 搜索 '{query}': 返回 {len(results)} 条")
            return results

        except httpx.TimeoutException:
            logger.warning(f"Serper 搜索超时: {query}")
            return []
        except Exception as e:
            logger.error(f"Serper 搜索失败: {e}")
            return []

    def _mock_search(self, query: str, max_results: int) -> List[SearchResult]:
        """Mock 模式预置结果"""
        return [
            SearchResult(
                title=f"{query} - Google 搜索结果 1",
                url="https://www.example.com/result1",
                snippet=f"Serper Mock 结果：{query} 的第一条搜索结果。",
                source=self.name,
                position=1,
            ),
            SearchResult(
                title=f"{query} - Google 搜索结果 2",
                url="https://www.example.com/result2",
                snippet=f"Serper Mock 结果：{query} 的第二条搜索结果。",
                source=self.name,
                position=2,
            ),
        ][:max_results]
