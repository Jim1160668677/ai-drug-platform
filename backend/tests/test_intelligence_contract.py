"""智能系统契约测试 — 主对话 body 契约 + SSE 流式契约

复用 test_api_contract.py 的 ASGITransport + 内存 SQLite 基础设施，
验证前端调用契约与后端一致：
- POST /agent/chat 接受 body ChatRequest(message/capability_hint)，session_id 为 query
- POST /sessions/{id}/stream 返回 text/event-stream
"""
import os
import sys
import uuid as uuid_mod
from types import SimpleNamespace
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.deps import get_current_user, oauth2_scheme  # noqa: E402
from app.core.security import UserRole, create_access_token, hash_password  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000010")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def auth_token() -> str:
    return create_access_token(
        subject=str(TEST_USER_ID), role=UserRole.CHIEF_RESEARCHER
    )


@pytest_asyncio.fixture
async def client(db_session, auth_token) -> AsyncGenerator[AsyncClient, None]:
    u = User(
        id=TEST_USER_ID,
        email="intel-contract@test.com",
        name="Intel Contract Tester",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()

    async def mock_get_user(token=auth_token):
        return SimpleNamespace(
            id=TEST_USER_ID,
            email="intel-contract@test.com",
            name="Intel Contract Tester",
            role=UserRole.CHIEF_RESEARCHER,
            is_active=True,
        )

    async def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[oauth2_scheme] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_agent_chat_accepts_body_chat_request(client: AsyncClient):
    """body 携带 message/capability_hint 时路由通过(非 422)"""
    import app.api.v1.endpoints.intelligence as intel_endpoint
    from unittest.mock import AsyncMock, patch

    session_id = uuid_mod.uuid4()

    async def mock_get_session_or_404(db, sid, user):
        return SimpleNamespace(id=sid, project_id=None)

    with patch(
        "app.services.intelligence.unified_agent_gateway.UnifiedAgentGateway"
    ) as mock_gateway, \
         patch.object(intel_endpoint, "_get_session_or_404", side_effect=mock_get_session_or_404), \
         patch.object(intel_endpoint, "get_llm_client_with_fallback", new=AsyncMock()):
        mock_gateway.return_value.chat = AsyncMock(
            return_value={"response": "ok", "capability": "qa", "metadata": {}}
        )
        resp = await client.post(
            f"/api/v1/intelligence/agent/chat?session_id={session_id}",
            json={"message": "你好", "capability_hint": "qa"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["response"] == "ok"


@pytest.mark.asyncio
async def test_agent_chat_missing_message_returns_422(client: AsyncClient):
    """body 缺 message 时返回 422（前端必须将 message 放 body）"""
    resp = await client.post(
        f"/api/v1/intelligence/agent/chat?session_id={uuid_mod.uuid4()}",
        json={},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stream_endpoint_media_type(client: AsyncClient):
    """stream 端点对存在的会话返回 text/event-stream"""
    import app.api.v1.endpoints.intelligence as intel_endpoint
    from unittest.mock import AsyncMock, patch

    session_id = uuid_mod.uuid4()

    async def mock_get_session_or_404(db, sid, user):
        return SimpleNamespace(id=sid, project_id=None)

    with patch.object(intel_endpoint, "_get_session_or_404", side_effect=mock_get_session_or_404), \
         patch.object(intel_endpoint, "get_llm_client_with_fallback", new=AsyncMock()):
        resp = await client.post(
            f"/api/v1/intelligence/sessions/{session_id}/stream",
            json={"message": "hi"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_trace_tree_rejects_other_users_run(client: AsyncClient, db_session):
    """trace-tree/cost/decisions 必须校验 run 归属：非 owner 返回 403"""
    from app.models.coscientist_run import CoScientistRun, RunStatus

    other_user_id = uuid_mod.uuid4()
    other = User(
        id=other_user_id,
        email="other@test.com",
        name="Other User",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    run_id = uuid_mod.uuid4()
    db_session.add(other)
    db_session.add(CoScientistRun(
        id=run_id,
        user_id=other_user_id,
        research_goal="他人研究目标",
        status=RunStatus.COMPLETED,
    ))
    await db_session.commit()

    for path in (f"/api/v1/intelligence/runs/{run_id}/trace-tree",
                 f"/api/v1/intelligence/runs/{run_id}/cost",
                 f"/api/v1/intelligence/runs/{run_id}/decisions"):
        resp = await client.get(path)
        assert resp.status_code == 403, f"{path} 应拒绝越权访问，实际 {resp.status_code}"


@pytest.mark.asyncio
async def test_trace_tree_allows_owner(client: AsyncClient, db_session):
    """owner 访问 trace-tree 通过校验（无数据时返回空树 200）"""
    from app.models.coscientist_run import CoScientistRun, RunStatus

    run_id = uuid_mod.uuid4()
    db_session.add(CoScientistRun(
        id=run_id,
        user_id=TEST_USER_ID,
        research_goal="我的研究目标",
        status=RunStatus.COMPLETED,
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/intelligence/runs/{run_id}/trace-tree")
    assert resp.status_code == 200, f"owner 应可访问，实际 {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_trace_tree_unknown_run_returns_404(client: AsyncClient):
    """不存在的 run 返回 404"""
    resp = await client.get(f"/api/v1/intelligence/runs/{uuid_mod.uuid4()}/trace-tree")
    assert resp.status_code == 404
