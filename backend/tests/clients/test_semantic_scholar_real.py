"""Semantic Scholar real 客户端测试 — 4 个核心用例

S2 Graph API 返回 JSON,字段含 paperId/title/abstract/year/externalIds/authors。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.base import AcademicPaper
from app.clients.real.semantic_scholar_real import RealSemanticScholarClient


def _fake_s2_response(query="EGFR", count=2):
    """构造 Semantic Scholar /paper/search 响应 JSON"""
    data = []
    for i in range(count):
        data.append({
            "paperId": f"abc{i:05d}",
            "title": f"{query} research paper {i}",
            "abstract": f"Study on {query} in non-small cell lung cancer.",
            "year": 2024,
            "externalIds": {"DOI": f"10.1234/foo.{i:05d}"},
            "url": f"https://www.semanticscholar.org/paper/abc{i:05d}",
            "authors": [
                {"name": "Lynch T", "authorId": str(i * 10)},
                {"name": "Bell D", "authorId": str(i * 10 + 1)},
            ],
            "influentialCitationCount": 5,
            "citationCount": 42,
        })
    return {"total": count, "offset": 0, "data": data}


class TestRealSemanticScholarClientSearch:
    """Semantic Scholar 客户端 search 方法"""

    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        """happy path:正常返回 AcademicPaper 列表"""
        client = RealSemanticScholarClient()

        mock_response = MagicMock()
        mock_response.json.return_value = _fake_s2_response("EGFR", 2)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_response)
        ))):
            results = await client.search("EGFR", limit=10)

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert results[0].source == "semantic_scholar"
        assert "EGFR" in results[0].title
        assert results[0].doi == "10.1234/foo.00000"
        assert results[0].year == 2024
        assert len(results[0].authors) == 2
        assert results[0].authors[0] == "Lynch T"

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """网络异常降级返回空列表"""
        client = RealSemanticScholarClient()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        ))):
            results = await client.search("EGFR", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(self):
        """缓存命中时不发起 HTTP 请求"""
        client = RealSemanticScholarClient()

        cached_papers = [AcademicPaper(title="cached", authors=[], source="semantic_scholar")]
        with patch.object(client, "_get_cached", new=AsyncMock(return_value=cached_papers)):
            mock_http = MagicMock(get=AsyncMock())
            with patch.object(client, "_get_http_client", new=AsyncMock(return_value=mock_http)):
                results = await client.search("EGFR", limit=10)

            mock_http.get.assert_not_called()
        assert results == cached_papers

    @pytest.mark.asyncio
    async def test_search_uses_semaphore_for_rate_limit(self):
        """速率限制:S2 无 API Key 限 100 req/5min ≈ 1 req/3s,保守并发=1"""
        client = RealSemanticScholarClient()
        assert isinstance(client._semaphore, asyncio.Semaphore)
        assert client._semaphore._value <= 2
