"""ws_handler 单元测试 — 鉴权与事件构造"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.security import (
    UserRole,
    create_access_token,
    create_refresh_token,
)
from app.services.agent.ws_handler import (
    WS_CODE_AUTH_FAILED,
    WS_CODE_FORBIDDEN,
    WS_CODE_INVALID,
    WS_CODE_SERVER_ERROR,
    authenticate_ws_token,
    make_event,
    reject_ws,
)


# ========== WS 关闭码常量 ==========


def test_ws_code_constants():
    assert WS_CODE_AUTH_FAILED == 4401
    assert WS_CODE_FORBIDDEN == 4403
    assert WS_CODE_INVALID == 4400
    assert WS_CODE_SERVER_ERROR == 4500


# ========== authenticate_ws_token ==========


@pytest.mark.asyncio
async def test_authenticate_ws_token_valid():
    token = create_access_token("user-123", UserRole.FOUNDER)
    user_id = await authenticate_ws_token(token)
    assert user_id == "user-123"


@pytest.mark.asyncio
async def test_authenticate_ws_token_empty():
    assert await authenticate_ws_token(None) is None
    assert await authenticate_ws_token("") is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_invalid_string():
    """非 JWT 字符串应被拒绝（不抛异常）"""
    assert await authenticate_ws_token("not-a-jwt") is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_refresh_rejected():
    """refresh token 应被拒绝（type != "access"）"""
    token = create_refresh_token("user-1", UserRole.FOUNDER)
    assert await authenticate_ws_token(token) is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_expired():
    """已过期的 access token 应被拒绝"""
    import jose.jwt as jwt
    from app.core.config import settings

    payload = {
        "sub": "user-x",
        "type": "access",
        "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
    }
    expired = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert await authenticate_ws_token(expired) is None


# ========== reject_ws ==========


@pytest.mark.asyncio
async def test_reject_ws_calls_close():
    ws = MagicMock()
    ws.close = AsyncMock()
    await reject_ws(ws, WS_CODE_AUTH_FAILED, "鉴权失败")
    ws.close.assert_awaited()
    args = ws.close.call_args
    assert args.kwargs["code"] == WS_CODE_AUTH_FAILED
    assert args.kwargs["reason"] == "鉴权失败"


@pytest.mark.asyncio
async def test_reject_ws_swallows_exception():
    """close 抛异常时函数不应抛出"""
    ws = MagicMock()
    ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
    # 不抛即通过
    await reject_ws(ws, WS_CODE_FORBIDDEN, "forbidden")


# ========== make_event ==========


def test_make_event_structure():
    event = make_event("plan", "task-1", {"a": 1})
    assert event["type"] == "plan"
    assert event["task_id"] == "task-1"
    assert event["payload"] == {"a": 1}
    assert "timestamp" in event


def test_make_event_timestamp_iso_format():
    event = make_event("thought", "task-2", {"thought": "x"})
    # 能被 fromisoformat 解析即合法