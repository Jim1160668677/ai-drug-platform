"""NCBI E-utilities 客户端单元测试

覆盖：
1. MockNcbiClient：所有 4 个原子方法 + 4 个高层封装方法
2. RealNcbiClient：使用 httpx.MockTransport 模拟响应
   - 正常响应、HTTP 错误、429 限流、网络异常、API Key 注入、缓存
3. ToolRegistry：SearchNcbiTool 工具调用
"""
import asyncio
import json
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# 测试环境强制 Mock 模式
os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")

from app.clients.base import NcbiClient
from app.clients.mock.ncbi_mock import (
    CLINVAR_DATABASE,
    FASTA_DATABASE,
    GENE_INFO_DATABASE,
    PUBMED_DATABASE,
    MockNcbiClient,
)
from app.clients.real.ncbi_real import RealNcbiClient


# ========== MockNcbiClient 测试 ==========


class TestMockNcbiClientAtoms:
    """MockNcbiClient 原子方法测试"""

    @pytest.fixture
    def client(self):
        return MockNcbiClient()

    @pytest.mark.asyncio
    async def test_esearch_pubmed(self, client: MockNcbiClient):
        """esearch pubmed 返回 EGFR 相关文献 ID"""
        result = await client.esearch(db="pubmed", term="EGFR", retmax=5)
        assert "esearchresult" in result
        id_list = result["esearchresult"]["idlist"]
        assert len(id_list) > 0
        assert all(isinstance(uid, str) for uid in id_list)

    @pytest.mark.asyncio
    async def test_esearch_clinvar(self, client: MockNcbiClient):
        """esearch clinvar 按基因返回致病变异 ID"""
        result = await client.esearch(
            db="clinvar",
            term="TP53[gene] AND pathogenic[clinsig]",
            retmax=3,
        )
        id_list = result["esearchresult"]["idlist"]
        assert len(id_list) > 0
        assert "VCV" in id_list[0]  # ClinVar UID 格式

    @pytest.mark.asyncio
    async def test_esearch_gene(self, client: MockNcbiClient):
        """esearch gene 返回基因 Entrez ID"""
        result = await client.esearch(
            db="gene",
            term="EGFR[Gene Name] AND Homo sapiens[Organism]",
        )
        id_list = result["esearchresult"]["idlist"]
        assert id_list == ["1956"]  # EGFR Entrez ID

    @pytest.mark.asyncio
    async def test_esearch_unknown_gene_returns_default(self, client: MockNcbiClient):
        """esearch 未知基因返回默认文献（设计行为：fallback 到 default）"""
        result = await client.esearch(db="pubmed", term="UNKNOWNGENE12345", retmax=5)
        # Mock 设计：未匹配时返回 default 文献
        assert len(result["esearchresult"]["idlist"]) >= 1

    @pytest.mark.asyncio
    async def test_esummary_pubmed(self, client: MockNcbiClient):
        """esummary pubmed 返回文献详情"""
        # 先 esearch 拿 ID
        search = await client.esearch(db="pubmed", term="EGFR", retmax=1)
        uid = search["esearchresult"]["idlist"][0]

        summary = await client.esummary(db="pubmed", ids=[uid])
        assert uid in summary["result"]
        rec = summary["result"][uid]
        assert rec["title"]
        assert rec["fulljournalname"]

    @pytest.mark.asyncio
    async def test_esummary_clinvar(self, client: MockNcbiClient):
        """esummary clinvar 返回变异详情"""
        search = await client.esearch(
            db="clinvar",
            term="TP53[gene] AND pathogenic[clinsig]",
            retmax=1,
        )
        uid = search["esearchresult"]["idlist"][0]

        summary = await client.esummary(db="clinvar", ids=[uid])
        rec = summary["result"][uid]
        assert rec["title"]
        assert rec["clinical_significance"]["description"]

    @pytest.mark.asyncio
    async def test_esummary_empty_ids(self, client: MockNcbiClient):
        """esummary 空列表返回空结果"""
        result = await client.esummary(db="pubmed", ids=[])
        assert result["result"]["uids"] == []

    @pytest.mark.asyncio
    async def test_efetch_fasta(self, client: MockNcbiClient):
        """efetch protein 返回 FASTA 序列"""
        result = await client.efetch(
            db="protein",
            ids=["NP_005219"],  # EGFR
            rettype="fasta",
            retmode="text",
        )
        assert ">NP_005219" in result
        assert "EGFR" in result or "epidermal" in result.lower()

    @pytest.mark.asyncio
    async def test_efetch_empty_ids(self, client: MockNcbiClient):
        """efetch 空 ID 列表返回空字符串"""
        result = await client.efetch(db="protein", ids=[])
        assert result == ""

    @pytest.mark.asyncio
    async def test_elink(self, client: MockNcbiClient):
        """elink 返回跨库链接"""
        result = await client.elink(dbfrom="gene", db="pubmed", id="1956")
        assert "linksets" in result
        assert len(result["linksets"]) > 0


class TestMockNcbiClientHighLevel:
    """MockNcbiClient 高层封装方法测试"""

    @pytest.fixture
    def client(self):
        return MockNcbiClient()

    @pytest.mark.asyncio
    async def test_search_pubmed_egfr(self, client: MockNcbiClient):
        """search_pubmed 返回 EGFR 文献"""
        results = await client.search_pubmed("EGFR", retmax=5)
        assert len(results) > 0
        assert all("title" in r for r in results)
        assert all("authors" in r for r in results)
        # 验证内容相关性
        assert any("EGFR" in r["title"] for r in results)

    @pytest.mark.asyncio
    async def test_search_pubmed_default(self, client: MockNcbiClient):
        """search_pubmed 未知基因返回默认文献"""
        results = await client.search_pubmed("UNKNOWNGENE", retmax=3)
        assert len(results) >= 1  # 默认文献

    @pytest.mark.asyncio
    async def test_fetch_gene_info_egfr(self, client: MockNcbiClient):
        """fetch_gene_info EGFR"""
        info = await client.fetch_gene_info("EGFR")
        assert info["symbol"] == "EGFR"
        assert info["entrez_id"] == "1956"
        assert "epidermal" in info["name"].lower()

    @pytest.mark.asyncio
    async def test_fetch_gene_info_unknown(self, client: MockNcbiClient):
        """fetch_gene_info 未知基因返回占位"""
        info = await client.fetch_gene_info("UNKNOWNGENE")
        assert info["symbol"] == "UNKNOWNGENE"
        assert info["entrez_id"] is None
        assert info.get("note") == "mock_placeholder"

    @pytest.mark.asyncio
    async def test_fetch_clinvar_variants_tp53(self, client: MockNcbiClient):
        """fetch_clinvar_variants TP53 返回致病变异"""
        variants = await client.fetch_clinvar_variants("TP53", retmax=5)
        assert len(variants) == 5
        assert all(v["gene"] == "TP53" for v in variants)
        # 验证含 R175H/R248Q/R273H 热点
        titles = " ".join(v["title"] for v in variants)
        assert "Arg175His" in titles or "R175H" in titles or "175" in titles

    @pytest.mark.asyncio
    async def test_fetch_clinvar_variants_egfr(self, client: MockNcbiClient):
        """fetch_clinvar_variants EGFR"""
        variants = await client.fetch_clinvar_variants("EGFR", retmax=3)
        assert len(variants) > 0
        # 含 T790M/L858R 等经典突变
        titles = " ".join(v["title"] for v in variants)
        assert "790" in titles or "858" in titles or "719" in titles

    @pytest.mark.asyncio
    async def test_fetch_clinvar_variants_unknown(self, client: MockNcbiClient):
        """fetch_clinvar_variants 未知基因返回空"""
        variants = await client.fetch_clinvar_variants("UNKNOWNGENE")
        assert variants == []

    @pytest.mark.asyncio
    async def test_fetch_sequences(self, client: MockNcbiClient):
        """fetch_sequences 返回 FASTA"""
        fasta = await client.fetch_sequences(["NP_005219"], db="protein")
        assert ">NP_005219" in fasta


# ========== RealNcbiClient 测试（使用 MockTransport） ==========


def make_mock_transport(handler):
    """构造 httpx.MockTransport"""
    return httpx.MockTransport(handler)


class TestRealNcbiClientRetry:
    """RealNcbiClient 重试 + 错误处理测试"""

    @pytest.fixture
    def client(self):
        return RealNcbiClient()

    @pytest.mark.asyncio
    async def test_esearch_success(self, client: RealNcbiClient):
        """esearch 正常响应"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["12345"], "count": "1"}},
            )

        # 临时替换 http client
        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        try:
            result = await client.esearch(db="pubmed", term="EGFR")
            assert result["esearchresult"]["idlist"] == ["12345"]
        finally:
            await client._http_client.aclose()
            client._http_client = original_client

    @pytest.mark.asyncio
    async def test_esearch_429_retry(self, client: RealNcbiClient):
        """esearch 429 限流后重试成功"""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 2:
                return httpx.Response(429, text="Rate limited")
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["12345"], "count": "1"}},
            )

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        # 缩短重试间隔加速测试
        with patch("app.clients.real.ncbi_real._RETRY_DELAYS", [0.01]):
            try:
                result = await client.esearch(db="pubmed", term="EGFR")
                assert result["esearchresult"]["idlist"] == ["12345"]
                assert call_count["n"] == 2  # 第一次失败 + 第二次成功
            finally:
                await client._http_client.aclose()
                client._http_client = original_client

    @pytest.mark.asyncio
    async def test_esearch_500_all_retries_failed(self, client: RealNcbiClient):
        """esearch 5xx 全部重试失败返回空"""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(500, text="Internal Server Error")

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        with patch("app.clients.real.ncbi_real._RETRY_DELAYS", [0.01, 0.01, 0.01]):
            try:
                result = await client.esearch(db="pubmed", term="EGFR")
                # 重试耗尽后返回空结果
                assert result["esearchresult"]["idlist"] == []
                assert call_count["n"] == client.max_retries + 1
            finally:
                await client._http_client.aclose()
                client._http_client = original_client

    @pytest.mark.asyncio
    async def test_esearch_network_error(self, client: RealNcbiClient):
        """esearch 网络异常返回空"""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        with patch("app.clients.real.ncbi_real._RETRY_DELAYS", [0.01, 0.01, 0.01]):
            try:
                result = await client.esearch(db="pubmed", term="EGFR")
                assert result["esearchresult"]["idlist"] == []
            finally:
                await client._http_client.aclose()
                client._http_client = original_client

    @pytest.mark.asyncio
    async def test_api_key_injection(self, client: RealNcbiClient):
        """API Key 自动注入到请求参数"""
        captured_params = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params["query"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": [], "count": "0"}},
            )

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        original_key = client.api_key
        client.api_key = "test_api_key_12345"
        try:
            await client.esearch(db="pubmed", term="EGFR")
            assert captured_params["query"].get("api_key") == "test_api_key_12345"
        finally:
            client.api_key = original_key
            await client._http_client.aclose()
            client._http_client = original_client

    @pytest.mark.asyncio
    async def test_no_api_key_when_empty(self, client: RealNcbiClient):
        """无 API Key 时不附加 api_key 参数"""
        captured_params = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params["query"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": [], "count": "0"}},
            )

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        original_key = client.api_key
        client.api_key = ""
        try:
            await client.esearch(db="pubmed", term="EGFR")
            assert "api_key" not in captured_params["query"]
        finally:
            client.api_key = original_key
            await client._http_client.aclose()
            client._http_client = original_client


class TestRealNcbiClientHighLevel:
    """RealNcbiClient 高层封装方法测试"""

    @pytest.fixture
    def client(self):
        return RealNcbiClient()

    @pytest.mark.asyncio
    async def test_search_pubmed_parse(self, client: RealNcbiClient):
        """search_pubmed 正确解析 esummary 响应"""
        # 模拟两步调用：esearch 返回 ID，esummary 返回详情
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "esearch" in url:
                return httpx.Response(
                    200,
                    json={"esearchresult": {"idlist": ["36123456"], "count": "1"}},
                )
            elif "esummary" in url:
                return httpx.Response(
                    200,
                    json={
                        "result": {
                            "uids": ["36123456"],
                            "36123456": {
                                "uid": "36123456",
                                "title": "EGFR in NSCLC",
                                "authors": [{"name": "Lynch TJ"}],
                                "fulljournalname": "N Engl J Med",
                                "pubdate": "2024 Jun",
                                "abstract": "EGFR mutations...",
                                "elocationid": "doi:10.1056/NEJMra2401234",
                                "pubtype": ["Review"],
                                "source": "N Engl J Med",
                            },
                        }
                    },
                )
            return httpx.Response(404)

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        try:
            results = await client.search_pubmed("EGFR", retmax=5)
            assert len(results) == 1
            assert results[0]["uid"] == "36123456"
            assert results[0]["title"] == "EGFR in NSCLC"
            assert results[0]["journal"] == "N Engl J Med"
            assert "Lynch TJ" in results[0]["authors"]
        finally:
            await client._http_client.aclose()
            client._http_client = original_client

    @pytest.mark.asyncio
    async def test_fetch_clinvar_variants_parse(self, client: RealNcbiClient):
        """fetch_clinvar_variants 正确解析 ClinVar esummary"""
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "esearch" in url:
                return httpx.Response(
                    200,
                    json={"esearchresult": {"idlist": ["VCV000011821"], "count": "1"}},
                )
            elif "esummary" in url:
                return httpx.Response(
                    200,
                    json={
                        "result": {
                            "uids": ["VCV000011821"],
                            "VCV000011821": {
                                "uid": "VCV000011821",
                                "title": "NM_000546.6(TP53):c.524G>A (p.Arg175His)",
                                "clinical_significance": {
                                    "description": "Pathogenic",
                                    "review_status": "reviewed by expert panel",
                                },
                                "genes": [{"symbol": "TP53", "name": "TP53"}],
                                "variation_set": [{"variation_class": "single_nucleotide_variant"}],
                            },
                        }
                    },
                )
            return httpx.Response(404)

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        try:
            variants = await client.fetch_clinvar_variants("TP53", retmax=5)
            assert len(variants) == 1
            v = variants[0]
            assert v["clnsig"] == "Pathogenic"
            assert v["gene"] == "TP53"
            assert v["hgvs_p"] == "p.Arg175His"
            assert v["hgvs_c"] == "c.524G>A"
            assert v["variant_type"] == "single_nucleotide_variant"
        finally:
            await client._http_client.aclose()
            client._http_client = original_client

    @pytest.mark.asyncio
    async def test_search_pubmed_empty_result(self, client: RealNcbiClient):
        """search_pubmed esearch 返回空 → 整体返回空"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": [], "count": "0"}},
            )

        original_client = client._http_client
        client._http_client = httpx.AsyncClient(
            transport=make_mock_transport(handler),
            timeout=5.0,
        )
        try:
            results = await client.search_pubmed("NONEXISTENT_TERM")
            assert results == []
        finally:
            await client._http_client.aclose()
            client._http_client = original_client


# ========== ToolRegistry 集成测试 ==========


class TestSearchNcbiTool:
    """SearchNcbiTool 工具测试"""

    @pytest.fixture
    def registry(self):
        from app.services.agent.tools.registry import ToolRegistry
        r = ToolRegistry()
        r.register_all()
        return r

    @pytest.mark.asyncio
    async def test_tool_registered(self, registry):
        """工具已注册"""
        tool = registry.get_tool("search_ncbi")
        assert tool is not None
        assert tool.name == "search_ncbi"

    @pytest.mark.asyncio
    async def test_tool_info(self, registry):
        """工具 info 结构正确"""
        tool = registry.get_tool("search_ncbi")
        info = tool.to_info()
        assert info["name"] == "search_ncbi"
        assert "pubmed" in info["parameters"]["properties"]["db"]["enum"]
        assert info["required_role"] == "researcher"

    @pytest.mark.asyncio
    async def test_search_pubmed_via_tool(self, registry):
        """通过 ToolRegistry 执行 search_ncbi pubmed"""
        from app.core.security import UserRole, hash_password
        from app.models.user import User
        from app.services.agent.tools.base import ToolContext

        # 构造测试用户
        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        ctx = ToolContext(
            db=None,
            user=user,
            task_id="test-task",
            session_id="test-session",
        )

        result = await registry.execute_tool(
            tool_name="search_ncbi",
            params={"db": "pubmed", "query": "EGFR", "retmax": 2},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )

        assert result.success
        assert result.data["total"] > 0
        assert any("EGFR" in a["title"] for a in result.data["articles"])

    @pytest.mark.asyncio
    async def test_search_clinvar_via_tool(self, registry):
        """通过 ToolRegistry 执行 search_ncbi clinvar"""
        from app.core.security import UserRole
        from app.services.agent.tools.base import ToolContext

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        result = await registry.execute_tool(
            tool_name="search_ncbi",
            params={"db": "clinvar", "query": "TP53", "retmax": 3},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )

        assert result.success
        assert result.data["total"] > 0
        assert all(v["gene"] == "TP53" for v in result.data["variants"])

    @pytest.mark.asyncio
    async def test_search_gene_via_tool(self, registry):
        """通过 ToolRegistry 执行 search_ncbi gene"""
        from app.core.security import UserRole
        from app.services.agent.tools.base import ToolContext

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        result = await registry.execute_tool(
            tool_name="search_ncbi",
            params={"db": "gene", "query": "EGFR"},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )

        assert result.success
        assert result.data["gene_info"]["symbol"] == "EGFR"
        assert result.data["gene_info"]["entrez_id"] == "1956"

    @pytest.mark.asyncio
    async def test_search_protein_via_tool(self, registry):
        """通过 ToolRegistry 执行 search_ncbi protein 获取 FASTA"""
        from app.core.security import UserRole
        from app.services.agent.tools.base import ToolContext

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        result = await registry.execute_tool(
            tool_name="search_ncbi",
            params={"db": "protein", "query": "NP_005219", "rettype": "fasta"},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )

        assert result.success
        assert ">NP_005219" in result.data["fasta"]

    @pytest.mark.asyncio
    async def test_invalid_db_returns_fail(self, registry):
        """不支持的数据库返回失败"""
        from app.core.security import UserRole

        user = MagicMock()
        user.id = "test-user-id"
        user.role = UserRole.RESEARCHER

        # 参数校验阶段就会失败（enum 限制）
        result = await registry.execute_tool(
            tool_name="search_ncbi",
            params={"db": "invalid_db", "query": "test"},
            user=user,
            task_id="test-task",
            session_id="test-session",
        )
        # validate_params 会因 enum 不匹配失败
        assert not result.success

    @pytest.mark.asyncio
    async def test_permission_researcher_ok(self, registry):
        """RESEARCHER 角色可使用 search_ncbi"""
        from app.core.security import UserRole
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("search_ncbi", UserRole.RESEARCHER)

    @pytest.mark.asyncio
    async def test_permission_doctor_ok(self, registry):
        """DOCTOR 角色可使用 search_ncbi（与 search_literature 一致）"""
        from app.core.security import UserRole
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("search_ncbi", UserRole.DOCTOR)
