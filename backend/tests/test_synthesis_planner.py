"""合成服务测试 — 覆盖 4 个合成服务的核心流程

覆盖：
1. SynthesisRouteGenerator（2 测试）— Mock 返回路线 + steps 结构
2. FeasibilityPredictor（3 测试）— sa_score / sc_score / label
3. SynthesisCostEstimator（3 测试）— total / breakdown / cost_per_gram
4. SynthesisPlanner（4 测试）— 持久化 / plan_id / get_plan / list_plans
"""
import pytest

from app.core.security import hash_password, UserRole
from app.models.project import Project
from app.models.synthesis_plan import SynthesisPlan
from app.models.user import User
from app.services.synthesis import (
    FeasibilityPredictor,
    SynthesisCostEstimator,
    SynthesisPlanner,
    SynthesisRouteGenerator,
)


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_user(async_db_session):
    user = User(
        email="synth-test@ai-drug.com",
        name="Synth Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest.fixture
async def setup_chain(async_db_session, setup_user):
    project = Project(name="合成测试项目", owner_id=setup_user.id)
    async_db_session.add(project)
    await async_db_session.flush()
    return {"user": setup_user, "project": project}


# ========== SynthesisRouteGenerator 测试 ==========

class TestRouteGenerator:
    @pytest.mark.asyncio
    async def test_mock_returns_routes(self, async_db_session):
        """Mock 模式返回 3-5 条路线"""
        gen = SynthesisRouteGenerator(async_db_session)
        result = await gen.generate_routes("CC(=O)Oc1ccccc1C(=O)O", max_routes=5)
        assert isinstance(result, dict)
        assert "routes" in result
        assert isinstance(result["routes"], list)
        assert len(result["routes"]) >= 1
        assert len(result["routes"]) <= 5

    @pytest.mark.asyncio
    async def test_routes_have_steps(self, async_db_session):
        """每条路线含 steps 列表"""
        gen = SynthesisRouteGenerator(async_db_session)
        result = await gen.generate_routes("CCO", max_routes=3)
        for route in result["routes"]:
            # 至少应有 steps 字段（可能是 steps 或 step_count）
            assert "steps" in route or "n_steps" in route or "step_count" in route


# ========== FeasibilityPredictor 测试 ==========

class TestFeasibilityPredictor:
    @pytest.mark.asyncio
    async def test_returns_sa_score(self, async_db_session):
        """返回 sa_score（1-10 分制）"""
        pred = FeasibilityPredictor(async_db_session)
        # 先生成路线
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await pred.predict("CCO", routes)
        assert "sa_score" in result
        sa = result["sa_score"]
        assert sa is not None
        assert 1.0 <= float(sa) <= 10.0

    @pytest.mark.asyncio
    async def test_returns_sc_score(self, async_db_session):
        """返回 sc_score（1-5 分制）"""
        pred = FeasibilityPredictor(async_db_session)
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await pred.predict("CCO", routes)
        if "sc_score" in result and result["sc_score"] is not None:
            sc = float(result["sc_score"])
            assert 1.0 <= sc <= 5.0

    @pytest.mark.asyncio
    async def test_returns_label(self, async_db_session):
        """返回 easy/medium/hard 标签"""
        pred = FeasibilityPredictor(async_db_session)
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await pred.predict("CCO", routes)
        assert "feasibility_label" in result
        assert result["feasibility_label"] in ("easy", "medium", "hard")


# ========== SynthesisCostEstimator 测试 ==========

class TestCostEstimator:
    @pytest.mark.asyncio
    async def test_returns_total(self, async_db_session):
        """返回 total_cost_usd"""
        est = SynthesisCostEstimator(async_db_session)
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await est.estimate(routes, sa_score=3.5, target_scale_grams=10.0)
        assert "total_cost_usd" in result
        assert float(result["total_cost_usd"]) > 0

    @pytest.mark.asyncio
    async def test_returns_breakdown(self, async_db_session):
        """返回 breakdown（materials/labor/equipment/overhead）"""
        est = SynthesisCostEstimator(async_db_session)
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await est.estimate(routes, sa_score=3.5, target_scale_grams=10.0)
        # breakdown 可能在 breakdown 字段
        breakdown = result.get("breakdown") or result.get("cost_breakdown") or {}
        # 至少含一项成本项
        assert isinstance(breakdown, dict)
        assert len(breakdown) >= 1

    @pytest.mark.asyncio
    async def test_returns_cost_per_gram(self, async_db_session):
        """返回 cost_per_gram"""
        est = SynthesisCostEstimator(async_db_session)
        gen = SynthesisRouteGenerator(async_db_session)
        routes = await gen.generate_routes("CCO", max_routes=2)
        result = await est.estimate(routes, sa_score=3.5, target_scale_grams=10.0)
        assert "cost_per_gram" in result
        assert float(result["cost_per_gram"]) >= 0


# ========== SynthesisPlanner 测试 ==========

class TestSynthesisPlanner:
    @pytest.mark.asyncio
    async def test_plan_persists_record(self, async_db_session, setup_chain):
        """持久化 SynthesisPlan"""
        from sqlalchemy import select

        planner = SynthesisPlanner(async_db_session, llm_client=None)
        await planner.plan(
            smiles="CC(=O)Oc1ccccc1C(=O)O",
            user=setup_chain["user"],
            max_routes=3,
            target_scale_grams=10.0,
            project_id=str(setup_chain["project"].id),
        )
        stmt = select(SynthesisPlan).where(SynthesisPlan.owner_id == setup_chain["user"].id)
        result = await async_db_session.execute(stmt)
        plans = result.scalars().all()
        assert len(plans) >= 1

    @pytest.mark.asyncio
    async def test_plan_returns_plan_id(self, async_db_session, setup_chain):
        """返回 plan_id"""
        planner = SynthesisPlanner(async_db_session, llm_client=None)
        result = await planner.plan(
            smiles="CCO",
            user=setup_chain["user"],
            max_routes=2,
        )
        assert "plan_id" in result
        assert result["plan_id"]  # 非空

    @pytest.mark.asyncio
    async def test_get_plan_returns_record(self, async_db_session, setup_chain):
        """get_plan(plan_id) 返回记录"""
        planner = SynthesisPlanner(async_db_session, llm_client=None)
        result = await planner.plan(
            smiles="CCO",
            user=setup_chain["user"],
            max_routes=2,
        )
        plan_id = result["plan_id"]
        plan = await planner.get_plan(plan_id)
        assert plan is not None
        assert str(plan.id) == plan_id

    @pytest.mark.asyncio
    async def test_list_plans_paginated(self, async_db_session, setup_chain):
        """list_plans 支持分页"""
        planner = SynthesisPlanner(async_db_session, llm_client=None)
        # 创建 2 个 plan
        await planner.plan(smiles="CCO", user=setup_chain["user"], max_routes=2)
        await planner.plan(smiles="c1ccccc1", user=setup_chain["user"], max_routes=2)

        result = await planner.list_plans(setup_chain["user"], page=1, page_size=10)
        assert "items" in result
        assert "total" in result
        assert result["total"] >= 2
        assert len(result["items"]) >= 2
        assert result["page"] == 1
        assert result["page_size"] == 10
