"""Agent WebSocket 端点测试 — agent_ws

测试 /api/v1/agent/ws/{session_id}?token=xxx WebSocket 端点。

用 starlette.testclient.TestClient（同步 WS 测试），不能用 AsyncClient。
TestClient 需要直接挂在 app 上，且不能与 client fixture（AsyncClient）共享。

关键设计：WS 端点在 agent.py 内部直接 `from app.db.session import async_session_factory`
绕过了 get_db 依赖注入，因此 conftest 的 dependency_overrides[get_db] 不生效。
这里用 ws_db_session fixture monkeypatch async_session_factory 指向测试 engine，
让 WS 端点与测试 fixture 共享同一个 in-memory SQLite。
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.core.security import (
    UserRole,
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.models.agent_session import AgentSession, SessionStatus
from app.models.agent_task import AgentTask, TaskStatus
from app.models.base import Base  # noqa: F401
from app.models.user import User


# ========== WS 测试专用 fixture ==========


@pytest_asyncio.fixture
async def ws_db_session(monkeypatch):
    """WS 测试专用 db session。

    创建独立 SQLite in-memory engine + 全部表，并 monkeypatch
    app.db.session.async_session_factory 指向测试 engine 的 session factory，
    使 WS 端点内部 `from app.db.session import async_session_factory` 能拿到
    同一 engine，从而查询到测试创建的数据。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    # 关键：patch 全局 async_session_factory，让 WS 端点与测试共享 engine
    monkeypatch.setattr("app.db.session.async_session_factory", session_factory)

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    await engine.dispose()


# ========== 辅助函数 ==========


def _make_app():
    """构造 app 实例（避免与 client fixture 冲突）"""
    from app.main import app
    return app


def _ws_connect(token: str, session_id: str):
    """构造 WS 连接 URL"""
    return f"/api/v1/agent/ws/{session_id}?token={token}"


# ========== 鉴权测试 ==========


def test_ws_connect_no_token_rejected(ws_db_session):
    """无 token → close 4401"""
    app = _make_app()
    with TestClient(app) as client:
        with pytest.raises(Exception) as exc:
            with client.websocket_connect(_ws_connect("", str(uuid.uuid4()))) as ws:
                ws.receive_json()
        # WebSocketDisconnect with code 4401


def test_ws_connect_invalid_token_rejected(ws_db_session):
    """token="bad" → close 4401"""
    app = _make_app()
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(_ws_connect("bad", str(uuid.uuid4()))) as ws:
                ws.receive_json()


def test_ws_connect_refresh_token_rejected(ws_db_session):
    """refresh token → close 4401"""
    app = _make_app()
    user = User(
        email="ws-test@ai-drug.com",
        name="ws-test",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    # 不需 flush：create_refresh_token 只用 user.id（UUIDMixin 构造时已生成）
    refresh_token = create_refresh_token(str(user.id), UserRole.FOUNDER)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                _ws_connect(refresh_token, str(uuid.uuid4()))
            ) as ws:
                ws.receive_json()


def test_ws_connect_nonexistent_session(ws_db_session):
    """随机 session_id → close 4403"""
    app = _make_app()
    user = User(
        email="ws-ne@ai-drug.com",
        name="ws-ne",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    # 不需 flush：create_access_token 只用 user.id（UUIDMixin 构造时已生成）
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                _ws_connect(access_token, str(uuid.uuid4()))
            ) as ws:
                ws.receive_json()


def test_ws_connect_invalid_session_id_format(ws_db_session):
    """session_id="not-uuid" → close 4400"""
    app = _make_app()
    user = User(
        email="ws-bad@ai-drug.com",
        name="ws-bad",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    # 不需 flush：create_access_token 只用 user.id（UUIDMixin 构造时已生成）
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                _ws_connect(access_token, "not-uuid")
            ) as ws:
                ws.receive_json()


# ========== 正常连接 + 消息循环 ==========


@pytest.mark.asyncio
async def test_ws_connect_valid_token(ws_db_session):
    """合法 token → 收到 "connected" 事件"""
    user = User(
        email="ws-ok@ai-drug.com",
        name="ws-ok",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS测试", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            event = ws.receive_json()
            assert event["type"] == "connected"
            assert event["payload"]["session_id"] == str(session.id)


@pytest.mark.asyncio
async def test_ws_ping_pong(ws_db_session):
    """发送 ping → 收到 pong"""
    user = User(
        email="ws-ping@ai-drug.com",
        name="ws-ping",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS ping", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            # 先收 connected 事件
            ws.receive_json()
            # 发送 ping
            ws.send_json({"type": "ping", "task_id": "x"})
            event = ws.receive_json()
            assert event["type"] == "pong"


@pytest.mark.asyncio
async def test_ws_invalid_json(ws_db_session):
    """发非 JSON → 收 error 事件"""
    user = User(
        email="ws-badjson@ai-drug.com",
        name="ws-badjson",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS bad json", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            ws.receive_json()  # connected
            ws.send_text("not-json")
            event = ws.receive_json()
            assert event["type"] == "error"
            assert "JSON" in event["payload"]["error"]


@pytest.mark.asyncio
async def test_ws_unsubscribe_ack(ws_db_session):
    """unsubscribe → unsubscribed"""
    user = User(
        email="ws-unsub@ai-drug.com",
        name="ws-unsub",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS unsub", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "unsubscribe", "task_id": "t-1"})
            event = ws.receive_json()
            assert event["type"] == "unsubscribed"


@pytest.mark.asyncio
async def test_ws_subscribe_not_found_task(ws_db_session):
    """subscribe 不存在的 task → not_found 事件"""
    user = User(
        email="ws-subnf@ai-drug.com",
        name="ws-subnf",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS subnf", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "task_id": str(uuid.uuid4())})
            event = ws.receive_json()
            assert event["type"] == "not_found"


@pytest.mark.asyncio
async def test_ws_cancel_task(ws_db_session):
    """subscribe + cancel 同一任务 → task_cancelled"""
    user = User(
        email="ws-cancel@ai-drug.com",
        name="ws-cancel",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    ws_db_session.add(user)
    await ws_db_session.flush()
    session = AgentSession(user_id=user.id, title="WS cancel", status=SessionStatus.ACTIVE)
    ws_db_session.add(session)
    await ws_db_session.flush()
    task = AgentTask(
        session_id=session.id,
        user_id=user.id,
        query="待取消",
        status=TaskStatus.RUNNING,
    )
    ws_db_session.add(task)
    await ws_db_session.commit()
    access_token = create_access_token(str(user.id), UserRole.FOUNDER)

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_token, str(session.id))) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cancel", "task_id": str(task.id)})
            # 可能先收到一个事件，循环直到收到 task_cancelled 或超时
            for _ in range(5):
                event = ws.receive_json()
                if event["type"] == "task_cancelled":
                    assert event["payload"]["reason"] == "user_cancelled"
                    return
            pytest.fail("未收到 task_cancelled 事件")


@pytest.mark.asyncio
async def test_ws_subscribe_other_user_task(ws_db_session):
    """用户 B subscribe 用户 A 的任务 → error 事件"""
    user_a = User(
        email="ws-a@ai-drug.com",
        name="ws-a",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    user_b = User(
        email="ws-b@ai-drug.com",
        name="ws-b",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    ws_db_session.add_all([user_a, user_b])
    await ws_db_session.flush()
    session_a = AgentSession(user_id=user_a.id, title="A", status=SessionStatus.ACTIVE)
    ws_db_session.add(session_a)
    await ws_db_session.flush()
    task_a = AgentTask(
        session_id=session_a.id,
        user_id=user_a.id,
        query="A 的任务",
        status=TaskStatus.RUNNING,
    )
    ws_db_session.add(task_a)
    await ws_db_session.commit()

    # 用户 B 用自己的 session 但订阅 A 的任务
    session_b = AgentSession(user_id=user_b.id, title="B", status=SessionStatus.ACTIVE)
    ws_db_session.add(session_b)
    await ws_db_session.commit()
    access_b = create_access_token(str(user_b.id), UserRole.RESEARCHER)

    # 在 progress_manager 中注入 owner_id 让越权校验生效
    from app.api.v1.endpoints.ws import get_progress_manager
    pm = get_progress_manager()
    pm.update_progress(
        task_id=str(task_a.id),
        percent=50.0,
        message='{"type":"task_started"}',
        status="running",
        owner_id=str(user_a.id),  # 任务属于 A
    )

    app = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect(_ws_connect(access_b, str(session_b.id))) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "task_id": str(task_a.id)})
            event = ws.receive_json()
            assert event["type"] == "error"
            assert "无权" in event["payload"]["error"]
