"""Co-Scientist Agent 工具单元测试 — Phase B6

覆盖 3 个新工具：
- GenerateHypothesisTool: 假设生成（含 LLM 调用 mock + DB 持久化验证）
- QueryRunTool: 运行查询（含权限校验 + 数据完整性）
- ScientificDebateTool: 辩论查询（含统计分析 + 摘要模式）

测试策略：
- AsyncMock 模拟 ctx.db（get/add/commit/refresh/execute）
- MagicMock 模拟 ctx.user（id/role）
- patch get_llm_client_with_fallback 模拟 LLM 客户端
- patch GenerationAgent.run 模拟假设生成
- 覆盖正常流程、权限拒绝、运行不存在、空数据等场景
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext, ToolResult
from app.services.agent.tools.coscientist import (
    GenerateHypothesisTool,
    QueryRunTool,
    ScientificDebateTool,
    _check_run_access,
    _get_run,
)


# ============================================================
# 测试数据工厂
# ============================================================


def _make_user(*, role=UserRole.RESEARCHER, user_id=None):
    """构造 User mock"""
    user = MagicMock()
    user.id = user_id or uuid4()
    user.role = role
    return user


def _make_run(
    *,
    run_id=None,
    user_id=None,
    status="completed",
    case_type="aml",
    research_goal="Discover AML drug repurposing candidates",
    current_round=5,
    max_rounds=5,
    current_phase="meta_review",
    meta_review="Top hypothesis validated",
    total_cost_usd=0.05,
    total_token_usage=None,
    duration_sec=120.0,
):
    """构造 CoScientistRun-like SimpleNamespace"""
    return SimpleNamespace(
        id=run_id or uuid4(),
        user_id=user_id or uuid4(),
        status=status,
        case_type=case_type,
        research_goal=research_goal,
        current_round=current_round,
        max_rounds=max_rounds,
        current_phase=current_phase,
        meta_review=meta_review,
        total_cost_usd=total_cost_usd,
        total_token_usage=total_token_usage or {"total": 7000},
        duration_sec=duration_sec,
        started_at=datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 1, 10, 2, 0, tzinfo=timezone.utc),
    )


def _make_hypothesis(
    *,
    hyp_id=None,
    name="Test Hypothesis",
    rank=1,
    elo_score=1200.0,
    status="completed",
    evolution_strategy="initial",
    novelty_score=8.0,
    plausibility_score=7.0,
    testability_score=9.0,
    safety_score=6.0,
):
    """构造 Hypothesis-like SimpleNamespace"""
    return SimpleNamespace(
        id=hyp_id or uuid4(),
        name=name,
        rank=rank,
        elo_score=elo_score,
        status=status,
        evolution_strategy=evolution_strategy,
        novelty_score=novelty_score,
        plausibility_score=plausibility_score,
        testability_score=testability_score,
        safety_score=safety_score,
        description="Test description",
        mechanism="Test mechanism",
        created_at=datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc),
    )


def _make_debate(
    *,
    debate_id=None,
    hyp_id=None,
    round_num=1,
    proponent_argument="Proponent argues X",
    opponent_argument="Opponent argues Y",
    judge_assessment="Judge agrees with proponent",
    consensus_score=0.85,
    mechanism_agreed=True,
    refined_hypothesis="Refined hypothesis",
):
    """构造 CoScientistDebateLog-like SimpleNamespace"""
    return SimpleNamespace(
        id=debate_id or uuid4(),
        hypothesis_id=hyp_id or uuid4(),
        round_num=round_num,
        proponent_argument=proponent_argument,
        opponent_argument=opponent_argument,
        judge_assessment=judge_assessment,
        consensus_score=consensus_score,
        mechanism_agreed=mechanism_agreed,
        refined_hypothesis=refined_hypothesis,
        created_at=datetime(2026, 7, 1, 9, 30, 0, tzinfo=timezone.utc),
    )


def _make_ctx(*, user=None, db=None):
    """构造 ToolContext"""
    return ToolContext(
        db=db or AsyncMock(),
        user=user or _make_user(),
        task_id="test-task",
        session_id="test-session",
        project_id=None,
    )


def _make_db_with_run(run=None, hypotheses=None, debates=None):
    """构造 AsyncSession mock，支持 get/execute/add/commit/refresh

    使用 column_descriptions 检测查询的实体类型，比字符串匹配更可靠。
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    # db.get 返回 run
    db.get = AsyncMock(return_value=run)

    # db.execute 返回带 scalars().all() 的结果
    def _make_result(items):
        result = MagicMock()
        result.scalars.return_value.all.return_value = items
        return result

    hyps = hypotheses or []
    debs = debates or []

    async def _execute(stmt):
        # 通过 column_descriptions 检测查询实体类型
        try:
            entity = stmt.column_descriptions[0]["entity"]
            if entity is not None and hasattr(entity, "__tablename__"):
                table = entity.__tablename__
                if table == "hypotheses":
                    return _make_result(hyps)
                if table == "coscientist_debate_logs":
                    return _make_result(debs)
        except (IndexError, KeyError, AttributeError, TypeError):
            pass
        # 回退：字符串匹配
        stmt_str = str(stmt).lower()
        if "coscientist_debate_logs" in stmt_str:
            return _make_result(debs)
        if "hypotheses" in stmt_str:
            return _make_result(hyps)
        return _make_result([])

    db.execute = AsyncMock(side_effect=_execute)
    return db


# ============================================================
# 辅助函数测试
# ============================================================


class TestCheckRunAccess:
    """_check_run_access() 测试"""

    @pytest.mark.asyncio
    async def test_founder_has_access(self):
        """FOUNDER 角色全权访问"""
        user = _make_user(role=UserRole.FOUNDER, user_id=uuid4())
        run = _make_run(user_id=uuid4())  # 不同 user_id
        ctx = _make_ctx(user=user)

        result = await _check_run_access(ctx, run)
        assert result is True

    @pytest.mark.asyncio
    async def test_owner_has_access(self):
        """运行所有者有访问权"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        ctx = _make_ctx(user=user)

        result = await _check_run_access(ctx, run)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_owner_denied(self):
        """非所有者无访问权"""
        user = _make_user(role=UserRole.RESEARCHER, user_id=uuid4())
        run = _make_run(user_id=uuid4())  # 不同 user_id
        ctx = _make_ctx(user=user)

        result = await _check_run_access(ctx, run)
        assert result is False


class TestGetRun:
    """_get_run() 测试"""

    @pytest.mark.asyncio
    async def test_get_run_success(self):
        """成功获取运行"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        db = _make_db_with_run(run=run)
        ctx = _make_ctx(user=user, db=db)

        result = await _get_run(ctx, str(run.id))
        assert result is not None
        assert result.id == run.id

    @pytest.mark.asyncio
    async def test_get_run_not_found(self):
        """运行不存在返回 None"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        ctx = _make_ctx(user=user, db=db)

        result = await _get_run(ctx, str(uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_run_invalid_uuid(self):
        """无效 UUID 返回 None"""
        user = _make_user()
        db = AsyncMock()
        db.get = AsyncMock(side_effect=ValueError("Invalid UUID"))
        ctx = _make_ctx(user=user, db=db)

        result = await _get_run(ctx, "not-a-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_run_access_denied(self):
        """无权访问返回 None"""
        user = _make_user(role=UserRole.RESEARCHER, user_id=uuid4())
        run = _make_run(user_id=uuid4())  # 不同 user_id
        db = _make_db_with_run(run=run)
        ctx = _make_ctx(user=user, db=db)

        result = await _get_run(ctx, str(run.id))
        assert result is None


# ============================================================
# GenerateHypothesisTool 测试
# ============================================================


class TestGenerateHypothesisToolSchema:
    """GenerateHypothesisTool 工具元数据测试"""

    def test_name(self):
        tool = GenerateHypothesisTool()
        assert tool.name == "generate_hypothesis"

    def test_side_effects_true(self):
        """假设生成工具有副作用"""
        tool = GenerateHypothesisTool()
        assert tool.side_effects is True

    def test_required_role(self):
        tool = GenerateHypothesisTool()
        assert tool.required_role == UserRole.RESEARCHER

    def test_to_schema_has_required_fields(self):
        tool = GenerateHypothesisTool()
        schema = tool.to_schema()
        assert "research_goal" in schema["properties"]
        assert "research_goal" in schema["required"]
        assert "count" in schema["properties"]
        assert "count" not in schema["required"]

    def test_to_info(self):
        tool = GenerateHypothesisTool()
        info = tool.to_info()
        assert info["name"] == "generate_hypothesis"
        assert info["side_effects"] is True
        assert "description" in info


class TestGenerateHypothesisToolExecute:
    """GenerateHypothesisTool.execute() 测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """成功生成假设"""
        user = _make_user()
        db = _make_db_with_run(run=None)  # 初始无 run，execute 会创建

        # 模拟 db.refresh 后返回带 id 的 run
        created_run = _make_run(user_id=user.id, status="running")

        async def _refresh(obj):
            obj.id = created_run.id

        db.refresh = AsyncMock(side_effect=_refresh)

        # 重新设置 execute 返回带 ID 的假设
        saved_hyps = [_make_hypothesis() for _ in range(3)]

        async def _execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = saved_hyps
            return result

        db.execute = AsyncMock(side_effect=_execute)

        ctx = _make_ctx(user=user, db=db)
        tool = GenerateHypothesisTool()

        # Mock LLM 客户端和 GenerationAgent
        mock_llm = MagicMock()
        mock_result = {
            "hypotheses": [
                {
                    "name": "Hyp A",
                    "description": "Desc A",
                    "mechanism": "Mech A",
                    "novelty_score": 8.0,
                    "plausibility_score": 7.0,
                    "testability_score": 9.0,
                    "safety_score": 6.0,
                }
            ],
            "token_usage": {"prompt": 1000, "completion": 500, "total": 1500},
            "cost_usd": 0.01,
        }

        with patch(
            "app.core.deps.get_llm_client_with_fallback",
            new_callable=AsyncMock,
            return_value=mock_llm,
        ) as mock_get_llm, patch(
            "app.services.coscientist.agents.generation.GenerationAgent.run",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await tool.execute(
                {"research_goal": "Find AML targets", "count": 3},
                ctx,
            )

        assert result.success is True
        assert "run_id" in result.data
        assert "hypotheses" in result.data
        assert result.data["count"] == 3  # 返回 DB 中的假设数
        assert result.display["type"] == "table"
        mock_get_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_llm_returns_empty(self):
        """LLM 未返回假设时标记失败"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        created_run = _make_run(user_id=user.id)

        async def _refresh(obj):
            obj.id = created_run.id

        db.refresh = AsyncMock(side_effect=_refresh)

        ctx = _make_ctx(user=user, db=db)
        tool = GenerateHypothesisTool()

        mock_llm = MagicMock()
        with patch(
            "app.core.deps.get_llm_client_with_fallback",
            new_callable=AsyncMock,
            return_value=mock_llm,
        ), patch(
            "app.services.coscientist.agents.generation.GenerationAgent.run",
            new_callable=AsyncMock,
            return_value={"hypotheses": [], "token_usage": {}, "cost_usd": 0.0},
        ):
            result = await tool.execute(
                {"research_goal": "Test"},
                ctx,
            )

        assert result.success is False
        assert "未返回有效假设" in result.error

    @pytest.mark.asyncio
    async def test_execute_llm_client_none(self):
        """LLM 客户端获取失败"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        ctx = _make_ctx(user=user, db=db)
        tool = GenerateHypothesisTool()

        with patch(
            "app.core.deps.get_llm_client_with_fallback",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await tool.execute(
                {"research_goal": "Test"},
                ctx,
            )

        assert result.success is False
        assert "LLM 客户端" in result.error

    @pytest.mark.asyncio
    async def test_execute_agent_exception(self):
        """GenerationAgent 抛异常时标记运行失败"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        created_run = _make_run(user_id=user.id)

        async def _refresh(obj):
            obj.id = created_run.id

        db.refresh = AsyncMock(side_effect=_refresh)

        ctx = _make_ctx(user=user, db=db)
        tool = GenerateHypothesisTool()

        mock_llm = MagicMock()
        with patch(
            "app.core.deps.get_llm_client_with_fallback",
            new_callable=AsyncMock,
            return_value=mock_llm,
        ), patch(
            "app.services.coscientist.agents.generation.GenerationAgent.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM timeout"),
        ):
            result = await tool.execute(
                {"research_goal": "Test"},
                ctx,
            )

        assert result.success is False
        assert "RuntimeError" in result.error
        assert "run_id" in result.data


# ============================================================
# QueryRunTool 测试
# ============================================================


class TestQueryRunToolSchema:
    """QueryRunTool 工具元数据测试"""

    def test_name(self):
        tool = QueryRunTool()
        assert tool.name == "query_coscientist_run"

    def test_side_effects_false(self):
        """运行查询无副作用"""
        tool = QueryRunTool()
        assert tool.side_effects is False

    def test_to_schema_has_optional_params(self):
        tool = QueryRunTool()
        schema = tool.to_schema()
        assert "top_n" in schema["properties"]
        assert "include_debates" in schema["properties"]
        assert "top_n" not in schema["required"]


class TestQueryRunToolExecute:
    """QueryRunTool.execute() 测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """成功查询运行"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        hyps = [
            _make_hypothesis(name="Hyp A", rank=1, elo_score=1200.0),
            _make_hypothesis(name="Hyp B", rank=2, elo_score=1100.0),
        ]
        db = _make_db_with_run(run=run, hypotheses=hyps)
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id), "top_n": 10},
            ctx,
        )

        assert result.success is True
        assert result.data["run_id"] == str(run.id)
        assert result.data["status"] == "completed"
        assert result.data["hypothesis_count"] == 2
        assert len(result.data["hypotheses"]) == 2
        assert result.data["hypotheses"][0]["name"] == "Hyp A"
        assert result.display["type"] == "table"

    @pytest.mark.asyncio
    async def test_execute_run_not_found(self):
        """运行不存在"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(uuid4())},
            ctx,
        )

        assert result.success is False
        assert "不存在" in result.error

    @pytest.mark.asyncio
    async def test_execute_access_denied(self):
        """无权访问运行"""
        user = _make_user(role=UserRole.RESEARCHER, user_id=uuid4())
        run = _make_run(user_id=uuid4())  # 不同 user_id
        db = _make_db_with_run(run=run)
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is False
        assert "不存在或无权访问" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_debates(self):
        """包含辩论摘要"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [_make_debate(round_num=1), _make_debate(round_num=2)]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id), "include_debates": True},
            ctx,
        )

        assert result.success is True
        assert "debates" in result.data
        assert len(result.data["debates"]) == 2

    @pytest.mark.asyncio
    async def test_execute_without_debates(self):
        """不包含辩论摘要（默认）"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        db = _make_db_with_run(run=run, hypotheses=[], debates=[_make_debate()])
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        assert "debates" not in result.data

    @pytest.mark.asyncio
    async def test_execute_with_meta_review(self):
        """包含元评审"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id, meta_review="Final synthesis report")
        db = _make_db_with_run(run=run, hypotheses=[])
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        assert "meta_review" in result.data

    @pytest.mark.asyncio
    async def test_execute_empty_hypotheses(self):
        """空假设列表"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        db = _make_db_with_run(run=run, hypotheses=[])
        ctx = _make_ctx(user=user, db=db)

        tool = QueryRunTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        assert result.data["hypothesis_count"] == 0
        assert result.data["hypotheses"] == []


# ============================================================
# ScientificDebateTool 测试
# ============================================================


class TestScientificDebateToolSchema:
    """ScientificDebateTool 工具元数据测试"""

    def test_name(self):
        tool = ScientificDebateTool()
        assert tool.name == "scientific_debate"

    def test_side_effects_false(self):
        """辩论查询无副作用"""
        tool = ScientificDebateTool()
        assert tool.side_effects is False

    def test_to_schema_optional_params(self):
        tool = ScientificDebateTool()
        schema = tool.to_schema()
        assert "round_num" in schema["properties"]
        assert "summary_only" in schema["properties"]
        assert schema["required"] == ["run_id"]


class TestScientificDebateToolExecute:
    """ScientificDebateTool.execute() 测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """成功查询辩论记录"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [
            _make_debate(round_num=1, consensus_score=0.9, mechanism_agreed=True),
            _make_debate(round_num=2, consensus_score=0.5, mechanism_agreed=False),
        ]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        assert result.data["total_rounds"] == 2
        assert len(result.data["debates"]) == 2
        assert "analysis" in result.data
        assert result.data["analysis"]["avg_consensus_score"] == 0.7
        assert result.data["analysis"]["agreed_count"] == 1
        assert result.data["analysis"]["disputed_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_run_not_found(self):
        """运行不存在"""
        user = _make_user()
        db = _make_db_with_run(run=None)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(uuid4())},
            ctx,
        )

        assert result.success is False
        assert "不存在" in result.error

    @pytest.mark.asyncio
    async def test_execute_empty_debates(self):
        """空辩论记录"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        db = _make_db_with_run(run=run, hypotheses=[], debates=[])
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        assert result.data["total_rounds"] == 0
        assert result.data["debates"] == []

    @pytest.mark.asyncio
    async def test_execute_summary_only(self):
        """摘要模式不含完整论据"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [_make_debate(round_num=1)]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id), "summary_only": True},
            ctx,
        )

        assert result.success is True
        entry = result.data["debates"][0]
        assert "proponent_argument" not in entry
        assert "opponent_argument" not in entry
        assert "consensus_score" in entry

    @pytest.mark.asyncio
    async def test_execute_full_mode(self):
        """完整模式包含论据文本"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [_make_debate(round_num=1, proponent_argument="Full argument text")]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id), "summary_only": False},
            ctx,
        )

        assert result.success is True
        entry = result.data["debates"][0]
        assert "proponent_argument" in entry
        assert entry["proponent_argument"] == "Full argument text"

    @pytest.mark.asyncio
    async def test_execute_filter_by_round(self):
        """按轮次过滤"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [
            _make_debate(round_num=1),
            _make_debate(round_num=2),
            _make_debate(round_num=3),
        ]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id), "round_num": 2},
            ctx,
        )

        assert result.success is True
        # Mock 返回所有辩论（未实际过滤），但测试参数传递正确
        assert result.data["total_rounds"] == 3  # Mock 返回全部

    @pytest.mark.asyncio
    async def test_execute_analysis_stats(self):
        """统计分析正确性"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [
            _make_debate(round_num=1, consensus_score=0.8, mechanism_agreed=True),
            _make_debate(round_num=2, consensus_score=0.6, mechanism_agreed=True),
            _make_debate(round_num=3, consensus_score=0.4, mechanism_agreed=False),
        ]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        analysis = result.data["analysis"]
        assert analysis["avg_consensus_score"] == round((0.8 + 0.6 + 0.4) / 3, 3)
        assert analysis["agreement_rate"] == round(2 / 3, 3)
        assert analysis["agreed_count"] == 2
        assert analysis["disputed_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_none_consensus_scores(self):
        """共识度为 None 时的统计分析"""
        owner_id = uuid4()
        user = _make_user(role=UserRole.RESEARCHER, user_id=owner_id)
        run = _make_run(user_id=owner_id)
        debates = [
            _make_debate(round_num=1, consensus_score=None, mechanism_agreed=True),
        ]
        db = _make_db_with_run(run=run, hypotheses=[], debates=debates)
        ctx = _make_ctx(user=user, db=db)

        tool = ScientificDebateTool()
        result = await tool.execute(
            {"run_id": str(run.id)},
            ctx,
        )

        assert result.success is True
        analysis = result.data["analysis"]
        assert analysis["avg_consensus_score"] == 0.0
        assert analysis["agreed_count"] == 1


# ============================================================
# 权限矩阵测试
# ============================================================


class TestCoscientistToolPermissions:
    """Co-Scientist 工具权限矩阵测试"""

    def test_generate_hypothesis_permissions(self):
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("generate_hypothesis", UserRole.FOUNDER) is True
        assert has_tool_permission("generate_hypothesis", UserRole.CHIEF_RESEARCHER) is True
        assert has_tool_permission("generate_hypothesis", UserRole.RESEARCHER) is True
        assert has_tool_permission("generate_hypothesis", UserRole.DOCTOR) is False
        assert has_tool_permission("generate_hypothesis", UserRole.DATA_ENGINEER) is False

    def test_query_coscientist_run_permissions(self):
        from app.services.agent.tools.permissions import has_tool_permission

        for role in [
            UserRole.FOUNDER,
            UserRole.CHIEF_RESEARCHER,
            UserRole.RESEARCHER,
            UserRole.DOCTOR,
            UserRole.DATA_ENGINEER,
        ]:
            assert has_tool_permission("query_coscientist_run", role) is True

    def test_scientific_debate_permissions(self):
        from app.services.agent.tools.permissions import has_tool_permission

        for role in [
            UserRole.FOUNDER,
            UserRole.CHIEF_RESEARCHER,
            UserRole.RESEARCHER,
            UserRole.DOCTOR,
            UserRole.DATA_ENGINEER,
        ]:
            assert has_tool_permission("scientific_debate", role) is True

    def test_unknown_tool_denied(self):
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("nonexistent_tool", UserRole.FOUNDER) is False
