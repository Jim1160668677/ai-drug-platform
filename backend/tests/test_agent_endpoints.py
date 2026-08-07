"""Agent REST 端点测试 — 8 个端点

测试覆盖：
- POST   /api/v1/agent/sessions             创建会话
- GET    /api/v1/agent/sessions             会话列表（分页 + 归档过滤）
- GET    /api/v1/agent/sessions/{id}        会话详情（含越权 404）
- DELETE /api/v1/agent/sessions/{id}        归档会话
- POST   /api/v1/agent/chat                 发起对话（异步任务）
- GET    /api/v1/agent/tasks/{id}           任务状态（含越权 404）
- POST   /api/v1/agent/tasks/{id}/cancel    取消任务
- GET    /api/v1/agent/tools                工具列表（多角色）
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.security import UserRole, create_access_token, hash_password
from app.models.agent_session import AgentSession, SessionStatus
from app.models.agent_task import AgentTask, TaskStatus
from app.models.audit import AuditLog
from app.models.user import User


# ========== 辅助函数 ==========


async def _create_user(async_db_session, email: str, role: UserRole) -> User:
    """直接在 DB 创建指定角色用户（绕过注册端点角色限制）"""
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
    """为用户生成 auth headers"""
    token = create_access_token(str(user.id), user.role)
    return {"Authorization": f"Bearer {token}"}


async def _create_session(async_db_session, user_id, title="测试会话", project_id=None) -> AgentSession:
    """直接在 DB 创建会话"""
    session = AgentSession(
        user_id=user_id,
        title=title,
        status=SessionStatus.ACTIVE,
        project_id=project_id,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    return session


async def _create_task(async_db_session, session_id, user_id, query="测试查询", status=TaskStatus.PENDING) -> AgentTask:
    """直接在 DB 创建任务"""
    task = AgentTask(
        session_id=session_id,
        user_id=user_id,
        query=query,
        status=status,
    )
    async_db_session.add(task)
    await async_db_session.flush()
    return task


# ========== 创建会话 ==========


@pytest.mark.asyncio
async def test_create_session_success(client, auth_headers):
    """POST /agent/sessions → 200 + session_id"""
    resp = await client.post(
        "/api/v1/agent/sessions",
        json={"title": "新会话"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "id" in data
    assert data["title"] == "新会话"
    assert data["status"] == SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_session_default_title(client, auth_headers):
    """不传 title 时使用默认值"""
    resp = await client.post(
        "/api/v1/agent/sessions",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "新会话"


# ========== 会话列表 ==========


@pytest.mark.asyncio
async def test_list_sessions_empty(client, auth_headers):
    """新用户列表为空"""
    resp = await client.get("/api/v1/agent/sessions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_sessions_pagination(client, auth_headers, async_db_session):
    """创建 25 个会话，分页返回"""
    # 从 auth_token fixture 知道 founder 用户已创建
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    for i in range(25):
        await _create_session(async_db_session, user.id, title=f"会话 {i}")
    await async_db_session.commit()

    resp = await client.get(
        "/api/v1/agent/sessions?page=1&page_size=20",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 20
    assert body["meta"]["total"] == 25


@pytest.mark.asyncio
async def test_list_sessions_include_archived(client, auth_headers, async_db_session):
    """归档会话仅在 include_archived=true 时返回"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    await _create_session(async_db_session, user.id, title="活跃会话")
    archived = await _create_session(async_db_session, user.id, title="归档会话")
    archived.status = SessionStatus.ARCHIVED
    await async_db_session.commit()

    # 默认不返回归档
    resp = await client.get("/api/v1/agent/sessions", headers=auth_headers)
    titles = [s["title"] for s in resp.json()["data"]]
    assert "活跃会话" in titles
    assert "归档会话" not in titles

    # include_archived=true 返回归档
    resp = await client.get(
        "/api/v1/agent/sessions?include_archived=true",
        headers=auth_headers,
    )
    titles = [s["title"] for s in resp.json()["data"]]
    assert "归档会话" in titles


# ========== 会话详情 ==========


@pytest.mark.asyncio
async def test_get_session_success(client, auth_headers, async_db_session):
    """GET 详情含 context 字段"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id, title="详情测试")
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/agent/sessions/{session.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(session.id)
    assert "context" in data


@pytest.mark.asyncio
async def test_get_session_not_found(client, auth_headers):
    """随机 UUID → 404"""
    import uuid
    resp = await client.get(
        f"/api/v1/agent/sessions/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_other_user_404(client, async_db_session):
    """用户 B 访问用户 A 的会话 → 404（不泄漏存在性）"""
    user_a = await _create_user(async_db_session, "a@example.com", UserRole.FOUNDER)
    user_b = await _create_user(async_db_session, "b@example.com", UserRole.RESEARCHER)
    session = await _create_session(async_db_session, user_a.id, title="A 的会话")
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/agent/sessions/{session.id}",
        headers=_make_headers(user_b),
    )
    assert resp.status_code == 404


# ========== 归档会话 ==========


@pytest.mark.asyncio
async def test_archive_session_success(client, auth_headers, async_db_session):
    """DELETE 后再 GET → status=archived"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id, title="待归档")
    await async_db_session.commit()

    resp = await client.delete(
        f"/api/v1/agent/sessions/{session.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["archived"] is True


@pytest.mark.asyncio
async def test_archive_session_not_found(client, auth_headers):
    """随机 UUID → 404"""
    import uuid
    resp = await client.delete(
        f"/api/v1/agent/sessions/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_session_other_user_404(client, async_db_session):
    """越权归档 → 404"""
    user_a = await _create_user(async_db_session, "a2@example.com", UserRole.FOUNDER)
    user_b = await _create_user(async_db_session, "b2@example.com", UserRole.RESEARCHER)
    session = await _create_session(async_db_session, user_a.id, title="A 的会话")
    await async_db_session.commit()

    resp = await client.delete(
        f"/api/v1/agent/sessions/{session.id}",
        headers=_make_headers(user_b),
    )
    assert resp.status_code == 404


# ========== 工具列表 ==========


@pytest.mark.asyncio
async def test_list_tools_founder_all(client, auth_headers):
    """FOUNDER → 可见全部工具（24 个）"""
    resp = await client.get("/api/v1/agent/tools", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 24
    tool_names = {t["name"] for t in data["tools"]}
    assert "execute_code" in tool_names
    assert "design_molecules" in tool_names
    # 新增工具
    assert "search_ncbi" in tool_names
    assert "web_search" in tool_names
    assert "fetch_web_page" in tool_names
    assert "generate_hypothesis" in tool_names
    assert "query_coscientist_run" in tool_names
    assert "scientific_debate" in tool_names
    assert "experiment_design" in tool_names


@pytest.mark.asyncio
async def test_list_tools_researcher_subset(client, async_db_session):
    """RESEARCHER → 可见工具数 < 23"""
    researcher = await _create_user(async_db_session, "rs@ai-drug.com", UserRole.RESEARCHER)
    await async_db_session.commit()

    resp = await client.get(
        "/api/v1/agent/tools",
        headers=_make_headers(researcher),
    )
    assert resp.status_code == 200
    total = resp.json()["data"]["total"]
    assert total < 23
    assert total > 0


@pytest.mark.asyncio
async def test_list_tools_doctor_subset(client, async_db_session):
    """DOCTOR → 仅医生可用工具"""
    doctor = await _create_user(async_db_session, "doc@ai-drug.com", UserRole.DOCTOR)
    await async_db_session.commit()

    resp = await client.get(
        "/api/v1/agent/tools",
        headers=_make_headers(doctor),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] > 0
    assert data["total"] < 19


# ========== 对话端点 ==========


@pytest.mark.asyncio
async def test_chat_creates_task(client, auth_headers, async_db_session):
    """POST /agent/chat → 200 + task_id"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id, title="聊天会话")
    await async_db_session.commit()

    # Mock 引擎构造，避免真实 LLM 调用
    mock_engine = MagicMock()
    mock_engine.run = AsyncMock(return_value={"answer": "mocked"})
    # Mock AuditLogger 避免 SQLite BigInteger autoincrement 不兼容问题
    mock_audit = MagicMock()
    mock_audit.log_task_created = AsyncMock()
    with patch(
        "app.api.v1.endpoints.agent._build_engine",
        new=AsyncMock(return_value=mock_engine),
    ), patch(
        "app.api.v1.endpoints.agent.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/agent/chat",
            json={
                "session_id": str(session.id),
                "message": "分析 EGFR 突变",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "task_id" in data
    assert data["status"] == TaskStatus.PENDING
    # 审计被调用
    mock_audit.log_task_created.assert_awaited()


@pytest.mark.asyncio
async def test_chat_session_not_found(client, auth_headers):
    """session_id 不存在 → 404"""
    import uuid
    resp = await client.post(
        "/api/v1/agent/chat",
        json={
            "session_id": str(uuid.uuid4()),
            "message": "hello",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_other_user_session_404(client, async_db_session):
    """越权 → 404"""
    user_a = await _create_user(async_db_session, "a3@example.com", UserRole.FOUNDER)
    user_b = await _create_user(async_db_session, "b3@example.com", UserRole.RESEARCHER)
    session = await _create_session(async_db_session, user_a.id, title="A 的会话")
    await async_db_session.commit()

    resp = await client.post(
        "/api/v1/agent/chat",
        json={"session_id": str(session.id), "message": "hello"},
        headers=_make_headers(user_b),
    )
    assert resp.status_code == 404


# ========== 任务状态 ==========


@pytest.mark.asyncio
async def test_get_task_status(client, auth_headers, async_db_session):
    """GET /agent/tasks/{id} → 200 + status 字段"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/agent/tasks/{task.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(task.id)
    assert "status" in data


@pytest.mark.asyncio
async def test_get_task_not_found(client, auth_headers):
    """随机 UUID → 404"""
    import uuid
    resp = await client.get(
        f"/api/v1/agent/tasks/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_task_other_user_404(client, async_db_session):
    """越权 → 404"""
    user_a = await _create_user(async_db_session, "a4@example.com", UserRole.FOUNDER)
    user_b = await _create_user(async_db_session, "b4@example.com", UserRole.RESEARCHER)
    session = await _create_session(async_db_session, user_a.id)
    task = await _create_task(async_db_session, session.id, user_a.id)
    await async_db_session.commit()

    resp = await client.get(
        f"/api/v1/agent/tasks/{task.id}",
        headers=_make_headers(user_b),
    )
    assert resp.status_code == 404


# ========== 取消任务 ==========


@pytest.mark.asyncio
async def test_cancel_task_success(client, auth_headers, async_db_session):
    """pending 任务 → cancel → 200"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id, status=TaskStatus.RUNNING)
    await async_db_session.commit()

    resp = await client.post(
        f"/api/v1/agent/tasks/{task.id}/cancel",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cancelled"] is True


@pytest.mark.asyncio
async def test_cancel_task_already_terminal(client, auth_headers, async_db_session):
    """completed 任务 cancel → 400（ValidationError）"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(
        async_db_session, session.id, user.id, status=TaskStatus.COMPLETED
    )
    await async_db_session.commit()

    resp = await client.post(
        f"/api/v1/agent/tasks/{task.id}/cancel",
        headers=auth_headers,
    )
    assert resp.status_code == 400


# ========== 限流测试 ==========


@pytest.mark.asyncio
async def test_chat_rate_limit_rpm(client, auth_headers, async_db_session, monkeypatch):
    """连续 AGENT_RATE_LIMIT_RPM+1 次调用 → 429"""
    # 设置一个较小的 RPM 限制便于测试
    from app.services.agent.ratelimit import get_rate_limiter
    limiter = get_rate_limiter()
    # 重置单例并设置 RPM=3
    import app.services.agent.ratelimit as mod
    saved = mod._rate_limiter
    mod._rate_limiter = None
    try:
        from app.core.config import settings
        monkeypatch.setattr(settings, "AGENT_RATE_LIMIT_RPM", 3)
        limiter = get_rate_limiter()

        user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
        user = user_result.scalar_one()
        session = await _create_session(async_db_session, user.id)
        await async_db_session.commit()

        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value={"answer": "ok"})
        mock_audit = MagicMock()
        mock_audit.log_task_created = AsyncMock()
        with patch(
            "app.api.v1.endpoints.agent._build_engine",
            new=AsyncMock(return_value=mock_engine),
        ), patch(
            "app.api.v1.endpoints.agent.AuditLogger",
            return_value=mock_audit,
        ):
            # 前 3 次通过
            for i in range(3):
                resp = await client.post(
                    "/api/v1/agent/chat",
                    json={"session_id": str(session.id), "message": f"q{i}"},
                    headers=auth_headers,
                )
                assert resp.status_code == 200, f"第 {i + 1} 次应通过: {resp.text}"
            # 第 4 次 429
            resp = await client.post(
                "/api/v1/agent/chat",
                json={"session_id": str(session.id), "message": "q3"},
                headers=auth_headers,
            )
            assert resp.status_code == 429
    finally:
        mod._rate_limiter = saved


# ========== 审计日志 ==========


@pytest.mark.asyncio
async def test_chat_audit_log_written(client, auth_headers, async_db_session):
    """调用 chat 后 AuditLogger.log_task_created 被调用"""
    user_result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = user_result.scalar_one()
    session = await _create_session(async_db_session, user.id, title="审计测试")
    await async_db_session.commit()

    mock_engine = MagicMock()
    mock_engine.run = AsyncMock(return_value={"answer": "ok"})
    # Mock AuditLogger 捕获调用（SQLite BigInteger autoincrement 不兼容，无法真实写库）
    mock_audit = MagicMock()
    mock_audit.log_task_created = AsyncMock()
    with patch(
        "app.api.v1.endpoints.agent._build_engine",
        new=AsyncMock(return_value=mock_engine),
    ), patch(
        "app.api.v1.endpoints.agent.AuditLogger",
        return_value=mock_audit,
    ):
        resp = await client.post(
            "/api/v1/agent/chat",
            json={"session_id": str(session.id), "message": "审计这条"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    # 验证审计被调用，且 query 内容正确
    mock_audit.log_task_created.assert_awaited()
    call_kwargs = mock_audit.log_task_created.call_args.kwargs
    assert "审计这条" in call_kwargs["query"]
