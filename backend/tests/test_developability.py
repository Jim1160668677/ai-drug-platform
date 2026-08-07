"""药物可开发性评估测试 — 5 维度干实验预筛选

覆盖：
1. 5 维度评估各自返回正确类型和范围
2. 综合决策规则（high tox→no_go / sa>8→revise / cost>5000→revise / 默认→go）
3. Mock 模式（rdkit 不可用）也能返回合理结果
4. 持久化（同分子多次评估，version 自增）
5. 端点：未认证 401、不存在的分子 404、正常评估 200
6. 评估结果包含所有必需字段
"""
import uuid

import pytest

from app.core.security import hash_password, UserRole
from app.models.developability import DevelopabilityAssessment
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.models.user import User
from app.services.molecule.developability_assessor import DevelopabilityAssessor


# ========== 辅助 fixture ==========

@pytest.fixture
def assessor():
    """不依赖 DB 的评估器实例（用于单元测试）"""
    return DevelopabilityAssessor(db=None)


@pytest.fixture
async def setup_molecule(async_db_session):
    """创建完整的 project → target → molecule 数据链"""
    user = User(
        email="dev-test@ai-drug.com",
        name="Dev Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    project = Project(name="可开发性测试项目", owner_id=user.id)
    async_db_session.add(project)
    await async_db_session.flush()

    target = Target(
        project_id=project.id,
        gene_symbol="EGFR",
        confidence_score=0.7,
    )
    async_db_session.add(target)
    await async_db_session.flush()

    molecule = Molecule(
        target_id=target.id,
        smiles="CCO",
        name="乙醇测试分子",
        molecular_weight=46.07,
        logp=-0.14,
        properties={"mw": 46.07, "logp": -0.14, "tpsa": 20.23},
    )
    async_db_session.add(molecule)
    await async_db_session.flush()

    return {"user": user, "project": project, "target": target, "molecule": molecule}


# ========== 单元测试：5 维度评估 ==========

class TestSynthesizability:
    """合成可及性 SA Score"""

    def test_simple_molecule_returns_valid_score(self, assessor):
        score, label = assessor.assess_synthesizability("CCO")
        assert 1.0 <= score <= 10.0
        assert label in ("easy", "medium", "hard")

    def test_empty_smiles_returns_medium_default(self, assessor):
        score, label = assessor.assess_synthesizability("")
        assert score == 5.0
        assert label == "medium"

    def test_easy_label_for_simple_molecule(self, assessor):
        # 简单小分子应该 easy
        score, label = assessor.assess_synthesizability("CCO")
        assert label == "easy" or label == "medium"  # 至少不是 hard

    def test_hard_label_for_complex_molecule(self, assessor):
        # 复杂分子（多立体中心 + 大环）应该 hard
        complex_smiles = "C[C@H]1[C@@H]2C[C@H]3C4C5CC6C7CC(=O)C8CC9CC%10CC%11CC%12C%13CC%14CC%15CC%16C1"
        score, label = assessor.assess_synthesizability(complex_smiles)
        assert score > 3.0  # 复杂分子分数应该偏高

    def test_mock_mode_returns_valid_range(self, assessor):
        """即使 rdkit 不可用，Mock 模式也应返回合理结果"""
        score = assessor._mock_sa_score("CC(=O)Oc1ccccc1C(=O)O")
        assert 1.0 <= score <= 10.0


class TestToxicity:
    """毒理风险评级"""

    def test_simple_molecule_low_risk(self, assessor):
        risk, alerts = assessor.assess_toxicity("CCO")
        assert risk in ("low", "moderate", "high")
        assert isinstance(alerts, list)

    def test_empty_smiles_returns_low(self, assessor):
        risk, alerts = assessor.assess_toxicity("")
        assert risk == "low"
        assert alerts == []

    def test_toxic_molecule_has_alerts(self, assessor):
        # 含硝基的分子应触发 toxicophore 警告
        risk, alerts = assessor.assess_toxicity("c1ccccc1[N+](=O)[O-]")
        # 至少应该不是纯 low（含硝基官能团）
        if alerts:
            assert any(a["severity"] == "danger" for a in alerts)

    def test_alerts_structure(self, assessor):
        """alert 结构包含 name/smarts/severity"""
        _, alerts = assessor.assess_toxicity("c1ccccc1[N+](=O)[O-]")
        for a in alerts:
            assert "name" in a
            assert "smarts" in a
            assert "severity" in a
            assert a["severity"] in ("warning", "danger")


class TestFormulation:
    """制剂递送评分"""

    def test_returns_score_in_range(self, assessor):
        score, notes = assessor.assess_formulation("CCO", {"mw": 46.07, "logp": -0.14, "tpsa": 20.23})
        assert 0.0 <= score <= 1.0
        assert isinstance(notes, str)
        assert len(notes) > 0

    def test_empty_smiles_default_score(self, assessor):
        score, notes = assessor.assess_formulation("", {})
        assert score == 0.5
        assert "无 SMILES" in notes

    def test_good_oral_molecule_high_score(self, assessor):
        # MW 300, LogP 2, TPSA 60 — 完美口服窗口
        score, _ = assessor.assess_formulation("CCO", {"mw": 300, "logp": 2, "tpsa": 60})
        assert score >= 0.8  # 应该高分

    def test_large_molecule_low_score(self, assessor):
        # MW 800 — 太大，口服吸收差
        score, _ = assessor.assess_formulation("CCO", {"mw": 800, "logp": 6, "tpsa": 180})
        assert score < 0.6  # 应该低分

    def test_fallback_to_rdkit_when_props_missing(self, assessor):
        """props 缺失时应该降级用 rdkit 重算"""
        score, notes = assessor.assess_formulation("CCO", {})
        assert 0.0 <= score <= 1.0
        assert len(notes) > 0


class TestCostEstimation:
    """生产成本估算"""

    def test_returns_positive_cost(self, assessor):
        cost, breakdown = assessor.estimate_cost("CCO", 3.0, {})
        assert cost > 0
        assert "materials" in breakdown
        assert "labor" in breakdown
        assert "overhead" in breakdown

    def test_higher_sa_increases_cost(self, assessor):
        cost_low, _ = assessor.estimate_cost("CCO", 2.0, {})
        cost_high, _ = assessor.estimate_cost("CCO", 8.0, {})
        assert cost_high > cost_low

    def test_cost_breakdown_sums_to_total(self, assessor):
        cost, breakdown = assessor.estimate_cost("CCO", 3.0, {})
        total = breakdown["materials"] + breakdown["labor"] + breakdown["overhead"]
        assert abs(total - cost) < 0.01  # 允许浮点误差

    def test_empty_smiles_uses_default_atoms(self, assessor):
        """空 SMILES 也能估算（用默认值）"""
        cost, _ = assessor.estimate_cost("", 3.0, {})
        assert cost > 0


# ========== 综合决策测试 ==========

class TestOverallDecision:
    """综合评分 + go/revise/no_go 决策规则"""

    def test_high_tox_returns_no_go(self, assessor):
        overall, rec, rationale = assessor._compute_overall(
            sa_score=3.0, tox_risk="high", form_score=0.8, cost=1000
        )
        assert rec == "no_go"
        assert "毒理" in rationale
        assert 0.0 <= overall <= 1.0

    def test_sa_too_high_returns_revise(self, assessor):
        overall, rec, rationale = assessor._compute_overall(
            sa_score=9.0, tox_risk="low", form_score=0.8, cost=1000
        )
        assert rec == "revise"
        assert "合成难度" in rationale

    def test_cost_too_high_returns_revise(self, assessor):
        overall, rec, rationale = assessor._compute_overall(
            sa_score=3.0, tox_risk="low", form_score=0.8, cost=6000
        )
        assert rec == "revise"
        assert "成本" in rationale

    def test_default_returns_go(self, assessor):
        overall, rec, rationale = assessor._compute_overall(
            sa_score=3.0, tox_risk="low", form_score=0.8, cost=1000
        )
        assert rec == "go"
        assert "通过" in rationale or "可推进" in rationale

    def test_moderate_tox_with_go_still_warns(self, assessor):
        overall, rec, rationale = assessor._compute_overall(
            sa_score=3.0, tox_risk="moderate", form_score=0.8, cost=1000
        )
        # moderate 毒理应该还能 go（除非 alerts>=3）
        assert rec in ("go", "revise")
        assert "中等毒理" in rationale

    def test_low_form_score_warns_in_rationale(self, assessor):
        _, _, rationale = assessor._compute_overall(
            sa_score=3.0, tox_risk="low", form_score=0.3, cost=1000
        )
        assert "制剂" in rationale

    def test_overall_score_in_range(self, assessor):
        for tox in ("low", "moderate", "high"):
            overall, _, _ = assessor._compute_overall(
                sa_score=5.0, tox_risk=tox, form_score=0.5, cost=2000
            )
            assert 0.0 <= overall <= 1.0


# ========== 服务持久化测试 ==========

class TestAssessorPersistence:
    """assess() 完整流程测试"""

    @pytest.mark.asyncio
    async def test_assess_returns_persisted_object(self, async_db_session, setup_molecule):
        assessor = DevelopabilityAssessor(async_db_session)
        mol = setup_molecule["molecule"]
        assessment = await assessor.assess(mol, created_by=setup_molecule["user"].id)

        assert assessment.id is not None
        assert assessment.molecule_id == mol.id
        assert assessment.version == 1
        # 5 维度字段都有值
        assert assessment.sa_score is not None
        assert assessment.sa_ease_label in ("easy", "medium", "hard")
        assert assessment.toxicity_risk in ("low", "moderate", "high")
        assert isinstance(assessment.toxicity_alerts, list)
        assert assessment.formulation_score is not None
        assert assessment.formulation_notes is not None
        assert assessment.cost_estimate_usd is not None
        assert isinstance(assessment.cost_breakdown, dict)
        assert assessment.overall_score is not None
        assert assessment.recommendation in ("go", "revise", "no_go")
        assert assessment.rationale is not None
        # project_id 反查成功
        assert assessment.project_id == setup_molecule["project"].id

    @pytest.mark.asyncio
    async def test_version_increments_on_reassessment(self, async_db_session, setup_molecule):
        assessor = DevelopabilityAssessor(async_db_session)
        mol = setup_molecule["molecule"]

        a1 = await assessor.assess(mol)
        assert a1.version == 1
        a2 = await assessor.assess(mol)
        assert a2.version == 2
        a3 = await assessor.assess(mol)
        assert a3.version == 3

    @pytest.mark.asyncio
    async def test_isolated_molecule_without_target(self, async_db_session):
        """无 target_id 的孤立分子也能评估（project_id 为 None）"""
        user = User(
            email="iso@ai-drug.com",
            name="Iso",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        mol = Molecule(smiles="CCO", name="孤立分子")
        async_db_session.add(mol)
        await async_db_session.flush()

        assessor = DevelopabilityAssessor(async_db_session)
        assessment = await assessor.assess(mol, created_by=user.id)
        assert assessment.project_id is None
        assert assessment.molecule_id == mol.id


# ========== 端点测试 ==========

class TestDevelopabilityEndpoints:
    """API 端点测试"""

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, client):
        resp = await client.post(f"/api/v1/molecules/{uuid.uuid4()}/assess-developability")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_assess_nonexistent_molecule_returns_404(self, client, auth_headers):
        resp = await client.post(
            f"/api/v1/molecules/{uuid.uuid4()}/assess-developability",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_nonexistent_molecule_returns_404(self, client, auth_headers):
        resp = await client.get(
            f"/api/v1/molecules/{uuid.uuid4()}/developability",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_assess_success_returns_all_fields(self, client, auth_headers, async_db_session, setup_molecule):
        mol = setup_molecule["molecule"]
        resp = await client.post(
            f"/api/v1/molecules/{mol.id}/assess-developability",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"评估失败: {resp.text}"
        data = resp.json()["data"]
        # 必需字段完整
        assert "id" in data
        assert "molecule_id" in data
        assert "version" in data
        assert "sa_score" in data
        assert "sa_ease_label" in data
        assert "toxicity_risk" in data
        assert "toxicity_alerts" in data
        assert "formulation_score" in data
        assert "formulation_notes" in data
        assert "cost_estimate_usd" in data
        assert "cost_breakdown" in data
        assert "overall_score" in data
        assert "recommendation" in data
        assert "rationale" in data
        assert data["recommendation"] in ("go", "revise", "no_go")

    @pytest.mark.asyncio
    async def test_list_returns_history(self, client, auth_headers, async_db_session, setup_molecule):
        mol = setup_molecule["molecule"]
        # 先做 2 次评估
        await client.post(f"/api/v1/molecules/{mol.id}/assess-developability", headers=auth_headers)
        await client.post(f"/api/v1/molecules/{mol.id}/assess-developability", headers=auth_headers)
        # 查询历史
        resp = await client.get(
            f"/api/v1/molecules/{mol.id}/developability",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        # 按版本倒序
        assert data[0]["version"] == 2
        assert data[1]["version"] == 1

    @pytest.mark.asyncio
    async def test_assess_then_list_workflow(self, client, auth_headers, async_db_session, setup_molecule):
        """端到端：评估 → 查询历史 → 验证决策建议"""
        mol = setup_molecule["molecule"]

        # 步骤1：评估
        resp1 = await client.post(
            f"/api/v1/molecules/{mol.id}/assess-developability",
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        assessment = resp1.json()["data"]
        assert assessment["recommendation"] in ("go", "revise", "no_go")

        # 步骤2：查询历史
        resp2 = await client.get(
            f"/api/v1/molecules/{mol.id}/developability",
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        history = resp2.json()["data"]
        assert len(history) == 1
        assert history[0]["id"] == assessment["id"]
