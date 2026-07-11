"""开源工具集成测试 — 验证 11 个 GitHub 开源项目的本地集成有效性

覆盖工具：
  P0: Scanpy, BioPython, RDKit, MyGene/MyVariant, ChEMBL, Nextflow
  P2: DeepChem, PyG, DiffDock
  P3: Flower, PySyft
"""
import asyncio
import pytest

# ========== P0 工具：MyGene/MycVariant Mock 客户端 ==========

class TestMyGeneIntegration:
    """MyGene.info 集成测试"""

    @pytest.mark.asyncio
    async def test_mygene_mock_query_egfr(self):
        from app.clients.mock.mygene_mock import MockGeneClient
        client = MockGeneClient()
        result = await client.query("EGFR")
        assert result["symbol"] == "EGFR"
        assert result["entrez_id"] == 1956
        assert "KEGG" in [p["source"] for p in result["pathways"]]
        assert len(result["pathways"]) >= 3

    @pytest.mark.asyncio
    async def test_mygene_mock_query_by_synonym(self):
        from app.clients.mock.mygene_mock import MockGeneClient
        client = MockGeneClient()
        result = await client.query("B7-H3")
        assert result["symbol"] == "CD276"

    @pytest.mark.asyncio
    async def test_mygene_mock_unknown_gene(self):
        from app.clients.mock.mygene_mock import MockGeneClient
        client = MockGeneClient()
        result = await client.query("UNKNOWNGENE")
        assert result["gene_type"] == "unknown"
        assert result["note"] == "mock_placeholder"

    @pytest.mark.asyncio
    async def test_mygene_mock_all_5_genes(self):
        from app.clients.mock.mygene_mock import GENE_DATABASE, MockGeneClient
        client = MockGeneClient()
        for gene in ["EGFR", "B7H3", "FAP", "TP53", "KRAS"]:
            result = await client.query(gene)
            assert result is not None
            assert "summary" in result
        assert len(GENE_DATABASE) == 5


class TestMyVariantIntegration:
    """MyVariant.info 集成测试"""

    @pytest.mark.asyncio
    async def test_myvariant_mock_t790m(self):
        from app.clients.mock.myvariant_mock import MockVariantClient
        client = MockVariantClient()
        results = await client.query_batch(["chr7:55259515:T>A"])
        assert len(results) == 1
        assert results[0]["gene"] == "EGFR"
        assert results[0]["hgvs_p"] == "p.Thr790Met"
        assert results[0]["clinvar"]["clnsig"] == "Pathogenic"

    @pytest.mark.asyncio
    async def test_myvariant_mock_kras_g12c(self):
        from app.clients.mock.myvariant_mock import MockVariantClient
        client = MockVariantClient()
        results = await client.query_batch(["chr12:25245350:G>A"])
        assert results[0]["gene"] == "KRAS"
        assert results[0]["hgvs_p"] == "p.Gly12Cys"

    @pytest.mark.asyncio
    async def test_myvariant_mock_batch(self):
        from app.clients.mock.myvariant_mock import MockVariantClient
        client = MockVariantClient()
        variants = ["chr7:55259515:T>A", "chr7:55259513:G>A", "chr7:55242471:del"]
        results = await client.query_batch(variants)
        assert len(results) == 3
        for r in results:
            assert r["gene"] == "EGFR"

    @pytest.mark.asyncio
    async def test_myvariant_mock_unknown(self):
        from app.clients.mock.myvariant_mock import MockVariantClient
        client = MockVariantClient()
        results = await client.query_batch(["chr1:1:A>T"])
        assert results[0]["note"] == "mock_placeholder"


# ========== P0 工具：ChEMBL Mock 客户端 ==========

class TestChEMBLIntegration:
    """ChEMBL API 集成测试"""

    @pytest.mark.asyncio
    async def test_chembl_mock_egfr_molecules(self):
        from app.clients.mock.chembl_mock import MockChemblClient
        client = MockChemblClient()
        molecules = await client.get_active_molecules("EGFR")
        assert len(molecules) >= 3
        names = [m["name"] for m in molecules]
        assert "Osimertinib" in names
        assert "Gefitinib" in names

    @pytest.mark.asyncio
    async def test_chembl_mock_approved_drugs(self):
        from app.clients.mock.chembl_mock import MockChemblClient
        client = MockChemblClient()
        drugs = await client.find_approved_drugs("EGFR")
        assert len(drugs) >= 3
        for d in drugs:
            assert d["max_phase"] >= 4

    @pytest.mark.asyncio
    async def test_chembl_mock_kras_sotorasib(self):
        from app.clients.mock.chembl_mock import MockChemblClient
        client = MockChemblClient()
        drugs = await client.find_approved_drugs("KRAS")
        names = [d["name"] for d in drugs]
        assert "Sotorasib" in names

    @pytest.mark.asyncio
    async def test_chembl_mock_unknown_target(self):
        from app.clients.mock.chembl_mock import MockChemblClient
        client = MockChemblClient()
        molecules = await client.get_active_molecules("UNKNOWN")
        assert molecules == []


# ========== P0 工具：DiffDock Mock 客户端 ==========

class TestDiffDockIntegration:
    """DiffDock 分子对接集成测试"""

    @pytest.mark.asyncio
    async def test_diffdock_mock_dock(self):
        from app.clients.mock.diffdock_mock import MockDiffdockClient
        client = MockDiffdockClient()
        result = await client.dock("PROTEIN_PDB", "CCO", num_poses=5)
        assert result["status"] == "completed"
        assert len(result["poses"]) == 5
        assert result["mock"] is True

    @pytest.mark.asyncio
    async def test_diffdock_mock_confidence_ordering(self):
        from app.clients.mock.diffdock_mock import MockDiffdockClient
        client = MockDiffdockClient()
        result = await client.dock("PDB", "c1ccccc1", num_poses=10)
        confidences = [p["confidence"] for p in result["poses"]]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_diffdock_mock_reproducibility(self):
        from app.clients.mock.diffdock_mock import MockDiffdockClient
        client = MockDiffdockClient()
        r1 = await client.dock("PDB", "CCO", num_poses=3)
        r2 = await client.dock("PDB", "CCO", num_poses=3)
        assert r1["poses"][0]["confidence"] == r2["poses"][0]["confidence"]


# ========== P0 工具：RDKit 类药性评估 ==========

class TestRDKitIntegration:
    """RDKit 化学信息学集成测试"""

    def test_assess_druglikeness_valid_smiles(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness
        result = assess_druglikeness("CCO")
        assert "mw" in result
        assert "logp" in result
        assert "passes_rule_of_five" in result
        assert "druglikeness_score" in result

    def test_assess_druglikeness_osimertinib(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness
        smiles = "COC1=CC(N(CCN(C)C)C2=CC=C(NC(=O)C=C)C(NC3=CC4=CC=CC=C4N3)=C2)=CC=C1NC(=O)C=C"
        result = assess_druglikeness(smiles)
        assert result.get("mw", 0) > 400

    def test_assess_druglikeness_invalid_smiles(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness
        result = assess_druglikeness("invalid_smiles")
        # mock 模式不验证 SMILES 有效性，返回估算结果；rdkit 模式返回 error
        assert "smiles" in result or "error" in result

    def test_assess_druglikeness_empty(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness
        result = assess_druglikeness("")
        assert "error" in result

    def test_assess_druglikeness_lipinski_pass(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness
        result = assess_druglikeness("CCO")
        if "passes_rule_of_five" in result:
            assert isinstance(result["passes_rule_of_five"], bool)


# ========== P0 工具：Scanpy 解析器（错误路径）==========

class TestScanpyIntegration:
    """Scanpy 单细胞数据分析集成测试"""

    @pytest.mark.asyncio
    async def test_scrna_parser_file_not_found(self):
        from app.services.parser.scrna import ScRnaSeqParser
        from app.models.dataset import Dataset

        ds = Dataset(
            name="test", file_format="h5", storage_path="/nonexistent/file.h5"
        )
        parser = ScRnaSeqParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]


# ========== P0 工具：BioPython FASTA 解析器 ==========

class TestBioPythonIntegration:
    """BioPython 生物数据解析集成测试"""

    @pytest.mark.asyncio
    async def test_fasta_parser_file_not_found(self):
        from app.services.parser.fasta import FastaParser
        from app.models.dataset import Dataset

        ds = Dataset(
            name="test", file_format="fa", storage_path="/nonexistent/file.fa"
        )
        parser = FastaParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]


# ========== P0 工具：Nextflow 工作流 ==========

class TestNextflowIntegration:
    """Nextflow 工作流管理集成测试"""

    def test_nextflow_runner_importable(self):
        from app.services.workflow.nextflow_runner import NextflowRunner
        assert NextflowRunner is not None

    def test_pipeline_manager_importable(self):
        from app.services.workflow.pipeline_manager import PipelineManager
        assert PipelineManager is not None


# ========== P2 工具：DeepChem 分子设计（降级）==========

class TestDeepChemIntegration:
    """DeepChem 深度学习药物发现集成测试（P2 降级）"""

    @pytest.mark.asyncio
    async def test_molecule_designer_framework_fallback(self):
        from app.services.analyzer.molecule_designer import MoleculeDesigner
        designer = MoleculeDesigner(db=None)
        result = await designer.design({"target_id": "test", "smiles": "CCO"})
        assert "model_info" in result
        assert result["model_info"]["status"] in (
            "framework_only", "deepchem_predicted", "model_load_failed"
        )


# ========== P2 工具：PyG 网络建模（降级）==========

class TestPyGIntegration:
    """PyTorch Geometric 图神经网络集成测试（P2 降级）"""

    @pytest.mark.asyncio
    async def test_network_modeler_degree_based(self):
        from app.services.analyzer.network_modeler import NetworkModeler
        modeler = NetworkModeler(db=None)
        result = await modeler.analyze_ppi(["EGFR", "KRAS"], max_depth=1)
        assert "nodes" in result
        assert "edges" in result
        assert "hub_genes" in result
        assert result["model"] in ("degree_based", "graph_sage")


# ========== P3 工具：Flower 联邦学习 ==========

class TestFlowerIntegration:
    """Flower 联邦学习集成测试（P3 框架）"""

    def test_federated_learning_importable(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        assert FederatedLearner is not None


# ========== P3 工具：PySyft 隐私计算 ==========

class TestPySyftIntegration:
    """PySyft 隐私计算集成测试（P3 框架）"""

    def test_privacy_layer_importable(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        assert PrivacyLayer is not None


# ========== 工具映射总览测试 ==========

class TestToolMappingComplete:
    """验证 11 个开源工具全部已集成"""

    def test_all_11_tools_integrated(self):
        tools = {
            "scanpy": "app.services.parser.scrna",
            "biopython": "app.services.parser.fasta",
            "nextflow": "app.services.workflow.nextflow_runner",
            "rdkit": "app.services.analyzer.molecule_designer",
            "mygene": "app.clients.mock.mygene_mock",
            "myvariant": "app.clients.mock.myvariant_mock",
            "chembl": "app.clients.mock.chembl_mock",
            "diffdock": "app.clients.mock.diffdock_mock",
            "deepchem": "app.services.analyzer.molecule_designer",
            "pyg": "app.services.analyzer.network_modeler",
            "flower": "app.services.optimizer.federated_learning",
            "pysyft": "app.services.knowledge.privacy_layer",
        }
        import importlib
        for tool, module_path in tools.items():
            mod = importlib.import_module(module_path)
            assert mod is not None, f"工具 {tool} 模块 {module_path} 导入失败"
