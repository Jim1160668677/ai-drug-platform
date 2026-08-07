"""bioRxiv real 客户端测试 — 4 个核心用例:happy path / 速率限制 / 网络降级 / 缓存命中"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.base import AcademicPaper
from app.clients.real.biorxiv_real import RealBiorxivClient


def _fake_biorxiv_response(query="EGFR", count=2):
    """构造 bioRxiv /details 响应 JSON"""
    collection = []
    for i in range(count):
        collection.append({
            "doi": f"10.1101/2024.01.{i:05d}",
            "title": f"{query} research paper {i}",
            "authors": "Lynch T;Bell D;Sordella R",
            "abstract": f"Study on {query} in non-small cell lung cancer.",
            "date": "2024-01-15",
            "category": "cancer-biology",
            "server": "biorxiv",
        })
    return {"messages": [{"status": "ok"}], "collection": collection}


class TestRealBiorxivClientSearch:
    """bioRxiv 客户端 search 方法"""

    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        """happy path:正常返回 AcademicPaper 列表"""
        client = RealBiorxivClient()

        # mock httpx 响应
        mock_response = MagicMock()
        mock_response.json.return_value = _fake_biorxiv_response("EGFR", 2)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_response)
        ))):
            results = await client.search("EGFR", limit=10)

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert results[0].source == "biorxiv"
        assert "EGFR" in results[0].title
        assert results[0].doi.startswith("10.1101/")

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """网络异常降级返回空列表,不抛异常"""
        client = RealBiorxivClient()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        ))):
            results = await client.search("EGFR", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(self):
        """缓存命中时不发起 HTTP 请求"""
        client = RealBiorxivClient()

        cached_papers = [AcademicPaper(title="cached", authors=[], source="biorxiv")]
        with patch.object(client, "_get_cached", new=AsyncMock(return_value=cached_papers)):
            mock_http = MagicMock(get=AsyncMock())
            with patch.object(client, "_get_http_client", new=AsyncMock(return_value=mock_http)):
                results = await client.search("EGFR", limit=10)

            # HTTP 未被调用
            mock_http.get.assert_not_called()
        assert results == cached_papers

    @pytest.mark.asyncio
    async def test_search_uses_semaphore_for_rate_limit(self):
        """速率限制:并发请求受 Semaphore 约束"""
        client = RealBiorxivClient()
        assert isinstance(client._semaphore, asyncio.Semaphore)
        # bioRxiv 无明确文档,保守 1 req/s
        assert client._semaphore._value <= 2
