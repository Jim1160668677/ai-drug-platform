"""arXiv real 客户端测试 — 4 个核心用例:happy path / 速率限制 / 网络降级 / 缓存命中

arXiv API 返回 Atom XML 格式,与 bioRxiv 的 JSON 不同,需独立测试 XML 解析。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.base import AcademicPaper
from app.clients.real.arxiv_real import RealArxivClient


def _fake_arxiv_xml(query="EGFR", count=2):
    """构造 arXiv /api/query 的 Atom XML 响应"""
    entries = []
    for i in range(count):
        entries.append(f"""
        <entry>
            <id>http://arxiv.org/abs/2401.{i:05d}v1</id>
            <title>{query} research paper {i}</title>
            <summary>Study on {query} in non-small cell lung cancer.</summary>
            <published>2024-01-15T00:00:00Z</published>
            <updated>2024-01-16T00:00:00Z</updated>
            <author><name>Lynch T</name></author>
            <author><name>Bell D</name></author>
            <link href="http://arxiv.org/abs/2401.{i:05d}v1" rel="alternate" type="text/html"/>
            <link href="http://arxiv.org/pdf/2401.{i:05d}v1" rel="related" type="application/pdf"/>
            <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.48550/arxiv.2401.{i:05d}</arxiv:doi>
            <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="q-bio.GN"/>
        </entry>
        """)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
    <title>arXiv Query: search_query=all:{query}</title>
    <id>http://arxiv.org/api/query?search_query=all:{query}</id>
    <totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">{count}</totalResults>
    {''.join(entries)}
</feed>"""


class TestRealArxivClientSearch:
    """arXiv 客户端 search 方法"""

    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        """happy path:正常返回 AcademicPaper 列表(XML 解析)"""
        client = RealArxivClient()

        mock_response = MagicMock()
        mock_response.text = _fake_arxiv_xml("EGFR", 2)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_response)
        ))):
            results = await client.search("EGFR", limit=10)

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert results[0].source == "arxiv"
        assert "EGFR" in results[0].title
        # arXiv DOI 格式 10.48550/arxiv.xxxx
        assert results[0].doi is not None
        assert "arxiv" in results[0].doi
        # 作者解析为列表
        assert len(results[0].authors) == 2
        assert results[0].authors[0] == "Lynch T"

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """网络异常降级返回空列表,不抛异常"""
        client = RealArxivClient()

        with patch.object(client, "_get_http_client", new=AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        ))):
            results = await client.search("EGFR", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(self):
        """缓存命中时不发起 HTTP 请求"""
        client = RealArxivClient()

        cached_papers = [AcademicPaper(title="cached", authors=[], source="arxiv")]
        with patch.object(client, "_get_cached", new=AsyncMock(return_value=cached_papers)):
            mock_http = MagicMock(get=AsyncMock())
            with patch.object(client, "_get_http_client", new=AsyncMock(return_value=mock_http)):
                results = await client.search("EGFR", limit=10)

            # HTTP 未被调用
            mock_http.get.assert_not_called()
        assert results == cached_papers

    @pytest.mark.asyncio
    async def test_search_uses_semaphore_for_rate_limit(self):
        """速率限制:并发请求受 Semaphore 约束(arXiv 建议并发=1)"""
        client = RealArxivClient()
        assert isinstance(client._semaphore, asyncio.Semaphore)
        # arXiv 建议 1 req per 3s,保守并发=1
        assert client._semaphore._value <= 2
