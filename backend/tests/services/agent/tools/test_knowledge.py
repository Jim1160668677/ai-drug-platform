"""knowledge 工具组测试 — 2 个工具"""
from unittest.mock import AsyncMock, MagicMock, patch
from collections import namedtuple

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.knowledge import (
    QueryKnowledgeBaseTool,
    SearchLiteratureTool,
)


def _make_ctx(db=None, user=None):
    return ToolContext(
        db=db or MagicMock(),
        user=user or MagicMock(),
        task_id="task-k",
        session_id="session-k",
    )


def _make_user(role=UserRole.FOUNDER):
    u = MagicMock()
    u.role = role
    return u


# ========== SearchLiteratureTool ==========


@pytest.mark.asyncio
async def test_search_literature_success():
    """成功：RAGEngine.retrieve 返回命名元组"""
    RetrievalResult = namedtuple("RetrievalResult", ["documents", "retrieval_mode"])
    mock_result = RetrievalResult(
        documents=[{"id": "d1", "title": "EGFR paper", "content": "..."}],
        retrieval_mode="vector",
    )

    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        tool = SearchLiteratureTool()
        ctx = _make_ctx(user=_make_user())
        result = await tool.execute({"query": "EGFR"}, ctx)

    assert result.success is True
    assert result.data["total"] == 1
    assert result.data["retrieval_mode"] == "vector"
    assert result.display["type"] == "literature_list"


@pytest.mark.asyncio
async def test_search_literature_dict_result():
    """RAGEngine.retrieve 返回 dict 形式"""
    mock_result = {"documents": [{"id": "d1"}], "retrieval_mode": "jaccard"}

    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        tool = SearchLiteratureTool()
        ctx = _make_ctx(user=_make_user())
        result = await tool.execute({"query": "test"}, ctx)

    assert result.success is True
    assert result.data["total"] == 1


@pytest.mark.asyncio
async def test_search_literature_top_k_clamped():
    """top_k=100 → 内部 clamp 到 20"""
    RetrievalResult = namedtuple("RetrievalResult", ["documents", "retrieval_mode"])
    mock_result = RetrievalResult(documents=[], retrieval_mode="auto")

    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_retrieve:
        tool = SearchLiteratureTool()
        ctx = _make_ctx(user=_make_user())
        await tool.execute({"query": "x", "top_k": 100}, ctx)
        # top_k 应被 clamp 到 20
        assert mock_retrieve.call_args.kwargs["top_k"] == 20


@pytest.mark.asyncio
async def test_search_literature_rag_raises():
    """RAGEngine 抛异常 → fail"""
    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        side_effect=RuntimeError("chromadb down"),
    ):
        tool = SearchLiteratureTool()
        ctx = _make_ctx(user=_make_user())
        result = await tool.execute({"query": "x"}, ctx)

    assert result.success is False
    assert "chromadb down" in result.error


# ========== QueryKnowledgeBaseTool ==========


@pytest.mark.asyncio
async def test_query_knowledge_base_success():
    """成功：retrieve + build_context"""
    RetrievalResult = namedtuple("RetrievalResult", ["documents", "retrieval_mode"])
    mock_retrieval = RetrievalResult(
        documents=[{"id": "d1", "title": "doc1"}],
        retrieval_mode="vector",
    )

    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        return_value=mock_retrieval,
    ), patch(
        "app.services.llm.rag.RAGEngine.build_context",
        new_callable=AsyncMock,
        return_value={"answer": "EGFR 是一种受体酪氨酸激酶"},
    ):
        tool = QueryKnowledgeBaseTool()
        ctx = _make_ctx(user=_make_user())
        result = await tool.execute({"question": "什么是 EGFR?"}, ctx)

    assert result.success is True
    assert result.data["answer"] == "EGFR 是一种受体酪氨酸激酶"
    assert result.data["question"] == "什么是 EGFR?"
    assert result.display["type"] == "knowledge_answer"


@pytest.mark.asyncio
async def test_query_knowledge_base_llm_failure():
    """build_context 抛异常 → fail"""
    RetrievalResult = namedtuple("RetrievalResult", ["documents", "retrieval_mode"])
    mock_retrieval = RetrievalResult(documents=[], retrieval_mode="auto")

    with patch(
        "app.services.llm.rag.RAGEngine.retrieve",
        new_callable=AsyncMock,
        return_value=mock_retrieval,
    ), patch(
        "app.services.llm.rag.RAGEngine.build_context",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM timeout"),
    ):
        tool = QueryKnowledgeBaseTool()
        ctx = _make_ctx(user=_make_user())
        result = await tool.execute({"question": "x"}, ctx)

    assert result.success is False
    assert "LLM timeout" in result.error
