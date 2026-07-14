"""生信分析引擎单元测试"""
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
