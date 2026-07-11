"""最终覆盖率补充 — network_modeler / target_identifier / graph / orchestrator 剩余分支"""
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ============================================================
# NetworkModeler — _compute_sage_embeddings 路径
# ============================================================

class TestNetworkModelerSage:
    @pytest.mark.asyncio
    async def test_analyze_ppi_without_pyg(self):
        """PyG 未安装时应走 degree_based 路径"""
        from app.services.analyzer.network_modeler import NetworkModeler

        # Mock KnowledgeGraph
        mock_kg = MagicMock()
        mock_kg.get_neighbors = AsyncMock(return_value={
            "neighbors": [
                {"gene": "KRAS", "interaction": "physical", "score": 0.9, "evidence": "exp"},
                {"gene": "BRAF", "interaction": "physical", "score": 0.8, "evidence": "exp"},
            ]
        })

        with patch("app.services.knowledge.graph.get_knowledge_graph", return_value=mock_kg):
            modeler = NetworkModeler(db=MagicMock())
            result = await modeler.analyze_ppi(["EGFR"], max_depth=1)

        assert result["model"] == "degree_based"
        assert result["embedding_dim"] == 0
        assert result["total_nodes"] >= 1
        assert len(result["edges"]) >= 2
        assert any(h["gene"] == "EGFR" for h in result["hub_genes"])

    @pytest.mark.asyncio
    async def test_analyze_ppi_no_neighbors(self):
        """无邻居时应返回单节点网络"""
        from app.services.analyzer.network_modeler import NetworkModeler

        mock_kg = MagicMock()
        mock_kg.get_neighbors = AsyncMock(return_value={"neighbors": []})

        with patch("app.services.knowledge.graph.get_knowledge_graph", return_value=mock_kg):
            modeler = NetworkModeler(db=MagicMock())
            result = await modeler.analyze_ppi(["EGFR"])

        assert result["total_nodes"] == 1
        assert result["total_edges"] == 0
        assert result["hub_genes"][0]["gene"] == "EGFR"

    @pytest.mark.asyncio
    async def test_compute_sage_embeddings_with_mock_torch(self):
        """Mock torch + torch_geometric 测试 SAGE 嵌入路径"""
        from app.services.analyzer.network_modeler import NetworkModeler

        # 构建 5+ 节点的网络
        nodes = [{"id": f"g{i}", "label": f"g{i}"} for i in range(6)]
        edges = [
            {"source": "g0", "target": "g1"},
            {"source": "g0", "target": "g2"},
            {"source": "g1", "target": "g3"},
            {"source": "g2", "target": "g4"},
            {"source": "g3", "target": "g5"},
        ]

        # Mock torch
        mock_torch = MagicMock()
        mock_tensor = MagicMock()
        # h.size(1) 应返回 32（整数），而非列表
        mock_tensor.size = MagicMock(return_value=32)
        mock_torch.tensor = MagicMock(return_value=mock_tensor)
        mock_torch.eye = MagicMock(return_value=MagicMock())
        mock_torch.long = MagicMock()
        mock_torch.float = MagicMock()
        mock_torch.no_grad = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)))

        # Mock SAGEConv
        mock_sage_conv = MagicMock()
        mock_conv_instance = MagicMock()
        mock_conv_instance.return_value = mock_tensor  # conv(x, edge_index) -> tensor
        mock_conv_instance.relu = MagicMock(return_value=mock_tensor)
        mock_sage_conv.return_value = mock_conv_instance

        # Mock Data
        mock_data_class = MagicMock()
        mock_data_instance = MagicMock()
        mock_data_instance.x = MagicMock()
        mock_data_instance.edge_index = MagicMock()
        mock_data_class.return_value = mock_data_instance

        mock_tg_nn = MagicMock()
        mock_tg_nn.SAGEConv = mock_sage_conv

        mock_tg_data = MagicMock()
        mock_tg_data.Data = mock_data_class

        modeler = NetworkModeler(db=MagicMock())

        with patch.dict("sys.modules", {
            "torch": mock_torch,
            "torch_geometric": MagicMock(),
            "torch_geometric.nn": mock_tg_nn,
            "torch_geometric.data": mock_tg_data,
        }):
            # 调用 _compute_sage_embeddings
            result = await modeler._compute_sage_embeddings(nodes, edges)

        # 应返回 32（embedding_dim）
        assert result == 32

    @pytest.mark.asyncio
    async def test_compute_sage_embeddings_too_few_nodes(self):
        """节点数 < 5 应返回 0"""
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        nodes = [{"id": "g1"}, {"id": "g2"}]
        edges = [{"source": "g1", "target": "g2"}]

        result = await modeler._compute_sage_embeddings(nodes, edges)
        assert result == 0

    @pytest.mark.asyncio
    async def test_compute_sage_embeddings_no_edges(self):
        """无边应返回 0"""
        from app.services.analyzer.network_modeler import NetworkModeler

        modeler = NetworkModeler(db=MagicMock())
        nodes = [{"id": f"g{i}"} for i in range(10)]
        edges = []

        result = await modeler._compute_sage_embeddings(nodes, edges)
        assert result == 0


# ============================================================
# TargetIdentifier — discover 各异常分支
# ============================================================

class TestTargetIdentifierBranches:
    @pytest.mark.asyncio
    async def test_discover_with_dataset_id_filter(self):
        """指定 dataset_id 应过滤数据集"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()
        dataset_id = uuid4()

        # Mock DB
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        identifier = TargetIdentifier(db=mock_db)
        result = await identifier.discover(
            project_id=project_id,
            dataset_id=dataset_id,
            tier="fast_screen",
        )

        assert result["count"] == 0
        assert result["message"] == "项目无可用数据集"

    @pytest.mark.asyncio
    async def test_discover_variant_annotation_failure(self):
        """变异注释失败应继续执行"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        # 构造含 variants 的 dataset
        mock_ds = MagicMock()
        mock_ds.parsed_summary = {"variants": ["chr7:55259515:T>A"]}
        mock_ds.file_format = "vcf"

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        # variant client 抛异常
        mock_vc = MagicMock()
        mock_vc.query_batch = AsyncMock(side_effect=Exception("variant service down"))

        # gene client 返回基本信息
        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR gene"})

        with patch("app.services.analyzer.target_identifier.get_variant_client", return_value=mock_vc), \
             patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(side_effect=Exception("chembl down")))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", side_effect=Exception("kg error")):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(project_id=project_id)

        # 应使用默认基因 EGFR/TP53/KRAS
        assert result["count"] > 0
        assert result["tier"] == "fast_screen"

    @pytest.mark.asyncio
    async def test_discover_with_scrna_top_genes_str(self):
        """scRNA-seq top_genes 含字符串格式"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        mock_ds = MagicMock()
        mock_ds.parsed_summary = {
            "top_genes": ["EGFR", "KRAS"],
            "top_markers_per_cluster": {
                "0": [{"gene": "TP53"}],
            },
        }
        mock_ds.file_format = "scrna"

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(return_value={"symbol": "EGFR", "name": "test"})

        with patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_variant_client", return_value=MagicMock()), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(return_value=[]))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", return_value=MagicMock(get_neighbors=AsyncMock(return_value={"neighbors": []}))):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(project_id=project_id)

        # 应识别 EGFR/KRAS/TP53
        gene_symbols = [t["gene_symbol"] for t in result["targets"]]
        assert "EGFR" in gene_symbols
        assert "KRAS" in gene_symbols
        assert "TP53" in gene_symbols

    @pytest.mark.asyncio
    async def test_discover_gene_query_failure(self):
        """基因查询失败应使用 fallback 基本信息"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        mock_ds = MagicMock()
        mock_ds.parsed_summary = {"top_genes": [{"symbol": "EGFR"}]}
        mock_ds.file_format = "scrna"

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        # gene client 对所有基因抛异常
        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(side_effect=Exception("gene service down"))

        with patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_variant_client", return_value=MagicMock()), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(return_value=[]))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", return_value=MagicMock(get_neighbors=AsyncMock(return_value={"neighbors": []}))):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(project_id=project_id)

        # 即使基因查询失败也应返回结果
        assert result["count"] > 0
        # fallback 应使用 gene symbol 作为 name
        assert any(t["gene_name"] == t["gene_symbol"] for t in result["targets"])

    @pytest.mark.asyncio
    async def test_discover_existing_target_skip(self):
        """已存在的靶点应跳过写入"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        mock_ds = MagicMock()
        mock_ds.parsed_summary = {"top_genes": ["EGFR"]}
        mock_ds.file_format = "scrna"

        # 第一次 execute 返回 dataset；第二次返回已存在的 target
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none = MagicMock(return_value=MagicMock())  # 已存在

        mock_dataset_result = MagicMock()
        mock_dataset_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_dataset_result, mock_existing_result])
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(return_value={"symbol": "EGFR", "name": "test"})

        with patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_variant_client", return_value=MagicMock()), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(return_value=[]))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", return_value=MagicMock(get_neighbors=AsyncMock(return_value={"neighbors": []}))):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(project_id=project_id)

        # db.add 不应被调用（已存在跳过）
        assert mock_db.add.call_count == 0
        assert result["count"] > 0

    @pytest.mark.asyncio
    async def test_discover_deep_insight_mode(self):
        """deep_insight 模式应调用 LLM 生成深度分析"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        mock_ds = MagicMock()
        mock_ds.parsed_summary = {"top_genes": ["EGFR"]}
        mock_ds.file_format = "scrna"

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))

        # 已存在 target 检查返回 None（不存在的 target）
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none = MagicMock(return_value=None)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result, mock_existing_result])
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(return_value={"symbol": "EGFR", "name": "test"})

        # LLM client mock
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "EGFR 是关键致癌基因，建议使用吉非替尼...",
            "references": [{"title": "EGFR inhibitors"}],
        })

        with patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_variant_client", return_value=MagicMock()), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(return_value=[]))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", return_value=MagicMock(get_neighbors=AsyncMock(return_value={"neighbors": []}))), \
             patch("app.services.analyzer.target_identifier.get_llm_client", return_value=mock_llm):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(
                project_id=project_id,
                tier="deep_insight",
            )

        assert result["tier"] == "deep_insight"
        # 前 5 个靶点应有 deep_analysis
        if result["targets"]:
            assert "deep_analysis" in result["targets"][0]
            assert result["targets"][0]["deep_analysis"] is not None

    @pytest.mark.asyncio
    async def test_discover_deep_insight_llm_failure(self):
        """deep_insight 模式 LLM 失败应不影响主流程"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = uuid4()

        mock_ds = MagicMock()
        mock_ds.parsed_summary = {"top_genes": ["EGFR"]}
        mock_ds.file_format = "scrna"

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ds])))

        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none = MagicMock(return_value=None)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result, mock_existing_result])
        mock_db.flush = AsyncMock()

        mock_gc = MagicMock()
        mock_gc.query = AsyncMock(return_value={"symbol": "EGFR", "name": "test"})

        # LLM 抛异常
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM service down"))

        with patch("app.services.analyzer.target_identifier.get_gene_client", return_value=mock_gc), \
             patch("app.services.analyzer.target_identifier.get_variant_client", return_value=MagicMock()), \
             patch("app.services.analyzer.target_identifier.get_chembl_client", return_value=MagicMock(find_approved_drugs=AsyncMock(return_value=[]))), \
             patch("app.services.knowledge.graph.get_knowledge_graph", return_value=MagicMock(get_neighbors=AsyncMock(return_value={"neighbors": []}))), \
             patch("app.services.analyzer.target_identifier.get_llm_client", return_value=mock_llm):
            identifier = TargetIdentifier(db=mock_db)
            result = await identifier.discover(project_id=project_id, tier="deep_insight")

        # LLM 失败不应影响主流程
        assert result["tier"] == "deep_insight"
        assert result["count"] > 0


# ============================================================
# KnowledgeGraph — get_neighbors 异常路径
# ============================================================

class TestKnowledgeGraphBranches:
    @pytest.mark.asyncio
    async def test_get_neighbors_mock_mode(self):
        """Mock 模式下 get_neighbors 应返回空列表"""
        from app.services.knowledge.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # Mock 模式默认 is_mock=True
        result = await kg.get_neighbors("EGFR", depth=1)

        # 应返回空邻居或 mock 数据
        assert isinstance(result, dict)
        assert "neighbors" in result

    @pytest.mark.asyncio
    async def test_get_neighbors_with_mock_neo4j(self):
        """Mock Neo4j driver 测试 real 模式"""
        from app.services.knowledge.graph import KnowledgeGraph
        from app.core.config import settings

        # Mock async session — graph.py 使用 async with driver.session()
        mock_record = MagicMock()
        mock_record.__getitem__ = MagicMock(side_effect=lambda key: {
            "gene": "KRAS",
            "name": "KRAS gene",
        }.get(key))

        # session.run 返回 async iterator
        async def _mock_aiter(*args, **kwargs):
            for r in [mock_record, mock_record]:
                yield r

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.run = MagicMock(return_value=_mock_aiter())

        mock_driver = MagicMock()
        mock_driver.session = MagicMock(return_value=mock_session)

        with patch.object(settings, "USE_MOCK", False):
            kg = KnowledgeGraph()
            kg._driver = mock_driver
            kg._neo4j_available = True

            result = await kg.get_neighbors("EGFR", depth=1)

        assert "neighbors" in result
        assert len(result["neighbors"]) >= 1


# ============================================================
# LLMOrchestrator — 剩余分支
# ============================================================

class TestLLMOrchestratorBranches:
    @pytest.mark.asyncio
    async def test_route_fast_screen(self):
        """fast_screen 模式路由"""
        from app.services.llm.orchestrator import LLMOrchestrator

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "EGFR 是致癌基因",
            "references": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # 构造 mock user
        mock_user = MagicMock()
        mock_user.id = uuid4()

        orch = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
        result = await orch.route(
            message="什么是 EGFR？",
            project_id=None,
            tier="fast_screen",
            user=mock_user,
        )

        assert result["tier"] == "fast_screen"
        assert "answer" in result

    @pytest.mark.asyncio
    async def test_route_deep_insight(self):
        """deep_insight 模式路由"""
        from app.services.llm.orchestrator import LLMOrchestrator

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "深度分析结果",
            "references": [{"title": "paper"}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        })

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_user = MagicMock()
        mock_user.id = uuid4()

        orch = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
        result = await orch.route(
            message="分析 EGFR 耐药机制",
            project_id=str(uuid4()),
            tier="deep_insight",
            user=mock_user,
        )

        assert result["tier"] == "deep_insight"
        assert "answer" in result
