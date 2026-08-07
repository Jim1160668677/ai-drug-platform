"""WebSocket 基类工具测试 — Phase C 代码复用

验证 app.core.websocket_base 的 WebSocketHandler 和 ConnectionManager：
- 认证流程（成功/失败）
- 消息收发与解析
- ping/pong 心跳
- ConnectionManager 连接管理 + 广播
- 断连自动清理
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.websocket_base import WebSocketHandler, ConnectionManager


def make_mock_ws():
    """创建 mock WebSocket"""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


class TestWebSocketHandlerAuth:
    """WebSocketHandler 认证测试"""

    @pytest.mark.asyncio
    async def test_accept_without_token(self):
        """无 token 时跳过认证"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token=None)
        result = await handler.accept_and_auth()
        assert result is True
        ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_accept_with_valid_token(self):
        """有效 token 认证成功"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token="valid_token")
        with patch("app.core.websocket_base.decode_token") as mock_decode:
            mock_decode.return_value = {"type": "access", "sub": "user123", "role": "founder"}
            result = await handler.accept_and_auth()
        assert result is True
        assert handler.user_id == "user123"
        assert handler.user_role == "founder"

    @pytest.mark.asyncio
    async def test_accept_with_invalid_token_type(self):
        """非 access 类型 token → 认证失败"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token="refresh_token")
        with patch("app.core.websocket_base.decode_token") as mock_decode:
            mock_decode.return_value = {"type": "refresh", "sub": "user123"}
            result = await handler.accept_and_auth()
        assert result is False
        ws.close.assert_called_once_with(code=4401)

    @pytest.mark.asyncio
    async def test_accept_with_expired_token(self):
        """过期 token → 认证失败"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token="expired")
        with patch("app.core.websocket_base.decode_token") as mock_decode:
            mock_decode.side_effect = Exception("token expired")
            result = await handler.accept_and_auth()
        assert result is False
        ws.close.assert_called_once_with(code=4401)


class TestWebSocketHandlerMessaging:
    """WebSocketHandler 消息收发测试"""

    @pytest.mark.asyncio
    async def test_send_json(self):
        """发送 JSON 消息"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()
        await handler.send_json({"type": "test", "data": 123})
        ws.send_text.assert_called_with('{"type": "test", "data": 123}')

    @pytest.mark.asyncio
    async def test_send_event(self):
        """发送标准化事件"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()
        await handler.send_event("progress", {"percent": 50})
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "progress"
        assert sent_data["payload"]["percent"] == 50
        assert "timestamp" in sent_data

    @pytest.mark.asyncio
    async def test_send_error(self):
        """发送错误消息"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()
        await handler.send_error("出错了", "VALIDATION_ERROR")
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "error"
        assert sent_data["payload"]["error"] == "出错了"
        assert sent_data["payload"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_send_pong(self):
        """响应 ping"""
        ws = make_mock_ws()
        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()
        await handler.send_pong()
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "pong"


class TestWebSocketHandlerMessageLoop:
    """WebSocketHandler 消息循环测试"""

    @pytest.mark.asyncio
    async def test_message_loop_receives_messages(self):
        """消息循环接收并解析 JSON"""
        ws = make_mock_ws()
        # 模拟接收两条消息后断开
        ws.receive_text.side_effect = [
            json.dumps({"type": "feedback", "payload": {"text": "hello"}}),
            json.dumps({"type": "ping"}),
            asyncio.CancelledError,  # 模拟断开
        ]
        # WebSocketDisconnect 不会被 asyncio.CancelledError 触发
        from fastapi import WebSocketDisconnect
        ws.receive_text.side_effect = [
            json.dumps({"type": "feedback", "payload": {"text": "hello"}}),
            json.dumps({"type": "ping"}),
            WebSocketDisconnect(),
        ]

        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()

        messages = []
        async for msg in handler.message_loop():
            messages.append(msg)

        # ping 被自动响应，不 yield
        assert len(messages) == 1
        assert messages[0]["type"] == "feedback"

    @pytest.mark.asyncio
    async def test_message_loop_handles_invalid_json(self):
        """无效 JSON → 发送错误但不中断循环"""
        ws = make_mock_ws()
        from fastapi import WebSocketDisconnect
        ws.receive_text.side_effect = [
            "not valid json",
            WebSocketDisconnect(),
        ]

        handler = WebSocketHandler(ws, token=None)
        await handler.accept_and_auth()

        messages = []
        async for msg in handler.message_loop():
            messages.append(msg)

        assert len(messages) == 0
        # 应该发送了错误消息
        assert ws.send_text.call_count >= 1


class TestConnectionManager:
    """ConnectionManager 测试"""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        """连接和断开"""
        manager = ConnectionManager()
        ws1 = make_mock_ws()

        await manager.connect("channel1", ws1)
        assert manager.get_channel_count("channel1") == 1

        await manager.disconnect("channel1", ws1)
        assert manager.get_channel_count("channel1") == 0
        # 频道为空后应被移除
        assert "channel1" not in manager._channels

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self):
        """广播到多个客户端"""
        manager = ConnectionManager()
        ws1 = make_mock_ws()
        ws2 = make_mock_ws()
        ws3 = make_mock_ws()

        await manager.connect("ch", ws1)
        await manager.connect("ch", ws2)
        await manager.connect("ch", ws3)

        sent = await manager.broadcast("ch", "update", {"data": "test"})
        assert sent == 3
        assert ws1.send_text.called
        assert ws2.send_text.called
        assert ws3.send_text.called

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self):
        """广播时自动清理断开的连接"""
        manager = ConnectionManager()
        ws_alive = make_mock_ws()
        ws_dead = make_mock_ws()
        ws_dead.send_text.side_effect = Exception("connection closed")

        await manager.connect("ch", ws_alive)
        await manager.connect("ch", ws_dead)

        sent = await manager.broadcast("ch", "update", {"data": "test"})
        # 只有一个成功
        assert sent == 1
        # 死连接应被清理
        assert manager.get_channel_count("ch") == 1

    @pytest.mark.asyncio
    async def test_broadcast_empty_channel(self):
        """空频道广播返回 0"""
        manager = ConnectionManager()
        sent = await manager.broadcast("nonexistent", "update", {"data": "test"})
        assert sent == 0

    @pytest.mark.asyncio
    async def test_get_total_connections(self):
        """总连接数统计"""
        manager = ConnectionManager()
        await manager.connect("ch1", make_mock_ws())
        await manager.connect("ch1", make_mock_ws())
        await manager.connect("ch2", make_mock_ws())
        assert manager.get_total_connections() == 3