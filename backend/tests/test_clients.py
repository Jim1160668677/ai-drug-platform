"""客户端测试 — Mock + Real 客户端全覆盖

覆盖：
- MockLLMClient（chat + embed）
- MockGeneClient / MockVariantClient / MockChemblClient / MockDiffdockClient
- RealLLMClient（httpx mock：成功/超时/HTTP 错误/异常/embed）
- RealChemblClient（httpx mock：target 查找/activity/drug_indication）
- RealGeneClient（httpx mock：hits/无 hits/pathway 解析）
- RealVariantClient（httpx mock：批量查询）
- RealDiffdockClient（httpx mock：同步响应/异步轮询/失败/超时）
"""
import asyncio
import hashlib
import struct
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.mock.chembl_mock import MockChemblClient, MOLECULE_DATABASE
from app.clients.mock.diffdock_mock import (
    MockDiffdockClient,
    _seeded_random,
    _generate_pose,
)
from app.clients.mock.llm_mock import MockLLMClient, QA_KNOWLEDGE
from app.clients.mock.mygene_mock import MockGeneClient, GENE_DATABASE
from app.clients.mock.myvariant_mock import MockVariantClient, VARIANT_DATABASE
from app.clients.real.chembl_real import RealChemblClient
from app.clients.real.diffdock_real import RealDiffdockClient
from app.clients.real.llm_real import RealLLMClient
from app.clients.real.mygene_real import RealGeneClient
from app.clients.real.myvariant_real import RealVariantClient


# ============================================================
# Mock LLM 客户端
# ============================================================

class TestMockLLMClient:
    @pytest.mark.asyncio
    async def test_chat_egfr_keyword(self):
        client = MockLLMClient()
        result = await client.chat(
            [{"role": "user", "content": "EGFR 突变有什么靶向药？"}],
            model="gpt-4o",
        )
        assert "EGFR" in result["content"]
        assert "Osimertinib" in result["content"]
        assert result["model"] == "gpt-4o"
        assert "prompt_tokens" in result["usage"]
        assert "completion_tokens" in result["usage"]
        assert len(result["references"]) > 0

    @pytest.mark.asyncio
    async def test_chat_b7h3_keyword(self):
        client = MockLLMClient()
        result = await client.chat(
            [{"role": "assistant", "content": "之前的话"},
             {"role": "user", "content": "B7H3 是什么？"}]
        )
        assert "B7-H3" in result["content"] or "B7H3" in result["content"]
        assert result["model"] == "mock-gpt-4o"  # 默认模型

    @pytest.mark.asyncio
    async def test_chat_fap_keyword(self):
        client = MockLLMClient()
        result = await client.chat(
            [{"role": "user", "content": "FAP 靶点呢"}]
        )
        assert "FAP" in result["content"]

    @pytest.mark.asyncio
    async def test_chat_no_keyword_fallback(self):
        client = MockLLMClient()
        result = await client.chat(
            [{"role": "user", "content": "今天天气怎么样"}]
        )
        assert "Mock 模式" in result["content"]
        assert "今天天气怎么样" in result["content"]
        assert result["references"] == []
        assert result["code"] is None

    @pytest.mark.asyncio
    async def test_chat_empty_messages(self):
        client = MockLLMClient()
        result = await client.chat([], model="test-model")
        assert result["model"] == "test-model"
        assert "Mock 模式" in result["content"]

    @pytest.mark.asyncio
    async def test_embed_returns_vector(self):
        """embed 返回固定维度向量（基于 sha256 派生）"""
        client = MockLLMClient()
        vec = await client.embed("hello world")
        assert len(vec) > 0
        assert all(isinstance(v, float) for v in vec)

    @pytest.mark.asyncio
    async def test_embed_deterministic(self):
        """相同输入应返回相同向量"""
        client = MockLLMClient()
        v1 = await client.embed("EGFR")
        v2 = await client.embed("EGFR")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_embed_different_inputs_differ(self):
        client = MockLLMClient()
        v1 = await client.embed("EGFR")
        v2 = await client.embed("KRAS")
        assert v1 != v2


# ============================================================
# Mock Gene 客户端
# ============================================================

class TestMockGeneClient:
    @pytest.mark.asyncio
    async def test_query_egfr(self):
        client = MockGeneClient()
        result = await client.query("EGFR")
        assert result["symbol"] == "EGFR"
        assert result["entrez_id"] == 1956
        assert result["uniprot_id"] == "P00533"
        assert "EGFR" in result["summary"]
        assert len(result["pathways"]) > 0
        assert result["drugbank_count"] == 12

    @pytest.mark.asyncio
    async def test_query_case_insensitive(self):
        client = MockGeneClient()
        result = await client.query("egfr")
        assert result["symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_query_by_synonym(self):
        """通过别名 ERBB1 应能找到 EGFR"""
        client = MockGeneClient()
        result = await client.query("ERBB1")
        assert result["symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_query_by_synonym_b7h3(self):
        client = MockGeneClient()
        result = await client.query("B7-H3")
        assert result["symbol"] == "CD276"

    @pytest.mark.asyncio
    async def test_query_unknown_gene(self):
        client = MockGeneClient()
        result = await client.query("UNKNOWNXYZ")
        assert result["symbol"] == "UNKNOWNXYZ"
        assert result["entrez_id"] is None
        assert result["note"] == "mock_placeholder"
        assert "无详细注释" in result["summary"]

    @pytest.mark.asyncio
    async def test_query_all_5_genes(self):
        client = MockGeneClient()
        for gene in ["EGFR", "B7H3", "FAP", "TP53", "KRAS"]:
            result = await client.query(gene)
            assert result is not None
            assert "symbol" in result


# ============================================================
# Mock Variant 客户端
# ============================================================

class TestMockVariantClient:
    @pytest.mark.asyncio
    async def test_query_t790m(self):
        client = MockVariantClient()
        result = await client.query_batch(["chr7:55259515:T>A"])
        assert len(result) == 1
        assert result[0]["gene"] == "EGFR"
        assert result[0]["hgvs_p"] == "p.Thr790Met"
        assert result[0]["clinvar"]["clnsig"] == "Pathogenic"

    @pytest.mark.asyncio
    async def test_query_l858r(self):
        client = MockVariantClient()
        result = await client.query_batch(["chr7:55259513:G>A"])
        assert result[0]["gene"] == "EGFR"
        assert result[0]["hgvs_p"] == "p.Leu858Arg"

    @pytest.mark.asyncio
    async def test_query_exon19del(self):
        client = MockVariantClient()
        result = await client.query_batch(["chr7:55242471:del"])
        assert result[0]["hgvs_p"] == "p.Glu746_Ala750del"

    @pytest.mark.asyncio
    async def test_query_kras_g12c(self):
        client = MockVariantClient()
        result = await client.query_batch(["chr12:25245350:G>A"])
        assert result[0]["gene"] == "KRAS"
        assert result[0]["hgvs_p"] == "p.Gly12Cys"

    @pytest.mark.asyncio
    async def test_query_batch_multiple(self):
        client = MockVariantClient()
        result = await client.query_batch([
            "chr7:55259515:T>A",
            "chr7:55259513:G>A",
            "chr12:25245350:G>A",
        ])
        assert len(result) == 3
        genes = [r["gene"] for r in result]
        assert "EGFR" in genes
        assert "KRAS" in genes

    @pytest.mark.asyncio
    async def test_query_unknown_variant(self):
        client = MockVariantClient()
        result = await client.query_batch(["chr1:1:A>T"])
        assert result[0]["gene"] is None
        assert result[0]["clinvar"] is None
        assert result[0]["note"] == "mock_placeholder"

    @pytest.mark.asyncio
    async def test_query_strips_whitespace(self):
        client = MockVariantClient()
        result = await client.query_batch(["  chr7:55259515:T>A  "])
        assert result[0]["gene"] == "EGFR"


# ============================================================
# Mock ChEMBL 客户端
# ============================================================

class TestMockChemblClient:
    @pytest.mark.asyncio
    async def test_get_active_molecules_egfr(self):
        client = MockChemblClient()
        result = await client.get_active_molecules("EGFR")
        assert len(result) == 4
        names = [m["name"] for m in result]
        assert "Osimertinib" in names
        assert "Gefitinib" in names
        assert all(m["target_gene"] == "EGFR" for m in result)

    @pytest.mark.asyncio
    async def test_get_active_molecules_case_insensitive(self):
        client = MockChemblClient()
        result = await client.get_active_molecules("kras")
        assert len(result) == 2
        assert "Sotorasib" in [m["name"] for m in result]

    @pytest.mark.asyncio
    async def test_get_active_molecules_unknown_target(self):
        client = MockChemblClient()
        result = await client.get_active_molecules("UNKNOWN")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_molecules_with_limit(self):
        client = MockChemblClient()
        result = await client.get_active_molecules("EGFR", limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_active_molecules_activity_filter(self):
        """activity_type=IC50 应过滤掉非 IC50 的分子"""
        client = MockChemblClient()
        result = await client.get_active_molecules("EGFR", activity_type="IC50")
        assert all(m["activity"]["activity_type"] == "IC50" for m in result)

    @pytest.mark.asyncio
    async def test_get_active_molecules_wrong_activity_returns_empty(self):
        client = MockChemblClient()
        result = await client.get_active_molecules("EGFR", activity_type="Ki")
        assert result == []

    @pytest.mark.asyncio
    async def test_find_approved_drugs_egfr(self):
        client = MockChemblClient()
        result = await client.find_approved_drugs("EGFR")
        assert len(result) == 4
        assert all(d["max_phase"] == 4 for d in result)
        assert "Osimertinib" in [d["name"] for d in result]

    @pytest.mark.asyncio
    async def test_find_approved_drugs_kras(self):
        client = MockChemblClient()
        result = await client.find_approved_drugs("KRAS")
        assert len(result) == 2
        assert "Sotorasib" in [d["name"] for d in result]
        assert "Adagrasib" in [d["name"] for d in result]

    @pytest.mark.asyncio
    async def test_find_approved_drugs_unknown(self):
        client = MockChemblClient()
        result = await client.find_approved_drugs("UNKNOWN")
        assert result == []


# ============================================================
# Mock DiffDock 客户端
# ============================================================

class TestMockDiffdockClient:
    @pytest.mark.asyncio
    async def test_dock_basic(self):
        client = MockDiffdockClient()
        protein = "ATOM      1  N   ALA A   1      11.104  6.134 -6.504  1.00  0.00           N"
        result = await client.dock(protein, "CCO", num_poses=3)
        assert result["status"] == "completed"
        assert result["num_poses"] == 3
        assert len(result["poses"]) == 3
        assert result["mock"] is True
        assert result["ligand_smiles"] == "CCO"

    @pytest.mark.asyncio
    async def test_dock_poses_sorted_by_confidence(self):
        client = MockDiffdockClient()
        result = await client.dock("PROTEIN", "c1ccccc1", num_poses=5)
        confidences = [p["confidence"] for p in result["poses"]]
        assert confidences == sorted(confidences, reverse=True)
        assert result["poses"][0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_dock_min_one_pose(self):
        client = MockDiffdockClient()
        result = await client.dock("P", "C", num_poses=0)
        # 实际应被 clamp 到 1
        assert result["num_poses"] >= 1

    @pytest.mark.asyncio
    async def test_dock_max_20_poses(self):
        client = MockDiffdockClient()
        result = await client.dock("P", "C", num_poses=100)
        assert result["num_poses"] <= 20

    @pytest.mark.asyncio
    async def test_dock_reproducibility(self):
        """相同输入应产生相同结果（基于种子）"""
        client = MockDiffdockClient()
        r1 = await client.dock("PROTEIN", "CCO", num_poses=2)
        r2 = await client.dock("PROTEIN", "CCO", num_poses=2)
        assert r1["poses"] == r2["poses"]

    @pytest.mark.asyncio
    async def test_dock_pose_structure(self):
        client = MockDiffdockClient()
        result = await client.dock("P", "C", num_poses=1)
        pose = result["poses"][0]
        assert "rank" in pose
        assert "confidence" in pose
        assert "positions" in pose
        assert "scores" in pose
        assert "smiles" in pose
        assert "num_atoms" in pose
        assert "binding_affinity_pred_kd" in pose
        assert 0 <= pose["confidence"] <= 1

    def test_seeded_random_deterministic(self):
        """_seeded_random 应基于种子确定性返回 0-1 之间"""
        r1 = _seeded_random("test_seed")
        r2 = _seeded_random("test_seed")
        assert r1 == r2
        assert 0 <= r1 <= 1

    def test_seeded_random_different_seeds(self):
        assert _seeded_random("seed1") != _seeded_random("seed2")

    def test_generate_pose_structure(self):
        pose = _generate_pose("protein_pdb", "CCO", rank=1, num_poses=3)
        assert pose["rank"] == 1
        assert pose["smiles"] == "CCO"
        assert len(pose["positions"]) == 20  # num_atoms = 20
        assert len(pose["scores"]) == 3


# ============================================================
# Real LLM 客户端（httpx mock）
# ============================================================

class TestRealLLMClient:
    def test_init_with_explicit_params(self):
        client = RealLLMClient(
            base_url="https://api.example.com/v1",
            api_key="sk-test-key-123456",
            upstream_protocol="chat_completions",
            default_model="gpt-4o",
            temperature=0.5,
            max_tokens=1000,
            timeout_sec=30,
        )
        assert client.base_url == "https://api.example.com/v1"
        assert client.api_key == "sk-test-key-123456"
        assert client.upstream_protocol == "chat_completions"
        assert client.default_model == "gpt-4o"

    def test_init_missing_api_key_raises(self):
        with patch("app.clients.real.llm_real.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.LLM_MODEL_DEEP = "gpt-4o"
            with pytest.raises(RuntimeError, match="LLM API key"):
                RealLLMClient()

    def test_build_chat_url_chat_completions(self):
        client = RealLLMClient(api_key="sk-test")
        assert client._build_chat_url().endswith("/chat/completions")

    def test_build_chat_url_completions(self):
        client = RealLLMClient(api_key="sk-test", upstream_protocol="completions")
        url = client._build_chat_url()
        assert url.endswith("/completions")
        assert "/chat/" not in url

    def test_build_chat_url_anthropic(self):
        client = RealLLMClient(api_key="sk-test", upstream_protocol="anthropic")
        assert client._build_chat_url().endswith("/messages")

    def test_build_chat_url_unknown_falls_back(self):
        client = RealLLMClient(api_key="sk-test", upstream_protocol="unknown_protocol")
        assert client._build_chat_url().endswith("/chat/completions")

    @pytest.mark.asyncio
    async def test_chat_success(self):
        """模拟 LLM 200 响应"""
        client = RealLLMClient(api_key="sk-test", default_model="gpt-4o")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result["content"] == "Hello!"
        assert result["model"] == "gpt-4o"
        assert result["usage"]["total_tokens"] == 15
        assert result["duration_sec"] >= 0
        assert result["references"] == []
        assert result["code"] is None

    @pytest.mark.asyncio
    async def test_chat_http_error(self):
        """模拟 LLM 500 错误响应"""
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert "[LLM HTTP 500]" in result["content"]
        assert result["usage"]["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_chat_timeout(self):
        """模拟超时异常"""
        client = RealLLMClient(api_key="sk-test", timeout_sec=1)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert "[LLM 调用超时]" in result["content"]

    @pytest.mark.asyncio
    async def test_chat_generic_exception(self):
        """模拟其他异常"""
        client = RealLLMClient(api_key="sk-test")

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(side_effect=ConnectionError("network down"))

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert "[LLM 调用失败]" in result["content"]

    @pytest.mark.asyncio
    async def test_chat_with_custom_kwargs(self):
        """透传 top_p 等额外参数"""
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            await client.chat(
                [{"role": "user", "content": "Hi"}],
                top_p=0.9,
                temperature=0.1,
                max_tokens=100,
            )

        call_args = mock_async_client.post.call_args
        body = call_args.kwargs["json"]
        assert body["top_p"] == 0.9
        assert body["temperature"] == 0.1
        assert body["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_chat_empty_choices(self):
        """响应没有 choices 字段时应返回空 content"""
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"model": "test", "usage": {}}

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result["content"] == ""

    @pytest.mark.asyncio
    async def test_chat_text_fallback_in_choices(self):
        """choices[0].message.content 为空时回退到 .text"""
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"text": "fallback text"}],
            "usage": {},
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result["content"] == "fallback text"

    @pytest.mark.asyncio
    async def test_embed_success(self):
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            vec = await client.embed("hello")

        assert vec == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_http_error_raises(self):
        client = RealLLMClient(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            with pytest.raises(RuntimeError, match="Embedding 失败"):
                await client.embed("hello")


# ============================================================
# Real ChEMBL 客户端
# ============================================================

class TestRealChemblClient:
    @pytest.mark.asyncio
    async def test_find_target_chembl_id_match(self):
        """pref_name 包含 gene_symbol 时直接返回"""
        client = RealChemblClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "targets": [
                {"target_chembl_id": "CHEMBL203", "pref_name": "Epidermal growth factor receptor"},
                {"target_chembl_id": "CHEMBL999", "pref_name": "Other"},
            ]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client._find_target_chembl_id("EGFR")

        assert result == "CHEMBL203"

    @pytest.mark.asyncio
    async def test_find_target_chembl_id_fallback_first(self):
        """无精确匹配时返回第一个结果"""
        client = RealChemblClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "targets": [
                {"target_chembl_id": "CHEMBL_FOO", "pref_name": "Unknown protein"},
            ]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client._find_target_chembl_id("EGFR")

        assert result == "CHEMBL_FOO"

    @pytest.mark.asyncio
    async def test_find_target_chembl_id_no_targets(self):
        client = RealChemblClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"targets": []}

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client._find_target_chembl_id("UNKNOWN")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_molecules_no_target(self):
        """找不到 target 时返回空列表"""
        client = RealChemblClient()

        with patch.object(client, "_find_target_chembl_id", new=AsyncMock(return_value=None)):
            result = await client.get_active_molecules("UNKNOWN")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_molecules_success(self):
        client = RealChemblClient()

        target_resp = MagicMock()
        target_resp.status_code = 200
        target_resp.raise_for_status = MagicMock()
        target_resp.json.return_value = {
            "targets": [
                {"target_chembl_id": "CHEMBL203", "pref_name": "Epidermal growth factor receptor"}
            ]
        }

        activity_resp = MagicMock()
        activity_resp.status_code = 200
        activity_resp.raise_for_status = MagicMock()
        activity_resp.json.return_value = {
            "activities": [
                {
                    "molecule_chembl_id": "CHEMBL123",
                    "molecule_pref_name": "Test Drug",
                    "activity_type": "IC50",
                    "standard_value": 12.5,
                    "standard_units": "nM",
                    "assay_type": "B",
                    "assay_description": "test assay",
                    "max_phase": 4,
                }
            ]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(side_effect=[target_resp, activity_resp])

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.get_active_molecules("EGFR")

        assert len(result) == 1
        assert result[0]["name"] == "Test Drug"
        assert result[0]["chembl_id"] == "CHEMBL123"
        assert result[0]["activity"]["activity_value"] == 12.5
        assert result[0]["target_gene"] == "EGFR"

    @pytest.mark.asyncio
    async def test_find_approved_drugs_no_target(self):
        client = RealChemblClient()
        with patch.object(client, "_find_target_chembl_id", new=AsyncMock(return_value=None)):
            result = await client.find_approved_drugs("UNKNOWN")
        assert result == []

    @pytest.mark.asyncio
    async def test_find_approved_drugs_success(self):
        client = RealChemblClient()

        target_resp = MagicMock()
        target_resp.status_code = 200
        target_resp.raise_for_status = MagicMock()
        target_resp.json.return_value = {
            "targets": [{"target_chembl_id": "CHEMBL203", "pref_name": "EGFR"}]
        }

        indication_resp = MagicMock()
        indication_resp.status_code = 200
        indication_resp.raise_for_status = MagicMock()
        indication_resp.json.return_value = {
            "drug_indications": [
                {
                    "molecule_chembl_id": "CHEMBL123",
                    "mesh_heading": "Lung Cancer",
                    "efo_term": "Carcinoma",
                    "max_phase_for_ind": 4,
                }
            ]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(side_effect=[target_resp, indication_resp])

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.find_approved_drugs("EGFR")

        assert len(result) == 1
        assert result[0]["chembl_id"] == "CHEMBL123"
        assert result[0]["indication"] == "Lung Cancer"
        assert result[0]["max_phase"] == 4


# ============================================================
# Real MyGene 客户端
# ============================================================

class TestRealGeneClient:
    @pytest.mark.asyncio
    async def test_query_success(self):
        client = RealGeneClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "hits": [{
                "symbol": "EGFR",
                "name": "Epidermal Growth Factor Receptor",
                "entrezgene": 1956,
                "ensembl": {"gene": "ENSG00000146648"},
                "uniprot": {"Swiss-Prot": "P00533"},
                "hgnc": "HGNC:3236",
                "type_of_gene": "protein_coding",
                "location": {"chr": "7", "start": 55019021, "end": 55211628},
                "summary": "EGFR receptor tyrosine kinase",
                "pathway": [{"id": "hsa04010", "name": "MAPK signaling"}],
                "alias": ["ERBB1", "HER1"],
            }]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query("EGFR")

        assert result["symbol"] == "EGFR"
        assert result["entrez_id"] == 1956
        assert result["ensembl_id"] == "ENSG00000146648"
        assert result["uniprot_id"] == "P00533"
        assert len(result["pathways"]) == 1
        assert result["pathways"][0]["source"] == "KEGG"
        assert result["synonyms"] == ["ERBB1", "HER1"]
        assert result["source"] == "mygene.info"

    @pytest.mark.asyncio
    async def test_query_no_hits(self):
        client = RealGeneClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"hits": []}

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query("UNKNOWNGENE")

        assert result["symbol"] == "UNKNOWNGENE"
        assert result["entrez_id"] is None
        assert result["note"] == "not_found"
        assert "未找到" in result["summary"]

    @pytest.mark.asyncio
    async def test_query_pathway_dict_format(self):
        """pathway 字段为 dict 时应转为 list"""
        client = RealGeneClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "hits": [{
                "symbol": "EGFR",
                "name": "EGFR",
                "pathway": {"id": "R-HSA-123", "name": "Reactome pathway"},
            }]
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query("EGFR")

        assert len(result["pathways"]) == 1
        assert result["pathways"][0]["source"] == "Reactome"


# ============================================================
# Real MyVariant 客户端
# ============================================================

class TestRealVariantClient:
    @pytest.mark.asyncio
    async def test_query_batch_empty(self):
        client = RealVariantClient()
        result = await client.query_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_query_batch_success(self):
        client = RealVariantClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [{
            "query": "chr7:55259515:T>A",
            "gene": "EGFR",
            "hgvs": {"p": "p.Thr790Met", "c": "c.2369C>T"},
            "clinvar": {
                "clnsig": "Pathogenic",
                "clinvar_id": "VCV000033373",
                "rcv": "RCV000029669",
                "review_status": "expert panel",
                "clndn": "Drug response",
                "last_evaluated": "2024-01-15",
            },
            "cosmic": {
                "cosmic_id": "COSM6224",
                "primary_site": "lung",
                "tumor_site": "lung",
                "mutation_description": "EGFR T790M",
                "occurrence_count": 1823,
            },
            "dbsnp": {"rsid": "rs121434564", "merged_into": None},
            "gnomad_genome": {
                "af": 0.00002,
                "ac": 5,
                "an": 251492,
                "afes_afr": 0.0,
                "afes_amr": 0.0,
                "afes_eas": 0.0001,
                "afes_nfe": 0.00001,
            },
            "ann": {"consequence": "missense_variant", "gene": "EGFR"},
        }]

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query_batch(["chr7:55259515:T>A"])

        assert len(result) == 1
        r = result[0]
        assert r["gene"] == "EGFR"
        assert r["hgvs_p"] == "p.Thr790Met"
        assert r["clinvar"]["clnsig"] == "Pathogenic"
        assert r["cosmic"]["cosmic_id"] == "COSM6224"
        assert r["dbsnp"]["rsid"] == "rs121434564"
        assert r["gnomad"]["af"] == 0.00002
        assert r["gnomad"]["populations"]["eur"] == 0.00001
        assert r["functional_consequence"] == "missense_variant"
        assert r["source"] == "myvariant.info"

    @pytest.mark.asyncio
    async def test_query_batch_dict_response(self):
        """API 返回 dict 而非 list 时应自动包装"""
        client = RealVariantClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "query": "chr1:1:A>T",
            "gene": "GENE",
        }

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query_batch(["chr1:1:A>T"])

        assert len(result) == 1
        assert result[0]["gene"] == "GENE"

    @pytest.mark.asyncio
    async def test_query_batch_with_missing_fields(self):
        """字段缺失时应安全返回 None"""
        client = RealVariantClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [{"query": "chr1:1:A>T"}]

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            result = await client.query_batch(["chr1:1:A>T"])

        assert result[0]["gene"] is None
        assert result[0]["clinvar"] is None
        assert result[0]["cosmic"] is None
        assert result[0]["dbsnp"] is None
        assert result[0]["gnomad"] is None


# ============================================================
# Real DiffDock 客户端
# ============================================================

class TestRealDiffdockClient:
    @pytest.mark.asyncio
    async def test_dock_missing_api_key_raises(self):
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = ""
            mock_settings.DIFFDOCK_NIM_URL = "https://example.com"
            client = RealDiffdockClient()
            with pytest.raises(RuntimeError, match="NVIDIA_NIM_API_KEY"):
                await client.dock("protein", "ligand", 1)

    @pytest.mark.asyncio
    async def test_dock_sync_response(self):
        """同步返回结果（无 job_id）"""
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"

            client = RealDiffdockClient()

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "poses": [
                    {
                        "rank": 1,
                        "confidence": 0.85,
                        "positions": [1.0, 2.0, 3.0],
                        "scores": [0.9],
                        "ligand_smiles": "CCO",
                    }
                ]
            }

            mock_async_client = MagicMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_async_client.post = AsyncMock(return_value=mock_response)

            with patch("httpx.AsyncClient", return_value=mock_async_client):
                result = await client.dock("protein", "CCO", num_poses=1)

        assert result["status"] == "completed"
        assert result["num_poses"] == 1
        assert result["mock"] is False
        assert result["poses"][0]["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_dock_async_polling_completed(self):
        """异步轮询模式 — 第一次返回 job_id，第二次返回 completed"""
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"

            client = RealDiffdockClient()

            submit_resp = MagicMock()
            submit_resp.status_code = 200
            submit_resp.raise_for_status = MagicMock()
            submit_resp.json.return_value = {"job_id": "job-123"}

            poll_resp = MagicMock()
            poll_resp.status_code = 200
            poll_resp.raise_for_status = MagicMock()
            poll_resp.json.return_value = {
                "status": "completed",
                "id": "job-123",
                "poses": [
                    {"confidence": 0.9, "positions": [1.0, 2.0, 3.0]}
                ],
            }

            mock_async_client = MagicMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_async_client.post = AsyncMock(return_value=submit_resp)
            mock_async_client.get = AsyncMock(return_value=poll_resp)

            with patch("httpx.AsyncClient", return_value=mock_async_client), \
                 patch("asyncio.sleep", new=AsyncMock()):
                result = await client.dock("protein", "CCO", num_poses=1)

        assert result["status"] == "completed"
        assert result["job_id"] == "job-123"

    @pytest.mark.asyncio
    async def test_dock_async_polling_failed(self):
        """异步轮询模式 — 任务失败"""
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"

            client = RealDiffdockClient()

            submit_resp = MagicMock()
            submit_resp.status_code = 200
            submit_resp.raise_for_status = MagicMock()
            submit_resp.json.return_value = {"job_id": "job-fail"}

            poll_resp = MagicMock()
            poll_resp.status_code = 200
            poll_resp.raise_for_status = MagicMock()
            poll_resp.json.return_value = {
                "status": "failed",
                "error": "GPU OOM",
            }

            mock_async_client = MagicMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_async_client.post = AsyncMock(return_value=submit_resp)
            mock_async_client.get = AsyncMock(return_value=poll_resp)

            with patch("httpx.AsyncClient", return_value=mock_async_client), \
                 patch("asyncio.sleep", new=AsyncMock()):
                result = await client.dock("protein", "CCO", num_poses=1)

        assert result["status"] == "failed"
        assert "GPU OOM" in result["error"]

    def test_parse_response_empty(self):
        """_parse_response 处理空 poses"""
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"
            client = RealDiffdockClient()
            result = client._parse_response({}, "protein", "CCO", 5)

        assert result["status"] == "completed"
        assert result["num_poses"] == 0
        assert result["best_confidence"] == 0.0

    def test_parse_response_with_poses(self):
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"
            client = RealDiffdockClient()

            data = {
                "id": "job-1",
                "poses": [
                    {"rank": 2, "confidence": 0.5, "positions": [1, 2, 3, 4, 5, 6]},
                    {"rank": 1, "confidence": 0.9, "positions": [7, 8, 9]},
                ],
            }
            result = client._parse_response(data, "protein", "CCO", 2)

        assert len(result["poses"]) == 2
        # 排序后最高 confidence 应排第一
        assert result["poses"][0]["confidence"] == 0.9
        assert result["poses"][0]["rank"] == 1
        assert result["best_confidence"] == 0.9
        assert result["job_id"] == "job-1"

    def test_parse_response_results_field(self):
        """data['results'] 字段也可作为 poses 来源"""
        with patch("app.clients.real.diffdock_real.settings") as mock_settings:
            mock_settings.NVIDIA_NIM_API_KEY = "test-key"
            mock_settings.DIFFDOCK_NIM_URL = "https://nim.example.com/diffdock"
            client = RealDiffdockClient()

            data = {
                "results": [
                    {"confidence": 0.7, "coords": [1.0, 2.0, 3.0]}
                ]
            }
            result = client._parse_response(data, "P", "C", 1)

        assert len(result["poses"]) == 1
        assert result["poses"][0]["confidence"] == 0.7
        assert result["poses"][0]["positions"] == [1.0, 2.0, 3.0]
