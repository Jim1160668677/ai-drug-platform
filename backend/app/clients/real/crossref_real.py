"""Real CrossRef 客户端 — 调用 https://api.crossref.org/works

特性:
1. 速率限制: asyncio.Semaphore(2) — CrossRef polite pool(含 mailto)50 req/s,免费池 2 req/s
2. 内存缓存: TTL 7 天
3. 指数退避重试: 429/5xx 自动重试 3 次
4. 网络异常降级: 返回空列表
5. JATS XML 摘要剥离: <jats:p>...</jats:p> -> 纯文本

设计遵循 CrossRef REST API: https://api.crossref.org/swagger-ui/
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.clients.base import AcademicClientBase, AcademicPaper
from app.core.config import settings

logger = logging.getLogger(__name__)

# 指数退避重试间隔(秒): 1s / 2s / 4s
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# 匹配 JATS XML 标签(如 <jats:p>...</jats:p>、<jats:italic>...</jats:italic>)
_JATS_TAG_RE = re.compile(r"</?jats:[^>]+>")


class RealCrossrefClient(AcademicClientBase):
    """真实 CrossRef 客户端

    Usage:
        client = RealCrossrefClient()
        papers = await client.search("EGFR lung cancer", limit=10)
    """

    source_name = "crossref"

    def __init__(self):
        self.base_url = "https://api.crossref.org/works"
        # CrossRef polite pool:在 User-Agent 中提供 mailto 可获得 50 req/s
        # 否则进入免费池 2 req/s
        self.mailto = getattr(settings, "CROSSREF_MAILTO", "") or ""
        self.timeout = 30
        self.max_retries = 3
        # 速率限制: 保守并发=2(免费池 2 req/s)
        self._semaphore = asyncio.Semaphore(2)
        # 连接池单例
        self._http_client: Optional[httpx.AsyncClient] = None
        # 内存缓存: query -> (papers, expires_at)
        self._mem_cache: Dict[str, Tuple[List[AcademicPaper], float]] = {}
        self._mem_cache_ttl = 7 * 86400  # 7 天

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取/复用 httpx.AsyncClient 单例(polite pool 注入 User-Agent)"""
        if self._http_client is None or self._http_client.is_closed:
            # CrossRef polite pool 要求 User-Agent 含 mailto
            ua = f"AI-Drug-Platform/1.0 (mailto:{self.mailto})" if self.mailto else "AI-Drug-Platform/1.0"
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=self.timeout, connect=8.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=3),
                headers={"User-Agent": ua},
            )
        return self._http_client

    async def _get_cached(self, query: str) -> Optional[List[AcademicPaper]]:
        """查询内存缓存"""
        cache_key = f"crossref:{query}"
        if cache_key in self._mem_cache:
            papers, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return papers
            del self._mem_cache[cache_key]
        return None

    async def _set_cached(self, query: str, papers: List[AcademicPaper]) -> None:
        """写入内存缓存"""
        cache_key = f"crossref:{query}"
        self._mem_cache[cache_key] = (papers, time.time() + self._mem_cache_ttl)

    def _strip_jats(self, abstract: Optional[str]) -> Optional[str]:
        """剥离 JATS XML 标签,返回纯文本

        输入: '<jats:p>Study on EGFR in NSCLC.</jats:p>'
        输出: 'Study on EGFR in NSCLC.'
        """
        if not abstract:
            return None
        return _JATS_TAG_RE.sub("", abstract).strip()

    def _parse_authors(self, authors_raw: List[Dict[str, Any]]) -> List[str]:
        """解析 CrossRef author 字段

        输入: [{'given': 'T', 'family': 'Lynch'}, {'given': 'D', 'family': 'Bell'}]
        输出: ['T Lynch', 'D Bell']
        """
        if not authors_raw:
            return []
        result: List[str] = []
        for a in authors_raw:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            # 拼接 given + family,空值跳过
            parts = [p for p in (given, family) if p]
            if parts:
                result.append(" ".join(parts))
        return result

    def _parse_year(self, item: Dict[str, Any]) -> Optional[int]:
        """从 published-print/published-online 提取年份

        CrossRef date-parts 格式: [[2024, 1, 15]]
        """
        for key in ("published-print", "published-online", "issued", "created"):
            date_obj = item.get(key)
            if not date_obj:
                continue
            parts = date_obj.get("date-parts") or []
            if parts and parts[0] and parts[0][0]:
                try:
                    return int(parts[0][0])
                except (ValueError, TypeError):
                    continue
        return None

    def _parse_response(self, data: Dict[str, Any]) -> List[AcademicPaper]:
        """解析 CrossRef /works 响应为 AcademicPaper 列表"""
        message = data.get("message") or {}
        items = message.get("items") or []
        papers: List[AcademicPaper] = []
        for item in items:
            # title 是数组(通常 1 个元素)
            titles = item.get("title") or []
            title = titles[0].strip() if titles else ""
            if not title:
                continue

            paper = AcademicPaper(
                title=title,
                authors=self._parse_authors(item.get("author")),
                source="crossref",
                abstract=self._strip_jats(item.get("abstract")),
                doi=item.get("DOI"),
                year=self._parse_year(item),
                url=item.get("URL"),
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
        """按关键词检索 CrossRef 文献

        使用 /works 端点,bibliographic query 匹配标题/摘要/作者等元数据。
        排序按相关性(score desc,默认)。

        Args:
            query: 检索词,如 "EGFR lung cancer"
            limit: 最大返回数(默认 10,CrossRef 上限 1000)
            **kwargs: 保留参数(filter/type)

        Returns:
            AcademicPaper 列表,失败时返回空列表
        """
        # 1. 缓存命中检查
        cached = await self._get_cached(query)
        if cached is not None:
            logger.info(f"CrossRef 缓存命中: {query[:60]}")
            return cached

        # 2. 构造请求参数
        params = {
            "query": query,
            "rows": min(limit, 1000),
        }
        # polite pool: mailto 作为参数也可(部分端点要求)
        if self.mailto:
            params["mailto"] = self.mailto

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
                                f"CrossRef HTTP {resp.status_code},"
                                f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(f"CrossRef HTTP {resp.status_code} 重试耗尽")
                        return []

                    if resp.status_code != 200:
                        logger.warning(f"CrossRef HTTP {resp.status_code}: {resp.text[:200]}")
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
                            f"CrossRef 网络异常 {type(e).__name__}: {e},"
                            f"{delay}s 后重试({attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"CrossRef 网络异常最终失败: {e}")
                    return []
                except Exception as e:
                    logger.error(f"CrossRef 请求异常: {e}", exc_info=True)
                    return []

        logger.error(f"CrossRef 请求最终失败: {last_error}")
        return []

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
