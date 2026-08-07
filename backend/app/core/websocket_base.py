"""WebSocket 基类工具 — Phase C 代码复用

消除 ws.py / agent.py / coscientist.py 中 WebSocket 端点的重复逻辑：
- JWT token 握手认证（query 参数 ?token=xxx）
- 连接生命周期管理（accept → 业务循环 → cleanup）
- JSON 消息收发 + ping/pong 心跳
- 统一错误处理 + 断连清理
- 多客户端广播器

使用方式：
    from app.core.websocket_base import WebSocketHandler, ConnectionManager

    manager = ConnectionManager()

    @router.websocket("/ws/{item_id}")
    async def ws_endpoint(websocket: WebSocket, item_id: str, token: str = Query(...)):
        handler = WebSocketHandler(websocket, token=token)
        await handler.accept_and_auth()
        await manager.connect(item_id, websocket)
        try:
            async for msg in handler.message_loop():
                if msg.get("type") == "ping":
                    await handler.send_pong()
                # 业务处理...
        finally:
            manager.disconnect(item_id, websocket)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from app.core.security import decode_token

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """单个 WebSocket 连接的封装

    封装握手认证、消息收发、心跳、错误处理，
    消除各 WS 端点中重复的 try/except/finally 样板代码。
    """

    def __init__(
        self,
        websocket: WebSocket,
        token: Optional[str] = None,
        max_conn_sec: int = 1800,
    ):
        """
        Args:
            websocket: FastAPI WebSocket 实例
            token: JWT token（query 参数），None 则跳过认证
            max_conn_sec: 最大连接时长（秒），防资源耗尽
        """
        self.ws = websocket
        self.token = token
        self.max_conn_sec = max_conn_sec
        self.user_id: Optional[str] = None
        self.user_role: Optional[str] = None
        self._accepted = False

    async def accept_and_auth(self) -> bool:
        """接受连接并认证 token

        Returns:
            True 认证成功，False 认证失败（已发送错误并关闭）
        """
        await self.ws.accept()
        self._accepted = True

        if self.token is None:
            return True  # 无需认证

        try:
            payload = decode_token(self.token)
            if not payload or payload.get("type") != "access":
                await self.send_error("无效的访问令牌")
                await self.ws.close(code=4401)
                return False
            self.user_id = payload.get("sub")
            self.user_role = payload.get("role")
            return True
        except Exception as e:
            logger.warning("[ws] token 认证失败: %s", e)
            await self.send_error(f"认证失败: {e}")
            await self.ws.close(code=4401)
            return False

    async def send_json(self, data: Any) -> None:
        """发送 JSON 消息（带时间戳）"""
        if not self._accepted:
            return
        try:
            message = json.dumps(data, ensure_ascii=False, default=str)
            await self.ws.send_text(message)
        except Exception as e:
            logger.debug("[ws] 发送失败: %s", e)

    async def send_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """发送标准化事件消息"""
        await self.send_json({
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        })

    async def send_error(self, message: str, code: str = "ERROR") -> None:
        """发送错误消息"""
        await self.send_json({
            "type": "error",
            "payload": {"error": message, "code": code},
        })

    async def send_pong(self) -> None:
        """响应 ping"""
        await self.send_json({"type": "pong"})

    async def message_loop(self, timeout_sec: Optional[int] = None):
        """异步生成器 — 循环接收并解析 JSON 消息

        自动处理：
        - WebSocketDisconnect（正常断开）
        - JSON 解析错误（发送 error 消息）
        - 超时（timeout_sec）
        - 最大连接时长（max_conn_sec）

        Yields:
            dict: 解析后的消息 {"type": "...", "payload": {...}}
        """
        loop = asyncio.get_event_loop()
        start_time = loop.time()

        while True:
            # 检查最大连接时长
            elapsed = loop.time() - start_time
            if elapsed >= self.max_conn_sec:
                await self.send_error("连接超时，请重新连接", "CONN_TIMEOUT")
                await self.ws.close(code=4408)
                break

            try:
                if timeout_sec:
                    raw = await asyncio.wait_for(
                        self.ws.receive_text(), timeout=timeout_sec
                    )
                else:
                    raw = await self.ws.receive_text()
            except asyncio.TimeoutError:
                # 心跳超时 — 发送 ping 探活
                await self.send_json({"type": "ping"})
                continue
            except WebSocketDisconnect:
                logger.info("[ws] 客户端断开连接")
                break

            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await self.send_pong()
                    continue
                yield msg
            except json.JSONDecodeError:
                await self.send_error("无效的 JSON 格式")


class ConnectionManager:
    """多客户端连接管理器 — 按 channel 分组广播

    线程安全：使用 asyncio.Lock 保护内部 dict。
    适用场景：Co-Scientist 运行进度推送、Agent 会话进度等。
    """

    def __init__(self):
        self._channels: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, channel_id: str, websocket: WebSocket) -> None:
        """注册客户端到频道"""
        async with self._lock:
            if channel_id not in self._channels:
                self._channels[channel_id] = set()
            self._channels[channel_id].add(websocket)

    async def disconnect(self, channel_id: str, websocket: WebSocket) -> None:
        """从频道移除客户端"""
        async with self._lock:
            clients = self._channels.get(channel_id)
            if clients:
                clients.discard(websocket)
                if not clients:
                    del self._channels[channel_id]

    async def broadcast(self, channel_id: str, event_type: str, payload: Dict[str, Any]) -> int:
        """向频道内所有客户端广播事件

        Returns:
            成功推送的客户端数
        """
        async with self._lock:
            clients = list(self._channels.get(channel_id, set()))
        if not clients:
            return 0

        message = json.dumps({
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }, ensure_ascii=False, default=str)

        sent = 0
        dead = []
        for ws in clients:
            try:
                await ws.send_text(message)
                sent += 1
            except Exception:
                dead.append(ws)

        # 清理断开的连接
        if dead:
            async with self._lock:
                clients_set = self._channels.get(channel_id)
                if clients_set:
                    for ws in dead:
                        clients_set.discard(ws)
                    if not clients_set:
                        del self._channels[channel_id]

        return sent

    def get_channel_count(self, channel_id: str) -> int:
        """获取频道客户端数"""
        return len(self._channels.get(channel_id, set()))

    def get_total_connections(self) -> int:
        """获取总连接数"""
        return sum(len(clients) for clients in self._channels.values())