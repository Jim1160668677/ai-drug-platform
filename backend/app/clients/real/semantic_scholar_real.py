"""Real Semantic Scholar 客户端 — 调用 https://api.semanticscholar.org/graph/v1

特性:
1. 速率限制: asyncio.Semaphore(1) 保守并发
   - 无 API Key: 100 req / 5 min ≈ 1 req / 3s
   - 有 API Key: 1 req/s(默认 5000 req/5min)
2. 内存缓存: TTL 7 天
3. 指数退避重试: 429/5xx 自动重试 3 次
4. 网络异常降级: 返回空列表

设计遵循 Semantic Scholar Graph API: https://api.semanticscholar.org/api-docs/graph
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.clients.base import AcademicClientBase, AcademicPaper
from app.core.config import settings

logger = logging.getLogger(__name__)

# 指数退避重试间隔(秒): 1s / 2s / 4s
_RETRY_DELAYS = [1.0, 2.0, 4.0]


class RealSemanticScholarClient(AcademicClientBase):
    """真实 Semantic Scholar 客户端

    Usage:
        client = RealSemanticScholarClient()
        papers = await client.search("EGFR lung cancer", limit=10)
    """

    source_name = "semantic_scholar"

    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        self.api_key = getattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "") or ""
        self.timeout = 30
        self.max_retries = 3
        # 速率限制: 无 API Key 时 100 req/5min ≈ 1 req/3s,保守并发=1
        self._semaphore = asyncio.Semaphore(1)
        # 连接池单例
        self._http_client: Optional[httpx.AsyncClient] = None
        # 内存缓存: query -> (papers, expires_at)
        self._mem_cache: Dict[str, Tuple[List[AcademicPaper], float]] = {}
        self._mem_cache_ttl = 7 * 86400  # 7 天

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取/复用 httpx.AsyncClient 单例(API Key 注入 header)"""
        if self._http_client is None or self._http_client.is_closed:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=self.timeout, connect=8.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=3),
                headers=headers,
            )
        return self._http_client

    async def _get_cached(self, query: str) -> Optional[List[AcademicPaper]]:
        """查询内存缓存,命中返回 AcademicPaper 列表,未命中返回 None"""
        cache_key = f"semantic_scholar:{query}"
        if cache_key in self._mem_cache:
            papers, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return papers
            del self._mem_cache[cache_key]
        return None

    async def _set_cached(self, query: str, papers: List[AcademicPaper]) -> None:
        """写入内存缓存"""
        cache_key = f"semantic_scholar:{query}"
        self._mem_cache[cache_key] = (papers, time.time() + self._mem_cache_ttl)

    def _parse_authors(self, authors_raw: List[Dict[str, Any]]) -> List[str]:
        """解析 S2 authors 字段 [{'name': 'Lynch T', 'authorId': '1'}, ...] -> ['Lynch T', ...]"""
        if not authors_raw:
            return []
        return [a.get("name", "").strip() for a in authors_raw if a.get("name")]

    def _parse_response(self, data: Dict[str, Any]) -> List[AcademicPaper]:
        """解析 S2 /paper/search 响应为 AcademicPaper 列表"""
        items = data.get("data") or []
        papers: List[AcademicPaper] = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            # DOI 在 externalIds 字段
            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI")

            paper = AcademicPaper(
                title=title,
                authors=self._parse_authors(item.get("authors")),
                source="semantic_scholar",
                abstract=item.get("abstract"),
                doi=doi,
                year=item.get("year"),
                url=item.get("url"),
                # S2 提供 citationCount/influentialCitationCount,可用作相关性近似
                relevance_score=None,
            )
            papers.append(paper)
        return papers

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索 Semantic Scholar 文献

        使用 /paper/search 端点,fields 参数指定返回字段。

        Args:
            query: 检索词,如 "EGFR lung cancer"
            limit: 最大返回数(默认 10,S2 上限 100)
            **kwargs: 保留参数(year/filter)

        Returns:
            AcademicPaper 列表,失败时返回空列表
        """
        # 1. 缓存命中检查
        cached = await self._get_cached(query)
        if cached is not None:
            logger.info(f"Semantic Scholar 缓存命中: {query[:60]}")
            return cached

        # 2. 构造请求参数
        # S2 限制 limit 上限 100
        s2_limit = min(limit, 100)
        params = {
            "query": query,
            "limit": s2_limit,
            "fields": "title,authors,abstract,year,externalIds,url,citationCount,influentialCitationCount",
        }

        last_error: Optional[Exception] = None
        async with self._semaphore:
            client = await self._get_http_client()
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.get(self.base_url, params=params)

                    # 429 限流或 5xx 服务器错误 -> 重试
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            logger.warning(
                                f"Semantic Scholar HTTP {resp.status_code},"
                                f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(f"Semantic Scholar HTTP {resp.status_code} 重试耗尽")
                        return []

                    if resp.status_code != 200:
                        logger.warning(f"Semantic Scholar HTTP {resp.status_code}: {resp.text[:200]}")
                        return []

                    data = resp.json()
                    papers = self._parse_response(data)
                    # 截断到 limit
                    papers = papers[:limit]

                    # 写入缓存(仅缓存非空结果)
                    if papers:
                        await self._set_cached(query, papers)

                    return papers

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_error = e
                    if attempt < self.max_retries:
                        delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        logger.warning(
                            f"Semantic Scholar 网络异常 {type(e).__name__}: {e},"
                            f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"Semantic Scholar 网络异常最终失败: {e}")
                    return []
                except Exception as e:
                    logger.error(f"Semantic Scholar 请求异常: {e}", exc_info=True)
                    return []

        logger.error(f"Semantic Scholar 请求最终失败: {last_error}")
        return []

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
