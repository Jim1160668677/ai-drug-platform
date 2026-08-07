"""4 个学术客户端 Mock 实现 + deps 注入 + 配置项 测试

覆盖:
1. 4 个 Mock 客户端返回预置 AcademicPaper 列表
2. 4 个 deps 工厂在 USE_MOCK=true 时返回 Mock 实现
3. settings 包含 SEMANTIC_SCHOLAR_API_KEY / CROSSREF_MAILTO 配置项
"""
import asyncio
from unittest.mock import patch

import pytest

from app.clients.base import AcademicClientBase, AcademicPaper
from app.core.config import settings


class TestMockAcademicClients:
    """4 个 Mock 学术客户端"""

    @pytest.mark.asyncio
    async def test_mock_biorxiv_client(self):
        """MockBiorxivClient 返回 AcademicPaper 列表,source=biorxiv"""
        from app.clients.mock.biorxiv_mock import MockBiorxivClient
        client = MockBiorxivClient()
        assert isinstance(client, AcademicClientBase)
        assert client.source_name == "biorxiv"

        results = await client.search("EGFR", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert all(p.source == "biorxiv" for p in results)

    @pytest.mark.asyncio
    async def test_mock_arxiv_client(self):
        """MockArxivClient 返回 AcademicPaper 列表,source=arxiv"""
        from app.clients.mock.arxiv_mock import MockArxivClient
        client = MockArxivClient()
        assert isinstance(client, AcademicClientBase)
        assert client.source_name == "arxiv"

        results = await client.search("EGFR", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert all(p.source == "arxiv" for p in results)

    @pytest.mark.asyncio
    async def test_mock_semantic_scholar_client(self):
        """MockSemanticScholarClient 返回 AcademicPaper 列表,source=semantic_scholar"""
        from app.clients.mock.semantic_scholar_mock import MockSemanticScholarClient
        client = MockSemanticScholarClient()
        assert isinstance(client, AcademicClientBase)
        assert client.source_name == "semantic_scholar"

        results = await client.search("EGFR", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert all(p.source == "semantic_scholar" for p in results)

    @pytest.mark.asyncio
    async def test_mock_crossref_client(self):
        """MockCrossrefClient 返回 AcademicPaper 列表,source=crossref"""
        from app.clients.mock.crossref_mock import MockCrossrefClient
        client = MockCrossrefClient()
        assert isinstance(client, AcademicClientBase)
        assert client.source_name == "crossref"

        results = await client.search("EGFR", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(p, AcademicPaper) for p in results)
        assert all(p.source == "crossref" for p in results)

    @pytest.mark.asyncio
    async def test_mock_clients_filter_by_query(self):
        """Mock 客户端应按 query 过滤(命中时返回结果,未命中时返回空或全量)"""
        from app.clients.mock.biorxiv_mock import MockBiorxivClient
        client = MockBiorxivClient()
        # 命中关键词
        hit_results = await client.search("EGFR", limit=5)
        assert len(hit_results) > 0
        # 验证标题或摘要包含 query(宽松匹配)
        assert any("EGFR" in p.title or "EGFR" in (p.abstract or "") for p in hit_results)


class TestAcademicClientDeps:
    """deps 注入:USE_MOCK=true 时返回 Mock,USE_MOCK=false 时返回 Real"""

    def test_get_biorxiv_client_mock_mode(self):
        """USE_MOCK=true → MockBiorxivClient"""
        from app.core.deps import get_biorxiv_client
        with patch.object(settings, "USE_MOCK", True):
            client = get_biorxiv_client()
        from app.clients.mock.biorxiv_mock import MockBiorxivClient
        assert isinstance(client, MockBiorxivClient)

    def test_get_biorxiv_client_real_mode(self):
        """USE_MOCK=false → RealBiorxivClient"""
        from app.core.deps import get_biorxiv_client
        with patch.object(settings, "USE_MOCK", False):
            client = get_biorxiv_client()
        from app.clients.real.biorxiv_real import RealBiorxivClient
        assert isinstance(client, RealBiorxivClient)

    def test_get_arxiv_client_mock_mode(self):
        from app.core.deps import get_arxiv_client
        with patch.object(settings, "USE_MOCK", True):
            client = get_arxiv_client()
        from app.clients.mock.arxiv_mock import MockArxivClient
        assert isinstance(client, MockArxivClient)

    def test_get_arxiv_client_real_mode(self):
        from app.core.deps import get_arxiv_client
        with patch.object(settings, "USE_MOCK", False):
            client = get_arxiv_client()
        from app.clients.real.arxiv_real import RealArxivClient
        assert isinstance(client, RealArxivClient)

    def test_get_semantic_scholar_client_mock_mode(self):
        from app.core.deps import get_semantic_scholar_client
        with patch.object(settings, "USE_MOCK", True):
            client = get_semantic_scholar_client()
        from app.clients.mock.semantic_scholar_mock import MockSemanticScholarClient
        assert isinstance(client, MockSemanticScholarClient)

    def test_get_semantic_scholar_client_real_mode(self):
        from app.core.deps import get_semantic_scholar_client
        with patch.object(settings, "USE_MOCK", False):
            client = get_semantic_scholar_client()
        from app.clients.real.semantic_scholar_real import RealSemanticScholarClient
        assert isinstance(client, RealSemanticScholarClient)

    def test_get_crossref_client_mock_mode(self):
        from app.core.deps import get_crossref_client
        with patch.object(settings, "USE_MOCK", True):
            client = get_crossref_client()
        from app.clients.mock.crossref_mock import MockCrossrefClient
        assert isinstance(client, MockCrossrefClient)

    def test_get_crossref_client_real_mode(self):
        from app.core.deps import get_crossref_client
        with patch.object(settings, "USE_MOCK", False):
            client = get_crossref_client()
        from app.clients.real.crossref_real import RealCrossrefClient
        assert isinstance(client, RealCrossrefClient)


class TestAcademicClientConfig:
    """配置项:SEMANTIC_SCHOLAR_API_KEY / CROSSREF_MAILTO"""

    def test_semantic_scholar_api_key_config_exists(self):
        """settings 必须有 SEMANTIC_SCHOLAR_API_KEY 字段(默认空字符串)"""
        assert hasattr(settings, "SEMANTIC_SCHOLAR_API_KEY")
        assert isinstance(settings.SEMANTIC_SCHOLAR_API_KEY, str)

    def test_crossref_mailto_config_exists(self):
        """settings 必须有 CROSSREF_MAILTO 字段(默认空字符串)"""
        assert hasattr(settings, "CROSSREF_MAILTO")
        assert isinstance(settings.CROSSREF_MAILTO, str)
