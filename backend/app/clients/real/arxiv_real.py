"""Real arXiv 客户端 — 调用 https://export.arxiv.org/api/query

特性:
1. 速率限制: asyncio.Semaphore(1) 保守并发(arXiv 建议 1 req per 3s)
2. 内存缓存: TTL 7 天(query -> AcademicPaper 列表)
3. 指数退避重试: 429/5xx 自动重试 3 次,间隔 1s/2s/4s
4. 网络异常降级: 返回空列表,不抛异常
5. Atom XML 解析: 使用标准库 xml.etree.ElementTree

设计遵循 arXiv API: https://info.arxiv.org/help/api/index.html
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.clients.base import AcademicClientBase, AcademicPaper

logger = logging.getLogger(__name__)

# 指数退避重试间隔(秒): 1s / 2s / 4s
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# arXiv Atom XML 命名空间
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"


class RealArxivClient(AcademicClientBase):
    """真实 arXiv 客户端

    Usage:
        client = RealArxivClient()
        papers = await client.search("EGFR lung cancer", limit=10)
    """

    source_name = "arxiv"

    def __init__(self):
        self.base_url = "https://export.arxiv.org/api/query"
        self.timeout = 30
        self.max_retries = 3
        # 速率限制: arXiv 建议并发=1(每 3s 1 请求)
        self._semaphore = asyncio.Semaphore(1)
        # 连接池单例
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
        cache_key = f"arxiv:{query}"
        if cache_key in self._mem_cache:
            papers, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return papers
            del self._mem_cache[cache_key]
        return None

    async def _set_cached(self, query: str, papers: List[AcademicPaper]) -> None:
        """写入内存缓存"""
        cache_key = f"arxiv:{query}"
        self._mem_cache[cache_key] = (papers, time.time() + self._mem_cache_ttl)

    def _parse_year(self, date_str: str) -> Optional[int]:
        """从 ISO 日期 '2024-01-15T00:00:00Z' 提取年份"""
        if not date_str or len(date_str) < 4:
            return None
        try:
            return int(date_str[:4])
        except (ValueError, TypeError):
            return None

    def _extract_doi(self, entry: ET.Element) -> Optional[str]:
        """从 entry 提取 arXiv DOI(命名空间 arxiv:doi)"""
        doi_elem = entry.find(f"{{{_ARXIV_NS}}}doi")
        if doi_elem is not None and doi_elem.text:
            return doi_elem.text.strip()
        return None

    def _extract_authors(self, entry: ET.Element) -> List[str]:
        """从 entry 提取作者列表(atom:author/atom:name)"""
        authors: List[str] = []
        for author_elem in entry.findall(f"{{{_ATOM_NS}}}author"):
            name_elem = author_elem.find(f"{{{_ATOM_NS}}}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        return authors

    def _extract_url(self, entry: ET.Element) -> Optional[str]:
        """从 entry 提取 alternate 链接(abs 页面)"""
        for link in entry.findall(f"{{{_ATOM_NS}}}link"):
            if link.get("rel") == "alternate":
                return link.get("href")
        # 回退到 <id>
        id_elem = entry.find(f"{{{_ATOM_NS}}}id")
        return id_elem.text.strip() if id_elem is not None and id_elem.text else None

    def _parse_response(self, xml_text: str) -> List[AcademicPaper]:
        """解析 arXiv Atom XML 响应为 AcademicPaper 列表"""
        if not xml_text:
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"arXiv XML 解析失败: {e}")
            return []

        papers: List[AcademicPaper] = []
        # 遍历 <entry> 元素(命名空间 atom)
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            # 标题(去除多余空白)
            title_elem = entry.find(f"{{{_ATOM_NS}}}title")
            title = (title_elem.text or "").strip() if title_elem is not None else ""
            if not title:
                continue

            # 摘要
            summary_elem = entry.find(f"{{{_ATOM_NS}}}summary")
            abstract = (summary_elem.text or "").strip() if summary_elem is not None else None

            # 发布日期
            published_elem = entry.find(f"{{{_ATOM_NS}}}published")
            published = published_elem.text if published_elem is not None else ""
            year = self._parse_year(published)

            # DOI / URL / 作者
            doi = self._extract_doi(entry)
            url = self._extract_url(entry)
            authors = self._extract_authors(entry)

            paper = AcademicPaper(
                title=title,
                authors=authors,
                source="arxiv",
                abstract=abstract,
                doi=doi,
                year=year,
                url=url,
                relevance_score=None,  # arXiv 不返回相关性分数
            )
            papers.append(paper)

        return papers

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索 arXiv 文献

        使用 arXiv /api/query 端点(search_query=all:KEYWORD),返回 Atom XML。
        支持排序 sort_by=submittedDate&sort_order=descending(默认按相关性)。

        Args:
            query: 检索词,如 "EGFR lung cancer"
            limit: 最大返回数(默认 10)
            **kwargs: 保留参数(sort_by/sort_order/category)

        Returns:
            AcademicPaper 列表,失败时返回空列表
        """
        # 1. 缓存命中检查
        cached = await self._get_cached(query)
        if cached is not None:
            logger.info(f"arXiv 缓存命中: {query[:60]}")
            return cached

        # 2. 构造请求参数
        # arXiv search_query 语法: all:keyword (搜索标题+摘要+全文)
        # 空格分隔的多词默认 AND
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
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
                                f"arXiv HTTP {resp.status_code},"
                                f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(f"arXiv HTTP {resp.status_code} 重试耗尽")
                        return []

                    if resp.status_code != 200:
                        logger.warning(f"arXiv HTTP {resp.status_code}: {resp.text[:200]}")
                        return []

                    # arXiv 返回 XML,使用 resp.text
                    papers = self._parse_response(resp.text)
                    # 截断到 limit(_parse_response 已按 max_results 限制,此处二次保险)
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
                            f"arXiv 网络异常 {type(e).__name__}: {e},"
                            f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"arXiv 网络异常最终失败: {e}")
                    return []
                except Exception as e:
                    logger.error(f"arXiv 请求异常: {e}", exc_info=True)
                    return []

        logger.error(f"arXiv 请求最终失败: {last_error}")
        return []

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
