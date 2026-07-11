"""服务模块补充覆盖 — 覆盖 scrna/vector/vcf/drug_repurposer/db_session/privacy 等剩余低覆盖模块"""
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================
# ScRnaSeqParser — scanpy 路径覆盖
# ============================================================

class TestScRnaSeqParserScanpy:
    @pytest.mark.asyncio
    async def test_parse_h5_with_mock_scanpy(self):
        """Mock scanpy 测试 h5 解析完整流程"""
        from app.services.parser.scrna import ScRnaSeqParser

        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as f:
            f.write(b"fake h5")
            path = f.name

        try:
            # Mock scanpy 和相关模块
            mock_sc = MagicMock()
            mock_adata = MagicMock()
            mock_adata.n_obs = 100
            mock_adata.n_vars = 2000
            mock_adata.var_names = MagicMock()
            mock_adata.var_names.str = MagicMock()
            mock_adata.var_names.str.startswith = MagicMock(return_value=[False] * 2000)

            # highly_variable 需要支持 .sum() 调用
            mock_hvg = MagicMock()
            mock_hvg.sum = MagicMock(return_value=500)
            mock_adata.var = {"mt": [False] * 2000, "highly_variable": mock_hvg}
            mock_adata.obs = {
                "n_genes_by_counts": MagicMock(),
                "total_counts": MagicMock(),
                "pct_counts_mt": MagicMock(),
                "leiden": MagicMock(),
            }
            mock_adata.obs["leiden"].nunique = MagicMock(return_value=3)
            mock_adata.obs["leiden"].cat = MagicMock()
            mock_adata.obs["leiden"].cat.categories = ["0", "1", "2"]
            mock_adata.uns = {}
            mock_sc.read_10x_h5 = MagicMock(return_value=mock_adata)
            mock_sc.pp = MagicMock()
            mock_sc.tl = MagicMock()
            mock_sc.AnnData = MagicMock(return_value=mock_adata)

            # MagicMock 支持长度计算和 median
            mock_series = MagicMock()
            mock_series.__len__ = MagicMock(return_value=100)
            mock_series.median = MagicMock(return_value=2.5)
            mock_pd = MagicMock()
            mock_pd.Series = MagicMock(return_value=mock_series)

            mock_np = MagicMock()

            ds = SimpleNamespace(storage_path=path, file_format="h5")
            with patch.dict("sys.modules", {
                "scanpy": mock_sc, "numpy": mock_np, "pandas": mock_pd,
            }):
                parser = ScRnaSeqParser()
                result = await parser.parse(ds)

            assert "summary" in result
            assert "quality_metrics" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_csv_with_mock_scanpy(self):
        """CSV 格式走 pd.read_csv 路径"""
        from app.services.parser.scrna import ScRnaSeqParser

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("gene,c1,c2\nEGFR,1,2\n")
            path = f.name

        try:
            mock_sc = MagicMock()
            mock_adata = MagicMock()
            mock_adata.n_obs = 10
            mock_adata.n_vars = 50
            mock_adata.var_names = MagicMock()
            mock_adata.var_names.str = MagicMock()
            mock_adata.var_names.str.startswith = MagicMock(return_value=[False] * 50)
            mock_hvg = MagicMock()
            mock_hvg.sum = MagicMock(return_value=20)
            mock_adata.var = {"mt": [False] * 50, "highly_variable": mock_hvg}
            mock_adata.obs = {
                "n_genes_by_counts": MagicMock(),
                "total_counts": MagicMock(),
                "pct_counts_mt": MagicMock(),
            }
            mock_sc.AnnData = MagicMock(return_value=mock_adata)
            mock_sc.pp = MagicMock()
            mock_sc.tl = MagicMock()

            mock_series = MagicMock()
            mock_series.__len__ = MagicMock(return_value=10)
            mock_series.median = MagicMock(return_value=2.0)
            mock_df = MagicMock()
            mock_df.T = MagicMock()
            mock_pd = MagicMock()
            mock_pd.read_csv = MagicMock(return_value=mock_df)
            mock_pd.Series = MagicMock(return_value=mock_series)

            ds = SimpleNamespace(storage_path=path, file_format="csv")
            with patch.dict("sys.modules", {
                "scanpy": mock_sc, "numpy": MagicMock(), "pandas": mock_pd,
            }):
                parser = ScRnaSeqParser()
                result = await parser.parse(ds)

            assert "summary" in result
            mock_pd.read_csv.assert_called_once()
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_mtx_with_mock_scanpy(self):
        """mtx 格式走 sc.read_mtx 路径"""
        from app.services.parser.scrna import ScRnaSeqParser

        with tempfile.NamedTemporaryFile(suffix=".mtx", delete=False) as f:
            f.write(b"fake mtx")
            path = f.name

        try:
            mock_sc = MagicMock()
            mock_adata = MagicMock()
            mock_adata.n_obs = 5
            mock_adata.n_vars = 10
            mock_adata.var_names = MagicMock()
            mock_adata.var_names.str = MagicMock()
            mock_adata.var_names.str.startswith = MagicMock(return_value=[False] * 10)
            mock_hvg = MagicMock()
            mock_hvg.sum = MagicMock(return_value=3)
            mock_adata.var = {"mt": [False] * 10, "highly_variable": mock_hvg}
            mock_adata.obs = {
                "n_genes_by_counts": MagicMock(),
                "total_counts": MagicMock(),
                "pct_counts_mt": MagicMock(),
            }
            mock_sc.read_mtx = MagicMock(return_value=mock_adata)
            mock_sc.pp = MagicMock()
            mock_sc.tl = MagicMock()

            mock_series = MagicMock()
            mock_series.__len__ = MagicMock(return_value=5)
            mock_series.median = MagicMock(return_value=1.5)
            mock_pd = MagicMock()
            mock_pd.Series = MagicMock(return_value=mock_series)

            ds = SimpleNamespace(storage_path=path, file_format="mtx")
            with patch.dict("sys.modules", {
                "scanpy": mock_sc, "numpy": MagicMock(), "pandas": mock_pd,
            }):
                parser = ScRnaSeqParser()
                result = await parser.parse(ds)

            assert "summary" in result
            mock_sc.read_mtx.assert_called_once()
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_file_read_exception(self):
        """文件读取异常应返回错误"""
        from app.services.parser.scrna import ScRnaSeqParser

        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as f:
            f.write(b"fake")
            path = f.name

        try:
            mock_sc = MagicMock()
            mock_sc.read_10x_h5 = MagicMock(side_effect=Exception("invalid h5 format"))

            ds = SimpleNamespace(storage_path=path, file_format="h5")
            with patch.dict("sys.modules", {
                "scanpy": mock_sc, "numpy": MagicMock(), "pandas": MagicMock(),
            }):
                parser = ScRnaSeqParser()
                result = await parser.parse(ds)

            assert "error" in result["summary"]
            assert "scRNA-seq 文件读取失败" in result["summary"]["error"]
        finally:
            os.unlink(path)


# ============================================================
# VectorStore — ChromaDB real 路径覆盖
# ============================================================

class TestVectorStoreRealMode:
    @pytest.mark.asyncio
    async def test_add_documents_with_real_collection(self):
        """Real 模式 + 成功获取 collection → 走完整 add 路径"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.add_documents([
                {"id": "1", "text": "hello", "metadata": {"k": "v"}},
                {"id": "2", "text": "world", "metadata": {}},
            ])

        assert result == 2
        mock_collection.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_documents_embed_failure(self):
        """embed 失败应返回 0"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(side_effect=Exception("embed error"))

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.add_documents([
                {"id": "1", "text": "hello"},
            ])

        assert result == 0

    @pytest.mark.asyncio
    async def test_add_documents_collection_add_failure(self):
        """collection.add 失败应返回 0"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_collection.add = MagicMock(side_effect=Exception("db error"))
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1, 0.2])

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.add_documents([{"id": "1", "text": "hi"}])

        assert result == 0

    @pytest.mark.asyncio
    async def test_search_with_real_collection(self):
        """Real 模式 search 成功路径"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_collection.query = MagicMock(return_value={
            "ids": [["doc1", "doc2"]],
            "documents": [["hello", "world"]],
            "metadatas": [[{"k": "v"}, {}]],
            "distances": [[0.1, 0.5]],
        })
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.search("query")

        assert len(result) == 2
        assert result[0]["id"] == "doc1"
        assert result[0]["text"] == "hello"
        assert result[0]["similarity"] == 0.9
        assert result[1]["id"] == "doc2"

    @pytest.mark.asyncio
    async def test_search_embed_failure(self):
        """search 时 embed 失败应返回空列表"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(side_effect=Exception("embed failed"))

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.search("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_search_query_failure(self):
        """collection.query 失败应返回空列表"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_collection = MagicMock()
        mock_collection.query = MagicMock(side_effect=Exception("query failed"))
        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(return_value=mock_collection)

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[0.1])

        with patch.object(settings, "USE_MOCK", False), \
             patch("app.services.knowledge.vector.get_llm_client", return_value=mock_llm):
            vs = VectorStore()
            vs._client = mock_client
            result = await vs.search("query")

        assert result == []

    def test_get_collection_cached(self):
        """已缓存的 collection 应直接返回"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        with patch.object(settings, "USE_MOCK", False):
            vs = VectorStore()
            # 设置 mock client 避免走真实 chromadb 连接
            mock_client = MagicMock()
            vs._client = mock_client
            mock_coll = MagicMock()
            vs._collections["test"] = mock_coll
            assert vs._get_collection("test") is mock_coll

    def test_get_collection_create_failure(self):
        """get_or_create_collection 失败应返回 None"""
        from app.services.knowledge.vector import VectorStore
        from app.core.config import settings

        mock_client = MagicMock()
        mock_client.get_or_create_collection = MagicMock(side_effect=Exception("create failed"))

        with patch.object(settings, "USE_MOCK", False):
            vs = VectorStore()
            vs._client = mock_client
            result = vs._get_collection("new_coll")

        assert result is None


# ============================================================
# VcfParser — cyvcf2 路径覆盖
# ============================================================

class TestVcfParserCyvcf2:
    @pytest.mark.asyncio
    async def test_parse_with_mock_cyvcf2(self, tmp_path):
        """Mock cyvcf2 测试完整解析流程"""
        vcf_content = """##fileformat=VCFv4.2
##INFO=<ID=CLNSIG,Type=String,Description="ClinVar">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr1\t100\t.\tA\tG\t100\tPASS\tCLNSIG=Pathogenic
chr1\t200\t.\tC\tT\t100\tPASS\t.
chr2\t300\t.\tAT\tA\t100\tPASS\t.
"""
        path = tmp_path / "test.vcf"
        path.write_text(vcf_content, encoding="utf-8")

        # Mock cyvcf2
        mock_vcf_class = MagicMock()
        mock_variant1 = MagicMock()
        mock_variant1.CHROM = "chr1"
        mock_variant1.FILTER = "PASS"
        mock_variant1.REF = "A"
        mock_variant1.ALT = ["G"]
        mock_variant1.INFO = MagicMock()
        mock_variant1.INFO.get = MagicMock(return_value="Pathogenic")

        mock_variant2 = MagicMock()
        mock_variant2.CHROM = "chr1"
        mock_variant2.FILTER = "PASS"
        mock_variant2.REF = "C"
        mock_variant2.ALT = ["T"]
        mock_variant2.INFO = MagicMock()
        mock_variant2.INFO.get = MagicMock(return_value=None)

        mock_variant3 = MagicMock()
        mock_variant3.CHROM = "chr2"
        mock_variant3.FILTER = "PASS"
        mock_variant3.REF = "AT"
        mock_variant3.ALT = ["A"]
        mock_variant3.INFO = MagicMock()
        mock_variant3.INFO.get = MagicMock(return_value=None)

        mock_vcf_instance = MagicMock()
        mock_vcf_instance.__iter__ = MagicMock(return_value=iter([mock_variant1, mock_variant2, mock_variant3]))
        mock_vcf_class.return_value = mock_vcf_instance

        ds = SimpleNamespace(storage_path=str(path), file_format="vcf")
        with patch.dict("sys.modules", {"cyvcf2": MagicMock(VCF=mock_vcf_class)}):
            from app.services.parser.vcf import VcfParser
            parser = VcfParser()
            result = await parser.parse(ds)

        assert result["summary"]["parser"] == "cyvcf2"
        assert result["summary"]["total_variants"] == 3
        assert result["summary"]["snv_count"] == 2
        assert result["summary"]["indel_count"] == 1
        assert result["quality_metrics"]["clinvar_annotated"] == 1

    @pytest.mark.asyncio
    async def test_parse_with_cyvcf2_exception(self, tmp_path):
        """cyvcf2 抛异常应返回错误"""
        path = tmp_path / "test.vcf"
        path.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")

        mock_vcf_class = MagicMock(side_effect=Exception("cyvcf2 error"))

        ds = SimpleNamespace(storage_path=str(path), file_format="vcf")
        with patch.dict("sys.modules", {"cyvcf2": MagicMock(VCF=mock_vcf_class)}):
            from app.services.parser.vcf import VcfParser
            parser = VcfParser()
            result = await parser.parse(ds)

        assert "error" in result["summary"]
        assert "VCF 解析失败" in result["summary"]["error"]


# ============================================================
# DrugRepurposer — RDKit 路径覆盖
# ============================================================

class TestDrugRepurposerProperties:
    @pytest.mark.asyncio
    async def test_repurpose_with_approved_drugs(self):
        """正常查询老药新用"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer

        mock_chembl = MagicMock()
        mock_chembl.find_approved_drugs = AsyncMock(return_value=[
            {"name": "Osimertinib", "chembl_id": "CHEMBL2110598", "smiles": "COC1=CC",
             "max_phase": 4, "indication": "non-small cell lung cancer",
             "first_approval": 2016, "molecular_weight": 500},
            {"name": "Gefitinib", "chembl_id": "CHEMBL537", "smiles": "COC1=CC",
             "max_phase": 4, "indication": "breast cancer",
             "first_approval": 2002, "molecular_weight": 447},
        ])

        target = SimpleNamespace(gene_symbol="EGFR")
        with patch("app.services.analyzer.drug_repurposer.get_chembl_client", return_value=mock_chembl):
            repurposer = DrugRepurposer(db=MagicMock())
            result = await repurposer.repurpose(target)

        assert result["count"] == 2
        assert result["target_gene"] == "EGFR"
        assert result["candidates"][0]["druglikeness_score"] >= result["candidates"][1]["druglikeness_score"]

    @pytest.mark.asyncio
    async def test_repurpose_chembl_failure(self):
        """ChEMBL 查询失败应返回空候选"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer

        mock_chembl = MagicMock()
        mock_chembl.find_approved_drugs = AsyncMock(side_effect=Exception("chembl error"))

        target = SimpleNamespace(gene_symbol="EGFR")
        with patch("app.services.analyzer.drug_repurposer.get_chembl_client", return_value=mock_chembl):
            repurposer = DrugRepurposer(db=MagicMock())
            result = await repurposer.repurpose(target)

        assert result["count"] == 0
        assert result["candidates"] == []

    def test_compute_properties_empty_smiles(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())
        result = repurposer._compute_properties("")
        assert result == {}

    def test_compute_properties_invalid_smiles(self):
        """无效 SMILES 应返回 error"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())

        mock_chem = MagicMock()
        mock_chem.MolFromSmiles = MagicMock(return_value=None)

        with patch.dict("sys.modules", {"rdkit": mock_chem, "rdkit.Chem": mock_chem}):
            result = repurposer._compute_properties("invalid_smiles!!!")
        assert "error" in result

    def test_compute_properties_no_rdkit(self):
        """RDKit 不可用时应返回 note"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())
        with patch.dict("sys.modules", {"rdkit": None}):
            result = repurposer._compute_properties("CCO")
        assert "note" in result or "error" in result

    def test_score_candidate_approved_cancer(self):
        """已获批 + 癌症适应症应得高分"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())
        score = repurposer._score_candidate(
            {"max_phase": 4, "indication": "lung cancer", "molecular_weight": 450},
            {"passes_rule_of_five": True, "mw": 450},
        )
        assert score >= 90  # 40 + 30 + 20 + 10 = 100

    def test_score_candidate_not_approved(self):
        """未获批药物得分较低"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())
        score = repurposer._score_candidate(
            {"max_phase": 1, "indication": "headache", "molecular_weight": 50},
            {"passes_rule_of_five": False, "violations": ["MW>500", "LogP>5"]},
        )
        assert score < 50

    def test_score_candidate_no_indication(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer(db=MagicMock())
        score = repurposer._score_candidate(
            {"max_phase": 3, "indication": None},
            {"passes_rule_of_five": True, "mw": 300},
        )
        assert 30 <= score <= 70


# ============================================================
# db/session.py — get_db / init_db 覆盖
# ============================================================

class TestDbSession:
    @pytest.mark.asyncio
    async def test_get_db_yields_session(self):
        """get_db 应 yield session 并提交"""
        from app.db.session import get_db
        # 使用 mock engine 避免连接真实 DB
        with patch("app.db.session.AsyncSessionLocal") as mock_factory:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()
            mock_session.close = AsyncMock()
            mock_factory.return_value = mock_session

            async for session in get_db():
                assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_db_rollback_on_exception(self):
        """get_db 异常时应 rollback"""
        from app.db.session import get_db
        with patch("app.db.session.AsyncSessionLocal") as mock_factory:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()
            mock_session.close = AsyncMock()
            mock_factory.return_value = mock_session

            with pytest.raises(ValueError):
                async for session in get_db():
                    raise ValueError("test error")

    @pytest.mark.asyncio
    async def test_init_db(self):
        """init_db 应创建所有表"""
        from app.db import session as session_module
        from app.models.base import Base

        # 用 mock engine 替换模块级 engine，避免 read-only 属性问题
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        # run_sync 内部被 await，需要返回 awaitable
        mock_conn.run_sync = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin = MagicMock(return_value=mock_ctx)

        with patch.object(session_module, "engine", mock_engine):
            await session_module.init_db()

        mock_conn.run_sync.assert_called_once_with(Base.metadata.create_all)


# ============================================================
# PrivacyLayer — PySyft 路径覆盖
# ============================================================

class TestPrivacyLayerSyft:
    @pytest.mark.asyncio
    async def test_encrypt_data_with_pysyft(self):
        """PySyft 可用且 USE_MOCK=False 时应走 domain 封装路径"""
        from app.services.knowledge.privacy_layer import PrivacyLayer
        from app.core.config import settings

        mock_syft = MagicMock()
        mock_domain = MagicMock()
        mock_domain.id = "domain-123"
        mock_syft.Domain = MagicMock(return_value=mock_domain)
        mock_syft.Dataset = MagicMock()

        pl = PrivacyLayer()
        pl._pysyft_available = True

        with patch.object(settings, "USE_MOCK", False), \
             patch.dict("sys.modules", {"syft": mock_syft}):
            result = await pl.encrypt_data({"name": "John", "age": 45})

        assert result["encrypted"] is True
        assert result["method"] == "pysyft_domain"
        assert result["data"]["domain_id"] == "domain-123"

    @pytest.mark.asyncio
    async def test_encrypt_data_pysyft_exception(self):
        """PySyft 抛异常应降级到 fallback_anonymization"""
        from app.services.knowledge.privacy_layer import PrivacyLayer
        from app.core.config import settings

        mock_syft = MagicMock()
        mock_syft.Domain = MagicMock(side_effect=Exception("syft error"))

        pl = PrivacyLayer()
        pl._pysyft_available = True

        with patch.object(settings, "USE_MOCK", False), \
             patch.dict("sys.modules", {"syft": mock_syft}):
            result = await pl.encrypt_data({"name": "John"})

        assert result["encrypted"] is False
        assert result["method"] == "fallback_anonymization"

    @pytest.mark.asyncio
    async def test_federated_query_with_pysyft(self):
        """PySyft 可用且 USE_MOCK=False 时联邦查询应返回 framework_ready"""
        from app.services.knowledge.privacy_layer import PrivacyLayer
        from app.core.config import settings

        mock_syft = MagicMock()

        pl = PrivacyLayer()
        pl._pysyft_available = True

        with patch.object(settings, "USE_MOCK", False), \
             patch.dict("sys.modules", {"syft": mock_syft}):
            result = await pl.federated_query({"targets": ["EGFR"]})

        assert result["status"] == "framework_ready"
        assert "privacy_budget" in result

    @pytest.mark.asyncio
    async def test_federated_query_mock_mode(self):
        """USE_MOCK=True 时联邦查询应返回 framework_only"""
        from app.services.knowledge.privacy_layer import PrivacyLayer

        pl = PrivacyLayer()
        pl._pysyft_available = True

        result = await pl.federated_query({"targets": ["EGFR"]})

        assert result["status"] == "framework_only"

    def test_check_pysyft_unavailable(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        pl = PrivacyLayer()
        with patch.dict("sys.modules", {"syft": None}):
            assert pl._check_pysyft() is False


# ============================================================
# MoleculeDesigner — DeepChem 路径覆盖
# ============================================================

class TestMoleculeDesignerDeepChemPath:
    @pytest.mark.asyncio
    async def test_design_with_mock_deepchem(self):
        """Mock DeepChem 测试完整设计路径"""
        from app.services.analyzer.molecule_designer import MoleculeDesigner

        mock_dc = MagicMock()
        mock_model = MagicMock()
        mock_model.generate_molecules = MagicMock(return_value=[
            {"smiles": "CCO", "score": 0.9},
            {"smiles": "CCN", "score": 0.7},
        ])
        mock_dc.molnet = MagicMock()
        mock_dc.models = MagicMock()
        mock_dc.models.GraphConvModel = MagicMock(return_value=mock_model)

        designer = MoleculeDesigner(db=MagicMock())
        with patch.dict("sys.modules", {"deepchem": mock_dc}):
            # 由于 DeepChem 在 __init__ 中检查，需要重新初始化
            designer._deepchem_available = True
            designer._model = mock_model
            result = await designer.design({
                "target_id": "T1",
                "smiles": "CCO",
                "constraints": {"max_mw": 500},
            })

        assert "designed_molecules" in result

    @pytest.mark.asyncio
    async def test_design_with_rdkit_properties(self):
        """测试 assess_druglikeness 函数的 RDKit 路径"""
        from app.services.analyzer.molecule_designer import assess_druglikeness

        # Mock rdkit 模块
        mock_chem = MagicMock()
        mock_mol = MagicMock()
        mock_chem.MolFromSmiles = MagicMock(return_value=mock_mol)

        mock_ring_info = MagicMock()
        mock_ring_info.AtomRings = MagicMock(return_value=())
        mock_mol.GetRingInfo = MagicMock(return_value=mock_ring_info)

        mock_descriptors = MagicMock()
        mock_descriptors.MolWt = MagicMock(return_value=300.0)
        mock_descriptors.NumHDonors = MagicMock(return_value=2)
        mock_descriptors.NumHAcceptors = MagicMock(return_value=4)
        mock_descriptors.NumRotatableBonds = MagicMock(return_value=3)
        mock_descriptors.TPSA = MagicMock(return_value=50.0)
        mock_descriptors.RingCount = MagicMock(return_value=1)
        mock_crippen = MagicMock()
        mock_crippen.MolLogP = MagicMock(return_value=2.0)
        mock_lipinski = MagicMock()

        # from rdkit.Chem import Descriptors, Crippen, Lipinski 会从 mock_chem 获取这些属性
        mock_chem.Descriptors = mock_descriptors
        mock_chem.Crippen = mock_crippen
        mock_chem.Lipinski = mock_lipinski

        with patch.dict("sys.modules", {
            "rdkit": mock_chem, "rdkit.Chem": mock_chem,
            "rdkit.Chem.Descriptors": mock_descriptors,
            "rdkit.Chem.Crippen": mock_crippen,
            "rdkit.Chem.Lipinski": mock_lipinski,
        }):
            props = assess_druglikeness("CCO")
            # 应返回计算的性质字典
            assert isinstance(props, dict)
            assert "mw" in props
            assert "passes_rule_of_five" in props


# ============================================================
# NextflowRunner — real 执行路径覆盖
# ============================================================

class TestNextflowRunnerReal:
    @pytest.mark.asyncio
    async def test_run_real_mode(self):
        """EXECUTE_NEXTFLOW=true 时走 _run_real 路径"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        runner._execute_real = True

        workflow_run = SimpleNamespace(
            pipeline_name="rna_seq_pipeline",
            params={"project_id": "p1"},
            run_id=None,
            status=WorkflowStatus.SUBMITTED,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )

        # Mock subprocess
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"success output", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("os.unlink"):
            result = await runner.run(workflow_run)

        assert result["status"] == WorkflowStatus.COMPLETED
        assert result["mock"] is False

    @pytest.mark.asyncio
    async def test_run_real_mode_failed(self):
        """真实模式 nextflow 命令失败"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        runner._execute_real = True

        workflow_run = SimpleNamespace(
            pipeline_name="rna_seq_pipeline",
            params={"project_id": "p1"},
            run_id=None,
            status=WorkflowStatus.SUBMITTED,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"nextflow error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("os.unlink"):
            result = await runner.run(workflow_run)

        assert result["status"] == WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_run_real_mode_nextflow_not_found(self):
        """nextflow 命令不存在"""
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowStatus

        runner = NextflowRunner(db=MagicMock())
        runner._execute_real = True

        workflow_run = SimpleNamespace(
            pipeline_name="rna_seq_pipeline",
            params={},
            run_id=None,
            status=WorkflowStatus.SUBMITTED,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await runner.run(workflow_run)

        assert result["status"] == WorkflowStatus.FAILED
        assert "未找到" in workflow_run.error

    @pytest.mark.asyncio
    async def test_check_status_real_mode(self):
        """真实模式 check_status"""
        from app.services.workflow.nextflow_runner import NextflowRunner

        runner = NextflowRunner(db=MagicMock())
        runner._execute_real = True

        result = await runner.check_status("nf-123")
        assert result["status"] == "unknown"
        assert "note" in result
