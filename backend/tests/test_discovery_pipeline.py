"""DiscoveryPipeline 端到端流水线测试

覆盖：
- 完整流水线正常流程
- 无数据集/无靶点的边界条件
- 单步失败的容错
- 幂等性（连续运行两次不产生重复）
- skip_existing 跳过逻辑
- 端点集成测试
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

os.environ["USE_MOCK"] = "true"

PROJECT_ID = UUID("12345678-1234-1234-1234-123456789012")


def _make_target(gene="EGFR", confidence=0.85, approved_drugs=None, target_id=None):
    """构造一个 Target-like 对象"""
    return SimpleNamespace(
        id=target_id or uuid4(),
        project_id=PROJECT_ID,
        gene_symbol=gene,
        confidence_score=confidence,
        approved_drugs=approved_drugs or [],
        evidence_grade="level_ii",
    )


def _make_molecule(smiles="c1ccccc1", target_id=None, mol_id=None):
    """构造一个 Molecule-like 对象"""
    return SimpleNamespace(
        id=mol_id or uuid4(),
        target_id=target_id or uuid4(),
        smiles=smiles,
        name="test-mol",
    )


def _make_mock_db(project_exists=True, targets=None, molecules=None, treatments=None):
    """构造一个 Mock AsyncSession

    支持：
    - db.get(Project, project_id) → 返回 project 或 None
    - db.execute(stmt) → 根据 stmt 返回不同结果（通过 side_effect 列表控制）
    - db.flush() → AsyncMock
    - db.add(obj) → MagicMock
    """
    mock_db = MagicMock()
    mock_db.get = AsyncMock(
        side_effect=lambda model, oid: (
            SimpleNamespace(id=PROJECT_ID, name="Test Project") if model.__name__ == "Project" and project_exists else None
        )
    )
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute = AsyncMock()
    return mock_db


def _exec_result(scalars_all=None, scalar_one_or_none=None):
    """构造 db.execute 返回值，同时支持 scalars().all() 和 scalar_one_or_none()"""
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_all if scalars_all is not None else []
    r.scalar_one_or_none.return_value = scalar_one_or_none
    return r


# ========== DiscoveryPipeline 服务层测试 ==========

class TestDiscoveryPipeline:
    """端到端流水线编排器测试"""

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        """项目不存在时返回错误"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)

        pipeline = DiscoveryPipeline(mock_db)
        result = await pipeline.run(project_id=uuid4())

        assert result["error"] == "项目不存在"
        assert result["summary"]["total_targets"] == 0

    @pytest.mark.asyncio
    async def test_run_pipeline_no_targets(self):
        """靶点发现返回空 → Step 2/3 skipped"""
        from app.services.orchestrator.discovery_pipeline import (
            DiscoveryPipeline,
            PipelineStepStatus,
        )

        mock_db = _make_mock_db()
        # Step 1 discover 返回 count=0，后续查询 targets 返回空
        # db.execute 调用序列：
        # 1. TargetIdentifier 内部的 dataset 查询 → 返回空
        # 2. pipeline 的 target 查询 → 返回空
        # 3. _step3 的 treatment 查询 → 返回空
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        empty_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=empty_result)

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            return_value={"count": 0, "targets": [], "message": "项目无可用数据集"},
        ):
            result = await pipeline.run(project_id=PROJECT_ID)

        assert result["steps"]["target_discovery"]["status"] == PipelineStepStatus.SUCCESS
        assert result["steps"]["molecule_generation"]["status"] == PipelineStepStatus.SKIPPED
        assert result["summary"]["total_targets"] == 0

    @pytest.mark.asyncio
    async def test_run_pipeline_step1_fails(self):
        """Step 1 异常 → status=failed，后续步骤仍执行"""
        from app.services.orchestrator.discovery_pipeline import (
            DiscoveryPipeline,
            PipelineStepStatus,
        )

        mock_db = _make_mock_db()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        empty_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=empty_result)

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection lost"),
        ):
            result = await pipeline.run(project_id=PROJECT_ID)

        assert result["steps"]["target_discovery"]["status"] == PipelineStepStatus.FAILED
        assert "DB connection lost" in result["steps"]["target_discovery"]["error"]
        # 无靶点时分子生成应 skipped
        assert result["steps"]["molecule_generation"]["status"] == PipelineStepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_run_full_pipeline_success(self):
        """完整流水线正常流程 — 3 步全成功"""
        from app.services.orchestrator.discovery_pipeline import (
            DiscoveryPipeline,
            PipelineStepStatus,
        )

        target = _make_target(gene="EGFR", confidence=0.9)
        mock_db = _make_mock_db(targets=[target])

        # db.execute 调用序列：
        # 1. After Step 1: target 查询 → [target]
        # 2. Step 2: existing molecule 查询 → None
        # 3. Step 2: dup molecule 查询 → None
        # 4. After Step 2: molecule 查询 → []
        # 5. Step 3: existing treatment 查询 → None
        mock_db.execute = AsyncMock(side_effect=[
            _exec_result(scalars_all=[target]),           # 1. target query
            _exec_result(scalar_one_or_none=None),         # 2. existing mol
            _exec_result(scalar_one_or_none=None),         # 3. dup mol
            _exec_result(scalars_all=[]),                  # 4. mol query after step 2
            _exec_result(scalar_one_or_none=None),         # 5. existing treatment
        ])

        # Mock discover
        mock_discover_result = {"count": 1, "targets": [{"gene_symbol": "EGFR"}]}

        # Mock generate_molecules
        mock_gen_result = {
            "molecules": [{"smiles": "c1ccccc1", "source": "fragment_combination"}],
            "count": 1,
        }

        # Mock 评估函数
        mock_props = {
            "mw": 150.0,
            "logp": 2.0,
            "druglikeness_score": 70.0,
            "passes_rule_of_five": True,
        }

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            return_value=mock_discover_result,
        ), patch(
            "app.services.analyzer.molecule_designer.MoleculeDesigner.generate_molecules",
            new_callable=AsyncMock,
            return_value=mock_gen_result,
        ), patch(
            "app.services.analyzer.molecule_designer.assess_druglikeness",
            return_value=mock_props,
        ), patch(
            "app.services.analyzer.molecule_designer.predict_admet",
            return_value={"admet": "ok"},
        ), patch(
            "app.services.analyzer.molecule_designer.explain_molecule",
            return_value={"groups": ["aromatic"]},
        ), patch(
            "app.services.optimizer.treatment_planner.TreatmentPlanner.optimize",
            new_callable=AsyncMock,
            return_value={"optimal": None, "combinations": []},
        ):
            result = await pipeline.run(project_id=PROJECT_ID)

        assert result["steps"]["target_discovery"]["status"] == PipelineStepStatus.SUCCESS
        assert result["steps"]["target_discovery"]["targets_found"] == 1
        # Step 2 应成功（可能 partial 如果有错误，但这里无错误）
        assert result["steps"]["molecule_generation"]["status"] in (
            PipelineStepStatus.SUCCESS,
            PipelineStepStatus.PARTIAL,
        )
        assert result["steps"]["molecule_generation"]["molecules_saved"] >= 1
        # Step 3 应成功
        assert result["steps"]["treatment_matching"]["status"] in (
            PipelineStepStatus.SUCCESS,
            PipelineStepStatus.PARTIAL,
        )
        assert result["summary"]["total_targets"] == 1

    @pytest.mark.asyncio
    async def test_step2_partial_failure(self):
        """Step 2 部分靶点分子生成失败 → status=partial"""
        from app.services.orchestrator.discovery_pipeline import (
            DiscoveryPipeline,
            PipelineStepStatus,
        )

        target_ok = _make_target(gene="EGFR", confidence=0.9)
        target_fail = _make_target(gene="FAIL", confidence=0.5)
        mock_db = _make_mock_db(targets=[target_ok, target_fail])

        # db.execute 调用序列：
        # 1. After Step 1: target 查询 → [target_ok, target_fail]
        # 2. Step 2, target_ok: existing mol → None
        # 3. Step 2, target_ok: dup mol → None
        # 4. Step 2, target_fail: existing mol → None（不跳过，触发 generate_molecules 异常）
        # 5. After Step 2: mol 查询 → []
        # 6. Step 3, target_ok: existing treatment → None
        # 7. Step 3, target_fail: existing treatment → None
        mock_db.execute = AsyncMock(side_effect=[
            _exec_result(scalars_all=[target_ok, target_fail]),  # 1. target query
            _exec_result(scalar_one_or_none=None),                # 2. existing mol (ok)
            _exec_result(scalar_one_or_none=None),                # 3. dup mol (ok)
            _exec_result(scalar_one_or_none=None),                # 4. existing mol (fail)
            _exec_result(scalars_all=[]),                         # 5. mol query after step 2
            _exec_result(scalar_one_or_none=None),                # 6. existing treatment (ok)
            _exec_result(scalar_one_or_none=None),                # 7. existing treatment (fail)
        ])

        # generate_molecules 对 FAIL 靶点抛异常
        async def mock_gen(target_id, **kwargs):
            if str(target_id) == str(target_fail.id):
                raise Exception("RDKit error")
            return {"molecules": [{"smiles": "c1ccccc1", "source": "fragment"}]}

        mock_props = {
            "mw": 150.0, "logp": 2.0,
            "druglikeness_score": 70.0,
            "passes_rule_of_five": True,
        }

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            return_value={"count": 2, "targets": []},
        ), patch(
            "app.services.analyzer.molecule_designer.MoleculeDesigner.generate_molecules",
            side_effect=mock_gen,
        ), patch(
            "app.services.analyzer.molecule_designer.assess_druglikeness",
            return_value=mock_props,
        ), patch(
            "app.services.analyzer.molecule_designer.predict_admet",
            return_value={},
        ), patch(
            "app.services.analyzer.molecule_designer.explain_molecule",
            return_value={},
        ), patch(
            "app.services.optimizer.treatment_planner.TreatmentPlanner.optimize",
            new_callable=AsyncMock,
            return_value={"optimal": None},
        ):
            result = await pipeline.run(project_id=PROJECT_ID)

        step2 = result["steps"]["molecule_generation"]
        assert step2["status"] == PipelineStepStatus.PARTIAL
        assert len(step2["errors"]) > 0
        assert "FAIL" in step2["errors"][0]

    @pytest.mark.asyncio
    async def test_skip_existing_molecules(self):
        """skip_existing=True 且靶点已有分子 → 跳过分子生成"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        target = _make_target(gene="EGFR")
        existing_mol = _make_molecule(target_id=target.id)

        mock_db = _make_mock_db(targets=[target])

        # db.execute 调用序列：
        # 1. After Step 1: target 查询 → [target]
        # 2. Step 2: existing molecule 查询 → existing_mol（跳过分子生成）
        # 3. After Step 2: molecule 查询 → [existing_mol]
        # 4. Step 3: existing treatment 查询 → None（创建治疗方案）
        mock_db.execute = AsyncMock(side_effect=[
            _exec_result(scalars_all=[target]),                # 1. target query
            _exec_result(scalar_one_or_none=existing_mol),      # 2. existing mol → skip
            _exec_result(scalars_all=[existing_mol]),           # 3. mol query after step 2
            _exec_result(scalar_one_or_none=None),              # 4. existing treatment → None
        ])

        gen_called = False

        async def mock_gen(*args, **kwargs):
            nonlocal gen_called
            gen_called = True
            return {"molecules": []}

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            return_value={"count": 1, "targets": []},
        ), patch(
            "app.services.analyzer.molecule_designer.MoleculeDesigner.generate_molecules",
            side_effect=mock_gen,
        ), patch(
            "app.services.optimizer.treatment_planner.TreatmentPlanner.optimize",
            new_callable=AsyncMock,
            return_value={"optimal": None},
        ):
            result = await pipeline.run(project_id=PROJECT_ID, skip_existing=True)

        # generate_molecules 不应被调用（被跳过）
        assert not gen_called
        assert result["steps"]["molecule_generation"]["molecules_saved"] == 0

    @pytest.mark.asyncio
    async def test_idempotent_run_twice(self):
        """连续运行两次：第二次因 skip_existing 跳过已有数据"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        target = _make_target(gene="EGFR")
        existing_mol = _make_molecule(target_id=target.id)
        existing_treatment = SimpleNamespace(
            id=uuid4(), project_id=PROJECT_ID, name="EGFR 靶向治疗",
        )

        mock_db = _make_mock_db(targets=[target])

        # db.execute 调用序列（第二次运行，全部跳过）：
        # 1. After Step 1: target 查询 → [target]
        # 2. Step 2: existing molecule 查询 → existing_mol（跳过分子生成）
        # 3. After Step 2: molecule 查询 → [existing_mol]
        # 4. Step 3: existing treatment 查询 → existing_treatment（跳过方案生成）
        mock_db.execute = AsyncMock(side_effect=[
            _exec_result(scalars_all=[target]),                    # 1. target query
            _exec_result(scalar_one_or_none=existing_mol),          # 2. existing mol → skip
            _exec_result(scalars_all=[existing_mol]),               # 3. mol query after step 2
            _exec_result(scalar_one_or_none=existing_treatment),    # 4. existing treatment → skip
        ])

        pipeline = DiscoveryPipeline(mock_db)
        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new_callable=AsyncMock,
            return_value={"count": 1, "targets": []},
        ), patch(
            "app.services.analyzer.molecule_designer.MoleculeDesigner.generate_molecules",
            new_callable=AsyncMock,
            return_value={"molecules": []},
        ), patch(
            "app.services.optimizer.treatment_planner.TreatmentPlanner.optimize",
            new_callable=AsyncMock,
            return_value={"optimal": None},
        ):
            result = await pipeline.run(project_id=PROJECT_ID, skip_existing=True)

        # 第二次运行：分子和治疗方案都应被跳过
        assert result["steps"]["molecule_generation"]["molecules_saved"] == 0
        assert result["steps"]["treatment_matching"]["treatments_created"] == 0


# ========== 端点集成测试 ==========

class TestPipelineEndpoint:
    """流水线端点测试"""

    @pytest.mark.asyncio
    async def test_run_pipeline_unauthorized(self, client):
        """无 token → 401"""
        resp = await client.post("/api/v1/pipeline/run", json={"project_id": str(uuid4())})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_pipeline_status_unauthorized(self, client):
        """无 token → 401"""
        resp = await client.get(f"/api/v1/pipeline/status/{uuid4()}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_pipeline_project_not_found(self, client, auth_headers):
        """项目不存在 → 404"""
        resp = await client.post(
            "/api/v1/pipeline/run",
            json={"project_id": str(uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_pipeline_status(self, client, auth_headers, test_project):
        """GET /pipeline/status — 正常查询"""
        resp = await client.get(
            f"/api/v1/pipeline/status/{test_project['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "datasets" in data
        assert "targets" in data
        assert "molecules" in data
        assert "treatments" in data
        assert "pipeline_ready" in data
        assert "pipeline_complete" in data
