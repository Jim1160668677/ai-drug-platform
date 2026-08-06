"""search_academic 工具测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agent.tools.academic_search import SearchAcademicTool
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register_all()
    return reg


def test_tool_registered(registry):
    tool = registry.get_tool("search_academic")
    assert tool is not None
    assert tool.name == "search_academic"


def test_tool_schema(registry):
    tool = registry.get_tool("search_academic")
    schema = tool.to_schema()
    assert schema["type"] == "object"
    assert "query" in schema["properties"]
    assert "source" in schema["properties"]
    assert "limit" in schema["properties"]
    assert "year_from" in schema["properties"]
    assert "year_to" in schema["properties"]
    assert schema["required"] == ["query", "source"]


def test_tool_info(registry):
    tool = registry.get_tool("search_academic")
    info = tool.to_info()
    assert info["name"] == "search_academic"
    assert info["side_effects"] is False
    assert info["required_role"] == "researcher"


@pytest.mark.asyncio
async def test_tool_execute_success():
    tool = SearchAcademicTool()
    fake_papers = [
        MagicMock(
            title="P1",
            authors=["A"],
            abstract="ab",
            doi="d1",
            source="biorxiv",
            year=2024,
            url="http://x",
            relevance_score=0.9,
        ),
        MagicMock(
            title="P2",
            authors=["B"],
            abstract="cd",
            doi="d2",
            source="biorxiv",
            year=2023,
            url="http://y",
            relevance_score=0.7,
        ),
    ]
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(return_value=fake_papers)
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        result = await tool.execute(
            {"query": "cancer", "source": "biorxiv", "limit": 5}, ctx
        )
    assert result.success
    assert result.data["total"] == 2
    assert result.data["source"] == "biorxiv"
    assert result.data["query"] == "cancer"
    assert len(result.data["articles"]) == 2
    assert result.data["articles"][0]["title"] == "P1"
    assert result.display["type"] == "literature_list"
    assert len(result.display["payload"]["articles"]) == 2


@pytest.mark.asyncio
async def test_tool_execute_empty_results():
    tool = SearchAcademicTool()
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(return_value=[])
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        result = await tool.execute(
            {"query": "obscure_topic", "source": "arxiv", "limit": 10}, ctx
        )
    assert result.success
    assert result.data["total"] == 0
    assert result.data["articles"] == []


@pytest.mark.asyncio
async def test_tool_execute_client_error():
    tool = SearchAcademicTool()
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(side_effect=RuntimeError("network error"))
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        result = await tool.execute(
            {"query": "test", "source": "crossref"}, ctx
        )
    assert not result.success
    assert "network error" in result.error


@pytest.mark.asyncio
async def test_tool_execute_default_limit():
    tool = SearchAcademicTool()
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(return_value=[])
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        await tool.execute({"query": "test", "source": "semantic_scholar"}, ctx)
    MC.return_value.search.assert_called_once_with(
        "semantic_scholar", "test", 10, None, None
    )


@pytest.mark.asyncio
async def test_tool_execute_clamps_limit():
    tool = SearchAcademicTool()
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(return_value=[])
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        await tool.execute(
            {"query": "test", "source": "pubmed", "limit": 100}, ctx
        )
    MC.return_value.search.assert_called_once_with(
        "pubmed", "test", 50, None, None
    )


@pytest.mark.asyncio
async def test_tool_execute_with_years():
    tool = SearchAcademicTool()
    with patch("app.services.analyzer.academic_search_client.AcademicSearchClient") as MC:
        MC.return_value.search = AsyncMock(return_value=[])
        ctx = ToolContext(user=MagicMock(), db=MagicMock(), task_id="t1", session_id="s1")
        await tool.execute(
            {"query": "test", "source": "biorxiv", "limit": 5, "year_from": 2020, "year_to": 2024},
            ctx,
        )
    MC.return_value.search.assert_called_once_with(
        "biorxiv", "test", 5, 2020, 2024
    )
