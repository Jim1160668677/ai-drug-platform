"""服务层集成测试 — 覆盖 analyzer / knowledge / llm / workflow / experiment / cdisc 等模块

本测试文件使用真实数据（Mock 模式下的预置数据集）验证：
- MoleculeDesigner + assess_druglikeness（含 RDKit 与 Mock 回退）
- NetworkModeler PPI 网络分析
- TargetIdentifier 靶点发现主流程
- KnowledgeGraph 邻居/路径/通路查询
- VectorStore Mock 降级
- ChEMBL 服务（activity/approved/repurposing score）
- LLMOrchestrator 路由 / 意图识别 / 成本估算 / 基因抽取 / full_analysis
- RAGEngine retrieve/augment
- PipelineManager 管道元数据
- FeedbackLoop 干湿闭环反馈
- LimsImporter 实验数据导入
- SDTMExporter CDISC 导出（SDTM + ADaM + CSV）
- prompts.build_context_prompt
"""
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 强制 Mock 模式
os.environ["USE_MOCK"] = "true"


# ========== MoleculeDesigner + assess_druglikeness ==========

class TestMoleculeDesigner:
    """分子设计引擎测试"""

    @pytest.mark.asyncio
    async def test_design_framework_only(self):
        """P0 框架模式（DeepChem 未安装）"""
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        designer = MoleculeDesigner(db=MagicMock())
        result = await designer.design({
            "target_id": "t1",
            "smiles": "CCO",
            "constraints": {"max_mw": 500},
        })
        assert result["designed_molecules"] == []
        assert result["model_info"]["status"] in ("framework_only", "model_load_failed")
        if result["model_info"]["status"] == "framework_only":
            assert "deepchem" in result["model_info"]["required_packages"]

    @pytest.mark.asyncio
    async def test_design_no_smiles(self):
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        designer = MoleculeDesigner(db=MagicMock())
        result = await designer.design({"target_id": "t1"})
        assert result["model_info"]["status"] in ("framework_only", "model_load_failed")
        if result["model_info"]["status"] == "framework_only":
            assert result["model_info"]["seed_smiles"] is None

    def test_assess_druglikeness_valid_smiles(self):
        """RDKit 可用时验证真实 SMILES"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过真实计算测试")

        from app.services.analyzer.molecule_designer import assess_druglikeness

        result = assess_druglikeness("CCO")  # 乙醇
        assert "mw" in result
        assert "logp" in result
        assert "passes_rule_of_five" in result
        assert "druglikeness_score" in result
        assert isinstance(result["passes_rule_of_five"], bool)

    def test_assess_druglikeness_invalid_smiles(self):
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装")

        from app.services.analyzer.molecule_designer import assess_druglikeness

        result = assess_druglikeness("not_a_smiles")
        assert "error" in result

    def test_assess_druglikeness_empty(self):
        from app.services.analyzer.molecule_designer import assess_druglikeness

        result = assess_druglikeness("")
        assert result == {"error": "SMILES 不能为空"}

    def test_mock_assess_druglikeness(self):
        """RDKit 未安装时的 Mock 回退"""
        from app.services.analyzer.molecule_designer import _mock_assess_druglikeness

        result = _mock_assess_druglikeness("CCN")
        assert "mw" in result
        assert "logp" in result
        assert "_note" in result
        assert result["mw"] > 0

    def test_mock_assess_druglikeness_empty(self):
        from app.services.analyzer.molecule_designer import _mock_assess_druglikeness

        assert _mock_assess_druglikeness("") == {"error": "SMILES 不能为空"}

    def test_predict_admet_valid(self):
        """ADMET 预测 — 阿司匹林真实计算"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过真实计算测试")

        from app.services.analyzer.molecule_designer import predict_admet
        result = predict_admet("CC(=O)Oc1ccccc1C(=O)O")  # 阿司匹林
        assert "error" not in result
        assert isinstance(result["logS"], float)
        valid_levels = {"high", "medium", "low"}
        assert result["bbb_permeability"] in valid_levels
        assert result["caco2_permeability"] in valid_levels
        assert result["herg_risk"] in valid_levels
        assert result["plasma_protein_binding"] in valid_levels
        assert isinstance(result["pains_alerts"], list)
        assert isinstance(result["toxicophore_alerts"], list)
        assert 0.0 <= result["bioavailability_score"] <= 1.0
        assert result["summary"]["toxicity"] in valid_levels

    def test_predict_admet_invalid(self):
        """ADMET 预测 — 无效 SMILES"""
        from app.services.analyzer.molecule_designer import predict_admet
        result = predict_admet("not_a_smiles")
        # RDKit 可用时返回 {"error": "无效 SMILES"}；Mock 路径可能返回带 _note 的估算结果
        assert "error" in result or "_note" in result

    def test_predict_admet_empty(self):
        """ADMET 预测 — 空 SMILES"""
        from app.services.analyzer.molecule_designer import predict_admet
        result = predict_admet("")
        assert result == {"error": "SMILES 不能为空"}

    def test_predict_admet_pains(self):
        """ADMET 预测 — PAINS 警告结构检测（甲基乙烯基酮匹配 ene_one_michael）"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过 PAINS 真实匹配测试")

        from app.services.analyzer.molecule_designer import predict_admet
        result = predict_admet("C=CC(=O)C")  # 甲基乙烯基酮
        assert "error" not in result
        pains_names = [a["name"] for a in result["pains_alerts"]]
        assert "ene_one_michael" in pains_names

    def test_predict_admet_toxicophore(self):
        """ADMET 预测 — 毒性警示结构检测（硝基苯匹配 nitro）"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过毒性警示真实匹配测试")

        from app.services.analyzer.molecule_designer import predict_admet
        result = predict_admet("O=[N+]([O-])c1ccccc1")  # 硝基苯
        assert "error" not in result
        tox_names = [a["name"] for a in result["toxicophore_alerts"]]
        assert "nitro" in tox_names

    def test_explain_valid(self):
        """分子可解释性 — 咖啡因功能团与环分析"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过真实计算测试")

        from app.services.analyzer.molecule_designer import explain_molecule
        result = explain_molecule("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")  # 咖啡因
        assert "error" not in result
        assert isinstance(result["functional_groups"], list)
        assert len(result["functional_groups"]) >= 1
        assert result["rings"]["total"] >= 1
        assert "C" in result["atom_counts"]
        assert "N" in result["atom_counts"]
        assert "O" in result["atom_counts"]

    def test_explain_invalid(self):
        """分子可解释性 — 无效 SMILES"""
        from app.services.analyzer.molecule_designer import explain_molecule
        result = explain_molecule("invalid_smiles")
        assert "error" in result or "_note" in result

    def test_explain_chiral(self):
        """分子可解释性 — L-丙氨酸手性中心检测"""
        try:
            from rdkit import Chem  # noqa: F401
        except ImportError:
            pytest.skip("RDKit 未安装，跳过手性中心真实检测测试")

        from app.services.analyzer.molecule_designer import explain_molecule
        result = explain_molecule("C[C@H](N)C(=O)O")  # L-丙氨酸
        assert "error" not in result
        assert result["stereochemistry"]["chiral_centers"] >= 1


# ========== NetworkModeler ==========

class TestNetworkModeler:
    """PPI 网络建模器测试"""

    @pytest.mark.asyncio
    async def test_analyze_ppi_with_egfr(self):
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi(["EGFR"], max_depth=1)

        assert "nodes" in result
        assert "edges" in result
        assert "hub_genes" in result
        assert result["total_nodes"] >= 1
        assert result["model"] in {"degree_based", "graph_sage"}
        # EGFR 应该在节点中
        node_ids = [n["id"] for n in result["nodes"]]
        assert "EGFR" in node_ids

    @pytest.mark.asyncio
    async def test_analyze_ppi_depth_2(self):
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi(["EGFR"], max_depth=2)
        # 深度 2 应当返回更多节点
        assert result["total_nodes"] >= 1
        # hub_genes 应按 degree 降序
        hub_genes = result["hub_genes"]
        if len(hub_genes) >= 2:
            assert hub_genes[0]["degree"] >= hub_genes[1]["degree"]

    @pytest.mark.asyncio
    async def test_analyze_ppi_empty_gene_list(self):
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi([], max_depth=1)
        assert result["total_nodes"] == 0
        assert result["total_edges"] == 0

    @pytest.mark.asyncio
    async def test_analyze_ppi_multiple_genes(self):
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        result = await modeler.analyze_ppi(["EGFR", "KRAS", "TP53"], max_depth=1)
        node_ids = [n["id"] for n in result["nodes"]]
        assert "EGFR" in node_ids
        assert "KRAS" in node_ids
        assert "TP53" in node_ids


# ========== KnowledgeGraph ==========

class TestKnowledgeGraph:
    """知识图谱服务测试"""

    @pytest.mark.asyncio
    async def test_get_neighbors_egfr(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.get_neighbors("EGFR", depth=1)
        assert result["root"] == "EGFR"
        assert result["source"] == "mock_ppi"
        assert len(result["neighbors"]) > 0
        # KRAS 应该是 EGFR 的邻居
        neighbor_genes = [n["gene"] for n in result["neighbors"]]
        assert "KRAS" in neighbor_genes

    @pytest.mark.asyncio
    async def test_get_neighbors_unknown_gene(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.get_neighbors("UNKNOWN_GENE", depth=1)
        assert result["root"] == "UNKNOWN_GENE"
        assert result["neighbors"] == []

    @pytest.mark.asyncio
    async def test_get_neighbors_depth_2(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        depth1 = await kg.get_neighbors("EGFR", depth=1)
        depth2 = await kg.get_neighbors("EGFR", depth=2)
        assert len(depth2["neighbors"]) >= len(depth1["neighbors"])

    @pytest.mark.asyncio
    async def test_find_path_direct(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # EGFR → KRAS（直接邻居）
        result = await kg.find_path("EGFR", "KRAS")
        assert result["length"] == 1
        assert len(result["paths"]) == 1

    @pytest.mark.asyncio
    async def test_find_path_two_hop(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # EGFR → KRAS → RAF1（二阶）
        result = await kg.find_path("EGFR", "RAF1")
        assert result["length"] in (1, 2)

    @pytest.mark.asyncio
    async def test_find_path_no_path(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.find_path("EGFR", "NONEXISTENT")
        assert result["length"] == 0
        assert result["paths"] == []

    @pytest.mark.asyncio
    async def test_get_pathway_genes_known(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.get_pathway_genes("hsa04010")
        assert result["name"] == "MAPK signaling pathway"
        assert "EGFR" in result["genes"]
        assert result["source"] == "mock_kegg"

    @pytest.mark.asyncio
    async def test_get_pathway_genes_unknown(self):
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.get_pathway_genes("hsa99999")
        assert result["genes"] == []
        assert "note" in result

    def test_knowledge_graph_singleton(self):
        from app.services.knowledge.graph import get_knowledge_graph

        kg1 = get_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is kg2


# ========== VectorStore ==========

class TestVectorStore:
    """向量存储测试 — Mock 模式下应返回空"""

    @pytest.mark.asyncio
    async def test_search_mock_returns_empty(self):
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        result = await store.search("EGFR inhibitor", collection="default", top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_add_documents_mock_returns_zero(self):
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        result = await store.add_documents([
            {"id": "1", "text": "test document"},
        ], collection="default")
        assert result == 0

    @pytest.mark.asyncio
    async def test_add_documents_empty(self):
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        result = await store.add_documents([], collection="default")
        assert result == 0

    def test_vector_store_singleton(self):
        from app.services.knowledge.vector import get_vector_store

        v1 = get_vector_store()
        v2 = get_vector_store()
        assert v1 is v2


# ========== ChEMBL 服务 ==========

class TestChemblService:
    """ChEMBL 服务函数测试"""

    @pytest.mark.asyncio
    async def test_search_active_molecules(self):
        from app.services.knowledge.chembl import search_active_molecules

        result = await search_active_molecules("EGFR", "IC50", limit=10)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_approved_drugs(self):
        from app.services.knowledge.chembl import get_approved_drugs

        result = await get_approved_drugs("EGFR")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_score_repurposing_candidates_with_cancer_match(self):
        from app.services.knowledge.chembl import score_repurposing_candidates

        candidates = [
            {"name": "Drug A", "max_phase": 4, "indication": "lung cancer", "molecular_weight": 400},
            {"name": "Drug B", "max_phase": 2, "indication": "diabetes", "molecular_weight": 700},
            {"name": "Drug C", "max_phase": 3, "indication": "NSCLC cancer", "molecular_weight": 350},
        ]
        scored = await score_repurposing_candidates(candidates, cancer_type="lung")
        # 应按分数降序
        assert scored[0]["druglikeness_score"] >= scored[-1]["druglikeness_score"]
        assert all("druglikeness_score" in c for c in scored)

    @pytest.mark.asyncio
    async def test_score_repurposing_candidates_empty(self):
        from app.services.knowledge.chembl import score_repurposing_candidates

        result = await score_repurposing_candidates([])
        assert result == []


# ========== LLMOrchestrator ==========

class TestLLMOrchestratorHelpers:
    """LLM 编排器辅助函数测试"""

    def test_detect_intent_target_discovery(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("帮我发现新的靶点") == "target_discovery"
        assert _detect_intent("EGFR 基因有什么突变") == "target_discovery"

    def test_detect_intent_drug_repurposing(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("老药新用候选有哪些") == "drug_repurposing"
        assert _detect_intent("已获批药物重定位") == "drug_repurposing"

    def test_detect_intent_molecule_design(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("设计新分子 SMILES") == "molecule_design"

    def test_detect_intent_pathway(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("分析 MAPK 通路") == "pathway_analysis"

    def test_detect_intent_clinical_trial(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("查询 NCT 临床试验") == "clinical_trial"

    def test_detect_intent_general(self):
        from app.services.llm.orchestrator import _detect_intent

        assert _detect_intent("你好，今天天气如何") == "general_qa"

    def test_estimate_cost_fast_screen(self):
        from app.services.llm.orchestrator import _estimate_cost
        from app.models.analysis_job import AnalysisTier

        cost = _estimate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 500},
            AnalysisTier.FAST_SCREEN,
        )
        # gpt-4o-mini: 0.15/M input + 0.60/M output
        expected = round((1000 * 0.15 + 500 * 0.60) / 1_000_000, 4)
        assert cost == expected

    def test_estimate_cost_deep_insight(self):
        from app.services.llm.orchestrator import _estimate_cost
        from app.models.analysis_job import AnalysisTier

        cost = _estimate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 500},
            AnalysisTier.DEEP_INSIGHT,
        )
        # gpt-4o: 5/M input + 15/M output
        expected = round((1000 * 5 + 500 * 15) / 1_000_000, 4)
        assert cost == expected

    def test_estimate_cost_no_usage(self):
        from app.services.llm.orchestrator import _estimate_cost
        from app.models.analysis_job import AnalysisTier

        assert _estimate_cost(None, AnalysisTier.FAST_SCREEN) == 0
        assert _estimate_cost({}, AnalysisTier.FAST_SCREEN) == 0


class TestLLMOrchestratorRoute:
    """LLM 编排器路由测试"""

    def test_extract_gene_egfr(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        assert orchestrator._extract_gene("分析 EGFR 突变") == "EGFR"
        # set 无序，断言为任一已知基因
        assert orchestrator._extract_gene("KRAS 和 TP53 的关系") in {"KRAS", "TP53"}
        assert orchestrator._extract_gene("今天天气不错") is None

    def test_select_model_with_config(self):
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        config = SimpleNamespace(
            fast_model="gpt-4o-mini",
            deep_model="gpt-4o",
            test_model="gpt-3.5-turbo",
        )
        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock(), llm_config=config)
        assert orchestrator._select_model(AnalysisTier.FAST_SCREEN) == "gpt-4o-mini"
        assert orchestrator._select_model(AnalysisTier.DEEP_INSIGHT) == "gpt-4o"

    def test_select_model_with_config_fallback_to_test(self):
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        config = SimpleNamespace(fast_model=None, deep_model=None, test_model="gpt-3.5-turbo")
        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock(), llm_config=config)
        assert orchestrator._select_model(AnalysisTier.FAST_SCREEN) == "gpt-3.5-turbo"
        assert orchestrator._select_model(AnalysisTier.DEEP_INSIGHT) == "gpt-3.5-turbo"

    @pytest.mark.asyncio
    async def test_route_fast_screen(self):
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "EGFR 是重要靶点",
            "references": [{"title": "Ref1"}],
            "code": None,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        orchestrator = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
        user = SimpleNamespace(id="user-1")
        result = await orchestrator.route(
            message="EGFR 是什么",
            project_id=None,
            tier=AnalysisTier.FAST_SCREEN,
            user=user,
        )
        assert result["answer"] == "EGFR 是重要靶点"
        assert result["tier"] == AnalysisTier.FAST_SCREEN
        assert "cost_usd" in result
        assert "duration_sec" in result


# ========== RAGEngine ==========

class TestRAGEngine:
    """RAG 引擎测试"""

    @pytest.mark.asyncio
    async def test_retrieve_mock_returns_empty(self):
        from app.services.llm.rag import RAGEngine

        rag = RAGEngine(db=MagicMock(), llm_client=MagicMock())
        result = await rag.retrieve("EGFR inhibitor", project_id="p1", top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_augment_empty_retrieved(self):
        from app.services.llm.rag import RAGEngine

        rag = RAGEngine(db=MagicMock(), llm_client=MagicMock())
        result = await rag.augment("原始问题", [])
        assert result == "原始问题"

    @pytest.mark.asyncio
    async def test_augment_with_documents(self):
        from app.services.llm.rag import RAGEngine

        rag = RAGEngine(db=MagicMock(), llm_client=MagicMock())
        docs = [
            {"text": "EGFR 是受体酪氨酸激酶", "similarity": 0.95, "metadata": {"source": "kegg"}},
            {"text": "KRAS 是 GTPase", "similarity": 0.85, "metadata": {"source": "uniprot"}},
        ]
        result = await rag.augment("解释 EGFR", docs)
        assert "EGFR 是受体酪氨酸激酶" in result
        assert "KRAS 是 GTPase" in result
        assert "解释 EGFR" in result
        assert "[文献 1]" in result


# ========== PipelineManager ==========

class TestPipelineManager:
    """管道管理器测试"""

    def test_list_pipelines(self):
        from app.services.workflow.pipeline_manager import PipelineManager

        mgr = PipelineManager()
        pipelines = mgr.list_pipelines()
        names = [p["name"] for p in pipelines]
        assert "scrna_pipeline" in names
        assert "rna_seq_pipeline" in names
        assert "variant_annotation" in names
        for p in pipelines:
            assert "description" in p
            assert "phase" in p
            assert "input_type" in p
            assert "output_files" in p

    def test_get_pipeline_config_known(self):
        from app.services.workflow.pipeline_manager import PipelineManager

        mgr = PipelineManager()
        config = mgr.get_pipeline_config("scrna_pipeline")
        assert config["name"] == "scrna_pipeline"
        assert "params_template" in config
        assert "script" in config

    def test_get_pipeline_config_unknown(self):
        from app.services.workflow.pipeline_manager import PipelineManager

        mgr = PipelineManager()
        result = mgr.get_pipeline_config("nonexistent_pipeline")
        assert "error" in result
        assert "available" in result


# ========== FeedbackLoop ==========

class TestFeedbackLoop:
    """干湿闭环反馈测试"""

    @pytest.mark.asyncio
    async def test_apply_feedback_with_matching_keys(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        exp = SimpleNamespace(
            id="exp-1",
            iteration=1,
            config={"predicted": {"ic50": 100, "viability": 0.5}},
            result={"measured": {"ic50": 120, "viability": 0.55}},
            exp_type="cytotoxicity",
            feedback_applied=False,
        )
        loop = FeedbackLoop(db=MagicMock())
        result = await loop.apply_feedback(exp)
        fb = result["feedback"]
        assert "error_metrics" in fb
        assert "direction_match" in fb
        assert "next_iteration" in fb
        assert fb["next_iteration"] == 2
        assert "suggested_adjustments" in fb
        assert isinstance(fb["suggested_adjustments"], list)
        assert exp.feedback_applied is True

    @pytest.mark.asyncio
    async def test_apply_feedback_no_data(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        exp = SimpleNamespace(
            id="exp-2", iteration=1, config={}, result={},
            exp_type="in_vitro", feedback_applied=False,
        )
        loop = FeedbackLoop(db=MagicMock())
        result = await loop.apply_feedback(exp)
        assert result["feedback"]["error_metrics"]["mae"] == 0

    def test_compute_errors_float_input(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        errors = loop._compute_errors(100.0, 110.0)
        assert errors["mae"] == 10.0
        assert errors["rmse"] == 10.0
        assert errors["mape"] == pytest.approx(9.09, abs=0.1)

    def test_compute_errors_no_match(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        errors = loop._compute_errors({"a": 1}, {"b": 2})
        assert errors["mae"] == 0
        assert "无匹配指标" in errors.get("note", "")

    def test_normalize_metrics_variants(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        assert loop._normalize_metrics(None) == {}
        assert loop._normalize_metrics(42.5) == {"value": 42.5}
        assert loop._normalize_metrics({"a": 1}) == {"a": 1}
        assert loop._normalize_metrics([1, 2, 3]) == {"0": 1, "1": 2, "2": 3}
        assert loop._normalize_metrics("3.14") == {"value": 3.14}
        assert loop._normalize_metrics("not a number") == {}

    def test_check_direction_match(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        assert loop._check_direction({"a": 10}, {"a": 15}) is True
        assert loop._check_direction({"a": 10}, {"a": -5}) is False
        assert loop._check_direction({}, {}) is True  # 无数据默认一致

    def test_suggest_adjustments_high_mape(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        exp = SimpleNamespace(exp_type="cytotoxicity", iteration=1)
        suggestions = loop._suggest_adjustments(
            {"mae": 50, "mape": 75},
            direction_match=False,
            experiment=exp,
        )
        assert any("MAPE>50%" in s for s in suggestions)
        assert any("方向" in s for s in suggestions)
        assert any("浓度梯度" in s for s in suggestions)

    def test_suggest_adjustments_pdx(self):
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(db=MagicMock())
        exp = SimpleNamespace(exp_type="pdx", iteration=2)
        suggestions = loop._suggest_adjustments(
            {"mae": 5, "mape": 10},
            direction_match=True,
            experiment=exp,
        )
        assert any("PDX" in s for s in suggestions)


# ========== LimsImporter ==========

class TestLimsImporter:
    """LIMS 数据导入器测试"""

    @pytest.mark.asyncio
    async def test_import_data_empty(self):
        from app.services.experiment.lims_importer import LimsImporter

        importer = LimsImporter(db=MagicMock())
        result = await importer.import_data({"experiments": []})
        assert result["count"] == 0
        assert "无实验数据" in result["errors"]

    @pytest.mark.asyncio
    async def test_import_data_missing_project_id(self):
        from app.services.experiment.lims_importer import LimsImporter

        importer = LimsImporter(db=MagicMock())
        result = await importer.import_data({
            "experiments": [{"name": "exp1", "exp_type": "in_vitro"}]
        })
        assert result["count"] == 0
        assert any("project_id" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_import_data_invalid_uuid(self):
        from app.services.experiment.lims_importer import LimsImporter

        importer = LimsImporter(db=MagicMock())
        result = await importer.import_data({
            "experiments": [{
                "name": "exp1",
                "project_id": "not-a-uuid",
                "exp_type": "in_vitro",
            }]
        })
        assert result["count"] == 0
        assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_import_data_success(self):
        from app.services.experiment.lims_importer import LimsImporter

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # patch UUID 构造，避免真实 UUID 解析失败
        with patch("app.services.experiment.lims_importer.Experiment") as mock_exp_class:
            mock_instance = MagicMock()
            mock_instance.id = "new-exp-uuid"
            mock_exp_class.return_value = mock_instance

            importer = LimsImporter(db=mock_db)
            result = await importer.import_data({
                "experiments": [{
                    "name": "Test Exp",
                    "project_id": "12345678-1234-1234-1234-123456789012",
                    "exp_type": "cytotoxicity",
                    "config": {"dose": 10},
                    "result": {"viability": 0.5},
                }]
            })
        assert result["count"] == 1
        assert len(result["imported_ids"]) == 1
        assert result["errors"] == []


# ========== SDTMExporter ==========

class TestSDTMExporter:
    """CDISC SDTM 导出器测试"""

    @pytest.mark.asyncio
    async def test_export_basic(self):
        from app.services.cdisc.sdtm_exporter import SDTMExporter

        project_id = "12345678-1234-1234-1234-123456789012"
        mock_project = SimpleNamespace(
            id=project_id,
            created_at=datetime.now(timezone.utc),
            cancer_type="NSCLC",
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_project)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        exporter = SDTMExporter(db=mock_db)
        result = await exporter.export(project_id)

        assert "domains" in result
        assert "metadata" in result
        assert "DM" in result["domains"]
        assert "VS" in result["domains"]
        assert "RS" in result["domains"]
        assert "EX" in result["domains"]
        assert "SV" in result["domains"]
        assert result["metadata"]["study_id"].startswith("PDD-")
        assert result["metadata"]["version"] == "SDTMIG 3.3"

    @pytest.mark.asyncio
    async def test_export_adam(self):
        from app.services.cdisc.sdtm_exporter import SDTMExporter

        project_id = "12345678-1234-1234-1234-123456789012"
        mock_project = SimpleNamespace(
            id=project_id,
            created_at=datetime.now(timezone.utc),
            cancer_type="NSCLC",
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_project)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        exporter = SDTMExporter(db=mock_db)
        result = await exporter.export_adam(project_id)

        assert "datasets" in result
        assert "ADSL" in result["datasets"]
        assert "ADRS" in result["datasets"]
        assert "ADAE" in result["datasets"]
        assert result["metadata"]["adam_version"] == "ADaMIG 1.1"

    def test_to_csv_with_data(self):
        from app.services.cdisc.sdtm_exporter import SDTMExporter

        exporter = SDTMExporter(db=MagicMock())
        sdtm_data = {
            "domains": {
                "DM": [{"STUDYID": "PDD-TEST", "DOMAIN": "DM", "USUBJID": "u1", "ARM": "NSCLC"}],
                "VS": [],
            },
            "metadata": {
                "study_id": "PDD-TEST",
                "version": "SDTMIG 3.3",
                "export_time": "2026-01-01T00:00:00Z",
                "record_counts": {"DM": 1, "VS": 0},
            },
        }
        csv_str = exporter.to_csv(sdtm_data)
        assert "CDISC SDTM Export" in csv_str
        assert "PDD-TEST" in csv_str
        assert "DM Domain" in csv_str
        # 空域应被跳过
        assert "VS Domain" not in csv_str

    def test_to_csv_empty(self):
        from app.services.cdisc.sdtm_exporter import SDTMExporter

        exporter = SDTMExporter(db=MagicMock())
        csv_str = exporter.to_csv({"domains": {}, "metadata": {}})
        assert "CDISC SDTM Export" in csv_str


# ========== prompts.build_context_prompt ==========

class TestPrompts:
    """Prompt 模板测试"""

    def test_build_context_prompt_empty(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({})
        assert result == "无可用上下文"

    def test_build_context_prompt_with_gene(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({"gene": "EGFR"})
        assert "EGFR" in result
        assert "目标基因" in result

    def test_build_context_prompt_with_variants(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({
            "gene": "EGFR",
            "variants": [
                {"query": "chr7:55259515:T>A", "hgvs_p": "p.L858R", "clinvar": {"clnsig": "Pathogenic"}}
            ],
        })
        assert "L858R" in result
        assert "Pathogenic" in result

    def test_build_context_prompt_with_drugs(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({
            "drugs": [{"name": "Osimertinib", "max_phase": 4}],
        })
        assert "Osimertinib" in result

    def test_build_context_prompt_with_pathway(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({
            "pathway": {"pathways": ["MAPK signaling", "ErbB signaling"]},
        })
        assert "MAPK signaling" in result

    def test_build_context_prompt_with_neighbors(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({
            "ppi_neighbors": [{"gene": "KRAS", "interaction": "activation"}],
        })
        assert "KRAS" in result

    def test_build_context_prompt_with_trials(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({
            "clinical_trials": [{"nct_id": "NCT02296125", "title": "FLAURA Study"}],
        })
        assert "NCT02296125" in result
        assert "FLAURA" in result

    def test_build_context_prompt_with_extra(self):
        from app.services.llm.prompts import build_context_prompt

        result = build_context_prompt({"extra": "补充信息内容"})
        assert "补充信息" in result

    def test_system_prompts_exist(self):
        from app.services.llm.prompts import SYSTEM_PROMPTS

        assert "fast_screen" in SYSTEM_PROMPTS
        assert "deep_insight" in SYSTEM_PROMPTS
        assert len(SYSTEM_PROMPTS["fast_screen"]) > 0
        assert len(SYSTEM_PROMPTS["deep_insight"]) > 0
