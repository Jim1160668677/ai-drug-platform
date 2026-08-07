"""Agent WebSocket 鉴权与事件协议处理

设计来源：2026-07-18-agent-functional-design.md §6

抽取自 ws.py 的 token 校验逻辑，供 Agent WS 端点复用。
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token

logger = logging.getLogger(__name__)


# WS 关闭码（与 ws.py 保持一致）
WS_CODE_AUTH_FAILED = 4401
WS_CODE_FORBIDDEN = 4403
WS_CODE_INVALID = 4400
WS_CODE_SERVER_ERROR = 4500


async def authenticate_ws_token(token: Optional[str]) -> Optional[str]:
    """WebSocket 握手阶段校验 JWT

    Args:
        token: query 参数 ?token=xxx 传入的 JWT
    Returns:
        user_id 字符串；校验失败返回 None
    """
    if not token:
        return None
    try:
        payload = decode_token(token)
        # 安全：仅允许 access token
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        return str(user_id) if user_id else None
    except Exception as e:
        logger.debug(f"WS token 校验失败: {e}")
        return None


async def reject_ws(websocket: WebSocket, code: int, reason: str = "") -> None:
    """拒绝 WebSocket 连接（统一封装）"""
    logger.warning(f"WS 拒绝连接 code={code}: {reason}")
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


def make_event(event_type: str, task_id: str, payload: dict) -> dict:
    """构造 WS 事件信封"""
    return {
        "type": event_type,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
