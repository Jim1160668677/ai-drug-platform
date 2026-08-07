"""Real bioRxiv 客户端 — 调用 https://api.biorxiv.org

特性:
1. 速率限制: asyncio.Semaphore(1) 保守 1 req/s(bioRxiv 无明确限速文档)
2. 内存缓存: TTL 7 天(query -> AcademicPaper 列表)
3. 指数退避重试: 429/5xx 自动重试 3 次,间隔 1s/2s/4s
4. 网络异常降级: 返回空列表,不抛异常(业务层降级)

设计遵循 bioRxiv API: https://api.biorxiv.org
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.clients.base import AcademicClientBase, AcademicPaper

logger = logging.getLogger(__name__)

# 指数退避重试间隔(秒): 1s / 2s / 4s
_RETRY_DELAYS = [1.0, 2.0, 4.0]


class RealBiorxivClient(AcademicClientBase):
    """真实 bioRxiv 客户端

    Usage:
        client = RealBiorxivClient()
        papers = await client.search("EGFR lung cancer", limit=10)
    """

    source_name = "biorxiv"

    def __init__(self):
        self.base_url = "https://api.biorxiv.org"
        self.timeout = 30
        self.max_retries = 3
        # 速率限制: bioRxiv 无明确文档,保守 1 req/s
        self._semaphore = asyncio.Semaphore(1)
        # 连接池单例(避免每次请求创建新 client)
        self._http_client: Optional[httpx.AsyncClient] = None
        # 内存缓存: query -> (papers, expires_at)
        self._mem_cache: Dict[str, Tuple[List[AcademicPaper], float]] = {}
        self._mem_cache_ttl = 7 * 86400  # 7 天

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取/复用 httpx.AsyncClient 单例"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=self.timeout, connect=8.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=3),
            )
        return self._http_client

    async def _get_cached(self, query: str) -> Optional[List[AcademicPaper]]:
        """查询内存缓存,命中返回 AcademicPaper 列表,未命中返回 None"""
        cache_key = f"biorxiv:{query}"
        if cache_key in self._mem_cache:
            papers, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return papers
            del self._mem_cache[cache_key]
        return None

    async def _set_cached(self, query: str, papers: List[AcademicPaper]) -> None:
        """写入内存缓存"""
        cache_key = f"biorxiv:{query}"
        self._mem_cache[cache_key] = (papers, time.time() + self._mem_cache_ttl)

    def _parse_authors(self, authors_str: str) -> List[str]:
        """解析作者字符串 'Lynch T;Bell D;Sordella R' -> ['Lynch T', 'Bell D', 'Sordella R']"""
        if not authors_str:
            return []
        return [a.strip() for a in authors_str.split(";") if a.strip()]

    def _parse_year(self, date_str: str) -> Optional[int]:
        """从日期字符串 '2024-01-15' 提取年份"""
        if not date_str or len(date_str) < 4:
            return None
        try:
            return int(date_str[:4])
        except (ValueError, TypeError):
            return None

    def _parse_response(self, data: Dict[str, Any]) -> List[AcademicPaper]:
        """解析 bioRxiv /details 响应为 AcademicPaper 列表"""
        collection = data.get("collection") or []
        papers: List[AcademicPaper] = []
        for item in collection:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            doi = item.get("doi")
            paper = AcademicPaper(
                title=title,
                authors=self._parse_authors(item.get("authors", "")),
                source="biorxiv",
                abstract=item.get("abstract"),
                doi=doi,
                year=self._parse_year(item.get("date", "")),
                url=f"https://www.biorxiv.org/content/{doi}v1" if doi else None,
                relevance_score=None,  # bioRxiv 不返回相关性分数
            )
            papers.append(paper)
        return papers

    def _filter_by_query(self, papers: List[AcademicPaper], query: str) -> List[AcademicPaper]:
        """客户端按 query 过滤 title/abstract(不区分大小写)"""
        if not query:
            return papers
        q_lower = query.lower()
        return [
            p for p in papers
            if q_lower in p.title.lower()
            or (p.abstract and q_lower in (p.abstract or "").lower())
        ]

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索 bioRxiv 文献

        bioRxiv API 不支持原生关键词搜索,使用 /details 端点按日期范围检索,
        然后客户端按 title/abstract 过滤匹配 query 的论文。

        Args:
            query: 检索词,如 "EGFR lung cancer"
            limit: 最大返回数(默认 10)
            **kwargs: 保留参数(category/year_from/year_to)

        Returns:
            AcademicPaper 列表(按日期倒序),失败时返回空列表
        """
        # 1. 缓存命中检查
        cached = await self._get_cached(query)
        if cached is not None:
            logger.info(f"bioRxiv 缓存命中: {query[:60]}")
            return cached

        # 2. 构造请求 - bioRxiv /details 端点(最近 30 天,limit 条)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        url = (
            f"{self.base_url}/details/biorxiv/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/{limit}"
        )

        last_error: Optional[Exception] = None
        async with self._semaphore:
            client = await self._get_http_client()
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.get(url)

                    # 429 限流或 5xx 服务器错误 -> 重试
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            logger.warning(
                                f"bioRxiv HTTP {resp.status_code},"
                                f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(f"bioRxiv HTTP {resp.status_code} 重试耗尽")
                        return []

                    if resp.status_code != 200:
                        logger.warning(f"bioRxiv HTTP {resp.status_code}: {resp.text[:200]}")
                        return []

                    data = resp.json()
                    papers = self._parse_response(data)
                    # 客户端按 query 过滤
                    papers = self._filter_by_query(papers, query)
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
                            f"bioRxiv 网络异常 {type(e).__name__}: {e},"
                            f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"bioRxiv 网络异常最终失败: {e}")
                    return []
                except Exception as e:
                    logger.error(f"bioRxiv 请求异常: {e}", exc_info=True)
                    return []

        logger.error(f"bioRxiv 请求最终失败: {last_error}")
        return []

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
