"""CrossRef real 客户端测试 — 4 个核心用例

CrossRef /works 返回 JSON,字段含 DOI/title(数组)/author(given+family)/abstract(JATS XML).
需独立测试:
- title[0] 提取
- author given+family 拼接
- abstract JATS 标签剥离
- date-parts 解析
"""
import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.base import AcademicPaper
from app.clients.real.crossref_real import RealCrossrefClient


def _fake_crossref_response(query="EGFR", count=2):
    """构造 CrossRef /works 响应 JSON"""
    items = []
    for i in range(count):
        items.append({
            "DOI": f"10.1234/foo.{i:05d}",
            "title": [f"{query} research paper {i}"],
            "abstract": f"<jats:p>Study on {query} in non-small cell lung cancer.</jats:p>",
            "author": [
                {"given": "T", "family": "Lynch", "sequence": "first"},
                {"given": "D", "family": "Bell", "sequence": "additional"},
            ],
            "published-print": {"date-parts": [[2024, 1, 15]]},
            "published-online": {"date-parts": [[2024, 1, 10]]},
            "URL": f"http://dx.doi.org/10.1234/foo.{i:05d}",
            "container-title": ["Journal of Cancer Research"],
            "type": "journal-article",
            "is-referenced-by-count": 42,
        })
    return {
        "status": "ok",
        "message-type": "work-list",
        "message": {
            "total-results": count,
            "items-per-page": count,
            "query": {"search-terms": query},
            "items": items,
        },
    }


class TestRealCrossrefClientSearch:
    """CrossRef 客户端 search 方法"""

    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        """happy path:正常返回 AcademicPaper 列表(JATS 摘要剥离 + author 拼接)"""
        client = RealCrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = _fake_crossref_response("EGFR", 2)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_response)
        ))):
            results = await client.search("EGFR", limit=10)

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert results[0].source == "crossref"
        assert "EGFR" in results[0].title
        assert results[0].doi == "10.1234/foo.00000"
        assert results[0].year == 2024
        # author given+family 拼接: "T Lynch"
        assert len(results[0].authors) == 2
        assert results[0].authors[0] == "T Lynch"
        # JATS 标签应被剥离
        assert results[0].abstract is not None
        assert "<jats:" not in results[0].abstract
        assert "Study on EGFR" in results[0].abstract

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """网络异常降级返回空列表"""
        client = RealCrossrefClient()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        ))):
            results = await client.search("EGFR", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(self):
        """缓存命中时不发起 HTTP 请求"""
        client = RealCrossrefClient()

        cached_papers = [AcademicPaper(title="cached", authors=[], source="crossref")]
        with patch.object(client, "_get_cached", new=AsyncMock(return_value=cached_papers)):
            mock_http = MagicMock(get=AsyncMock())
            with patch.object(client, "_get_http_client", new=AsyncMock(return_value=mock_http)):
                results = await client.search("EGFR", limit=10)

            mock_http.get.assert_not_called()
        assert results == cached_papers

    @pytest.mark.asyncio
    async def test_search_uses_semaphore_for_rate_limit(self):
        """速率限制:CrossRef polite pool 50 req/s,免费池 2 req/s;保守并发=2"""
        client = RealCrossrefClient()
        assert isinstance(client._semaphore, asyncio.Semaphore)
        assert client._semaphore._value <= 3
