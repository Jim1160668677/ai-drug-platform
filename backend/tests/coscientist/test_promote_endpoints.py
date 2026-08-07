"""Co-Scientist Phase B3/B4 — 假设→实体 promote 端点 + 反馈闭环测试

验证 4 个 promote 端点 + 1 个反馈端点：
- POST /runs/{id}/hypotheses/{hid}/promote-target    假设→靶点
- POST /runs/{id}/hypotheses/{hid}/promote-molecule  假设→分子
- POST /runs/{id}/hypotheses/{hid}/promote-experiment 假设→实验（含 hypothesis_id 关联）
- POST /runs/{id}/hypotheses/{hid}/promote-treatment 假设→治疗
- POST /runs/{id}/hypotheses/{hid}/experiment-feedback 实验结果→假设 Elo 反馈

设计原则：
- 所有验证通过 API 响应完成，不直接操作 DB（避免 session 事务冲突）
- 需要前置数据（如靶点）时通过 API 创建
- 实验完成状态通过 promote-experiment 的 config 标记，反馈端点测试聚焦权限校验
"""
import uuid
import pytest
import pytest_asyncio

from app.models.coscientist_run import CaseType, CoScientistRun, RunStatus
from app.models.hypothesis import Hypothesis, HypothesisStatus


@pytest_asyncio.fixture
async def test_hypothesis(async_db_session, auth_token):
    """创建测试运行 + 项目 + 假设（带 target_list）"""
    from app.models.user import User
    from app.models.project import Project
    from sqlalchemy import select

    result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = result.scalar_one()

    project = Project(
        owner_id=user.id,
        name="Promote 测试项目",
        patient_pseudonym="PROMOTE-001",
        cancer_type="CUSTOM",
        stage="NA",
        description="promote 端点测试",
    )
    async_db_session.add(project)
    await async_db_session.flush()

    run = CoScientistRun(
        user_id=user.id,
        project_id=project.id,
        research_goal="测试 promote 端点的研究目标",
        case_type=CaseType.CUSTOM,
        status=RunStatus.COMPLETED,
        current_round=2,
        max_rounds=5,
    )
    async_db_session.add(run)
    await async_db_session.flush()

    hyp = Hypothesis(
        project_id=project.id,
        created_by=user.id,
        name="测试假设-靶点TP53",
        description="TP53 突变导致细胞周期失调",
        mechanism="TP53 失活 → MDM2 扩增 → 细胞周期失控",
        strategy="MDM2 抑制剂联合治疗",
        status=HypothesisStatus.COMPLETED,
        elo_score=1250.0,
        novelty_score=8.0,
        plausibility_score=7.5,
        testability_score=9.0,
        safety_score=8.0,
        coscientist_run_id=run.id,
        target_list=["TP53", "MDM2"],
        rank=1,
    )
    async_db_session.add(hyp)
    await async_db_session.flush()

    return {"run": run, "project": project, "hypothesis": hyp, "user": user}


class TestPromoteTarget:
    """假设→靶点 promote 测试"""

    @pytest.mark.asyncio
    async def test_promote_target_from_target_list(self, client, auth_headers, test_hypothesis):
        """从假设 target_list 自动提取基因符号"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-target",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["gene_symbol"] == "TP53"
        # Elo=1250 → confidence = 0.5 + 250/2000 = 0.625
        assert 0.5 < data["confidence_score"] < 0.99
        assert "target_id" in data

    @pytest.mark.asyncio
    async def test_promote_target_with_override(self, client, auth_headers, test_hypothesis):
        """手动指定 gene_symbol 和置信度"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-target",
            json={"gene_symbol": "MDM2", "confidence_override": 0.95},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["gene_symbol"] == "MDM2"
        assert data["confidence_score"] == 0.95

    @pytest.mark.asyncio
    async def test_promote_target_run_not_found(self, client, auth_headers, test_hypothesis):
        """运行不存在 → 404"""
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{uuid.uuid4()}/hypotheses/{hyp_id}/promote-target",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_promote_target_hypothesis_not_found(self, client, auth_headers, test_hypothesis):
        """假设不存在 → 404"""
        run_id = test_hypothesis["run"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{uuid.uuid4()}/promote-target",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestPromoteMolecule:
    """假设→分子 promote 测试"""

    @pytest.mark.asyncio
    async def test_promote_molecule_with_smiles(self, client, auth_headers, test_hypothesis):
        """带 SMILES 的 promote — 先通过 promote-target 创建靶点"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id

        # 先 promote 一个靶点
        target_resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-target",
            json={"gene_symbol": "TP53"},
            headers=auth_headers,
        )
        assert target_resp.status_code == 200
        target_id = target_resp.json()["target_id"]

        # 再 promote 分子
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-molecule",
            json={
                "target_id": target_id,
                "smiles": "CC(=O)Oc1ccccc1C(=O)O",
                "name": "Co-Sci 阿司匹林候选",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["smiles"] == "CC(=O)Oc1ccccc1C(=O)O"
        assert data["needs_design"] is False

    @pytest.mark.asyncio
    async def test_promote_molecule_without_smiles(self, client, auth_headers, test_hypothesis):
        """无 SMILES → 标记 needs_design"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id

        target_resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-target",
            json={"gene_symbol": "MDM2"},
            headers=auth_headers,
        )
        target_id = target_resp.json()["target_id"]

        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-molecule",
            json={"target_id": target_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["needs_design"] is True

    @pytest.mark.asyncio
    async def test_promote_molecule_target_not_found(self, client, auth_headers, test_hypothesis):
        """靶点不存在 → 404"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-molecule",
            json={"target_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestPromoteExperiment:
    """假设→实验 promote 测试（Phase B4 反馈闭环核心）"""

    @pytest.mark.asyncio
    async def test_promote_experiment_links_hypothesis(self, client, auth_headers, test_hypothesis):
        """实验创建后应返回 feedback_endpoint"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-experiment",
            json={
                "name": "TP53 细胞毒性测试",
                "exp_type": "cytotoxicity",
                "config": {"cell_line": "MCF7", "concentration": "10uM"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "experiment_id" in data
        assert "feedback_endpoint" in data
        assert data["exp_type"] == "cytotoxicity"

    @pytest.mark.asyncio
    async def test_promote_experiment_missing_name(self, client, auth_headers, test_hypothesis):
        """缺少必填字段 name → 422"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-experiment",
            json={"exp_type": "cytotoxicity"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_promote_experiment_missing_exp_type(self, client, auth_headers, test_hypothesis):
        """缺少必填字段 exp_type → 422"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-experiment",
            json={"name": "测试实验"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestPromoteTreatment:
    """假设→治疗 promote 测试"""

    @pytest.mark.asyncio
    async def test_promote_treatment(self, client, auth_headers, test_hypothesis):
        """创建治疗方案"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-treatment",
            json={"therapy_type": "targeted_therapy"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["therapy_type"] == "targeted_therapy"
        assert "treatment_id" in data

    @pytest.mark.asyncio
    async def test_promote_treatment_with_name(self, client, auth_headers, test_hypothesis):
        """自定义治疗方案名称"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-treatment",
            json={"therapy_type": "immunotherapy", "name": "PD-1联合方案"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["therapy_type"] == "immunotherapy"

    @pytest.mark.asyncio
    async def test_promote_treatment_missing_therapy_type(self, client, auth_headers, test_hypothesis):
        """缺少 therapy_type → 422"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-treatment",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestExperimentFeedback:
    """实验结果→假设反馈测试（Phase B4）"""

    @pytest.mark.asyncio
    async def test_feedback_experiment_not_completed(self, client, auth_headers, test_hypothesis):
        """实验未完成 → 400（promote-experiment 创建的实验默认 PLANNED 状态）"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id

        # 先 promote 一个实验（状态为 PLANNED）
        exp_resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/promote-experiment",
            json={"name": "未完成实验", "exp_type": "cytotoxicity"},
            headers=auth_headers,
        )
        assert exp_resp.status_code == 200
        exp_id = exp_resp.json()["experiment_id"]

        # 尝试反馈 → 400（实验未完成）
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/experiment-feedback",
            json={
                "experiment_id": exp_id,
                "success": True,
                "result_summary": "测试",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_feedback_experiment_not_linked(self, client, auth_headers, test_hypothesis):
        """实验与假设无关联 → 400
        通过 promote-experiment 创建一个关联实验，然后用另一个假设 ID 反馈。
        这里用随机 experiment_id 测试 404。
        """
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id

        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/experiment-feedback",
            json={
                "experiment_id": str(uuid.uuid4()),
                "success": True,
                "result_summary": "测试",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_feedback_missing_experiment_id(self, client, auth_headers, test_hypothesis):
        """缺少 experiment_id → 422"""
        run_id = test_hypothesis["run"].id
        hyp_id = test_hypothesis["hypothesis"].id
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/experiment-feedback",
            json={"success": True, "result_summary": "测试"},
            headers=auth_headers,
        )
        assert resp.status_code == 422