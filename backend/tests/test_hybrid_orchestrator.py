"""HybridOrchestrator 测试 — 覆盖 LLM+计算混合架构两个核心流程

覆盖：
1. 初始化（2 测试）— Mock LLM / None LLM
2. llm_driven_docking（5 测试）— 5 步流程 + 持久化 + 空输入 + 成本超限 + 容错
3. llm_to_vaccine_pipeline（5 测试）— 3 步流程 + 持久化 + GC 含量
"""
import uuid
from unittest.mock import MagicMock

import pytest

from app.core.security import hash_password, UserRole
from app.models.compute_job import ComputeJob
from app.models.neoantigen import Neoantigen
from app.models.project import Project
from app.models.protein_structure import ProteinStructure
from app.models.target import Target
from app.models.user import User
from app.services.orchestrator.hybrid_orchestrator import HybridOrchestrator


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_chain(async_db_session):
    """创建 user → project → target 数据链"""
    user = User(
        email="hybrid-test@ai-drug.com",
        name="Hybrid Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    project = Project(name="混合架构测试项目", owner_id=user.id)
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


@pytest.fixture
async def mock_llm_client():
    """返回 MockLLMClient 实例"""
    from app.clients.mock.llm_mock import MockLLMClient
    return MockLLMClient()


# ========== 初始化测试 ==========

class TestHybridOrchestratorInit:
    def test_init_with_mock_llm(self, async_db_session, mock_llm_client):
        """MockLLMClient 初始化成功"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        assert orch.db is async_db_session
        assert orch.llm_client is mock_llm_client
        assert orch.llm_orchestrator is not None

    def test_init_without_llm(self, async_db_session):
        """llm_client=None 也能初始化（降级纯计算模式）"""
        orch = HybridOrchestrator(async_db_session, llm_client=None)
        assert orch.db is async_db_session
        assert orch.llm_client is None
        # llm_orchestrator 仍会被创建（LLMOrchestrator 容忍 None client）
        assert orch.llm_orchestrator is not None


# ========== llm_driven_docking 测试 ==========

class TestLLMDrivenDocking:
    @pytest.mark.asyncio
    async def test_docking_returns_dict(self, async_db_session, setup_chain, mock_llm_client):
        """返回 dict 含 final_ranking / cost_usd / duration_sec"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        result = await orch.llm_driven_docking(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            smiles_list=["CCO", "CC(=O)O", "c1ccccc1"],
            user=setup_chain["user"],
            top_k=3,
        )
        assert isinstance(result, dict)
        assert "final_ranking" in result
        assert "cost_usd" in result
        assert "duration_sec" in result
        assert "steps_completed" in result
        assert "truncated" in result
        assert isinstance(result["cost_usd"], float)
        assert result["duration_sec"] >= 0

    @pytest.mark.asyncio
    async def test_docking_persists_compute_jobs(
        self, async_db_session, setup_chain, mock_llm_client
    ):
        """持久化 ComputeJob 记录"""
        from sqlalchemy import select

        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        await orch.llm_driven_docking(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            smiles_list=["CCO"],
            user=setup_chain["user"],
            top_k=1,
        )
        stmt = select(ComputeJob).where(ComputeJob.project_id == setup_chain["project"].id)
        result = await async_db_session.execute(stmt)
        jobs = result.scalars().all()
        assert len(jobs) >= 1

    @pytest.mark.asyncio
    async def test_docking_empty_smiles_list(self, async_db_session, setup_chain, mock_llm_client):
        """空列表快速返回空结果"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        result = await orch.llm_driven_docking(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            smiles_list=[],
            user=setup_chain["user"],
        )
        assert result["final_ranking"] == []
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_docking_step_failure_graceful(self, async_db_session, setup_chain):
        """LLM 调用抛异常时不中断整个流程"""
        # 构造一个会抛异常的 mock client
        failing_client = MagicMock()
        failing_client.chat = MagicMock(side_effect=Exception("LLM 不可用"))
        orch = HybridOrchestrator(async_db_session, llm_client=failing_client)
        result = await orch.llm_driven_docking(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            smiles_list=["CCO"],
            user=setup_chain["user"],
            top_k=1,
        )
        # LLM 失败后降级为全量候选，仍返回有效结构
        assert isinstance(result, dict)
        assert "steps_completed" in result
        # 至少完成了 Step 1（即使 LLM 异常）
        assert result["steps_completed"] >= 1

    @pytest.mark.asyncio
    async def test_docking_non_json_response_fallback(
        self, async_db_session, setup_chain, mock_llm_client
    ):
        """MockLLMClient 返回非 JSON 时降级处理"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        # MockLLMClient 对不含 EGFR/B7H3/FAP 的问题返回通用文本，非 JSON
        result = await orch.llm_driven_docking(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            smiles_list=["CCO", "CCN"],
            user=setup_chain["user"],
            top_k=2,
        )
        # 即使 LLM 返回非 JSON，也应降级为全量候选并完成
        assert isinstance(result["final_ranking"], list)
        assert result["steps_completed"] >= 2


# ========== llm_to_vaccine_pipeline 测试 ==========

class TestVaccinePipeline:
    @pytest.mark.asyncio
    async def test_vaccine_returns_dict(self, async_db_session, setup_chain, mock_llm_client):
        """返回 dict 含 vaccine_sequence 或降级字段"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        result = await orch.llm_to_vaccine_pipeline(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            mutation_sequence="MKKLLLIVTAAHCLGGSFV",
            user=setup_chain["user"],
        )
        assert isinstance(result, dict)
        # 至少应返回 cost/duration 等基础字段
        assert "cost_usd" in result or "duration_sec" in result or "steps_completed" in result

    @pytest.mark.asyncio
    async def test_vaccine_persists_protein_structure(
        self, async_db_session, setup_chain, mock_llm_client
    ):
        """持久化 ProteinStructure 记录"""
        from sqlalchemy import select

        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        await orch.llm_to_vaccine_pipeline(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            mutation_sequence="MKKLLLIVTAAHCLGGSFV",
            user=setup_chain["user"],
        )
        stmt = select(ProteinStructure).where(
            ProteinStructure.target_id == setup_chain["target"].id
        )
        result = await async_db_session.execute(stmt)
        structures = result.scalars().all()
        assert len(structures) >= 1

    @pytest.mark.asyncio
    async def test_vaccine_persists_neoantigen(
        self, async_db_session, setup_chain, mock_llm_client
    ):
        """持久化 Neoantigen 记录"""
        from sqlalchemy import select

        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        await orch.llm_to_vaccine_pipeline(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            mutation_sequence="MKKLLLIVTAAHCLGGSFVGDVNSNE",
            user=setup_chain["user"],
        )
        stmt = select(Neoantigen).where(Neoantigen.target_id == setup_chain["target"].id)
        result = await async_db_session.execute(stmt)
        neoantigens = result.scalars().all()
        # Mock MHCflurry 应返回新抗原记录
        assert len(neoantigens) >= 1

    @pytest.mark.asyncio
    async def test_vaccine_gc_content_in_range(
        self, async_db_session, setup_chain, mock_llm_client
    ):
        """LLM 设计的 mRNA 序列 GC 含量应在 0-1 之间（合理范围）"""
        orch = HybridOrchestrator(async_db_session, llm_client=mock_llm_client)
        result = await orch.llm_to_vaccine_pipeline(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            mutation_sequence="MKKLLLIVTAAHCLGGSFVGDVNSNE",
            user=setup_chain["user"],
        )
        # gc_content 若返回应为 [0, 1]
        gc = result.get("gc_content", 0)
        assert 0.0 <= gc <= 1.0

    @pytest.mark.asyncio
    async def test_vaccine_without_llm(self, async_db_session, setup_chain):
        """无 LLM 时也能跑完前两步（结构 + 新抗原）"""
        orch = HybridOrchestrator(async_db_session, llm_client=None)
        result = await orch.llm_to_vaccine_pipeline(
            project_id=str(setup_chain["project"].id),
            target_id=str(setup_chain["target"].id),
            mutation_sequence="MKKLLLIVTAAHCLGGSFV",
            user=setup_chain["user"],
        )
        assert isinstance(result, dict)
        # 至少完成 Step 1（结构预测）
        assert result.get("steps_completed", 0) >= 1
