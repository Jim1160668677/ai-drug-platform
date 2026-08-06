"""AcademicSearchClient 单元测试"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.clients.base import AcademicPaper
from app.services.analyzer.academic_search_client import AcademicSearchClient


@pytest_asyncio.fixture
def client():
    """AcademicSearchClient 实例"""
    return AcademicSearchClient()


def _make_paper(
    title: str,
    source: str,
    doi: str = None,
    year: int = 2024,
    relevance_score: float = None,
) -> AcademicPaper:
    """快速构造 AcademicPaper"""
    return AcademicPaper(
        title=title,
        authors=["Author A"],
        source=source,
        abstract=f"Abstract for {title}",
        doi=doi,
        year=year,
        url=f"https://example.com/{doi}" if doi else None,
        relevance_score=relevance_score,
    )


@pytest.mark.asyncio
async def test_search_all_parallel(client):
    """测试并行聚合查询 — mock 2 个数据源"""
    pubmed_papers = [
        _make_paper("PubMed Paper 1", "pubmed", "10.1000/abc", 2024, 0.9),
        _make_paper("PubMed Paper 2", "pubmed", "10.1000/def", 2023, 0.7),
    ]
    arxiv_papers = [
        _make_paper("ArXiv Paper 1", "arxiv", "10.48550/arxiv.123", 2024, 0.85),
    ]

    mock_ncbi = AsyncMock()
    mock_ncbi.search_pubmed = AsyncMock(
        return_value=[
            {
                "uid": "12345",
                "title": "PubMed Paper 1",
                "authors": [{"name": "Author A"}],
                "pubdate": "2024-01-15",
                "abstract": "Abstract for PubMed Paper 1",
                "doi": "10.1000/abc",
            },
            {
                "uid": "67890",
                "title": "PubMed Paper 2",
                "authors": [{"name": "Author A"}],
                "pubdate": "2023-06-01",
                "abstract": "Abstract for PubMed Paper 2",
                "doi": "10.1000/def",
            },
        ]
    )

    mock_arxiv = MagicMock()
    mock_arxiv.search = AsyncMock(return_value=arxiv_papers)

    with patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_pubmed",
        new_callable=AsyncMock,
        return_value=mock_ncbi,
    ), patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_client",
        new_callable=AsyncMock,
        return_value=mock_arxiv,
    ):
        results = await client.search_all(
            "EGFR lung cancer",
            sources=["pubmed", "arxiv"],
            limit_per_source=5,
        )

    assert "pubmed" in results
    assert "arxiv" in results
    assert len(results["pubmed"]) == 2
    assert len(results["arxiv"]) == 1
    assert results["pubmed"][0].title == "PubMed Paper 1"
    assert results["pubmed"][0].source == "pubmed"
    assert results["pubmed"][0].doi == "10.1000/abc"
    assert results["arxiv"][0].title == "ArXiv Paper 1"


@pytest.mark.asyncio
async def test_search_invalid_source_raises_value_error(client):
    """测试无效数据源抛出 ValueError"""
    with pytest.raises(ValueError, match="无效数据源"):
        await client.search("invalid_source", "test query")


@pytest.mark.asyncio
async def test_search_exception_degrades_to_empty_list(client):
    """测试单个数据源异常降级为空列表,不阻塞其他源"""
    arxiv_papers = [_make_paper("ArXiv Paper 1", "arxiv", "10.48550/x1")]

    mock_ncbi = AsyncMock()
    mock_ncbi.search_pubmed = AsyncMock(side_effect=Exception("Network error"))

    mock_arxiv = MagicMock()
    mock_arxiv.search = AsyncMock(return_value=arxiv_papers)

    with patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_pubmed",
        new_callable=AsyncMock,
        return_value=mock_ncbi,
    ), patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_client",
        new_callable=AsyncMock,
        return_value=mock_arxiv,
    ):
        results = await client.search_all(
            "test query",
            sources=["pubmed", "arxiv"],
            limit_per_source=5,
        )

    assert results["pubmed"] == []
    assert len(results["arxiv"]) == 1


def test_duplicate_by_doi_keeps_higher_relevance():
    """测试 DOI 去重 — 保留更高 relevance_score"""
    papers = [
        _make_paper("Paper A", "pubmed", "10.1000/ABC", 2024, 0.7),
        _make_paper("Paper B", "arxiv", "10.1000/abc", 2024, 0.9),
        _make_paper("Paper C", "crossref", "10.1000/xyz", 2023, 0.5),
    ]
    deduped = AcademicSearchClient.deduplicate(papers)
    assert len(deduped) == 2
    doi_abc = [p for p in deduped if p.doi and p.doi.lower() == "10.1000/abc"]
    assert len(doi_abc) == 1
    assert doi_abc[0].relevance_score == 0.9


def test_sort_by_relevance(client):
    """测试相关性排序 — score 降序(None 在后),year 降序"""
    papers = [
        _make_paper("Low", "arxiv", "10.0001/1", 2020, 0.3),
        _make_paper("High", "arxiv", "10.0001/2", 2022, 0.9),
        _make_paper("None1", "arxiv", "10.0001/3", 2023, None),
        _make_paper("Medium", "arxiv", "10.0001/4", 2021, 0.6),
        _make_paper("None2", "arxiv", "10.0001/5", 2019, None),
    ]
    sorted_papers = AcademicSearchClient.sort_by_relevance(papers)
    assert sorted_papers[0].title == "High"
    assert sorted_papers[1].title == "Medium"
    assert sorted_papers[2].title == "Low"
    # None scores at end, sorted by year desc
    assert sorted_papers[3].title == "None1"
    assert sorted_papers[4].title == "None2"


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(client):
    """测试超时返回空列表"""
    async def slow_search(*args, **kwargs):
        await asyncio.sleep(20)
        return []

    mock_ncbi = AsyncMock()
    mock_ncbi.search_pubmed = AsyncMock(side_effect=slow_search)

    with patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_pubmed",
        new_callable=AsyncMock,
        return_value=mock_ncbi,
    ):
        result = await client.search("pubmed", "test", limit=5)

    assert result == []


@pytest.mark.asyncio
async def test_search_source_exception_does_not_block_others(client):
    """测试单个数据源异常不阻塞其他源"""
    good = _make_paper("Good", "biorxiv", "10.1234/good", 2024, 0.8)

    mock_biorxiv = MagicMock()
    mock_biorxiv.search = AsyncMock(return_value=[good])

    mock_arxiv = MagicMock()
    mock_arxiv.search = AsyncMock(side_effect=RuntimeError("network error"))

    def _get_client_side_effect(source):
        if source == "biorxiv":
            return mock_biorxiv
        elif source == "arxiv":
            return mock_arxiv
        return MagicMock()

    with patch(
        "app.services.analyzer.academic_search_client.AcademicSearchClient._get_client",
        new_callable=AsyncMock,
        side_effect=_get_client_side_effect,
    ):
        result = await client.search_all("test", ["biorxiv", "arxiv"])

    assert len(result["biorxiv"]) == 1
    assert result["arxiv"] == []


@pytest.mark.asyncio
async def test_search_invalid_source_raises(client):
    """测试无效数据源抛出 ValueError"""
    with pytest.raises(ValueError, match="无效数据源"):
        await client.search("invalid_db", "test")


def test_deduplicate_by_doi(client):
    """测试 DOI 去重 — 保留更高 relevance_score"""
    p1 = _make_paper("Title A", "biorxiv", "10.1234/same", 2024, 0.6)
    p2 = _make_paper("Title B", "arxiv", "10.1234/same", 2024, 0.9)
    p3 = _make_paper("Title C", "crossref", "10.1234/other", 2023, 0.5)
    result = client.deduplicate([p1, p2, p3])
    dois = [p.doi for p in result]
    assert "10.1234/same" in dois and "10.1234/other" in dois
    kept = [p for p in result if p.doi == "10.1234/same"]
    assert len(kept) == 1 and kept[0].relevance_score == 0.9


def test_sort_by_relevance_mixed_scores(client):
    """测试相关性排序 — 混合 score(None + float),None 排最后"""
    papers = [
        _make_paper("A", "biorxiv", "10.0001/a", 2024, None),
        _make_paper("B", "arxiv", "10.0001/b", 2024, 0.9),
        _make_paper("C", "crossref", "10.0001/c", 2024, 0.5),
    ]
    result = AcademicSearchClient.sort_by_relevance(papers)
    assert result[0].doi == "10.0001/b" and result[1].doi == "10.0001/c"
    assert result[-1].doi == "10.0001/a"
