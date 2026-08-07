"""指标采集中间件 — Phase F

纯 ASGI 中间件，自动采集 HTTP 请求指标，注入到 Prometheus。

设计：
- 纯 ASGI 实现（非 BaseHTTPMiddleware），与 EnvelopeMiddleware 一致
- 在请求开始时 in_progress +1，结束时 -1
- 请求结束时记录 total + duration
- 异常请求（500）也记录，status 标签为 "500"
- 路径自动归一化，避免 cardinality 爆炸

注册顺序（main.py）：
    CORSMiddleware（外层）
        ↓
    MetricsMiddleware  ← 新增
        ↓
    EnvelopeMiddleware（注入 X-Request-ID / duration_ms）
        ↓
    SlowAPIMiddleware
        ↓
    路由

注意：MetricsMiddleware 必须在 EnvelopeMiddleware 外层，
以便能捕获所有响应（包括信封注入失败的情况）。
"""
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.observability.metrics import (
    HTTP_REQUESTS_IN_PROGRESS,
    record_http_request,
)


class MetricsMiddleware:
    """HTTP 指标采集中间件

    采集指标：
    - precision_drug_http_requests_total{method, path, status}
    - precision_drug_http_request_duration_seconds{method, path}
    - precision_drug_http_requests_in_progress

    用法：
        app.add_middleware(MetricsMiddleware)
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        start_time = time.perf_counter()
        status_code = 500  # 默认 500，若中间件内部异常能正确记录

        # 进行中请求 +1
        try:
            HTTP_REQUESTS_IN_PROGRESS.inc()
        except Exception:
            pass  # 降级：prometheus_client 不可用时不影响请求

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 未捕获的异常 — 记录为 500
            status_code = 500
            raise
        finally:
            # 进行中请求 -1
            try:
                HTTP_REQUESTS_IN_PROGRESS.dec()
            except Exception:
                pass

            # 记录请求指标
            duration = time.perf_counter() - start_time
            record_http_request(
                method=method,
                path=path,
                status=status_code,
                duration_sec=duration,
            )
