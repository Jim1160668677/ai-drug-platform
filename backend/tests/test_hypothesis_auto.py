"""假设自动生成器单元测试"""
import pytest

from app.services.knowledge.hypothesis_generator import HypothesisGenerator


@pytest.fixture
def generator():
    """HypothesisGenerator 实例 — db 传 None（generate 方法不直接依赖 db 查询时）"""
    return HypothesisGenerator(db=None)


class TestHypothesisGenerator:

    @pytest.mark.asyncio
    async def test_generate_from_de_results(self, generator):
        """测试基于 DE 结果生成假设"""
        context = {
            "de_genes": [
                {"gene": "TP53", "log2fc": 2.5, "pvalue": 0.001},
                {"gene": "EGFR", "log2fc": 1.8, "pvalue": 0.005},
            ],
            "pathways": [
                {"name": "p53 signaling pathway", "pvalue": 0.001},
            ],
        }
        result = await generator.generate("project-1", context, max_hypotheses=5)

        assert isinstance(result, list)
        assert len(result) > 0
        # 应该生成靶点假设
        hyp = result[0]
        assert "title" in hyp
        assert "description" in hyp
        assert "supporting_evidence" in hyp
        assert "verification_method" in hyp
        assert "confidence" in hyp
        assert "category" in hyp

    @pytest.mark.asyncio
    async def test_generate_from_pathway(self, generator):
        """测试基于通路富集生成假设"""
        context = {
            "de_genes": [
                {"gene": "KRAS", "log2fc": 1.5, "pvalue": 0.01},
            ],
            "pathways": [
                {"name": "MAPK signaling pathway", "pvalue": 0.001},
                {"name": "ERK signaling", "pvalue": 0.005},
            ],
        }
        result = await generator.generate("project-1", context, max_hypotheses=3)

        assert len(result) > 0
        # 应该包含通路相关假设
        titles = [h["title"] for h in result]
        assert any("MAPK" in t or "通路" in t or "靶点" in t for t in titles)

    @pytest.mark.asyncio
    async def test_generate_from_molecules(self, generator):
        """测试基于分子设计结果生成假设"""
        context = {
            "molecules": [
                {"smiles": "CCO", "composite_score": 0.85, "properties": {"druglikeness_score": 75}},
                {"smiles": "c1ccccc1", "composite_score": 0.72, "properties": {"druglikeness_score": 65}},
            ],
        }
        result = await generator.generate("project-1", context, max_hypotheses=5)

        assert len(result) > 0
        # 应该包含分子设计相关假设
        categories = [h["category"] for h in result]
        assert "molecule_design" in categories or "default" in categories

    @pytest.mark.asyncio
    async def test_generate_from_clinical(self, generator):
        """测试基于临床反馈生成假设"""
        context = {
            "clinical_feedbacks": [
                {"efficacy": "progressive", "adverse_reactions": ["恶心", "呕吐", "头痛"]},
                {"efficacy": "partial", "adverse_reactions": ["皮疹"]},
            ],
        }
        result = await generator.generate("project-1", context, max_hypotheses=5)

        assert len(result) > 0
        # 应该包含方案优化假设
        categories = [h["category"] for h in result]
        assert "treatment_optimization" in categories or "default" in categories

    @pytest.mark.asyncio
    async def test_generate_confidence_score(self, generator):
        """测试置信度计算"""
        context = {
            "de_genes": [
                {"gene": "TP53", "log2fc": 2.5, "pvalue": 0.001},
            ],
            "pathways": [
                {"name": "p53 pathway", "pvalue": 0.001},
            ],
        }
        result = await generator.generate("project-1", context, max_hypotheses=5)

        for hyp in result:
            assert 0.0 <= hyp["confidence"] <= 1.0, f"置信度 {hyp['confidence']} 超出 [0,1] 范围"

    @pytest.mark.asyncio
    async def test_generate_max_limit(self, generator):
        """测试最大数量限制"""
        context = {
            "de_genes": [{"gene": f"GENE{i}", "log2fc": 1.0, "pvalue": 0.01} for i in range(20)],
            "pathways": [{"name": f"Pathway{i}", "pvalue": 0.01} for i in range(10)],
            "molecules": [{"smiles": f"C{'C'*i}", "composite_score": 0.5, "properties": {"druglikeness_score": 70}} for i in range(5)],
            "clinical_feedbacks": [{"efficacy": "progressive", "adverse_reactions": ["a", "b", "c"]}],
            "clusters": [{"id": i} for i in range(3)],
        }
        result = await generator.generate("project-1", context, max_hypotheses=3)

        assert len(result) <= 3, f"生成 {len(result)} 个假设，超过最大限制 3"

    @pytest.mark.asyncio
    async def test_generate_default_hypothesis(self, generator):
        """测试无数据时生成默认假设"""
        result = await generator.generate("project-1", {}, max_hypotheses=5)

        assert len(result) > 0
        assert result[0]["category"] == "default"
        assert result[0]["confidence"] < 0.5

    @pytest.mark.asyncio
    async def test_generate_sorted_by_confidence(self, generator):
        """测试结果按置信度降序排列"""
        context = {
            "de_genes": [{"gene": "TP53", "log2fc": 2.5, "pvalue": 0.001}],
            "pathways": [{"name": "p53 pathway", "pvalue": 0.001}],
            "molecules": [{"smiles": "CCO", "composite_score": 0.8, "properties": {"druglikeness_score": 75}}],
            "clinical_feedbacks": [{"efficacy": "progressive", "adverse_reactions": ["a", "b", "c"]}],
        }
        result = await generator.generate("project-1", context, max_hypotheses=10)

        confidences = [h["confidence"] for h in result]
        assert confidences == sorted(confidences, reverse=True), "假设未按置信度降序排列"
