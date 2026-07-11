"""信封中间件 — 注入 X-Request-ID / X-Response-Time-ms / meta.duration_ms

设计来源：repowiki/zh/content/API参考文档/API概览与规范.md
           repowiki/zh/content/系统架构/后端架构设计/中间件系统/统一信封响应中间件.md

功能：
1. 解析或生成 X-Request-ID，写入 scope.state 与响应头
2. 计算请求耗时，写入 X-Response-Time-ms 响应头
3. 仅对 application/json 且 content-length < 1MB 的 200 响应注入 meta.duration_ms
4. 流式响应（more_body=True）直接透传，不修改 body

实现说明：
- 使用纯 ASGI 中间件而非 BaseHTTPMiddleware，避免后者已知的 body 消费与异常传播问题
- 通过包装 send 回调来捕获响应体并注入 duration_ms
"""
import contextvars
import json
import time
import uuid
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 上下文变量 — 保存当前请求的 request_id，供服务层日志关联
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

# 信封注入阈值 — 超过此大小的 JSON 响应不注入 duration_ms
_MAX_ENVELOPE_BODY_SIZE = 1 * 1024 * 1024  # 1 MB


def get_request_id() -> str:
    """获取当前请求的 request_id（供服务层日志关联使用）

    Returns:
        当前请求的 request_id；若不在请求上下文中则返回空字符串
    """
    return _request_id_var.get()


def _generate_request_id() -> str:
    """生成新的 request_id"""
    return uuid.uuid4().hex


class EnvelopeMiddleware:
    """统一信封响应中间件（纯 ASGI 实现）

    - 注入 X-Request-ID 响应头（解析请求头或自动生成）
    - 注入 X-Response-Time-ms 响应头
    - 对 200 application/json 响应注入 meta.duration_ms（仅 < 1MB）

    纯 ASGI 实现避免 BaseHTTPMiddleware 的已知问题：
    - body_iterator 消费后 response.body 赋值无效
    - 异常处理器在 BaseHTTPMiddleware 外层时不被调用
    """

    def __init__(self, app: ASGIApp, max_body_size: int = _MAX_ENVELOPE_BODY_SIZE):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. 解析或生成 request_id
        headers = scope.get("headers", [])
        request_id = ""
        for key, val in headers:
            if key == b"x-request-id":
                request_id = val.decode("latin-1")
                break
        if not request_id:
            request_id = _generate_request_id()

        # 写入 scope.state 供下游使用
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        # 设置上下文变量（供服务层日志关联）
        token = _request_id_var.set(request_id)

        # 2. 记录开始时间
        start_time = time.perf_counter()

        # 3. 包装 send 回调以注入响应头和 duration_ms
        body_chunks: list = []
        response_started = False
        response_status = 0
        response_headers: list = []
        content_type = ""
        content_length = 0
        is_streaming = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, response_status, response_headers
            nonlocal content_type, content_length, is_streaming

            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                response_headers = list(message.get("headers", []))

                # 解析 content-type 和 content-length
                for key, val in response_headers:
                    if key == b"content-type":
                        content_type = val.decode("latin-1")
                    elif key == b"content-length":
                        try:
                            content_length = int(val)
                        except ValueError:
                            content_length = 0

                # 注入 X-Request-ID 和 X-Response-Time-ms 响应头
                # 避免重复：先移除已有的同名头
                response_headers = [
                    (k, v) for k, v in response_headers
                    if k not in (b"x-request-id", b"x-response-time-ms")
                ]
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                response_headers.append(
                    (b"x-response-time-ms", str(duration_ms).encode("latin-1"))
                )

                message["headers"] = response_headers
                await send(message)
                return

            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                if more_body:
                    # 流式响应 — 直接透传，不缓存
                    is_streaming = True
                    await send(message)
                    return

                # 最后一块 body（或非流式响应的唯一一块）
                if is_streaming:
                    # 流式响应的最后一块 — 直接透传
                    await send(message)
                    return

                # 非流式响应 — 缓存 body 以便注入 duration_ms
                body_chunks.append(body)

                # 检查是否需要注入 duration_ms
                should_inject = (
                    response_status == 200
                    and content_type.startswith("application/json")
                    and content_length < self.max_body_size
                )

                if should_inject:
                    full_body = b"".join(body_chunks)
                    # 在 body 注入时重新计算 duration_ms（此时为完整请求耗时）
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    try:
                        data = json.loads(full_body)
                        if isinstance(data, dict):
                            meta = data.get("meta")
                            if isinstance(meta, dict):
                                meta["duration_ms"] = duration_ms
                                if not meta.get("request_id"):
                                    meta["request_id"] = request_id
                            elif "success" in data:
                                data["meta"] = {
                                    "duration_ms": duration_ms,
                                    "request_id": request_id,
                                }
                            else:
                                # 不符合信封结构，不修改
                                await send({"type": "http.response.body", "body": full_body})
                                return
                            new_body = json.dumps(
                                data, ensure_ascii=False, default=str
                            ).encode("utf-8")
                            # 更新 content-length
                            for i, (key, val) in enumerate(response_headers):
                                if key == b"content-length":
                                    response_headers[i] = (
                                        b"content-length",
                                        str(len(new_body)).encode("latin-1"),
                                    )
                                    break
                            await send({"type": "http.response.body", "body": new_body})
                            return
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                # 不需要注入或注入失败 — 原样发送
                await send(message)
                return

            # 其他消息类型 — 直接透传
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id_var.reset(token)
