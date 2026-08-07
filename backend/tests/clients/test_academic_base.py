"""AcademicPaper 类型与 AcademicClientBase 基类接口契约测试"""
import pytest

from app.clients.base import AcademicClientBase, AcademicPaper


class TestAcademicPaper:
    """AcademicPaper 共享数据模型"""

    def test_can_instantiate_with_required_fields(self):
        """必填字段:title/authors/source"""
        paper = AcademicPaper(
            title="EGFR mutations in NSCLC",
            authors=["Lynch TJ", "Bell DW"],
            source="biorxiv",
        )
        assert paper.title == "EGFR mutations in NSCLC"
        assert paper.authors == ["Lynch TJ", "Bell DW"]
        assert paper.source == "biorxiv"

    def test_optional_fields_default_none(self):
        """可选字段:abstract/doi/year/url/relevance_score 默认 None"""
        paper = AcademicPaper(title="T", authors=[], source="arxiv")
        assert paper.abstract is None
        assert paper.doi is None
        assert paper.year is None
        assert paper.url is None
        assert paper.relevance_score is None

    def test_full_fields(self):
        """全字段实例化"""
        paper = AcademicPaper(
            title="Osimertinib FLAURA",
            authors=["Soria JC"],
            abstract="Phase III trial",
            doi="10.1056/NEJMoa2401234",
            source="semantic_scholar",
            year=2024,
            url="https://example.com/paper",
            relevance_score=0.95,
        )
        assert paper.doi == "10.1056/NEJMoa2401234"
        assert paper.year == 2024
        assert paper.relevance_score == 0.95


class TestAcademicClientBase:
    """AcademicClientBase 抽象基类契约"""

    def test_cannot_instantiate_directly(self):
        """抽象基类不能直接实例化"""
        with pytest.raises(TypeError):
            AcademicClientBase()  # type: ignore[abstract]

    def test_subclass_must_implement_search(self):
        """未实现 search 的子类不能实例化"""

        class IncompleteClient(AcademicClientBase):
            pass

        with pytest.raises(TypeError):
            IncompleteClient()  # type: ignore[abstract]

    def test_subclass_with_search_can_instantiate(self):
        """实现 search 的子类可实例化"""

        class DummyClient(AcademicClientBase):
            source_name = "dummy"

            async def search(self, query, limit=10, **kwargs):
                return [AcademicPaper(title=query, authors=[], source="dummy")]

        client = DummyClient()
        assert client.source_name == "dummy"

    @pytest.mark.asyncio
    async def test_search_returns_list_of_academic_paper(self):
        """search 返回 AcademicPaper 列表"""

        class DummyClient(AcademicClientBase):
            source_name = "dummy"

            async def search(self, query, limit=10, **kwargs):
                return [AcademicPaper(title=query, authors=[], source="dummy")]

        client = DummyClient()
        results = await client.search("EGFR", limit=5)
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], AcademicPaper)
        assert results[0].title == "EGFR"
