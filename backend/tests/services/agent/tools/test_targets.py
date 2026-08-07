"""targets 工具组测试 — 3 个工具 + 2 个权限校验函数"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.targets import (
    BuildEvidenceChainTool,
    DiscoverTargetsTool,
    PredictSynergyTool,
    _check_project_owner,
    _check_target_access,
)


# 合法 UUID 字符串（避免源代码内 UUID(project_id) 转换失败）
_P1 = str(uuid4())
_T1 = str(uuid4())
_T2 = str(uuid4())


def _make_ctx(db=None, user=None):
    """构造 ToolContext"""
    return ToolContext(
        db=db or MagicMock(),
        user=user or MagicMock(),
        task_id="task-t",
        session_id="session-t",
    )


def _make_user(role):
    """构造指定角色的 mock user"""
    u = MagicMock()
    u.id = uuid4()
    u.role = role
    return u


# ========== _check_project_owner ==========


@pytest.mark.asyncio
async def test_check_project_owner_founder_bypass():
    """FOUNDER 角色直接 True，不查 DB"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)
    result = await _check_project_owner(ctx, _P1)
    assert result is True


@pytest.mark.asyncio
async def test_check_project_owner_researcher_owner():
    """researcher + owner 匹配 → True"""
    user = _make_user(UserRole.RESEARCHER)
    project = MagicMock()
    project.owner_id = user.id
    db = MagicMock()
    db.get = AsyncMock(return_value=project)
    ctx = _make_ctx(db, user)
    result = await _check_project_owner(ctx, _P1)
    assert result is True


@pytest.mark.asyncio
async def test_check_project_owner_researcher_not_owner():
    """researcher + owner 不匹配 → False"""
    user = _make_user(UserRole.RESEARCHER)
    project = MagicMock()
    project.owner_id = uuid4()  # 不同的 owner
    db = MagicMock()
    db.get = AsyncMock(return_value=project)
    ctx = _make_ctx(db, user)
    result = await _check_project_owner(ctx, _P1)
    assert result is False


@pytest.mark.asyncio
async def test_check_project_owner_nonexistent_project():
    """项目不存在 → False"""
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)
    result = await _check_project_owner(ctx, _P1)
    assert result is False


# ========== _check_target_access ==========


@pytest.mark.asyncio
async def test_check_target_access_founder_bypass():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)
    result = await _check_target_access(ctx, _T1)
    assert result is True


@pytest.mark.asyncio
async def test_check_target_access_target_not_found():
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)
    result = await _check_target_access(ctx, _T1)
    assert result is False


@pytest.mark.asyncio
async def test_check_target_access_no_project_id():
    """target 存在但 project_id=None → False"""
    user = _make_user(UserRole.RESEARCHER)
    target = MagicMock()
    target.project_id = None
    db = MagicMock()
    db.get = AsyncMock(return_value=target)
    ctx = _make_ctx(db, user)
    result = await _check_target_access(ctx, _T1)
    assert result is False


# ========== DiscoverTargetsTool ==========


@pytest.mark.asyncio
async def test_discover_targets_no_permission():
    """非 FOUNDER + 非 owner → fail"""
    user = _make_user(UserRole.RESEARCHER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)  # 项目不存在
    ctx = _make_ctx(db, user)

    tool = DiscoverTargetsTool()
    result = await tool.execute({"project_id": _P1}, ctx)
    assert result.success is False
    assert "无权操作" in result.error


@pytest.mark.asyncio
async def test_discover_targets_success():
    """FOUNDER + TargetIdentifier 成功"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.target_identifier.TargetIdentifier"
    ) as MockIdentifier:
        instance = MockIdentifier.return_value
        instance.discover = AsyncMock(
            return_value={"targets": [{"gene": "EGFR", "confidence_score": 0.9}]}
        )
        tool = DiscoverTargetsTool()
        result = await tool.execute({"project_id": _P1}, ctx)

    assert result.success is True
    assert result.data["total"] == 1
    assert result.data["tier"] == "fast_screen"
    assert result.display["type"] == "table"


@pytest.mark.asyncio
async def test_discover_targets_deep_insight_tier():
    """tier=deep_insight 透传"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.target_identifier.TargetIdentifier"
    ) as MockIdentifier:
        instance = MockIdentifier.return_value
        instance.discover = AsyncMock(return_value={"targets": []})
        tool = DiscoverTargetsTool()
        result = await tool.execute(
            {"project_id": _P1, "tier": "deep_insight"}, ctx
        )

    assert result.success is True
    assert result.data["tier"] == "deep_insight"


@pytest.mark.asyncio
async def test_discover_targets_identifier_raises():
    """TargetIdentifier 抛异常 → fail"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.target_identifier.TargetIdentifier"
    ) as MockIdentifier:
        instance = MockIdentifier.return_value
        instance.discover = AsyncMock(side_effect=RuntimeError("identifier failed"))
        tool = DiscoverTargetsTool()
        result = await tool.execute({"project_id": _P1}, ctx)

    assert result.success is False
    assert "identifier failed" in result.error


# ========== BuildEvidenceChainTool ==========


@pytest.mark.asyncio
async def test_build_evidence_chain_success():
    user = _make_user(UserRole.FOUNDER)
    target = MagicMock()
    target.id = _T1
    db = MagicMock()
    db.get = AsyncMock(return_value=target)
    ctx = _make_ctx(db, user)

    with patch(
        "app.services.analyzer.evidence_chain.EvidenceChainBuilder"
    ) as MockBuilder:
        instance = MockBuilder.return_value
        instance.build = AsyncMock(return_value={"chain": ["evidence1"]})
        tool = BuildEvidenceChainTool()
        result = await tool.execute({"target_id": _T1}, ctx)

    assert result.success is True
    assert result.display["type"] == "evidence_chain"


@pytest.mark.asyncio
async def test_build_evidence_chain_target_not_found():
    user = _make_user(UserRole.FOUNDER)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    ctx = _make_ctx(db, user)

    tool = BuildEvidenceChainTool()
    result = await tool.execute({"target_id": _T2}, ctx)
    assert result.success is False
    assert "靶点不存在" in result.error


# ========== PredictSynergyTool ==========


@pytest.mark.asyncio
async def test_predict_synergy_success():
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    with patch(
        "app.services.analyzer.network_modeler.NetworkModeler"
    ) as MockModeler:
        instance = MockModeler.return_value
        instance.predict_synergy = AsyncMock(
            return_value={"pairs": [{"a": "EGFR", "b": "KRAS", "score": 0.85}]}
        )
        tool = PredictSynergyTool()
        result = await tool.execute(
            {"target_pairs": [["EGFR", "KRAS"]]}, ctx
        )

    assert result.success is True
    assert result.display["type"] == "table"


@pytest.mark.asyncio
async def test_predict_synergy_empty_pairs():
    """空数组 → fail"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    tool = PredictSynergyTool()
    result = await tool.execute({"target_pairs": []}, ctx)
    assert result.success is False
    assert "非空数组" in result.error


@pytest.mark.asyncio
async def test_predict_synergy_non_list_pairs():
    """非数组类型 → fail"""
    user = _make_user(UserRole.FOUNDER)
    ctx = _make_ctx(MagicMock(), user)

    tool = PredictSynergyTool()
    result = await tool.execute({"target_pairs": "not-a-list"}, ctx)
    assert result.success is False
