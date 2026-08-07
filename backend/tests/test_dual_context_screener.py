"""DualContextScreener 测试 — 覆盖双上下文筛选与条件放大器识别

覆盖：
1. 初始化（1 测试）
2. screen 方法（5 测试）— 默认上下文 / 放大器得分 / 阈值 / 自定义上下文 / 空列表
3. screen_with_target 方法（2 测试）— 加载靶点 / 不存在靶点
"""
import pytest

from app.core.exceptions import NotFoundError
from app.core.security import hash_password, UserRole
from app.models.project import Project
from app.models.target import Target
from app.models.user import User
from app.services.orchestrator.dual_context_screener import DualContextScreener


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_chain(async_db_session):
    """创建 user → project → target 数据链"""
    user = User(
        email="dctx-test@ai-drug.com",
        name="DualContext Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    project = Project(name="双上下文测试项目", owner_id=user.id)
    async_db_session.add(project)
    await async_db_session.flush()

    target = Target(
        project_id=project.id,
        gene_symbol="EGFR",
        confidence_score=0.7,
    )
    async_db_session.add(target)
    await async_db_session.flush()

    return {"user": user, "project": project, "target": target}


# ========== 初始化测试 ==========

class TestDualContextScreenerInit:
    def test_init_creates_screener(self, async_db_session):
        """初始化成功"""
        screener = DualContextScreener(async_db_session)
        assert screener.db is async_db_session
        # 无 LLM 时 llm_orchestrator 应为 None
        assert screener.llm_orchestrator is None


# ========== screen 方法测试 ==========

class TestDualContextScreen:
    @pytest.mark.asyncio
    async def test_screen_default_contexts(self, async_db_session):
        """默认双上下文 ['immune_active', 'neutral']"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen(
            smiles_list=["CCO", "CCN"],
            target_pdb="",
        )
        assert "contexts" in result
        assert "immune_active" in result["contexts"]
        assert "neutral" in result["contexts"]
        assert len(result["contexts"]) == 2

    @pytest.mark.asyncio
    async def test_screen_returns_amplification_score(self, async_db_session):
        """返回 conditional_amplification_score"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen(
            smiles_list=["CCO"],
            target_pdb="",
        )
        assert "results" in result
        assert len(result["results"]) >= 1
        first = result["results"][0]
        assert "conditional_amplification_score" in first
        assert "efficacy_active" in first
        assert "efficacy_neutral" in first

    @pytest.mark.asyncio
    async def test_screen_amplifier_threshold(self, async_db_session):
        """score > 阈值（0.2）应标记为 is_amplifier"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen(
            smiles_list=["CCO", "CCN", "c1ccccc1"],
            target_pdb="",
        )
        # immune_active 有 +0.1 偏移，理论上 active > neutral，score > 0
        for r in result["results"]:
            assert "is_amplifier" in r
            assert isinstance(r["is_amplifier"], bool)
            # 若 score > threshold，则 is_amplifier 应为 True
            if r["conditional_amplification_score"] > result["threshold"]:
                assert r["is_amplifier"] is True
        # n_amplifiers 应等于 results 中 is_amplifier=True 的数量
        expected_n = sum(1 for r in result["results"] if r["is_amplifier"])
        assert result["n_amplifiers"] == expected_n

    @pytest.mark.asyncio
    async def test_screen_custom_contexts(self, async_db_session):
        """自定义上下文列表生效"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen(
            smiles_list=["CCO"],
            target_pdb="",
            contexts=["inflamed", "quiescent"],
        )
        assert "inflamed" in result["contexts"]
        assert "quiescent" in result["contexts"]

    @pytest.mark.asyncio
    async def test_screen_empty_smiles_list(self, async_db_session):
        """空列表返回空结果"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen(
            smiles_list=[],
            target_pdb="",
        )
        assert result["results"] == []
        assert result["n_total"] == 0
        assert result["n_amplifiers"] == 0


# ========== screen_with_target 方法测试 ==========

class TestScreenWithTarget:
    @pytest.mark.asyncio
    async def test_screen_with_target_loads_target(self, async_db_session, setup_chain):
        """通过 target_id 加载靶点"""
        screener = DualContextScreener(async_db_session)
        result = await screener.screen_with_target(
            target_id=str(setup_chain["target"].id),
            smiles_list=["CCO"],
        )
        assert result.get("target_id") == str(setup_chain["target"].id)
        assert result.get("target_gene") == "EGFR"

    @pytest.mark.asyncio
    async def test_screen_with_target_not_found_raises(self, async_db_session):
        """不存在的 target_id 抛 NotFoundError"""
        import uuid as uuid_mod
        screener = DualContextScreener(async_db_session)
        with pytest.raises(NotFoundError):
            await screener.screen_with_target(
                target_id=str(uuid_mod.uuid4()),
                smiles_list=["CCO"],
            )
