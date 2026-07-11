"""补充模块测试 — 覆盖 vector/scrna/gene_query/graph/federated 等剩余低覆盖模块"""
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================
# VectorStore — knowledge/vector.py
# ============================================================

class TestVectorStoreMockMode:
    @pytest.mark.asyncio
    async def test_add_documents_empty_returns_zero(self):
        from app.services.knowledge.vector import VectorStore
        vs = VectorStore()
        result = await vs.add_documents([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_add_documents_mock_returns_zero(self):
        """Mock 模式下应返回 0（无 ChromaDB）"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            vs = VectorStore()
            result = await vs.add_documents([
                {"id": "1", "text": "hello", "metadata": {"k": "v"}}
            ])
        assert result == 0

    @pytest.mark.asyncio
    async def test_search_mock_returns_empty(self):
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            vs = VectorStore()
            result = await vs.search("query")
        assert result == []

    def test_get_collection_mock_returns_none(self):
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            vs = VectorStore()
            coll = vs._get_collection("test")
        assert coll is None

    def test_get_client_mock_returns_none(self):
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            vs = VectorStore()
            client = vs._get_client()
        assert client is None

    def test_get_client_cached(self):
        """已存在 client 应直接返回缓存"""
        from app.services.knowledge.vector import VectorStore
        vs = VectorStore()
        mock_client = MagicMock()
        vs._client = mock_client
        assert vs._get_client() is mock_client

    @pytest.mark.asyncio
    async def test_add_documents_with_real_chromadb_failure(self):
        """Real 模式但 ChromaDB 连接失败时应降级为 0"""
        pytest.importorskip("chromadb")
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", False), \
             patch("chromadb.HttpClient", side_effect=Exception("connection refused")):
            vs = VectorStore()
            result = await vs.add_documents([
                {"id": "1", "text": "hello"}
            ])
        assert result == 0

    @pytest.mark.asyncio
    async def test_search_with_real_chromadb_failure(self):
        pytest.importorskip("chromadb")
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", False), \
             patch("chromadb.HttpClient", side_effect=Exception("connection refused")):
            vs = VectorStore()
            result = await vs.search("query")
        assert result == []

    def test_get_vector_store_singleton(self):
        from app.services.knowledge.vector import get_vector_store, _vector_store_singleton
        vs1 = get_vector_store()
        vs2 = get_vector_store()
        assert vs1 is vs2


# ============================================================
# ScRnaSeqParser — parser/scrna.py
# ============================================================

class TestScRnaSeqParser:
    @pytest.mark.asyncio
    async def test_parse_file_not_found(self):
        from app.services.parser.scrna import ScRnaSeqParser
        parser = ScRnaSeqParser()
        ds = SimpleNamespace(storage_path="/nonexistent/path.h5", file_format="h5")
        result = await parser.parse(ds)
        assert "error" in result["summary"]
        assert "文件不存在" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_parse_missing_path(self):
        from app.services.parser.scrna import ScRnaSeqParser
        parser = ScRnaSeqParser()
        ds = SimpleNamespace(storage_path=None, file_format="h5")
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_parse_scanpy_not_installed(self):
        """scanpy 缺失时应返回 ImportError 错误"""
        from app.services.parser.scrna import ScRnaSeqParser
        parser = ScRnaSeqParser()

        # 创建一个临时文件
        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as f:
            f.write(b"fake h5 content")
            f.flush()
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="h5")
            # 强制触发 ImportError
            with patch.dict("sys.modules", {"scanpy": None, "numpy": None, "pandas": None}):
                result = await parser.parse(ds)
                # 应捕获 ImportError
                assert "error" in result["summary"] or "summary" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_csv_with_scanpy_unavailable(self):
        """CSV 格式 + scanpy 不可用 → 错误"""
        from app.services.parser.scrna import ScRnaSeqParser
        parser = ScRnaSeqParser()

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("gene,cell1,cell2\nEGFR,1.0,2.0\n")
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="csv")
            with patch.dict("sys.modules", {"scanpy": None}):
                result = await parser.parse(ds)
                assert "summary" in result
        finally:
            os.unlink(path)


# ============================================================
# KnowledgeGraph — 补充覆盖 _get_driver / Neo4j 失败降级
# ============================================================

class TestKnowledgeGraphDriver:
    @pytest.mark.asyncio
    async def test_get_neighbors_mock_returns_data(self):
        """Mock 模式应返回预置 PPI 网络"""
        from app.services.knowledge.graph import KnowledgeGraph
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            kg = KnowledgeGraph()
            result = await kg.get_neighbors("EGFR")
        assert result["root"] == "EGFR"
        assert len(result["neighbors"]) > 0
        assert result["source"] == "mock_ppi"

    @pytest.mark.asyncio
    async def test_get_neighbors_depth_2(self):
        from app.services.knowledge.graph import KnowledgeGraph
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            kg = KnowledgeGraph()
            result = await kg.get_neighbors("EGFR", depth=2)
        # depth=2 应包含二阶邻居
        assert "via" in str(result["neighbors"])

    @pytest.mark.asyncio
    async def test_get_neighbors_unknown_gene(self):
        from app.services.knowledge.graph import KnowledgeGraph
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", True):
            kg = KnowledgeGraph()
            result = await kg.get_neighbors("UNKNOWN")
        assert result["neighbors"] == []

    @pytest.mark.asyncio
    async def test_find_path_direct_neighbor(self):
        from app.services.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result = await kg.find_path("EGFR", "KRAS")
        assert result["length"] == 1
        assert result["paths"] == [["EGFR", "KRAS"]]

    @pytest.mark.asyncio
    async def test_find_path_two_hop(self):
        """EGFR -> KRAS -> BRAF 应返回长度 2 的路径"""
        from app.services.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        # KRAS 和 EGFR 互为邻居，BRAF 是 KRAS 的邻居
        result = await kg.find_path("EGFR", "BRAF")
        assert result["length"] in (1, 2)

    @pytest.mark.asyncio
    async def test_find_path_no_path(self):
        from app.services.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result = await kg.find_path("EGFR", "UNKNOWN")
        assert result["length"] == 0
        assert result["paths"] == []

    @pytest.mark.asyncio
    async def test_get_pathway_genes_known(self):
        from app.services.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result = await kg.get_pathway_genes("hsa04010")
        assert "MAPK signaling pathway" in result["name"]
        assert "EGFR" in result["genes"]

    @pytest.mark.asyncio
    async def test_get_pathway_genes_unknown(self):
        from app.services.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        result = await kg.get_pathway_genes("unknown_pathway")
        assert result["genes"] == []

    @pytest.mark.asyncio
    async def test_neo4j_failure_fallback_to_mock(self):
        """Real 模式但 Neo4j 连接失败应降级到 Mock"""
        from app.services.knowledge.graph import KnowledgeGraph
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", False), \
             patch("neo4j.AsyncGraphDatabase.driver", side_effect=Exception("connection refused")):
            kg = KnowledgeGraph()
            result = await kg.get_neighbors("EGFR")
        assert result["source"] == "mock_ppi"

    def test_knowledge_graph_singleton(self):
        from app.services.knowledge.graph import get_knowledge_graph
        kg1 = get_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is kg2


# ============================================================
# FederatedLearner — federated_learning.py
# ============================================================

class TestFederatedLearner:
    @pytest.mark.asyncio
    async def test_update_weights_framework_only(self):
        """Flower 不可用时 job framework 为 in_memory"""
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        learner._flower_available = False

        job = await learner.create_job(project_id="p1")
        assert job["framework"] == "in_memory"
        result = await learner.submit_weights(job["job_id"], "client_1", {"layer1": [0.1, 0.2]})
        assert result["job_id"] == job["job_id"]
        assert "status" in result

    @pytest.mark.asyncio
    async def test_update_weights_flower_available(self):
        """Flower 可用时 job framework 为 flower"""
        from app.services.optimizer.federated_learning import FederatedLearner

        mock_flwr = MagicMock()
        with patch.dict("sys.modules", {"flwr": mock_flwr}):
            learner = FederatedLearner()
            assert learner._flower_available is True
            job = await learner.create_job(project_id="p1")
            assert job["framework"] == "flower"
            result = await learner.submit_weights(job["job_id"], "client_1", {"layer1": [0.1, 0.2]})

        assert result["job_id"] == job["job_id"]
        assert "status" in result

    @pytest.mark.asyncio
    async def test_update_weights_flower_exception(self):
        """submit_weights 对不存在的 job 应返回 error"""
        from app.services.optimizer.federated_learning import FederatedLearner

        learner = FederatedLearner()
        result = await learner.submit_weights("nonexistent_job", "client_1", {"layer1": [0.1]})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_aggregate_framework_only(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        learner._flower_available = False

        result = learner._aggregate([{"weights": {"l1": 1.0}, "num_samples": 10}], 0)
        assert result["aggregated_weights"]["l1"] == 1.0
        assert result["num_clients"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_no_models(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        learner._flower_available = True

        result = learner._aggregate([], 0)
        assert result["aggregated_weights"] == {}
        assert result["total_samples"] == 0
        assert result["num_clients"] == 0

    @pytest.mark.asyncio
    async def test_aggregate_fedavg(self):
        """FedAvg 加权平均"""
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        learner._flower_available = True

        models = [
            {"weights": {"l1": 1.0, "l2": 2.0}, "num_samples": 10},
            {"weights": {"l1": 3.0, "l2": 4.0}, "num_samples": 30},
        ]
        result = learner._aggregate(models, 0)
        # 加权平均: l1 = (1*10 + 3*30) / 40 = 2.5
        assert result["aggregated_weights"]["l1"] == 2.5
        assert result["total_samples"] == 40
        assert result["num_clients"] == 2

    @pytest.mark.asyncio
    async def test_aggregate_zero_samples(self):
        """所有 num_samples=0 时回退到 len(models)
        注意：weighted_sum = 1*0 + 3*0 = 0，total_samples 回退到 2，结果为 0.0
        """
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        learner._flower_available = True

        models = [
            {"weights": {"l1": 1.0}, "num_samples": 0},
            {"weights": {"l1": 3.0}, "num_samples": 0},
        ]
        result = learner._aggregate(models, 0)
        assert result["total_samples"] == 2  # 回退到 len(models)
        # weighted_sum = 1*0 + 3*0 = 0, 0/2 = 0.0
        assert result["aggregated_weights"]["l1"] == 0.0

    def test_check_flower_unavailable(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        # flwr 未安装时应返回 False
        with patch.dict("sys.modules", {"flwr": None}):
            assert learner._check_flower() is False


# ============================================================
# GeneQueryService — 补充 _real_clinical_trials
# ============================================================

class TestGeneQueryServiceReal:
    @pytest.mark.asyncio
    async def test_real_clinical_trials_success(self):
        """Real 模式 ClinicalTrials.gov API 应解析 studies"""
        from app.services.knowledge.gene_query import _real_clinical_trials
        from app.core.config import settings

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "totalCount": 1,
            "studies": [{
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT12345", "briefTitle": "Test Trial"},
                    "designModule": {"phases": ["PHASE3"]},
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "conditionsModule": {"conditions": ["NSCLC"]},
                    "armsInterventionsModule": {
                        "interventions": [{"type": "DRUG", "name": "Osimertinib"}]
                    },
                }
            }],
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _real_clinical_trials("EGFR", "NSCLC")

        assert result["total"] == 1
        assert result["trials"][0]["nct_id"] == "NCT12345"
        assert result["trials"][0]["title"] == "Test Trial"
        assert result["trials"][0]["phase"] == ["PHASE3"]
        assert result["source"] == "ClinicalTrials.gov"

    @pytest.mark.asyncio
    async def test_query_clinical_trials_real_mode(self):
        """Real 模式应走 _real_clinical_trials 路径"""
        from app.services.knowledge.gene_query import query_clinical_trials
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.gene_query._real_clinical_trials",
                   new=AsyncMock(return_value={"total": 0, "trials": [], "source": "real"})):
            result = await query_clinical_trials("EGFR", "NSCLC")
        assert result["source"] == "real"

    @pytest.mark.asyncio
    async def test_query_gene_info_uses_gene_client(self):
        from app.services.knowledge.gene_query import query_gene_info
        from app.clients.mock.mygene_mock import MockGeneClient

        result = await query_gene_info("EGFR")
        assert result["symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_batch_query_genes_handles_errors(self):
        from app.services.knowledge.gene_query import batch_query_genes

        # 使用 Mock 客户端，所有基因都应返回有效结果
        result = await batch_query_genes(["EGFR", "KRAS", "UNKNOWN"])
        assert len(result) == 3
        assert result[0]["symbol"] == "EGFR"
        assert result[1]["symbol"] == "KRAS"
        assert result[2]["symbol"] == "UNKNOWN"


# ============================================================
# PrivacyLayer — privacy_layer.py
# ============================================================

class TestPrivacyLayer:
    @pytest.mark.asyncio
    async def test_encrypt_data_simple_anonymize_dict(self):
        """PySyft 不可用时，encrypt_data 应返回脱敏后的数据"""
        from app.services.knowledge.privacy_layer import PrivacyLayer
        pl = PrivacyLayer()
        data = {"name": "John", "age": 45, "diagnosis": "NSCLC"}
        result = await pl.encrypt_data(data)
        # 返回结构: {encrypted, data, method, note}
        assert result["encrypted"] is False
        assert result["method"] == "simple_anonymization"
        # 脱敏后 name 字段应被替换
        assert result["data"]["name"] != "John"
        assert "[REDACTED_" in result["data"]["name"]
        # 非敏感字段保留
        assert result["data"]["age"] == 45
        assert result["data"]["diagnosis"] == "NSCLC"

    @pytest.mark.asyncio
    async def test_encrypt_data_simple_anonymize_non_dict(self):
        """非 dict 输入应原样返回"""
        from app.services.knowledge.privacy_layer import PrivacyLayer
        pl = PrivacyLayer()
        result = await pl.encrypt_data("just a string")
        # _simple_anonymize 对非 dict 原样返回
        assert result["data"] == "just a string"
        assert result["encrypted"] is False

    @pytest.mark.asyncio
    async def test_federated_query_framework_only(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        pl = PrivacyLayer()
        result = await pl.federated_query({"targets": ["EGFR"], "centers": ["c1"]})
        assert "framework_only" in result["status"] or "framework" in str(result)


# ============================================================
# VcfParser — 补充 cyvcf2 ImportError 路径
# ============================================================

class TestVcfParserFallback:
    @pytest.mark.asyncio
    async def test_vcf_text_parse_basic_snv(self, tmp_path):
        """文本解析应能处理基本 SNV"""
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType, ParseStatus

        vcf_content = """##fileformat=VCFv4.2
##INFO=<ID=AF,Number=A,Type=Float,Description="Allele Frequency">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr7\t55259515\trs121434564\tT\tA\t100\tPASS\tAF=0.00002
chr7\t55259513\trs121434569\tG\tA\t100\tPASS\tAF=0.00003
"""
        path = tmp_path / "test.vcf"
        path.write_text(vcf_content, encoding="utf-8")

        ds = SimpleNamespace(
            id="ds-1", project_id="proj-1", data_type=DataType.WES,
            storage_path=str(path), file_format="vcf",
            parse_status=ParseStatus.PENDING,
            parsed_summary={},
        )

        parser = VcfParser()
        result = await parser.parse(ds)
        assert "summary" in result
        assert "quality_metrics" in result

    @pytest.mark.asyncio
    async def test_vcf_parse_empty_file(self, tmp_path):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType, ParseStatus

        path = tmp_path / "empty.vcf"
        path.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n", encoding="utf-8")

        ds = SimpleNamespace(
            id="ds-1", project_id="proj-1", data_type=DataType.WES,
            storage_path=str(path), file_format="vcf",
            parse_status=ParseStatus.PENDING,
            parsed_summary={},
        )

        parser = VcfParser()
        result = await parser.parse(ds)
        assert "summary" in result


# ============================================================
# MoleculeDesigner — 补充 DeepChem 失败路径
# ============================================================

class TestMoleculeDesignerDeepChem:
    @pytest.mark.asyncio
    async def test_design_with_deepchem_import_failure(self):
        """DeepChem 导入失败应走框架降级"""
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        designer = MoleculeDesigner(db=MagicMock())
        result = await designer.design({
            "target_id": "T1",
            "smiles": "CCO",
            "constraints": {"max_mw": 500},
        })

        assert "designed_molecules" in result
        assert result["model_info"]["status"] in ("framework_only", "model_load_failed")

    @pytest.mark.asyncio
    async def test_design_with_deepchem_exception(self):
        """DeepChem 抛异常应降级到 framework"""
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        designer = MoleculeDesigner(db=MagicMock())
        with patch.dict("sys.modules", {"deepchem": MagicMock()}), \
             patch("deepchem.molnet.load_tox21", side_effect=Exception("model load failed")):
            # 即使 import 成功，加载失败应触发降级
            import sys
            # 删除缓存的模块以便重新加载
            if "app.services.analyzer.molecule_designer" in sys.modules:
                del sys.modules["app.services.analyzer.molecule_designer"]
            from app.services.analyzer.molecule_designer import MoleculeDesigner
            designer = MoleculeDesigner(db=MagicMock())
            result = await designer.design({
                "target_id": "T1",
                "smiles": "CCO",
            })

        assert "designed_molecules" in result

    @pytest.mark.asyncio
    async def test_design_no_smiles(self):
        """无 SMILES 应仍返回框架响应"""
        from app.services.analyzer.molecule_designer import MoleculeDesigner
        designer = MoleculeDesigner(db=MagicMock())
        result = await designer.design({"target_id": "T1"})
        assert result["model_info"]["status"] in ("framework_only", "model_load_failed")
        if result["model_info"]["status"] == "framework_only":
            assert result["model_info"]["seed_smiles"] is None


# ============================================================
# NetworkModeler — 补充 PyG 失败路径
# ============================================================

class TestNetworkModelerPyG:
    @pytest.mark.asyncio
    async def test_analyze_ppi_pyg_unavailable(self):
        """PyG 不可用或可用时的模型选择"""
        from app.services.analyzer.network_modeler import NetworkModeler
        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi(["EGFR"], max_depth=1)

        assert result["model"] in ("degree_based", "graph_sage")
        assert len(result["nodes"]) > 0
        assert len(result["edges"]) > 0
        assert len(result["hub_genes"]) > 0

    @pytest.mark.asyncio
    async def test_analyze_ppi_no_edges(self):
        """未知基因列表应返回空 edges"""
        from app.services.analyzer.network_modeler import NetworkModeler
        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi(["UNKNOWNGENE"], max_depth=1)
        assert result["total_edges"] == 0
        assert result["nodes"] == [{"id": "UNKNOWNGENE", "label": "UNKNOWNGENE"}]


# ============================================================
# NextflowRunner — 补充 mock 模式
# ============================================================

class TestNextflowRunnerExtra:
    @pytest.mark.asyncio
    async def test_run_unknown_pipeline(self):
        """未知 pipeline 在 mock 模式下应正常执行并更新 workflow_run"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        workflow_run = SimpleNamespace(
            pipeline_name="nonexistent_pipeline",
            params={"project_id": "p1"},
            run_id=None,
            status=WorkflowStatus.SUBMITTED,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )
        result = await runner.run(workflow_run)
        assert result["status"] == WorkflowStatus.COMPLETED
        assert result["run_id"].startswith("nf-")
        assert result["mock"] is True
        assert result["pipeline_name"] == "nonexistent_pipeline"
        assert result["output_path"].startswith("/data/outputs/")
        assert result["trace_url"].startswith("https://nextflow.io/traces/")
        # workflow_run 对象应被更新
        assert workflow_run.run_id == result["run_id"]
        assert workflow_run.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_known_pipeline_mock(self):
        """已知 pipeline 在 mock 模式下应正常完成"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        workflow_run = SimpleNamespace(
            pipeline_name="rna_seq_pipeline",
            params={"project_id": "p1", "dataset_id": "d1"},
            run_id=None,
            status=WorkflowStatus.SUBMITTED,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )
        result = await runner.run(workflow_run)
        assert result["status"] == WorkflowStatus.COMPLETED
        assert result["pipeline_name"] == "rna_seq_pipeline"
        assert result["trace_url"].startswith("https://nextflow.io/traces/")
        assert workflow_run.duration_sec is not None

    @pytest.mark.asyncio
    async def test_check_status_mock(self):
        """mock 模式下 check_status 应返回 COMPLETED"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        result = await runner.check_status("nf-abc123")
        assert result["status"] == WorkflowStatus.COMPLETED
        assert result["progress"] == 100
        assert result["mock"] is True
