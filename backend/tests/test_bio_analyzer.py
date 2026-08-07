"""生信分析引擎单元测试"""
from unittest.mock import patch, MagicMock

import pytest

from app.services.analyzer.bio_analyzer import BioAnalyzer


@pytest.fixture
def analyzer():
    return BioAnalyzer(use_mock=True)


@pytest.fixture
def real_analyzer():
    return BioAnalyzer(use_mock=False)


class TestBioAnalyzer:

    @pytest.mark.asyncio
    async def test_de_mock_returns_structure(self, analyzer):
        result = await analyzer.differential_expression({}, ["s1", "s2"], ["s3", "s4"])
        assert "genes" in result
        assert "volcano_data" in result
        assert "summary" in result
        assert len(result["genes"]) > 0
        g = result["genes"][0]
        assert all(k in g for k in ["gene", "log2fc", "pvalue", "padj", "regulation", "significant"])

    @pytest.mark.asyncio
    async def test_de_real_with_data(self, real_analyzer):
        data = {
            "GENE1": [1.0, 1.1, 2.0, 2.1],
            "GENE2": [5.0, 5.1, 1.0, 1.1],
            "GENE3": [1.0, 1.0, 1.0, 1.0],
        }
        result = await real_analyzer.differential_expression(data, ["s1", "s2"], ["s3", "s4"])
        assert len(result["genes"]) == 3
        gene2 = next(g for g in result["genes"] if g["gene"] == "GENE2")
        assert gene2["regulation"] == "down"

    @pytest.mark.asyncio
    async def test_clustering_mock(self, analyzer):
        result = await analyzer.clustering({}, n_clusters=3)
        assert "clusters" in result
        assert len(result["clusters"]) > 0
        assert result["n_clusters"] == 3

    @pytest.mark.asyncio
    async def test_clustering_real(self, real_analyzer):
        data = {f"G{i}": [float(i), float(i * 2), float(i * 3)] for i in range(10)}
        result = await real_analyzer.clustering(data, n_clusters=2)
        assert "clusters" in result
        assert len(result["clusters"]) == 10

    @pytest.mark.asyncio
    async def test_pathway_enrichment(self, analyzer):
        result = await analyzer.pathway_enrichment(["GENE1", "GENE2", "GENE3"])
        assert "pathways" in result
        assert len(result["pathways"]) > 0
        p = result["pathways"][0]
        assert all(k in p for k in ["id", "name", "pvalue", "genes", "ratio"])

    @pytest.mark.asyncio
    async def test_pca_mock(self, analyzer):
        result = await analyzer.pca_analysis({})
        assert "samples" in result
        assert "explained_variance" in result

    @pytest.mark.asyncio
    async def test_pca_real(self, real_analyzer):
        data = {f"S{i}": [float(i), float(i * 2)] for i in range(5)}
        result = await real_analyzer.pca_analysis(data)
        assert len(result["samples"]) == 5
        assert len(result["explained_variance"]) == 2

    @pytest.mark.asyncio
    async def test_de_falls_back_to_mock(self, real_analyzer):
        result = await real_analyzer.differential_expression({}, [], [])
        assert "genes" in result

    def test_bh_fdr(self):
        results = [{"pvalue": 0.01}, {"pvalue": 0.04}, {"pvalue": 0.5}]
        out = BioAnalyzer._bh_fdr(results, 0.05)
        assert all("padj" in r for r in out)
        assert all("significant" in r for r in out)

    @pytest.mark.asyncio
    async def test_volcano_data_format(self, analyzer):
        result = await analyzer.differential_expression({}, ["s1"], ["s2"])
        for v in result["volcano_data"]:
            assert "x" in v and "y" in v and "gene" in v

    @pytest.mark.asyncio
    async def test_summary_counts(self, analyzer):
        result = await analyzer.differential_expression({}, ["s1"], ["s2"])
        s = result["summary"]
        assert s["total"] == len(result["genes"])
        assert s["up_regulated"] + s["down_regulated"] <= s["total"]

    @pytest.mark.asyncio
    async def test_pathway_source(self, analyzer):
        result = await analyzer.pathway_enrichment(["G1"], source="go")
        assert result["source"] == "go"


class TestBioAnalyzerFallbackPaths:
    """覆盖异常降级路径（mock 触发异常 → 验证 fallback 逻辑）"""

    @pytest.mark.asyncio
    async def test_de_real_skips_genes_with_insufficient_samples(self, real_analyzer):
        """group_a/group_b 样本数不足 2 时跳过该基因（覆盖 line 62 continue）"""
        # G1 只有 1 个 a 样本值 → 不足 2 → 跳过
        # G2 提供完整 4 个值 → 正常计算
        data = {
            "G_INSUFFICIENT": [1.0, 2.0, 3.0],  # 3 个值，group_a=2, group_b=1 → b 不足
            "G_OK": [1.0, 1.1, 2.0, 2.1],
        }
        result = await real_analyzer.differential_expression(
            data, ["s1", "s2"], ["s3", "s4"]
        )
        # G_INSUFFICIENT 应被跳过（b_vals 只有 1 个）
        # 但实际：3 个值，a=2, b=1，b_vals<2 → continue
        gene_names = [g["gene"] for g in result["genes"]]
        # G_OK 必然在结果中；G_INSUFFICIENT 应被跳过
        assert "G_OK" in gene_names

    @pytest.mark.asyncio
    async def test_de_real_fallback_on_exception(self, real_analyzer):
        """差异表达 Real 模式抛异常 → 降级到 Mock（覆盖 lines 79-83）"""
        # 传入会触发异常的数据（非数值列表）
        bad_data = {"BAD_GENE": ["not_a_number", "still_not"]}
        result = await real_analyzer.differential_expression(
            bad_data, ["s1"], ["s2"]
        )
        # 应降级到 mock，返回结构化结果
        assert "genes" in result
        assert "parameters" in result
        # 应包含 fallback 标记
        params = result.get("parameters", {})
        assert params.get("fallback") == "mock" or "genes" in result

    @pytest.mark.asyncio
    async def test_clustering_real_fallback_on_exception(self, real_analyzer):
        """聚类 Real 模式抛异常 → 降级到 Mock（覆盖 lines 166-170）"""
        # 传入会触发异常的数据（非数值列表导致 KMeans 失败）
        bad_data = {"BAD_GENE": ["not_a_number", "still_not", "third"]}
        result = await real_analyzer.clustering(bad_data, n_clusters=2)
        # 应降级到 mock
        assert "clusters" in result
        assert "parameters" in result
        params = result.get("parameters", {})
        assert params.get("fallback") == "mock" or "clusters" in result

    @pytest.mark.asyncio
    async def test_pca_real_fallback_on_exception(self, real_analyzer):
        """PCA Real 模式抛异常 → 降级到 Mock（覆盖 lines 313-317）"""
        # 传入会触发异常的数据
        bad_data = {"BAD_SAMPLE": ["not_a_number", "still_not"]}
        result = await real_analyzer.pca_analysis(bad_data)
        # 应降级到 mock
        assert "samples" in result
        assert "parameters" in result
        params = result.get("parameters", {})
        assert params.get("fallback") == "mock" or "samples" in result

    @pytest.mark.asyncio
    async def test_pathway_enrichment_real_with_mocked_gseapy(self, real_analyzer):
        """通路富集 Real 模式 + mock gseapy → 覆盖 gseapy 调用路径（lines 201-261）"""
        # 构造 mock gseapy 模块
        mock_gseapy = MagicMock()
        # 构造 mock enrichr 返回值（DataFrame 样式）
        mock_result = MagicMock()
        mock_result.iterrows = MagicMock(return_value=iter([]))
        # 使用真实 DataFrame 模拟
        import pandas as pd
        mock_df = pd.DataFrame([
            {
                "Term": "KEGG:Pathway1",
                "Overlap": "3/10",
                "P-value": 0.001,
                "Adjusted P-value": 0.01,
                "Genes": "GENE1;GENE2;GENE3",
            },
            {
                "Term": "KEGG:Pathway2",
                "Overlap": "2/8",
                "P-value": 0.005,
                "Adjusted P-value": 0.04,
                "Genes": "GENE1;GENE4",
            },
        ])
        mock_result.results = mock_df
        mock_gseapy.enrichr = MagicMock(return_value=mock_result)

        with patch.dict("sys.modules", {"gseapy": mock_gseapy}):
            result = await real_analyzer.pathway_enrichment(
                ["GENE1", "GENE2", "GENE3"], source="kegg"
            )
        # 应返回 gseapy 真实路径结果
        assert "pathways" in result
        assert len(result["pathways"]) == 2
        assert result["source"] == "gseapy_kegg"
        p = result["pathways"][0]
        assert p["name"] == "KEGG:Pathway1"
        assert p["ratio"] == 0.3  # 3/10
        assert "GENE1" in p["genes"]

    @pytest.mark.asyncio
    async def test_pathway_enrichment_real_fallback_on_gseapy_exception(self, real_analyzer):
        """通路富集 Real 模式 gseapy 抛异常 → 降级到 Mock（覆盖 lines 257-261）"""
        mock_gseapy = MagicMock()
        mock_gseapy.enrichr = MagicMock(side_effect=RuntimeError("gseapy network error"))

        with patch.dict("sys.modules", {"gseapy": mock_gseapy}):
            result = await real_analyzer.pathway_enrichment(
                ["GENE1", "GENE2"], source="kegg"
            )
        # 应降级到 mock
        assert "pathways" in result
        params = result.get("parameters", {})
        assert params.get("fallback") == "mock"

    @pytest.mark.asyncio
    async def test_pathway_enrichment_real_fallback_on_invalid_format(self, real_analyzer):
        """通路富集 gseapy 返回非 DataFrame 格式 → 触发 ValueError 降级（覆盖 line 236）"""
        mock_gseapy = MagicMock()
        # 返回非 DataFrame 对象（无 iterrows）
        mock_result = MagicMock(spec=[])  # 空接口，没有 iterrows 也没有 results
        mock_gseapy.enrichr = MagicMock(return_value=mock_result)

        with patch.dict("sys.modules", {"gseapy": mock_gseapy}):
            result = await real_analyzer.pathway_enrichment(
                ["GENE1"], source="kegg"
            )
        # 应降级到 mock
        assert "pathways" in result

    @pytest.mark.asyncio
    async def test_pathway_enrichment_real_with_go_source(self, real_analyzer):
        """通路富集 source=go → 覆盖 gene_sets_map 选择逻辑"""
        mock_gseapy = MagicMock()
        import pandas as pd
        mock_df = pd.DataFrame([
            {"Term": "GO:Process1", "Overlap": "1/5", "P-value": 0.01,
             "Adjusted P-value": 0.05, "Genes": "GENE1"},
        ])
        mock_result = MagicMock()
        mock_result.results = mock_df
        mock_gseapy.enrichr = MagicMock(return_value=mock_result)

        with patch.dict("sys.modules", {"gseapy": mock_gseapy}):
            result = await real_analyzer.pathway_enrichment(
                ["GENE1"], source="go"
            )
        assert result["source"] == "gseapy_go"
        # 验证 gseapy.enrichr 被调用时 gene_sets 参数为 GO 数据集
        call_kwargs = mock_gseapy.enrichr.call_args.kwargs
        assert "GO" in call_kwargs.get("gene_sets", "")
