"""AuditLogger 单元测试 — 审计写入 + 脱敏

注：SQLite BigInteger autoincrement 不兼容（生产用 PostgreSQL），
故 DB 写入测试改用 mock db 捕获 AuditLog 实例验证字段正确性，
与 tests/test_new_modules.py::TestAuditLogAction 模式一致。
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.audit import AuditLog
from app.services.agent.audit import AuditLogger, _mask_sensitive


# ========== _mask_sensitive 脱敏函数 ==========


def test_mask_sensitive_password():
    result = _mask_sensitive({"password": "abc"})
    assert result == {"password": "***REDACTED***"}


def test_mask_sensitive_api_key():
    result = _mask_sensitive({"api_key": "x"})
    assert result == {"api_key": "***REDACTED***"}


def test_mask_sensitive_token_nested():
    result = _mask_sensitive({"config": {"token": "x", "name": "y"}})
    assert result == {"config": {"token": "***REDACTED***", "name": "y"}}


def test_mask_sensitive_list_of_dicts():
    result = _mask_sensitive([{"password": "a"}, {"name": "b"}])
    assert result == [{"password": "***REDACTED***"}, {"name": "b"}]


def test_mask_sensitive_case_insensitive():
    """大小写都脱敏"""
    result = _mask_sensitive({"API_KEY": "x", "Token": "y"})
    assert result == {"API_KEY": "***REDACTED***", "Token": "***REDACTED***"}


def test_mask_sensitive_non_sensitive_unchanged():
    result = _mask_sensitive({"name": "x", "data": [1, 2, 3]})
    assert result == {"name": "x", "data": [1, 2, 3]}


# ========== 辅助：mock db 捕获 AuditLog 实例 ==========


def _make_mock_db():
    """构造 mock db，捕获 add() 调用的 AuditLog 实例"""
    mock_db = MagicMock()
    mock_db.flush = AsyncMock()
    added = []

    def _add(record):
        added.append(record)

    mock_db.add = _add
    return mock_db, added


# ========== log_action 基础 ==========


@pytest.mark.asyncio
async def test_log_action_basic():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_action(
        actor="user-1",
        role="founder",
        action="test.action",
        entity="test_entity",
        entity_id="ent-1",
        after_val={"foo": "bar"},
        detail="测试详情",
    )
    mock_db.flush.assert_awaited()
    assert len(added) == 1
    log = added[0]
    assert log.actor == "user-1"
    assert log.role == "founder"
    assert log.action == "test.action"
    assert log.entity == "test_entity"
    assert log.entity_id == "ent-1"
    assert log.after_val == {"foo": "bar"}
    assert log.detail == "测试详情"


@pytest.mark.asyncio
async def test_log_action_does_not_raise_on_db_error(caplog):
    """db.flush 抛异常时方法不应抛出，仅记录 error 日志"""
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock(side_effect=Exception("DB down"))

    logger = AuditLogger(mock_db)
    with caplog.at_level(logging.ERROR, logger="app.services.agent.audit"):
        await logger.log_action(actor="u", role="r", action="a")
    assert any("审计日志写入失败" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_log_action_masks_sensitive_after_val():
    """after_val 中的敏感字段应被脱敏后再赋值给 AuditLog"""
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_action(
        actor="u",
        role="r",
        action="a",
        after_val={"api_key": "sk-xxx", "name": "ok"},
    )
    log = added[0]
    assert log.after_val == {"api_key": "***REDACTED***", "name": "ok"}


@pytest.mark.asyncio
async def test_log_action_masks_sensitive_before_val():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_action(
        actor="u",
        role="r",
        action="a",
        before_val={"password": "p", "old": "v"},
    )
    log = added[0]
    assert log.before_val == {"password": "***REDACTED***", "old": "v"}


@pytest.mark.asyncio
async def test_log_action_entity_id_none_passed_through():
    """entity_id=None 时不强制转为字符串"""
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_action(actor="u", role="r", action="a", entity_id=None)
    log = added[0]
    assert log.entity_id is None


@pytest.mark.asyncio
async def test_log_action_entity_id_coerced_to_string():
    """entity_id 非 None 时转为字符串"""
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_action(actor="u", role="r", action="a", entity_id=12345)
    log = added[0]
    assert log.entity_id == "12345"


# ========== 业务方法 ==========


@pytest.mark.asyncio
async def test_log_task_created():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_task_created(
        user_id="user-2",
        role="researcher",
        task_id="task-1",
        session_id="session-1",
        query="分析 EGFR",
    )
    log = added[0]
    assert log.action == "agent.task.created"
    assert log.entity == "agent_task"
    assert log.entity_id == "task-1"
    assert log.after_val["session_id"] == "session-1"
    assert log.after_val["query"] == "分析 EGFR"


@pytest.mark.asyncio
async def test_log_task_created_truncates_long_query():
    """query > 500 字符时截断"""
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    long_query = "x" * 600
    await logger.log_task_created(
        user_id="u",
        role="r",
        task_id="t",
        session_id="s",
        query=long_query,
    )
    log = added[0]
    assert len(log.after_val["query"]) == 500


@pytest.mark.asyncio
async def test_log_tool_call_success():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_tool_call(
        user_id="u",
        role="r",
        task_id="t",
        tool="discover_targets",
        args={"project_id": "p1"},
        success=True,
    )
    log = added[0]
    assert log.action == "agent.tool.success"
    assert log.entity == "agent_tool_call"
    assert log.after_val["tool"] == "discover_targets"
    assert log.after_val["success"] is True


@pytest.mark.asyncio
async def test_log_tool_call_failed():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_tool_call(
        user_id="u", role="r", task_id="t", tool="x", args={}, success=False
    )
    log = added[0]
    assert log.action == "agent.tool.failed"
    assert log.after_val["success"] is False


@pytest.mark.asyncio
async def test_log_sandbox_exec_truncates_code():
    """code > 200 字符时仅保留前 200 字符"""
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    long_code = "print(1)\n" * 50  # > 200 字符
    await logger.log_sandbox_exec(
        user_id="u",
        role="r",
        task_id="t",
        sandbox_id="sb-1",
        code=long_code,
        exit_code=0,
        success=True,
    )
    log = added[0]
    assert log.action == "agent.sandbox.success"
    assert log.entity == "sandbox_execution"
    assert log.entity_id == "sb-1"
    assert len(log.after_val["code_preview"]) == 200
    assert log.after_val["exit_code"] == 0


@pytest.mark.asyncio
async def test_log_sandbox_exec_failed_action():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_sandbox_exec(
        user_id="u",
        role="r",
        task_id="t",
        sandbox_id="sb-2",
        code="x",
        exit_code=1,
        success=False,
    )
    log = added[0]
    assert log.action == "agent.sandbox.failed"


@pytest.mark.asyncio
async def test_log_confirmation_approved():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_confirmation(
        user_id="u", role="r", task_id="t", tool="execute_code", approved=True
    )
    log = added[0]
    assert log.action == "agent.confirm.approved"
    assert log.entity == "agent_confirmation"
    assert log.after_val["approved"] is True


@pytest.mark.asyncio
async def test_log_confirmation_rejected():
    mock_db, added = _make_mock_db()
    logger = AuditLogger(mock_db)
    await logger.log_confirmation(
        user_id="u", role="r", task_id="t", tool="execute_code", approved=False
    )
    log = added[0]
    assert log.action == "agent.confirm.rejected"
    assert log.after_val["approved"] is False
