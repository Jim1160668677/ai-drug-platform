"""Co-Scientist 知识库索引器单元测试 — Phase B7

覆盖：
- CoScientistIndexer: index_run() / auto_index_if_completed() / search_*() / get_stats()
- _build_hypothesis_text() / _build_run_text() 文本构建
- Mock VectorStore 验证索引调用

测试策略：
- AsyncMock 模拟 db.get / db.execute
- patch get_vector_store 模拟向量存储
- 覆盖正常流程、运行不存在、空假设、Mock 降级等场景
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.knowledge.coscientist_indexer import (
    COLLECTION_HYPOTHESES,
    COLLECTION_RUNS,
    CoScientistIndexer,
)


# ============================================================
# 测试数据工厂
# ============================================================


_UNSET = object()


def _make_run(
    *,
    run_id=None,
    status="completed",
    case_type="aml",
    research_goal="Discover AML drug repurposing candidates",
    meta_review="Top hypothesis validated",
    current_round=5,
    max_rounds=5,
    total_cost_usd=0.05,
):
    return SimpleNamespace(
        id=run_id or uuid4(),
        status=status,
        case_type=case_type,
        research_goal=research_goal,
        meta_review=meta_review,
        current_round=current_round,
        max_rounds=max_rounds,
        total_cost_usd=total_cost_usd,
    )


def _make_hypothesis(
    *,
    hyp_id=None,
    name="Test Hypothesis",
    description="A test hypothesis description",
    mechanism="Inhibition of FLT3 pathway",
    evolution_strategy="initial",
    elo_score=1200.0,
    rank=1,
    novelty_score=8.0,
    plausibility_score=7.0,
    status="completed",
):
    return SimpleNamespace(
        id=hyp_id or uuid4(),
        name=name,
        description=description,
        mechanism=mechanism,
        evolution_strategy=evolution_strategy,
        elo_score=elo_score,
        rank=rank,
        novelty_score=novelty_score,
        plausibility_score=plausibility_score,
        status=status,
    )


def _make_db(run=None, hypotheses=None):
    """构造 AsyncSession mock"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=run)

    hyps = hypotheses or []

    async def _execute(stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = hyps
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_vector_store_mock(
    add_count=1,
    search_results=None,
):
    """构造 VectorStore mock"""
    store = MagicMock()
    store._client = MagicMock()  # 非 None，表示已连接
    store.add_documents = AsyncMock(return_value=add_count)
    store.search = AsyncMock(return_value=search_results or [])
    return store


# ============================================================
# 文本构建测试
# ============================================================


class TestBuildHypothesisText:
    """_build_hypothesis_text() 测试"""

    def test_full_hypothesis(self):
        indexer = CoScientistIndexer(db=MagicMock())
        h = _make_hypothesis()
        text = indexer._build_hypothesis_text(h)

        assert "假设: Test Hypothesis" in text
        assert "描述: A test hypothesis description" in text
        assert "机制: Inhibition of FLT3 pathway" in text
        assert "Elo评分: 1200" in text
        assert "排名: #1" in text
        assert "新颖性: 8.0" in text
        assert "可信度: 7.0" in text

    def test_minimal_hypothesis(self):
        """只有 name 的假设"""
        indexer = CoScientistIndexer(db=MagicMock())
        h = SimpleNamespace(
            name="Min Hyp",
            description=None,
            mechanism=None,
            evolution_strategy=None,
            elo_score=None,
            rank=None,
            novelty_score=None,
            plausibility_score=None,
        )
        text = indexer._build_hypothesis_text(h)

        assert "假设: Min Hyp" in text
        # 不应包含未设置的字段
        assert "Elo评分" not in text
        assert "排名" not in text

    def test_empty_hypothesis(self):
        """所有字段为空的假设"""
        indexer = CoScientistIndexer(db=MagicMock())
        h = SimpleNamespace(
            name=None,
            description=None,
            mechanism=None,
            evolution_strategy=None,
            elo_score=None,
            rank=None,
            novelty_score=None,
            plausibility_score=None,
        )
        text = indexer._build_hypothesis_text(h)
        assert text == "（空假设）"

    def test_initial_strategy_not_in_text(self):
        """initial 策略不显示在文本中"""
        indexer = CoScientistIndexer(db=MagicMock())
        h = _make_hypothesis(evolution_strategy="initial")
        text = indexer._build_hypothesis_text(h)
        assert "进化策略" not in text

    def test_non_initial_strategy_in_text(self):
        """非 initial 策略显示在文本中"""
        indexer = CoScientistIndexer(db=MagicMock())
        h = _make_hypothesis(evolution_strategy="enhancement")
        text = indexer._build_hypothesis_text(h)
        assert "进化策略: enhancement" in text


class TestBuildRunText:
    """_build_run_text() 测试"""

    def test_full_run(self):
        indexer = CoScientistIndexer(db=MagicMock())
        run = _make_run()
        text = indexer._build_run_text(run)

        assert "研究目标: Discover AML drug repurposing candidates" in text
        assert "案例类型: aml" in text
        assert "元评审: Top hypothesis validated" in text
        assert "状态: completed" in text
        assert "轮次: 5/5" in text

    def test_minimal_run(self):
        """缺少可选字段的运行"""
        indexer = CoScientistIndexer(db=MagicMock())
        run = SimpleNamespace(
            research_goal="Test goal",
            case_type=None,
            meta_review=None,
            status="running",
            current_round=2,
            max_rounds=5,
        )
        text = indexer._build_run_text(run)

        assert "研究目标: Test goal" in text
        assert "案例类型" not in text
        assert "元评审" not in text
        assert "状态: running" in text


# ============================================================
# index_run() 测试
# ============================================================


class TestIndexRun:
    """CoScientistIndexer.index_run() 测试"""

    @pytest.mark.asyncio
    async def test_index_run_not_found(self):
        """运行不存在时抛出 NotFoundError"""
        db = _make_db(run=None)
        indexer = CoScientistIndexer(db)

        with pytest.raises(NotFoundError):
            await indexer.index_run(uuid4())

    @pytest.mark.asyncio
    async def test_index_run_success(self):
        """成功索引运行（假设 + 运行摘要）"""
        run = _make_run()
        hyps = [_make_hypothesis(), _make_hypothesis(name="Hyp B")]
        db = _make_db(run=run, hypotheses=hyps)

        store_mock = _make_vector_store_mock(add_count=2)

        indexer = CoScientistIndexer(db)
        # get_vector_store 在方法内部导入，需 patch 源模块
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            result = await indexer.index_run(run.id)

        assert result["run_id"] == str(run.id)
        assert result["hypotheses_indexed"] == 2
        assert result["run_indexed"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_index_run_empty_hypotheses(self):
        """空假设列表仍索引运行摘要"""
        run = _make_run()
        db = _make_db(run=run, hypotheses=[])

        store_mock = _make_vector_store_mock(add_count=1)

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            result = await indexer.index_run(run.id)

        assert result["hypotheses_indexed"] == 0
        assert result["run_indexed"] is True

    @pytest.mark.asyncio
    async def test_index_run_vector_store_failure(self):
        """向量存储失败时记录错误但不抛异常"""
        run = _make_run()
        hyps = [_make_hypothesis()]
        db = _make_db(run=run, hypotheses=hyps)

        store_mock = MagicMock()
        store_mock._client = MagicMock()
        store_mock.add_documents = AsyncMock(side_effect=RuntimeError("ChromaDB down"))

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            result = await indexer.index_run(run.id)

        # 索引失败不抛异常，记录到 errors
        assert len(result["errors"]) > 0
        assert "RuntimeError" in result["errors"][0]


# ============================================================
# auto_index_if_completed() 测试
# ============================================================


class TestAutoIndex:
    """CoScientistIndexer.auto_index_if_completed() 测试"""

    @pytest.mark.asyncio
    async def test_auto_index_completed(self):
        """完成的运行自动索引"""
        run = _make_run(status="completed")
        hyps = [_make_hypothesis()]
        db = _make_db(run=run, hypotheses=hyps)

        store_mock = _make_vector_store_mock(add_count=1)

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            result = await indexer.auto_index_if_completed(run.id)

        assert result is not None
        assert result["hypotheses_indexed"] == 1

    @pytest.mark.asyncio
    async def test_auto_index_not_completed(self):
        """未完成的运行不索引"""
        run = _make_run(status="running")
        db = _make_db(run=run)

        indexer = CoScientistIndexer(db)
        result = await indexer.auto_index_if_completed(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_auto_index_not_found(self):
        """运行不存在返回 None"""
        db = _make_db(run=None)
        indexer = CoScientistIndexer(db)

        result = await indexer.auto_index_if_completed(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_index_failed_status(self):
        """失败的运行不索引"""
        run = _make_run(status="failed")
        db = _make_db(run=run)

        indexer = CoScientistIndexer(db)
        result = await indexer.auto_index_if_completed(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_auto_index_cancelled_status(self):
        """取消的运行不索引"""
        run = _make_run(status="cancelled")
        db = _make_db(run=run)

        indexer = CoScientistIndexer(db)
        result = await indexer.auto_index_if_completed(run.id)

        assert result is None


# ============================================================
# 搜索方法测试
# ============================================================


class TestSearchHypotheses:
    """CoScientistIndexer.search_hypotheses() 测试"""

    @pytest.mark.asyncio
    async def test_search_with_results(self):
        """搜索返回结果"""
        db = _make_db()
        search_results = [
            {"id": "hyp-1", "text": "AML target", "similarity": 0.95, "metadata": {}},
            {"id": "hyp-2", "text": "Drug repurposing", "similarity": 0.85, "metadata": {}},
        ]
        store_mock = _make_vector_store_mock(search_results=search_results)

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            results = await indexer.search_hypotheses("AML drug targets", top_k=5)

        assert len(results) == 2
        assert results[0]["similarity"] == 0.95
        store_mock.search.assert_called_once_with(
            query="AML drug targets",
            collection=COLLECTION_HYPOTHESES,
            top_k=5,
        )

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """搜索无结果"""
        db = _make_db()
        store_mock = _make_vector_store_mock(search_results=[])

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            results = await indexer.search_hypotheses("nonexistent topic")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_top_k_clamped(self):
        """top_k 超出范围时被限制"""
        db = _make_db()
        store_mock = _make_vector_store_mock(search_results=[])

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            await indexer.search_hypotheses("test", top_k=100)

        # top_k 应被限制为 50
        call_args = store_mock.search.call_args
        assert call_args.kwargs["top_k"] == 50

    @pytest.mark.asyncio
    async def test_search_top_k_minimum(self):
        """top_k 小于 1 时被限制为 1"""
        db = _make_db()
        store_mock = _make_vector_store_mock(search_results=[])

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            await indexer.search_hypotheses("test", top_k=0)

        call_args = store_mock.search.call_args
        assert call_args.kwargs["top_k"] == 1


class TestSearchRuns:
    """CoScientistIndexer.search_runs() 测试"""

    @pytest.mark.asyncio
    async def test_search_with_results(self):
        db = _make_db()
        search_results = [
            {"id": "run-1", "text": "AML study", "similarity": 0.9, "metadata": {}},
        ]
        store_mock = _make_vector_store_mock(search_results=search_results)

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            results = await indexer.search_runs("AML", top_k=3)

        assert len(results) == 1
        store_mock.search.assert_called_once_with(
            query="AML",
            collection=COLLECTION_RUNS,
            top_k=3,
        )


class TestSearchAll:
    """CoScientistIndexer.search_all() 测试"""

    @pytest.mark.asyncio
    async def test_search_all_combines_results(self):
        """同时搜索假设和运行"""
        db = _make_db()
        hyp_results = [{"id": "hyp-1", "text": "hyp", "similarity": 0.9}]
        run_results = [{"id": "run-1", "text": "run", "similarity": 0.8}]

        store_mock = MagicMock()
        store_mock._client = MagicMock()
        store_mock.search = AsyncMock(
            side_effect=[hyp_results, run_results]
        )

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            result = await indexer.search_all("query", top_k=5)

        assert "hypotheses" in result
        assert "runs" in result
        assert len(result["hypotheses"]) == 1
        assert len(result["runs"]) == 1


# ============================================================
# get_stats() 测试
# ============================================================


class TestGetStats:
    """CoScientistIndexer.get_stats() 测试"""

    @pytest.mark.asyncio
    async def test_stats_structure(self):
        """统计信息结构完整性"""
        db = _make_db()
        store_mock = MagicMock()
        store_mock._client = MagicMock()  # 非 None

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            stats = await indexer.get_stats()

        assert "collections" in stats
        assert COLLECTION_HYPOTHESES in stats["collections"]
        assert COLLECTION_RUNS in stats["collections"]
        assert stats["vector_store_available"] is True
        assert "note" in stats

    @pytest.mark.asyncio
    async def test_stats_store_unavailable(self):
        """向量存储不可用时"""
        db = _make_db()
        store_mock = MagicMock()
        store_mock._client = None  # 未连接

        indexer = CoScientistIndexer(db)
        with patch(
            "app.services.knowledge.vector.get_vector_store",
            return_value=store_mock,
        ):
            stats = await indexer.get_stats()

        assert stats["vector_store_available"] is False
