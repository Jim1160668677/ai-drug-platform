"""沙箱端点测试 — 2 个 REST 端点

测试覆盖：
- POST /api/v1/sandbox/execute    代码执行（沙箱）
- GET  /api/v1/sandbox/{id}       查询执行结果

权限：仅 FOUNDER / CHIEF_RESEARCHER / DATA_ENGINEER 可调用 execute
默认 AGENT_SANDBOX_ENABLED=false，测试中用 monkeypatch 启用。
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.security import UserRole, create_access_token, hash_password
from app.models.sandbox_execution import SandboxExecution, SandboxStatus
from app.models.user import User


# ========== 辅助函数 ==========


async def _create_user(async_db_session, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password("test123456"),
        role=role,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


def _make_headers(user: User) -> dict:
    token = create_access_token(str(user.id), user.role)
    return {"Authorization": f"Bearer {token}"}


def _make_runner_mock(result_dict: dict) -> MagicMock:
    """构造 SandboxRunner mock：run() 返回 result_dict 同时把字段写入 record。

    端点代码用 SandboxExecuteResponse.model_validate(record) 序列化响应，
    因此 mock 必须像真实 SandboxRunner 一样把 stdout/stderr/exit_code 等写入 record，
    否则响应中这些字段会是 None。
    """
    mock_runner = MagicMock()

    async def _run(**kwargs):
        record = kwargs.get("record")
        if record is not None:
            record.stdout = result_dict.get("stdout")
            record.stderr = result_dict.get("stderr")
            record.exit_code = result_dict.get("exit_code")
            record.duration_ms = result_dict.get("duration_ms")
            record.memory_kb = result_dict.get("memory_kb")
            record.status = result_dict.get("status", SandboxStatus.COMPLETED)
        return result_dict

    mock_runner.run = AsyncMock(side_effect=_run)
    return mock_runner


# ========== POST /sandbox/execute ==========


@pytest.mark.asyncio
async def test_execute_code_disabled_returns_403(client, auth_headers):
    """默认 AGENT_SANDBOX_ENABLED=false → 403"""
    resp = await client.post(
        "/api/v1/sandbox/execute",
        json={"code": "print(1+1)"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_execute_code_researcher_forbidden(client, async_db_session, monkeypatch):
    """启用沙箱 + RESEARCHER 角色 → 403"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    researcher = await _create_user(async_db_session, "sb-rs@ai-drug.com", UserRole.RESEARCHER)
    await async_db_session.commit()

    resp = await client.post(
        "/api/v1/sandbox/execute",
        json={"code": "print(1+1)"},
        headers=_make_headers(researcher),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_execute_code_doctor_forbidden(client, async_db_session, monkeypatch):
    """启用沙箱 + DOCTOR → 403"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    doctor = await _create_user(async_db_session, "sb-doc@ai-drug.com", UserRole.DOCTOR)
    await async_db_session.commit()

    resp = await client.post(
        "/api/v1/sandbox/execute",
        json={"code": "print(1+1)"},
        headers=_make_headers(doctor),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_execute_code_founder_allowed(client, auth_headers, async_db_session, monkeypatch):
    """启用沙箱 + FOUNDER + Mock SandboxRunner → 200"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner = _make_runner_mock({
        "stdout": "2\n",
        "stderr": "",
        "exit_code": 0,
        "duration_ms": 100,
        "memory_kb": 10240,
        "status": SandboxStatus.COMPLETED,
    })
    mock_audit = MagicMock()
    mock_audit.log_sandbox_exec = AsyncMock()
    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner,
    ), patch(
        "app.api.v1.endpoints.sandbox.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "print(1+1)"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["stdout"] == "2\n"
    assert data["exit_code"] == 0


@pytest.mark.asyncio
async def test_execute_code_chief_researcher_allowed(client, async_db_session, monkeypatch):
    """启用沙箱 + CHIEF_RESEARCHER → 200"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    chief = await _create_user(async_db_session, "sb-cr@ai-drug.com", UserRole.CHIEF_RESEARCHER)
    await async_db_session.commit()

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(
        return_value={
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 50,
            "memory_kb": 5120,
            "status": SandboxStatus.COMPLETED,
        }
    )
    mock_audit = MagicMock()
    mock_audit.log_sandbox_exec = AsyncMock()
    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner,
    ), patch(
        "app.api.v1.endpoints.sandbox.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "print('ok')"},
            headers=_make_headers(chief),
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_execute_code_engineer_allowed(client, async_db_session, monkeypatch):
    """启用沙箱 + DATA_ENGINEER → 200"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    engineer = await _create_user(async_db_session, "sb-eng@ai-drug.com", UserRole.DATA_ENGINEER)
    await async_db_session.commit()

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(
        return_value={
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 30,
            "memory_kb": 4096,
            "status": SandboxStatus.COMPLETED,
        }
    )
    mock_audit = MagicMock()
    mock_audit.log_sandbox_exec = AsyncMock()
    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner,
    ), patch(
        "app.api.v1.endpoints.sandbox.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "x=1"},
            headers=_make_headers(engineer),
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_execute_code_docker_sdk_missing_502(client, auth_headers, monkeypatch):
    """启用沙箱 + SandboxRunner raise ImportError → 502"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    # 模拟 sandbox_runner 模块导入失败
    import sys
    original = sys.modules.get("app.services.agent.sandbox_runner")
    sys.modules["app.services.agent.sandbox_runner"] = None  # 触发 ImportError

    try:
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "print(1)"},
            headers=auth_headers,
        )
        assert resp.status_code == 502
    finally:
        if original is not None:
            sys.modules["app.services.agent.sandbox_runner"] = original
        else:
            sys.modules.pop("app.services.agent.sandbox_runner", None)


@pytest.mark.asyncio
async def test_execute_code_runtime_failure_502(client, auth_headers, monkeypatch):
    """启用沙箱 + runner.run 抛异常 → 502"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(side_effect=RuntimeError("docker daemon down"))
    mock_audit = MagicMock()
    mock_audit.log_sandbox_exec = AsyncMock()

    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner,
    ), patch(
        "app.api.v1.endpoints.sandbox.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "print(1)"},
            headers=auth_headers,
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_execute_code_audit_log_written(client, auth_headers, async_db_session, monkeypatch):
    """调用后 AuditLogger.log_sandbox_exec 被调用"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(
        return_value={
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 10,
            "memory_kb": 1024,
            "status": SandboxStatus.COMPLETED,
        }
    )
    # Mock AuditLogger 捕获调用（SQLite BigInteger autoincrement 不兼容）
    mock_audit = MagicMock()
    mock_audit.log_sandbox_exec = AsyncMock()
    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner,
    ), patch(
        "app.api.v1.endpoints.sandbox.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/sandbox/execute",
            json={"code": "print(1)"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    # 验证审计被调用
    mock_audit.log_sandbox_exec.assert_awaited()


# ========== GET /sandbox/{execution_id} ==========


@pytest.mark.asyncio
async def test_get_execution_not_found(client, auth_headers):
    """随机 UUID → 404"""
    resp = await client.get(
        f"/api/v1/sandbox/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_execution_success(client, auth_headers, async_db_session):
    """创建记录后 GET → 200"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    record = SandboxExecution(
        user_id=user.id,
        code="print(1)",
        language="python",
        status=SandboxStatus.COMPLETED,
        stdout="1\n",
        exit_code=0,
    )
    async_db_session.add(record)
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/sandbox/{record.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stdout"] == "1\n"
    assert data["exit_code"] == 0


@pytest.mark.asyncio
async def test_get_execution_other_user_forbidden(client, async_db_session):
    """用户 B GET 用户 A 记录 → 403"""
    user_a = await _create_user(async_db_session, "sb-a@ai-drug.com", UserRole.FOUNDER)
    user_b = await _create_user(async_db_session, "sb-b@ai-drug.com", UserRole.RESEARCHER)
    record = SandboxExecution(
        user_id=user_a.id,
        code="print(1)",
        language="python",
        status=SandboxStatus.COMPLETED,
    )
    async_db_session.add(record)
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/sandbox/{record.id}",
        headers=_make_headers(user_b),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_execution_founder_sees_all(client, async_db_session):
    """FOUNDER 跨用户 → 200"""
    user_a = await _create_user(async_db_session, "sb-a2@ai-drug.com", UserRole.RESEARCHER)
    user_founder = await _create_user(async_db_session, "sb-f@ai-drug.com", UserRole.FOUNDER)
    record = SandboxExecution(
        user_id=user_a.id,
        code="print(1)",
        language="python",
        status=SandboxStatus.COMPLETED,
    )
    async_db_session.add(record)
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/sandbox/{record.id}",
        headers=_make_headers(user_founder),
    )
    assert resp.status_code == 200
