"""molecules 工具组测试 — 4 个工具 + _check_molecule_access"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.molecules import (
    AssessDruglikenessTool,
    DesignMoleculesTool,
    DesignMultiTargetTool,
    DockMoleculeTool,
    _check_molecule_access,
)


# 合法 UUID 字符串
_M1 = str(uuid4())
_M2 = str(uuid4())
_T1 = str(uuid4())
_T2 = str(uuid4())


def _make_ctx(db=None, user=None):
    return ToolContext(
        db=db or MagicMock(),
        user=user or MagicMock(),
        task_id="task-m",
        session_id="session-m",
    )


def _make_user(role):
    u = MagicMock()
    u.id = uuid4()
    u.role = role
    return u


# ========== _check_molecule_access ==========


@pytest.mark.asyncio
async def test_check_molecule_access_founder_bypass():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)
    assert await _check_molecule_access(ctx, _M1) is True


@pytest.mark.asyncio
async def test_check_molecule_access_molecule_not_found():
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)
    assert await _check_molecule_access(ctx, _M1) is False


@pytest.mark.asyncio
async def test_check_molecule_access_no_target_id():
    """mol.target_id=None → False"""
    user = _make_user(UserRole.RESEARCHER)
    mol = MagicMock()
    mol.target_id = None
    db = MagicMock()
    db.get = AsyncMock(return_value=mol)
    ctx = _make_ctx(db, user)
    assert await _check_molecule_access(ctx, _M1) is False


@pytest.mark.asyncio
async def test_check_molecule_access_target_not_found():
    """target 不存在 → False"""
    user = _make_user(UserRole.RESEARCHER)
    mol = MagicMock()
    mol.target_id = uuid4()
    db = MagicMock()

    # 第一次 get(Molecule) 返回 mol，第二次 get(Target) 返回 None
    db.get = AsyncMock(side_effect=[mol, None])
    ctx = _make_ctx(db, user)
    assert await _check_molecule_access(ctx, _M1) is False


@pytest.mark.asyncio
async def test_check_molecule_access_chain_ok():
    """molecule→target→project→owner 链路通过 → True"""
    user = _make_user(UserRole.RESEARCHER)
    mol = MagicMock()
    mol.target_id = uuid4()
    target = MagicMock()
    target.project_id = uuid4()
    project = MagicMock()
    project.owner_id = user.id
    db = MagicMock()
    db.get = AsyncMock(side_effect=[mol, target, project])
    ctx = _make_ctx(db, user)
    assert await _check_molecule_access(ctx, _M1) is True


# ========== DesignMoleculesTool ==========


@pytest.mark.asyncio
async def test_design_molecules_success():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.MoleculeDesigner"
    ) as MockDesigner:
        instance = MockDesigner.return_value
        instance.generate_molecules = AsyncMock(
            return_value={"molecules": [{"smiles": "CCO"}]}
        )
        tool = DesignMoleculesTool()
        result = await tool.execute({"target_id": _T1}, ctx)

    assert result.success is True
    assert result.display["type"] == "molecule_list"


@pytest.mark.asyncio
async def test_design_molecules_no_permission():
    """非 FOUNDER + target 不存在 → fail"""
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)

    tool = DesignMoleculesTool()
    result = await tool.execute({"target_id": _T2}, ctx)
    assert result.success is False
    assert "靶点不存在" in result.error


@pytest.mark.asyncio
async def test_design_molecules_n_clamped_high():
    """n=100 → 内部 clamp 到 50"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.MoleculeDesigner"
    ) as MockDesigner:
        instance = MockDesigner.return_value
        instance.generate_molecules = AsyncMock(return_value={"molecules": []})
        tool = DesignMoleculesTool()
        await tool.execute({"target_id": _T1, "n": 100}, ctx)
        # 验证 n 被 clamp 到 50
        assert instance.generate_molecules.call_args.kwargs["n"] == 50


@pytest.mark.asyncio
async def test_design_molecules_n_clamped_low():
    """n=0 → clamp 到 1"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.MoleculeDesigner"
    ) as MockDesigner:
        instance = MockDesigner.return_value
        instance.generate_molecules = AsyncMock(return_value={"molecules": []})
        tool = DesignMoleculesTool()
        await tool.execute({"target_id": _T1, "n": 0}, ctx)
        assert instance.generate_molecules.call_args.kwargs["n"] == 1


# ========== DesignMultiTargetTool ==========


@pytest.mark.asyncio
async def test_design_multi_target_success():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.MoleculeDesigner"
    ) as MockDesigner:
        instance = MockDesigner.return_value
        instance.design_multi_target = AsyncMock(return_value={"molecules": []})
        tool = DesignMultiTargetTool()
        result = await tool.execute(
            {"targets": [{"target_id": _T1, "name": "EGFR"}]}, ctx
        )

    assert result.success is True


@pytest.mark.asyncio
async def test_design_multi_target_empty_targets():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    tool = DesignMultiTargetTool()
    result = await tool.execute({"targets": []}, ctx)
    assert result.success is False
    assert "非空数组" in result.error


@pytest.mark.asyncio
async def test_design_multi_target_too_many_targets():
    """超过 10 个靶点 → fail"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    targets = [{"target_id": str(uuid4())} for _ in range(11)]
    tool = DesignMultiTargetTool()
    result = await tool.execute({"targets": targets}, ctx)
    assert result.success is False
    assert "10" in result.error


# ========== AssessDruglikenessTool ==========


@pytest.mark.asyncio
async def test_assess_druglikeness_success():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.assess_druglikeness",
        return_value={"mw": 180, "logp": 2.5, "violations": 0},
    ):
        tool = AssessDruglikenessTool()
        result = await tool.execute({"smiles": "CCO"}, ctx)

    assert result.success is True
    assert result.data["mw"] == 180
    assert result.display["type"] == "stats"


@pytest.mark.asyncio
async def test_assess_druglikeness_error_in_result():
    """assess_druglikeness 返回 error 字段 → fail"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.assess_druglikeness",
        return_value={"error": "invalid SMILES"},
    ):
        tool = AssessDruglikenessTool()
        result = await tool.execute({"smiles": "xxx"}, ctx)

    assert result.success is False
    assert "invalid SMILES" in result.error


@pytest.mark.asyncio
async def test_assess_druglikeness_raises():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.molecule_designer.assess_druglikeness",
        side_effect=RuntimeError("rdkit failed"),
    ):
        tool = AssessDruglikenessTool()
        result = await tool.execute({"smiles": "CCO"}, ctx)

    assert result.success is False
    assert "rdkit failed" in result.error


# ========== DockMoleculeTool ==========


def test_dock_molecule_metadata():
    """元数据断言：side_effects + required_role"""
    tool = DockMoleculeTool()
    assert tool.name == "dock_molecule"
    assert tool.side_effects is True
    assert tool.required_role == UserRole.RESEARCHER


@pytest.mark.asyncio
async def test_dock_molecule_no_permission():
    """非 FOUNDER + 分子不存在 → fail"""
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)

    tool = DockMoleculeTool()
    result = await tool.execute(
        {"molecule_id": _M2, "protein_pdb": "PDB"}, ctx
    )
    assert result.success is False
    assert "无权操作" in result.error


@pytest.mark.asyncio
async def test_dock_molecule_success():
    user = _make_user(UserRole.FOUNDER)
    mol = MagicMock()
    mol.id = _M1
    mol.smiles = "CCO"
    db = MagicMock()
    db.get = AsyncMock(return_value=mol)
    db.flush = AsyncMock()  # dock_molecule 内部会 await ctx.db.flush()
    ctx = _make_ctx(db, user)

    with patch(
        "app.core.deps.get_diffdock_client",
        return_value=MagicMock(dock=AsyncMock(return_value={"score": -9.5})),
    ):
        tool = DockMoleculeTool()
        result = await tool.execute(
            {"molecule_id": _M1, "protein_pdb": "PDB"}, ctx
        )

    assert result.success is True
    assert result.data["score"] == -9.5
    assert result.display["type"] == "docking"
