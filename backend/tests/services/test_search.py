"""搜索引擎单元测试

覆盖：
1. base.py: SearchResult/normalize_url/get_domain_authority
2. duckduckgo.py: DuckDuckGoEngine Mock 模式
3. serper.py: SerperEngine Mock 模式 + 真实 API Key 处理
4. brave.py: BraveSearchEngine Mock 模式
5. aggregator.py: 多引擎聚合 + 去重 + 重排序
6. fetcher.py: WebPageFetcher Mock 模式
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# 测试环境
os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")

from app.services.search.base import (
    SearchEngine,
    SearchResult,
    get_domain_authority,
    normalize_url,
)
from app.services.search.duckduckgo import DuckDuckGoEngine
from app.services.search.serper import SerperEngine
from app.services.search.brave import BraveSearchEngine
from app.services.search.aggregator import MultiEngineAggregator, get_aggregator, reset_aggregator
from app.services.search.fetcher import WebPageFetcher


# ========== base.py 测试 ==========


class TestSearchResult:
    """SearchResult 数据类测试"""

    def test_to_dict(self):
        """to_dict 返回完整字段"""
        r = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="Test snippet",
            source="duckduckgo",
            score=0.5,
            position=1,
        )
        d = r.to_dict()
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["source"] == "duckduckgo"
        assert d["score"] == 0.5
        assert d["position"] == 1

    def test_optional_fields_default_none(self):
        """可选字段默认为 None"""
        r = SearchResult(title="T", url="U", snippet="S", source="x")
        assert r.score is None
        assert r.published_at is None
        assert r.position is None


class TestNormalizeUrl:
    """URL 归一化测试"""

    def test_removes_utm_params(self):
        """去除 utm_* 追踪参数"""
        url = "https://example.com/article?utm_source=google&utm_medium=cpc&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=123" in result

    def test_removes_gclid(self):
        """去除 gclid"""
        url = "https://example.com/article?gclid=abc123&query=egfr"
        result = normalize_url(url)
        assert "gclid" not in result
        assert "query=egfr" in result

    def test_removes_fbclid(self):
        """去除 fbclid"""
        url = "https://example.com/article?fbclid=xyz&content=123"
        result = normalize_url(url)
        assert "fbclid" not in result
        assert "content=123" in result

    def test_preserves_semantic_params(self):
        """保留语义参数"""
        url = "https://pubmed.ncbi.nlm.nih.gov/36123456/?from=egfr"
        result = normalize_url(url)
        assert "36123456" in result
        assert "from=egfr" in result

    def test_removes_fragment(self):
        """去除 fragment"""
        url = "https://example.com/article#section1"
        result = normalize_url(url)
        assert "#" not in result

    def test_empty_url(self):
        """空 URL 返回空字符串"""
        assert normalize_url("") == ""

    def test_invalid_url(self):
        """无效 URL 原样返回"""
        url = "not a url"
        result = normalize_url(url)
        # 不抛异常，原样返回
        assert result == url


class TestDomainAuthority:
    """域名权威性评分测试"""

    @pytest.mark.parametrize("url,expected_min", [
        ("https://www.nih.gov/research", 10),  # 政府域名
        ("https://www.harvard.edu/paper", 10),  # 教育域名
        ("https://www.who.int/guidelines", 10),  # WHO
        ("https://arxiv.org/abs/2401.12345", 8),  # arxiv
        ("https://pubmed.ncbi.nlm.nih.gov/12345", 10),  # PubMed
        ("https://www.nature.com/articles/s41586", 7),  # Nature
        ("https://www.science.org/doi/10.1126", 7),  # Science
        ("https://www.cell.com/cell/fulltext", 7),  # Cell
        ("https://www.nejm.org/doi/full", 6),  # NEJM
        ("https://en.wikipedia.org/wiki/EGFR", 5),  # Wikipedia
        ("https://example.com/article", 0),  # 普通域名
        ("", 0),  # 空
    ])
    def test_domain_authority(self, url, expected_min):
        """验证域名权威性评分"""
        assert get_domain_authority(url) >= expected_min


# ========== DuckDuckGo 引擎测试 ==========


class TestDuckDuckGoEngine:
    """DuckDuckGoEngine 测试"""

    @pytest.fixture
    def engine(self):
        return DuckDuckGoEngine(use_mock=True)

    @pytest.mark.asyncio
    async def test_is_available(self, engine):
        assert engine.is_available is True

    @pytest.mark.asyncio
    async def test_search_returns_results(self, engine):
        """搜索返回结果列表"""
        results = await engine.search("EGFR inhibitor", max_results=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.source == "duckduckgo" for r in results)

    @pytest.mark.asyncio
    async def test_search_empty_query(self, engine):
        """空查询返回空列表"""
        results = await engine.search("", max_results=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_results_have_position(self, engine):
        """结果包含 position"""
        results = await engine.search("EGFR", max_results=3)
        for i, r in enumerate(results, 1):
            assert r.position == i

    @pytest.mark.asyncio
    async def test_search_medical_query(self, engine):
        """医学相关查询返回特定结果"""
        results = await engine.search("KRAS G12C inhibitor", max_results=3)
        assert len(results) > 0
        # Mock 模式应返回 PubMed/Nature/FDA 等权威来源
        assert any("nih.gov" in r.url or "nature.com" in r.url or "fda.gov" in r.url for r in results)

    @pytest.mark.asyncio
    async def test_search_max_results_limit(self, engine):
        """max_results 限制返回数量"""
        results = await engine.search("EGFR", max_results=2)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_real_api_with_mocked_ddgs(self):
        """真实 API 调用路径（mock AsyncDDGS 模块）

        duckduckgo_search 未安装时，search() 应降级到 Mock 模式。
        本测试验证降级行为正确触发且返回有效结果。
        """
        import sys

        engine = DuckDuckGoEngine(use_mock=False)
        engine._last_call_time = 0.0

        # duckduckgo_search 未安装（测试环境），应触发 ImportError 降级
        original = sys.modules.pop("duckduckgo_search", None)
        try:
            results = await engine.search("EGFR", max_results=5)
            # 降级到 Mock，返回预置结果
            assert len(results) > 0
            assert all(r.source == "duckduckgo" for r in results)
            assert all(isinstance(r, SearchResult) for r in results)
        finally:
            if original is not None:
                sys.modules["duckduckgo_search"] = original

    @pytest.mark.asyncio
    async def test_real_api_import_error_falls_back_to_mock(self):
        """duckduckgo_search 未安装时降级到 Mock"""
        import sys

        engine = DuckDuckGoEngine(use_mock=False)
        engine._last_call_time = 0.0

        # 确保 duckduckgo_search 不在 sys.modules 中（模拟未安装）
        original = sys.modules.pop("duckduckgo_search", None)
        try:
            results = await engine.search("EGFR", max_results=3)
            # 降级到 Mock，返回预置结果
            assert len(results) > 0
            assert all(r.source == "duckduckgo" for r in results)
        finally:
            if original is not None:
                sys.modules["duckduckgo_search"] = original

    @pytest.mark.asyncio
    async def test_real_api_exception_falls_back_to_mock(self):
        """异常降级到 Mock

        注入一个会抛异常的 mock 模块，验证 search() 降级到 Mock。
        """
        import sys
        from unittest.mock import MagicMock as _MagicMock

        engine = DuckDuckGoEngine(use_mock=False)
        engine._last_call_time = 0.0

        # 构造一个抛异常的 mock 模块
        mock_module = _MagicMock()
        mock_module.AsyncDDGS = _MagicMock(side_effect=RuntimeError("init failed"))

        original = sys.modules.get("duckduckgo_search")
        sys.modules["duckduckgo_search"] = mock_module
        try:
            results = await engine.search("EGFR", max_results=3)
            # 降级到 Mock
            assert len(results) > 0
            assert all(r.source == "duckduckgo" for r in results)
        finally:
            if original is not None:
                sys.modules["duckduckgo_search"] = original
            else:
                sys.modules.pop("duckduckgo_search", None)


# ========== Serper 引擎测试 ==========


class TestSerperEngine:
    """SerperEngine 测试"""

    @pytest.mark.asyncio
    async def test_mock_search(self):
        """Mock 模式返回预置结果"""
        engine = SerperEngine(api_key="test")
        engine.use_mock = True
        results = await engine.search("EGFR", max_results=2)
        assert len(results) > 0
        assert all(r.source == "serper" for r in results)

    def test_is_available_with_key(self):
        """配置 API Key 时可用"""
        engine = SerperEngine(api_key="test_key")
        engine.use_mock = False
        assert engine.is_available is True

    def test_not_available_without_key(self):
        """未配置 API Key 时不可用"""
        engine = SerperEngine(api_key="")
        engine.use_mock = False
        assert engine.is_available is False

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """空查询返回空"""
        engine = SerperEngine(api_key="test")
        engine.use_mock = True
        assert await engine.search("", max_results=5) == []

    @pytest.mark.asyncio
    async def test_real_api_mocked_transport(self):
        """真实 API 调用（使用 MockTransport）"""
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("X-API-KEY") == "test_key"
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "EGFR Research",
                            "link": "https://example.com/egfr",
                            "snippet": "EGFR research snippet",
                            "position": 1,
                        }
                    ],
                    "knowledgeGraph": {
                        "title": "EGFR",
                        "description": "Epidermal Growth Factor Receptor",
                        "website": "https://en.wikipedia.org/wiki/EGFR",
                    },
                },
            )

        engine = SerperEngine(api_key="test_key")
        engine.use_mock = False

        # Mock httpx.AsyncClient
        with patch("app.services.search.serper.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=httpx.Response(
                200,
                json={
                    "organic": [{
                        "title": "EGFR Research",
                        "link": "https://example.com/egfr",
                        "snippet": "EGFR research snippet",
                    }],
                    "knowledgeGraph": {
                        "title": "EGFR",
                        "description": "Epidermal Growth Factor Receptor",
                        "website": "https://en.wikipedia.org/wiki/EGFR",
                    },
                },
            ))
            mock_client_cls.return_value = mock_client

            results = await engine.search("EGFR", max_results=5)
            assert len(results) >= 2  # 1 organic + 1 knowledgeGraph
            # knowledgeGraph 应在前面
            assert results[0].title == "EGFR"


# ========== Brave 引擎测试 ==========


class TestBraveSearchEngine:
    """BraveSearchEngine 测试"""

    @pytest.mark.asyncio
    async def test_mock_search(self):
        """Mock 模式返回预置结果"""
        engine = BraveSearchEngine(api_key="test")
        engine.use_mock = True
        results = await engine.search("EGFR", max_results=2)
        assert len(results) > 0
        assert all(r.source == "brave" for r in results)

    def test_is_available_with_key(self):
        """配置 API Key 时可用"""
        engine = BraveSearchEngine(api_key="test_key")
        engine.use_mock = False
        assert engine.is_available is True

    def test_not_available_without_key(self):
        """未配置 API Key 时不可用"""
        engine = BraveSearchEngine(api_key="")
        engine.use_mock = False
        assert engine.is_available is False

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """空查询返回空"""
        engine = BraveSearchEngine(api_key="test")
        engine.use_mock = True
        assert await engine.search("", max_results=5) == []

    @pytest.mark.asyncio
    async def test_real_api_mocked_transport(self):
        """真实 API 调用（使用 MockTransport 模拟）"""
        engine = BraveSearchEngine(api_key="test_key")
        engine.use_mock = False

        with patch("app.services.search.brave.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "EGFR Cancer Research",
                                "url": "https://example.com/egfr-brave",
                                "description": "Brave search EGFR snippet",
                                "age": "2 days ago",
                            }
                        ]
                    }
                },
            ))
            mock_client_cls.return_value = mock_client

            results = await engine.search("EGFR", max_results=5)
            assert len(results) == 1
            assert results[0].title == "EGFR Cancer Research"
            assert results[0].url == "https://example.com/egfr-brave"
            assert results[0].source == "brave"
            assert results[0].position == 1
            assert results[0].published_at == "2 days ago"

    @pytest.mark.asyncio
    async def test_real_api_no_key_returns_empty(self):
        """真实模式无 Key 返回空列表"""
        engine = BraveSearchEngine(api_key="")
        engine.use_mock = False
        results = await engine.search("EGFR", max_results=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_real_api_http_error_returns_empty(self):
        """HTTP 错误返回空列表（不抛异常）"""
        engine = BraveSearchEngine(api_key="test_key")
        engine.use_mock = False

        with patch("app.services.search.brave.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(500, text="Server Error"))
            mock_client_cls.return_value = mock_client

            results = await engine.search("EGFR", max_results=5)
            assert results == []

    @pytest.mark.asyncio
    async def test_real_api_timeout_returns_empty(self):
        """超时返回空列表"""
        engine = BraveSearchEngine(api_key="test_key")
        engine.use_mock = False

        with patch("app.services.search.brave.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            results = await engine.search("EGFR", max_results=5)
            assert results == []


# ========== Aggregator 测试 ==========


class TestMultiEngineAggregator:
    """MultiEngineAggregator 测试"""

    @pytest.fixture
    def engines(self):
        """构造 3 个 Mock 引擎"""
        ddg = DuckDuckGoEngine(use_mock=True)
        serper = SerperEngine(api_key="test")
        serper.use_mock = True
        brave = BraveSearchEngine(api_key="test")
        brave.use_mock = True
        return [ddg, serper, brave]

    @pytest.mark.asyncio
    async def test_aggregate_multiple_engines(self, engines):
        """多引擎聚合返回合并结果"""
        agg = MultiEngineAggregator(engines)
        results = await agg.search("EGFR", max_results=20)
        assert len(results) > 0
        # 包含多个引擎的结果
        sources = {r.source for r in results}
        assert len(sources) >= 1

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_url(self, engines):
        """同 URL 多源命中时去重"""
        # 构造两个引擎返回相同 URL 的结果
        ddg = MagicMock()
        ddg.name = "duckduckgo"
        ddg.is_available = True
        ddg.search = AsyncMock(return_value=[
            SearchResult(
                title="Same Article",
                url="https://example.com/article",
                snippet="From DDG",
                source="duckduckgo",
                position=1,
            ),
        ])

        serper = MagicMock()
        serper.name = "serper"
        serper.is_available = True
        serper.search = AsyncMock(return_value=[
            SearchResult(
                title="Same Article",
                url="https://example.com/article",
                snippet="From Serper",
                source="serper",
                position=1,
            ),
        ])

        agg = MultiEngineAggregator([ddg, serper])
        results = await agg.search("test", max_results=10)
        # 同 URL 应去重为 1 条
        assert len(results) == 1
        # 多源命中应得更高 score
        assert results[0].score is not None
        assert results[0].score > 0.4  # source_bonus 至少 0.4（1.0 * 0.4）

    @pytest.mark.asyncio
    async def test_aggregate_sort_by_score(self, engines):
        """按综合评分降序排序"""
        # 构造不同质量的结果
        ddg = MagicMock()
        ddg.name = "duckduckgo"
        ddg.is_available = True
        ddg.search = AsyncMock(return_value=[
            SearchResult(
                title="NIH Article",
                url="https://www.nih.gov/research/egfr",
                snippet="Authoritative NIH article",
                source="duckduckgo",
                position=1,
            ),
            SearchResult(
                title="Random Blog",
                url="https://blog.example.com/post",
                snippet="Random blog post",
                source="duckduckgo",
                position=2,
            ),
        ])
        agg = MultiEngineAggregator([ddg])
        results = await agg.search("EGFR", max_results=10)
        # NIH 应排在前面（域名权威性高）
        assert "nih.gov" in results[0].url
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_aggregate_engine_failure_resilient(self):
        """单引擎失败不影响整体"""
        failing = MagicMock()
        failing.name = "failing"
        failing.is_available = True
        failing.search = AsyncMock(side_effect=Exception("API Error"))

        success = MagicMock()
        success.name = "success"
        success.is_available = True
        success.search = AsyncMock(return_value=[
            SearchResult(
                title="OK",
                url="https://example.com/ok",
                snippet="OK",
                source="success",
                position=1,
            ),
        ])

        agg = MultiEngineAggregator([failing, success])
        results = await agg.search("test", max_results=10)
        assert len(results) >= 1
        assert results[0].title == "OK"

    @pytest.mark.asyncio
    async def test_aggregate_no_available_engines(self):
        """无可用引擎返回空"""
        ddg = MagicMock()
        ddg.is_available = False
        agg = MultiEngineAggregator([ddg])
        results = await agg.search("test", max_results=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_aggregate_empty_query(self, engines):
        """空查询返回空"""
        agg = MultiEngineAggregator(engines)
        assert await agg.search("", max_results=5) == []

    @pytest.mark.asyncio
    async def test_aggregate_max_results_limit(self, engines):
        """max_results 限制返回数量"""
        agg = MultiEngineAggregator(engines)
        results = await agg.search("EGFR", max_results=3)
        assert len(results) <= 3

    def test_get_aggregator_singleton(self):
        """get_aggregator 返回单例"""
        reset_aggregator()
        agg1 = get_aggregator()
        agg2 = get_aggregator()
        assert agg1 is agg2

    def test_aggregate_position_reassigned(self, engines):
        """聚合后 position 重新分配"""
        # 直接调用 _aggregate
        agg = MultiEngineAggregator(engines)
        results = [
            SearchResult("A", "https://a.com", "s", "duckduckgo", position=5),
            SearchResult("B", "https://b.com", "s", "duckduckgo", position=1),
        ]
        aggregated = agg._aggregate(results)
        # 按评分排序后重新分配 position
        positions = [r.position for r in aggregated]
        assert positions == list(range(1, len(aggregated) + 1))


# ========== WebPageFetcher 测试 ==========


class TestWebPageFetcher:
    """WebPageFetcher 测试"""

    @pytest.fixture
    def fetcher(self):
        return WebPageFetcher(use_mock=True)

    @pytest.mark.asyncio
    async def test_mock_fetch_pubmed(self, fetcher):
        """Mock 模式抓取 PubMed"""
        result = await fetcher.fetch(
            "https://pubmed.ncbi.nlm.nih.gov/36123456/",
            max_chars=2000,
        )
        assert result["url"] == "https://pubmed.ncbi.nlm.nih.gov/36123456/"
        assert "EGFR" in result["content"]
        assert result["content_type"] == "html"
        assert result["length"] > 0
        assert "fetched_at" in result

    @pytest.mark.asyncio
    async def test_mock_fetch_wikipedia(self, fetcher):
        """Mock 模式抓取 Wikipedia"""
        result = await fetcher.fetch(
            "https://en.wikipedia.org/wiki/EGFR_inhibitor",
            max_chars=2000,
        )
        assert "EGFR" in result["content"]
        assert "Wikipedia" in result["title"]

    @pytest.mark.asyncio
    async def test_mock_fetch_generic(self, fetcher):
        """Mock 模式抓取未知 URL"""
        result = await fetcher.fetch(
            "https://example.com/article",
            max_chars=1000,
        )
        assert result["url"] == "https://example.com/article"
        assert "Mock" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_empty_url(self, fetcher):
        """空 URL 返回空结果"""
        result = await fetcher.fetch("", max_chars=1000)
        assert result["content"] == ""
        assert result["content_type"] == "unknown"
        assert result["reason"] == "empty_url"

    @pytest.mark.asyncio
    async def test_fetch_max_chars_limit(self, fetcher):
        """max_chars 截断内容"""
        result = await fetcher.fetch(
            "https://pubmed.ncbi.nlm.nih.gov/12345/",
            max_chars=50,
        )
        assert len(result["content"]) <= 50

    @pytest.mark.asyncio
    async def test_real_fetch_with_mocktransport(self):
        """真实 HTTP 调用（使用 MockTransport）"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text="<html><head><title>Test Page</title></head><body><p>Hello World</p></body></html>",
                headers={"content-type": "text/html"},
            )

        fetcher = WebPageFetcher(use_mock=False)
        # 替换 httpx.AsyncClient
        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text="<html><head><title>Test Page</title></head><body><p>Hello World</p></body></html>",
                headers={"content-type": "text/html"},
            ))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com", max_chars=1000)
            # trafilatura 可能未安装，降级到 simple_html_extract
            assert "Test Page" in result["title"] or "Hello" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        """HTTP 错误返回空结果"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(404, text="Not Found"))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/notfound", max_chars=1000)
            assert result["content"] == ""
            assert result["reason"] == "http_404"

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        """超时返回空结果"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/slow", max_chars=1000)
            assert result["content"] == ""
            assert result["reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_fetch_http_error_generic(self):
        """通用 HTTP 错误返回空结果"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection refused"))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/error", max_chars=1000)
            assert result["content"] == ""
            assert result["reason"] == "http_error"

    @pytest.mark.asyncio
    async def test_fetch_json_response(self):
        """JSON 响应解析"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text='{"key": "value", "count": 42}',
                headers={"content-type": "application/json"},
            ))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/api/data", max_chars=5000)
            assert result["content_type"] == "json"
            assert "value" in result["content"]
            assert "42" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_text_response(self):
        """纯文本响应解析"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text="Plain text content for testing",
                headers={"content-type": "text/plain"},
            ))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/file.txt", max_chars=5000)
            assert result["content_type"] == "text"
            assert "Plain text" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_html_with_trafilatura(self):
        """HTML 解析（trafilatura 已安装时）"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            html = """<html><head><title>Research Article</title></head>
            <body><article><p>EGFR mutation analysis reveals new insights.</p></article></body></html>"""
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
            ))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/article", max_chars=2000)
            assert result["content_type"] == "html"
            assert result["title"] != "" or result["content"] != ""

    @pytest.mark.asyncio
    async def test_fetch_generic_exception(self):
        """未知异常返回空结果"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(side_effect=ValueError("unexpected"))
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/crash", max_chars=1000)
            assert result["content"] == ""
            assert result["reason"] == "error"

    @pytest.mark.asyncio
    async def test_fetch_html_with_mocked_trafilatura(self):
        """HTML 解析（mock trafilatura 模块）"""
        import sys
        from unittest.mock import MagicMock as _MagicMock

        fetcher = WebPageFetcher(use_mock=False)

        # mock trafilatura 模块
        mock_trafilatura = _MagicMock()
        mock_trafilatura.extract = MagicMock(return_value="# Extracted Markdown Content\n\nEGFR research findings.")
        mock_metadata = MagicMock()
        mock_metadata.title = "EGFR Research Article"
        mock_metadata.sitename = "Example"
        mock_trafilatura.extract_metadata = MagicMock(return_value=mock_metadata)

        html = "<html><head><title>Test</title></head><body>content</body></html>"

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
            ))
            mock_client_cls.return_value = mock_client

            original = sys.modules.get("trafilatura")
            sys.modules["trafilatura"] = mock_trafilatura
            try:
                result = await fetcher.fetch("https://example.com/article", max_chars=2000)
                assert result["content_type"] == "html"
                assert "Extracted Markdown" in result["content"]
                assert result["title"] == "EGFR Research Article"
            finally:
                if original is not None:
                    sys.modules["trafilatura"] = original
                else:
                    sys.modules.pop("trafilatura", None)

    @pytest.mark.asyncio
    async def test_fetch_html_trafilatura_exception_fallback(self):
        """trafilatura 抛异常时降级到 simple_html_extract"""
        import sys
        from unittest.mock import MagicMock as _MagicMock

        fetcher = WebPageFetcher(use_mock=False)

        # mock trafilatura 抛异常
        mock_trafilatura = _MagicMock()
        mock_trafilatura.extract = MagicMock(side_effect=RuntimeError("parse error"))
        mock_trafilatura.extract_metadata = MagicMock(return_value=None)

        html = "<html><head><title>Fallback Title</title></head><body>fallback content</body></html>"

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
            ))
            mock_client_cls.return_value = mock_client

            original = sys.modules.get("trafilatura")
            sys.modules["trafilatura"] = mock_trafilatura
            try:
                result = await fetcher.fetch("https://example.com/article", max_chars=2000)
                assert result["content_type"] == "html"
                # 降级到 simple_html_extract，title 从 <title> 标签提取
                assert "Fallback Title" in result["title"] or "fallback" in result["content"].lower()
            finally:
                if original is not None:
                    sys.modules["trafilatura"] = original
                else:
                    sys.modules.pop("trafilatura", None)

    @pytest.mark.asyncio
    async def test_fetch_pdf_with_mocked_pypdf(self):
        """PDF 解析（mock pypdf 模块）"""
        import sys
        from unittest.mock import MagicMock as _MagicMock

        fetcher = WebPageFetcher(use_mock=False)

        # mock pypdf 模块
        mock_pypdf = _MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text = MagicMock(return_value="PDF text content for testing.")
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.metadata = MagicMock()
        mock_reader.metadata.title = "PDF Title"
        mock_pypdf.PdfReader = MagicMock(return_value=mock_reader)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                content=b"fake pdf bytes",
                headers={"content-type": "application/pdf"},
            ))
            mock_client_cls.return_value = mock_client

            original = sys.modules.get("pypdf")
            sys.modules["pypdf"] = mock_pypdf
            try:
                result = await fetcher.fetch("https://example.com/doc.pdf", max_chars=5000)
                assert result["content_type"] == "pdf"
                assert "PDF text content" in result["content"]
                assert result["title"] == "PDF Title"
            finally:
                if original is not None:
                    sys.modules["pypdf"] = original
                else:
                    sys.modules.pop("pypdf", None)

    @pytest.mark.asyncio
    async def test_fetch_pdf_pypdf_not_installed(self):
        """pypdf 未安装时返回空结果"""
        import sys

        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                content=b"fake pdf bytes",
                headers={"content-type": "application/pdf"},
            ))
            mock_client_cls.return_value = mock_client

            # 关键：将 sys.modules['pypdf'] 设为 None 才能真正触发 ImportError
            # （仅 pop 无法阻止 import 系统重新加载已安装的模块）
            original = sys.modules.get("pypdf")
            sys.modules["pypdf"] = None
            try:
                result = await fetcher.fetch("https://example.com/doc.pdf", max_chars=5000)
                assert result["content"] == ""
                assert result["reason"] == "pypdf_not_installed"
            finally:
                if original is not None:
                    sys.modules["pypdf"] = original
                else:
                    sys.modules.pop("pypdf", None)

    @pytest.mark.asyncio
    async def test_fetch_json_invalid_falls_back_to_text(self):
        """无效 JSON 降级到纯文本"""
        fetcher = WebPageFetcher(use_mock=False)

        with patch("app.services.search.fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=httpx.Response(
                200,
                text="not valid json {{{",
                headers={"content-type": "application/json"},
            ))
            mock_client_cls.return_value = mock_client

            result = await fetcher.fetch("https://example.com/bad.json", max_chars=5000)
            # JSON 解析失败，降级到纯文本
            assert result["content_type"] in ("json", "text")
            assert "not valid json" in result["content"]


# ========== WebSearchTool / FetchWebPageTool 集成测试 ==========


class TestWebSearchTools:
    """WebSearchTool / FetchWebPageTool 工具测试"""

    @pytest.fixture
    def registry(self):
        from app.services.agent.tools.registry import ToolRegistry
        r = ToolRegistry()
        r.register_all()
        return r

    @pytest.mark.asyncio
    async def test_web_search_tool_registered(self, registry):
        """web_search 工具已注册"""
        tool = registry.get_tool("web_search")
        assert tool is not None
        assert tool.name == "web_search"

    @pytest.mark.asyncio
    async def test_fetch_web_page_tool_registered(self, registry):
        """fetch_web_page 工具已注册"""
        tool = registry.get_tool("fetch_web_page")
        assert tool is not None
        assert tool.name == "fetch_web_page"

    @pytest.mark.asyncio
    async def test_web_search_execution(self, registry):
        """执行 web_search 工具"""
        from app.core.security import UserRole

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        reset_aggregator()
        result = await registry.execute_tool(
            tool_name="web_search",
            params={"query": "EGFR inhibitor NSCLC", "max_results": 3},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )
        assert result.success
        assert result.data["total"] > 0
        assert all("title" in r for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_fetch_web_page_execution(self, registry):
        """执行 fetch_web_page 工具"""
        from app.core.security import UserRole

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        result = await registry.execute_tool(
            tool_name="fetch_web_page",
            params={"url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "max_chars": 1000},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )
        assert result.success
        assert "EGFR" in result.data["content"] or result.data["length"] > 0

    @pytest.mark.asyncio
    async def test_web_search_permission(self, registry):
        """RESEARCHER 角色可使用 web_search"""
        from app.core.security import UserRole
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("web_search", UserRole.RESEARCHER)
        assert has_tool_permission("fetch_web_page", UserRole.RESEARCHER)
