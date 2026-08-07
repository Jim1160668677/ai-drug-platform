"""干湿闭环验证编排器测试 — 阶段4 后端单测

覆盖：
1. TestSubmitTask（6 测试）— 创建并提交验证任务
   - 成功 / 缺 project / 空 hypothesis / 非法 task_type / 未知 target / 未知 molecule
2. TestLinkExperiment（3 测试）— 关联湿实验
   - 成功（→ in_progress）/ 未知 task / 未知 experiment
3. TestRecordResult（4 测试）— 记录实验结果与结论
   - validated / refuted / inconclusive / 非法 conclusion
4. TestApplyFeedback（10 测试）— 反馈到 target.confidence_score 与 molecule.properties
   - validated +0.1 / refuted -0.2 / inconclusive 不变 / None 初始化 0.5
   - 上限 1.0 / 下限 0.0 / 幂等 / molecule.properties 写入 / 未知 task / 无 conclusion
5. TestValidationEndpoints（4 测试）— 端点权限与全流程
   - 未认证 401 / 创建 200 / 列表 / apply-feedback 全流程

设计要点：
- Experiment fixture 必须含 name + exp_type（nullable=False）
- 反馈数值规则：validated +0.1（上限 1.0）/ refuted -0.2（下限 0.0）/ inconclusive 不变 / None 初始化 0.5
- 幂等：feedback_applied=True 后再次调用返回 {skipped: True}
"""
import uuid

import pytest

from app.core.security import hash_password, UserRole
from app.models.experiment import Experiment, ExperimentStatus
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.models.user import User
from app.models.validation import (
    ValidationConclusion,
    ValidationTask,
    ValidationTaskStatus,
    ValidationTaskType,
)
from app.services.validation import ValidationOrchestrator


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_chain(async_db_session):
    """创建完整 user → project → target → molecule 数据链

    target.confidence_score=0.7，方便验证 +0.1/-0.2 后结果。
    """
    user = User(
        email="val-test@ai-drug.com",
        name="Val Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    project = Project(name="干湿验证测试项目", owner_id=user.id)
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
        properties={"mw": 46.07, "logp": -0.14},
    )
    async_db_session.add(molecule)
    await async_db_session.flush()

    return {
        "user": user,
        "project": project,
        "target": target,
        "molecule": molecule,
    }


@pytest.fixture
async def setup_experiment(async_db_session, setup_chain):
    """在 setup_chain 基础上创建实验记录"""
    exp = Experiment(
        project_id=setup_chain["project"].id,
        name="EGFR 敲降实验",
        exp_type="in_vitro",
        status=ExperimentStatus.PLANNED,
        target_id=setup_chain["target"].id,
    )
    async_db_session.add(exp)
    await async_db_session.flush()
    setup_chain["experiment"] = exp
    return setup_chain


def _submit_payload(chain, **overrides):
    """构造 submit_task 标准入参（默认 target_knockdown 假设）"""
    payload = {
        "project_id": str(chain["project"].id),
        "target_id": str(chain["target"].id),
        "molecule_id": str(chain["molecule"].id),
        "task_type": ValidationTaskType.TARGET_KNOCKDOWN,
        "hypothesis": "EGFR 敲降后 A549 细胞活力下降 >30%",
        "prediction": "细胞活力下降至 65%",
    }
    payload.update(overrides)
    return payload


# ========== TestSubmitTask ==========

class TestSubmitTask:
    @pytest.mark.asyncio
    async def test_submit_task_success(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))

        assert task.id is not None
        assert task.project_id == setup_chain["project"].id
        assert task.target_id == setup_chain["target"].id
        assert task.molecule_id == setup_chain["molecule"].id
        assert task.task_type == ValidationTaskType.TARGET_KNOCKDOWN
        assert task.hypothesis == "EGFR 敲降后 A549 细胞活力下降 >30%"
        assert task.prediction == "细胞活力下降至 65%"
        assert task.status == ValidationTaskStatus.SUBMITTED
        assert task.submitted_at is not None
        assert task.feedback_applied is False

    @pytest.mark.asyncio
    async def test_submit_task_missing_project_raises(self, async_db_session):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="project_id 不能为空"):
            await svc.submit_task({
                "task_type": ValidationTaskType.TARGET_KNOCKDOWN,
                "hypothesis": "测试假设",
            })

    @pytest.mark.asyncio
    async def test_submit_task_empty_hypothesis_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="hypothesis"):
            await svc.submit_task(_submit_payload(setup_chain, hypothesis="   "))

    @pytest.mark.asyncio
    async def test_submit_task_invalid_task_type_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="非法 task_type"):
            await svc.submit_task(_submit_payload(setup_chain, task_type="unknown_type"))

    @pytest.mark.asyncio
    async def test_submit_task_unknown_target_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="靶点不存在"):
            await svc.submit_task(_submit_payload(
                setup_chain, target_id=str(uuid.uuid4())
            ))

    @pytest.mark.asyncio
    async def test_submit_task_unknown_molecule_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="分子不存在"):
            await svc.submit_task(_submit_payload(
                setup_chain, molecule_id=str(uuid.uuid4())
            ))


# ========== TestLinkExperiment ==========

class TestLinkExperiment:
    @pytest.mark.asyncio
    async def test_link_experiment_success(self, async_db_session, setup_experiment):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_experiment))

        linked = await svc.link_experiment(
            str(task.id), str(setup_experiment["experiment"].id)
        )
        assert linked.experiment_id == setup_experiment["experiment"].id
        assert linked.status == ValidationTaskStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_link_experiment_unknown_task_raises(self, async_db_session, setup_experiment):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="验证任务不存在"):
            await svc.link_experiment(
                str(uuid.uuid4()), str(setup_experiment["experiment"].id)
            )

    @pytest.mark.asyncio
    async def test_link_experiment_unknown_experiment_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))
        with pytest.raises(Exception, match="实验不存在"):
            await svc.link_experiment(str(task.id), str(uuid.uuid4()))


# ========== TestRecordResult ==========

class TestRecordResult:
    @pytest.mark.asyncio
    async def test_record_result_validated(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))

        result = await svc.record_result(
            str(task.id),
            actual_result="细胞活力下降至 60%（预测 65%，方向一致）",
            conclusion=ValidationConclusion.VALIDATED,
            next_action="进入 PDX 动物模型验证",
        )
        assert result.conclusion == ValidationConclusion.VALIDATED
        assert result.status == ValidationConclusion.VALIDATED  # 状态即结论
        assert result.actual_result is not None
        assert result.next_action == "进入 PDX 动物模型验证"
        assert result.result_received_at is not None

    @pytest.mark.asyncio
    async def test_record_result_refuted(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))

        result = await svc.record_result(
            str(task.id),
            actual_result="细胞活力无明显变化",
            conclusion=ValidationConclusion.REFUTED,
        )
        assert result.conclusion == ValidationConclusion.REFUTED
        assert result.status == ValidationConclusion.REFUTED

    @pytest.mark.asyncio
    async def test_record_result_inconclusive(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))

        result = await svc.record_result(
            str(task.id),
            actual_result="实验样本量不足，结论不确定",
            conclusion=ValidationConclusion.INCONCLUSIVE,
        )
        assert result.conclusion == ValidationConclusion.INCONCLUSIVE
        assert result.status == ValidationConclusion.INCONCLUSIVE

    @pytest.mark.asyncio
    async def test_record_result_invalid_conclusion_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))
        with pytest.raises(Exception, match="非法 conclusion"):
            await svc.record_result(
                str(task.id),
                actual_result="结果",
                conclusion="wrong_conclusion",
            )


# ========== TestApplyFeedback ==========

class TestApplyFeedback:
    @pytest.mark.asyncio
    async def _prepare_recorded_task(self, async_db_session, setup_chain, conclusion):
        """辅助：提交任务 + 记录结论，返回 task_id"""
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))
        await svc.record_result(
            str(task.id), actual_result="结果", conclusion=conclusion
        )
        return svc, task

    @pytest.mark.asyncio
    async def test_apply_feedback_validated_increases_confidence(self, async_db_session, setup_chain):
        """validated → confidence 0.7 + 0.1 = 0.8"""
        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.VALIDATED
        )
        result = await svc.apply_feedback(str(task.id))

        assert result["feedback_applied"] is True
        assert result["conclusion"] == ValidationConclusion.VALIDATED
        assert result["target_confidence_before"] == 0.7
        assert result["target_confidence_after"] == 0.8

        # DB 中 target.confidence_score 已更新
        refreshed = await async_db_session.get(Target, setup_chain["target"].id)
        assert refreshed.confidence_score == 0.8

    @pytest.mark.asyncio
    async def test_apply_feedback_refuted_decreases_confidence(self, async_db_session, setup_chain):
        """refuted → confidence 0.7 - 0.2 = 0.5"""
        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.REFUTED
        )
        result = await svc.apply_feedback(str(task.id))

        assert result["target_confidence_before"] == 0.7
        assert result["target_confidence_after"] == 0.5

        refreshed = await async_db_session.get(Target, setup_chain["target"].id)
        assert refreshed.confidence_score == 0.5

    @pytest.mark.asyncio
    async def test_apply_feedback_inconclusive_no_change(self, async_db_session, setup_chain):
        """inconclusive → confidence 不变"""
        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.INCONCLUSIVE
        )
        result = await svc.apply_feedback(str(task.id))

        assert result["target_confidence_before"] == 0.7
        assert result["target_confidence_after"] == 0.7  # 不变

    @pytest.mark.asyncio
    async def test_apply_feedback_none_confidence_initialized(self, async_db_session, setup_chain):
        """confidence=None → 初始化 0.5 再调整（validated → 0.6）"""
        # 显式置空
        setup_chain["target"].confidence_score = None
        await async_db_session.flush()

        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.VALIDATED
        )
        result = await svc.apply_feedback(str(task.id))

        # None → 0.5 → +0.1 = 0.6
        assert result["target_confidence_before"] is None
        assert result["target_confidence_after"] == 0.6

    @pytest.mark.asyncio
    async def test_apply_feedback_validated_cap_at_1(self, async_db_session, setup_chain):
        """validated → confidence 0.95 + 0.1 = 1.05 → cap 1.0"""
        setup_chain["target"].confidence_score = 0.95
        await async_db_session.flush()

        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.VALIDATED
        )
        result = await svc.apply_feedback(str(task.id))
        assert result["target_confidence_after"] == 1.0

    @pytest.mark.asyncio
    async def test_apply_feedback_refuted_floor_at_0(self, async_db_session, setup_chain):
        """refuted → confidence 0.1 - 0.2 = -0.1 → floor 0.0"""
        setup_chain["target"].confidence_score = 0.1
        await async_db_session.flush()

        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.REFUTED
        )
        result = await svc.apply_feedback(str(task.id))
        assert result["target_confidence_after"] == 0.0

    @pytest.mark.asyncio
    async def test_apply_feedback_idempotent_skipped(self, async_db_session, setup_chain):
        """第二次调用返回 skipped=True，confidence 不再变化"""
        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.VALIDATED
        )
        # 第一次：0.7 → 0.8
        first = await svc.apply_feedback(str(task.id))
        assert first["feedback_applied"] is True
        assert first["target_confidence_after"] == 0.8

        # 第二次：跳过，confidence 不再 +0.1
        second = await svc.apply_feedback(str(task.id))
        assert second.get("skipped") is True

        refreshed = await async_db_session.get(Target, setup_chain["target"].id)
        assert refreshed.confidence_score == 0.8  # 仍是 0.8，未变成 0.9

    @pytest.mark.asyncio
    async def test_apply_feedback_writes_molecule_properties(self, async_db_session, setup_chain):
        """验证状态写入 molecule.properties['validation_status']"""
        svc, task = await self._prepare_recorded_task(
            async_db_session, setup_chain, ValidationConclusion.VALIDATED
        )
        result = await svc.apply_feedback(str(task.id))

        assert result["molecule_status"] == ValidationConclusion.VALIDATED
        assert result["molecule_id"] == str(setup_chain["molecule"].id)

        refreshed = await async_db_session.get(Molecule, setup_chain["molecule"].id)
        assert refreshed.properties["validation_status"] == ValidationConclusion.VALIDATED
        assert refreshed.properties["validation_task_id"] == str(task.id)

    @pytest.mark.asyncio
    async def test_apply_feedback_unknown_task_raises(self, async_db_session, setup_chain):
        svc = ValidationOrchestrator(async_db_session)
        with pytest.raises(Exception, match="验证任务不存在"):
            await svc.apply_feedback(str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_apply_feedback_no_conclusion_raises(self, async_db_session, setup_chain):
        """任务未记录结论就调用反馈 → AppException"""
        svc = ValidationOrchestrator(async_db_session)
        task = await svc.submit_task(_submit_payload(setup_chain))  # 未 record_result

        with pytest.raises(Exception):
            await svc.apply_feedback(str(task.id))


# ========== TestValidationEndpoints ==========

class TestValidationEndpoints:
    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, client):
        resp = await client.get("/api/v1/validations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_validation_endpoint(self, client, auth_headers, test_project, async_db_session):
        """创建验证任务端点 → 200"""
        # 直接 ORM 创建 target（targets.py 无 POST 创建端点）
        from uuid import UUID
        target = Target(
            project_id=UUID(test_project["id"]),
            gene_symbol="KRAS",
            confidence_score=0.6,
        )
        async_db_session.add(target)
        await async_db_session.flush()
        target_id = str(target.id)

        resp = await client.post(
            "/api/v1/validations",
            json={
                "project_id": test_project["id"],
                "target_id": target_id,
                "task_type": ValidationTaskType.TARGET_KNOCKDOWN,
                "hypothesis": "KRAS 敲降抑制 PDX 肿瘤生长",
                "prediction": "肿瘤体积下降 40%",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"创建失败: {resp.text}"
        data = resp.json()["data"]
        assert data["task_type"] == ValidationTaskType.TARGET_KNOCKDOWN
        assert data["status"] == ValidationTaskStatus.SUBMITTED
        assert data["hypothesis"] == "KRAS 敲降抑制 PDX 肿瘤生长"
        assert data["target_id"] == target_id

    @pytest.mark.asyncio
    async def test_list_validations_endpoint(self, client, auth_headers, test_project):
        """列表端点 → paged_response"""
        # 先创建 2 个任务
        for hyp in ["假设 A", "假设 B"]:
            await client.post(
                "/api/v1/validations",
                json={
                    "project_id": test_project["id"],
                    "task_type": ValidationTaskType.CELL_VIABILITY,
                    "hypothesis": hyp,
                },
                headers=auth_headers,
            )

        resp = await client.get(
            f"/api/v1/validations?project_id={test_project['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2
        assert len(body["data"]) == 2

    @pytest.mark.asyncio
    async def test_apply_feedback_full_workflow(self, client, auth_headers, test_project, async_db_session):
        """端到端全流程：创建 → result → apply-feedback"""
        # 步骤1：ORM 创建 target（confidence=0.5）
        from uuid import UUID
        target = Target(
            project_id=UUID(test_project["id"]),
            gene_symbol="BRAF",
            confidence_score=0.5,
        )
        async_db_session.add(target)
        await async_db_session.flush()

        # 步骤2：创建验证任务
        create_resp = await client.post(
            "/api/v1/validations",
            json={
                "project_id": test_project["id"],
                "target_id": str(target.id),
                "task_type": ValidationTaskType.TARGET_OVEREXPRESSION,
                "hypothesis": "BRAF 过表达促进细胞增殖",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["data"]["id"]

        # 步骤3：记录结果（record_result 不依赖 link-experiment）
        result_resp = await client.post(
            f"/api/v1/validations/{task_id}/result",
            json={
                "actual_result": "BRAF 过表达后细胞增殖提升 2.1 倍",
                "conclusion": ValidationConclusion.VALIDATED,
            },
            headers=auth_headers,
        )
        assert result_resp.status_code == 200
        assert result_resp.json()["data"]["conclusion"] == ValidationConclusion.VALIDATED

        # 步骤4：触发反馈 → target.confidence 0.5 → 0.6
        feedback_resp = await client.post(
            f"/api/v1/validations/{task_id}/apply-feedback",
            headers=auth_headers,
        )
        assert feedback_resp.status_code == 200, feedback_resp.text
        fb = feedback_resp.json()["data"]
        assert fb["feedback_applied"] is True
        assert fb["target_confidence_before"] == 0.5
        assert fb["target_confidence_after"] == 0.6
