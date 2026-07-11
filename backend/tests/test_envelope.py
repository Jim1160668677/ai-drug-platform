"""统一信封响应体系测试 — 覆盖 schemas/common.py + core/exceptions.py + core/middleware.py

测试范围：
1. ApiResponse / PagedResponse / ErrorResponse Pydantic 序列化与校验
2. success_response / paged_response / error_response helper 函数
3. 8 类 AppException 子类 → register_exception_handlers → 信封响应
4. EnvelopeMiddleware 注入 X-Request-ID / X-Response-Time-ms / meta.duration_ms
5. 大响应（>1MB）不注入 duration_ms
6. 流式响应不被修改
7. 非法请求触发 RequestValidationError → 400 信封
"""
import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    AppException,
    ConflictError,
    ForbiddenError,
    GuardrailBlockedError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    UpstreamError,
    ValidationError,
    _error_envelope,
    register_exception_handlers,
)
from app.core.middleware import EnvelopeMiddleware, get_request_id
from app.schemas.common import (
    ApiResponse,
    ErrorDetail,
    ErrorResponse,
    PagedMeta,
    PagedResponse,
    ResponseMeta,
    error_response,
    paged_response,
    success_response,
)


# ============================================================
# 1. Pydantic 模型序列化
# ============================================================

class TestApiResponseSerialization:
    """ApiResponse[T] / PagedResponse[T] / ErrorResponse 序列化测试"""

    def test_api_response_with_dict_data(self):
        """ApiResponse[dict] 应正确序列化"""
        resp = ApiResponse[Dict[str, Any]](
            success=True,
            data={"name": "test", "value": 42},
            meta=ResponseMeta(request_id="req-123", duration_ms=15),
        )
        d = resp.model_dump()
        assert d["success"] is True
        assert d["data"]["name"] == "test"
        assert d["data"]["value"] == 42
        assert d["meta"]["request_id"] == "req-123"
        assert d["meta"]["duration_ms"] == 15

    def test_api_response_with_list_data(self):
        """ApiResponse[List[int]] 应正确序列化"""
        resp = ApiResponse[List[int]](data=[1, 2, 3], meta=ResponseMeta(request_id="r1"))
        d = resp.model_dump()
        assert d["data"] == [1, 2, 3]
        assert d["success"] is True

    def test_api_response_with_none_data(self):
        """ApiResponse 无 data 时应为 None"""
        resp = ApiResponse[Any](meta=ResponseMeta(request_id="r2"))
        d = resp.model_dump()
        assert d["data"] is None
        assert d["success"] is True

    def test_paged_response_defaults(self):
        """PagedResponse 默认值应为空列表"""
        resp = PagedResponse[List[int]]()
        d = resp.model_dump()
        assert d["data"] == []
        assert d["success"] is True
        assert d["meta"] is None

    def test_paged_response_with_meta(self):
        """PagedResponse + PagedMeta 应正确序列化"""
        resp = PagedResponse[int](
            data=[1, 2, 3, 4, 5],
            meta=PagedMeta(
                request_id="r3",
                page=2,
                page_size=5,
                total=23,
                total_pages=5,
            ),
        )
        d = resp.model_dump()
        assert d["data"] == [1, 2, 3, 4, 5]
        assert d["meta"]["page"] == 2
        assert d["meta"]["total"] == 23
        assert d["meta"]["total_pages"] == 5

    def test_error_response_serialization(self):
        """ErrorResponse 应正确序列化"""
        resp = ErrorResponse(
            error=ErrorDetail(
                code="NOT_FOUND",
                message="资源不存在",
                details={"resource": "project", "id": "abc-123"},
            ),
            meta=ResponseMeta(request_id="r4"),
        )
        d = resp.model_dump()
        assert d["success"] is False
        assert d["error"]["code"] == "NOT_FOUND"
        assert d["error"]["message"] == "资源不存在"
        assert d["error"]["details"]["resource"] == "project"

    def test_response_meta_request_id_required(self):
        """ResponseMeta 必须有 request_id"""
        with pytest.raises(Exception):
            ResponseMeta()  # 缺少 request_id

    def test_paged_meta_page_validation(self):
        """PagedMeta page 必须 >= 1"""
        with pytest.raises(Exception):
            PagedMeta(request_id="r", page=0)

    def test_paged_meta_page_size_bounds(self):
        """PagedMeta page_size 必须 1-200"""
        with pytest.raises(Exception):
            PagedMeta(request_id="r", page_size=0)
        with pytest.raises(Exception):
            PagedMeta(request_id="r", page_size=201)


# ============================================================
# 2. Helper 函数
# ============================================================

class TestHelperFunctions:
    """success_response / paged_response / error_response 测试"""

    def test_success_response_basic(self):
        d = success_response(data={"key": "value"}, request_id="r1")
        assert d["success"] is True
        assert d["data"]["key"] == "value"
        assert d["meta"]["request_id"] == "r1"
        assert d["meta"]["duration_ms"] is None

    def test_success_response_with_duration(self):
        d = success_response(data="ok", request_id="r2", duration_ms=42)
        assert d["meta"]["duration_ms"] == 42

    def test_success_response_default_empty_data(self):
        d = success_response()
        assert d["data"] is None
        assert d["meta"]["request_id"] == ""

    def test_paged_response_total_pages_calculation(self):
        """total_pages 应正确计算"""
        d = paged_response(
            data=[1, 2, 3], page=1, page_size=10, total=25, request_id="r"
        )
        assert d["meta"]["total_pages"] == 3  # ceil(25/10) = 3

    def test_paged_response_total_pages_exact(self):
        """总数正好整除时"""
        d = paged_response(
            data=[1], page=2, page_size=10, total=20, request_id="r"
        )
        assert d["meta"]["total_pages"] == 2

    def test_paged_response_empty(self):
        """空数据分页"""
        d = paged_response(data=[], page=1, page_size=10, total=0, request_id="r")
        assert d["data"] == []
        assert d["meta"]["total_pages"] == 0

    def test_error_response_basic(self):
        d = error_response(
            code="VALIDATION_ERROR",
            message="参数错误",
            details=["field1 required"],
            request_id="r1",
        )
        assert d["success"] is False
        assert d["error"]["code"] == "VALIDATION_ERROR"
        assert d["error"]["message"] == "参数错误"
        assert d["error"]["details"] == ["field1 required"]
        assert d["meta"]["request_id"] == "r1"

    def test_error_response_no_details(self):
        d = error_response(code="NOT_FOUND", message="未找到", request_id="r")
        assert d["error"]["details"] is None


# ============================================================
# 3. AppException 体系
# ============================================================

class TestAppExceptions:
    """8 类 AppException 子类测试"""

    def test_validation_error_defaults(self):
        e = ValidationError()
        assert e.code == "VALIDATION_ERROR"
        assert e.status_code == 400
        assert "校验失败" in e.message

    def test_validation_error_custom_message(self):
        e = ValidationError("字段 name 必填")
        assert e.message == "字段 name 必填"

    def test_unauthorized_error(self):
        e = UnauthorizedError()
        assert e.code == "UNAUTHORIZED"
        assert e.status_code == 401

    def test_forbidden_error(self):
        e = ForbiddenError()
        assert e.code == "FORBIDDEN"
        assert e.status_code == 403

    def test_not_found_error(self):
        e = NotFoundError("项目不存在")
        assert e.code == "NOT_FOUND"
        assert e.status_code == 404
        assert e.message == "项目不存在"

    def test_conflict_error(self):
        e = ConflictError()
        assert e.code == "CONFLICT"
        assert e.status_code == 409

    def test_guardrail_blocked_error_with_rule(self):
        e = GuardrailBlockedError(rule="dose_limit")
        assert e.code == "GUARDRAIL_BLOCKED"
        assert e.status_code == 422
        assert e.details["rule"] == "dose_limit"

    def test_guardrail_blocked_error_no_rule(self):
        e = GuardrailBlockedError()
        assert e.details == {}

    def test_rate_limited_error_with_retry_after(self):
        e = RateLimitedError(retry_after=60)
        assert e.code == "RATE_LIMITED"
        assert e.status_code == 429
        assert e.details["retry_after"] == 60

    def test_upstream_error_with_service(self):
        e = UpstreamError(service="mygene")
        assert e.code == "UPSTREAM_ERROR"
        assert e.status_code == 502
        assert e.details["service"] == "mygene"

    def test_app_exception_to_dict(self):
        e = NotFoundError("项目不存在", details={"id": "abc"})
        d = e.to_dict()
        assert d["code"] == "NOT_FOUND"
        assert d["message"] == "项目不存在"
        assert d["details"]["id"] == "abc"

    def test_app_exception_inheritance(self):
        """所有子类应是 AppException 子类"""
        for exc_cls in [
            ValidationError, UnauthorizedError, ForbiddenError,
            NotFoundError, ConflictError, GuardrailBlockedError,
            RateLimitedError, UpstreamError,
        ]:
            assert issubclass(exc_cls, AppException)

    def test_error_envelope_structure(self):
        """_error_envelope 应返回正确结构"""
        env = _error_envelope(
            code="NOT_FOUND",
            message="资源不存在",
            details={"id": 1},
            request_id="r-001",
        )
        assert env["success"] is False
        assert env["error"]["code"] == "NOT_FOUND"
        assert env["error"]["message"] == "资源不存在"
        assert env["error"]["details"]["id"] == 1
        assert env["meta"]["request_id"] == "r-001"


# ============================================================
# 4. 异常处理器集成测试
# ============================================================

def _build_test_app() -> FastAPI:
    """构造带异常处理器 + EnvelopeMiddleware 的测试 App"""
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(EnvelopeMiddleware)

    @app.get("/raise/validation")
    async def raise_validation():
        raise ValidationError("参数错误", details=["field1"])

    @app.get("/raise/unauthorized")
    async def raise_unauthorized():
        raise UnauthorizedError()

    @app.get("/raise/forbidden")
    async def raise_forbidden():
        raise ForbiddenError()

    @app.get("/raise/not_found")
    async def raise_not_found():
        raise NotFoundError("项目不存在")

    @app.get("/raise/conflict")
    async def raise_conflict():
        raise ConflictError("名称已存在")

    @app.get("/raise/guardrail")
    async def raise_guardrail():
        raise GuardrailBlockedError(rule="dose_exceeded")

    @app.get("/raise/rate_limited")
    async def raise_rate_limited():
        raise RateLimitedError(retry_after=30)

    @app.get("/raise/upstream")
    async def raise_upstream():
        raise UpstreamError(service="mygene")

    @app.get("/raise/http_exception")
    async def raise_http():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="HTTPException not found")

    @app.get("/raise/unexpected")
    async def raise_unexpected():
        raise RuntimeError("意外错误")

    @app.get("/success/dict")
    async def success_dict():
        return {"success": True, "data": {"name": "ok"}, "meta": {"request_id": "x"}}

    @app.get("/success/list")
    async def success_list():
        return [1, 2, 3]

    @app.get("/validation_error_endpoint")
    async def validation_error_endpoint(q: int):
        """触发 RequestValidationError（q 必须是 int）"""
        return {"q": q}

    @app.get("/stream")
    async def stream_response():
        async def gen():
            yield b"chunk1"
            yield b"chunk2"
        return StreamingResponse(gen())

    return app


class TestExceptionHandlers:
    """异常处理器集成测试"""

    @pytest.fixture
    async def client(self):
        app = _build_test_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_validation_error_handler(self, client):
        resp = await client.get("/raise/validation")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "参数错误" in body["error"]["message"]
        assert "X-Request-ID" in resp.headers

    @pytest.mark.asyncio
    async def test_unauthorized_handler(self, client):
        resp = await client.get("/raise/unauthorized")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_forbidden_handler(self, client):
        resp = await client.get("/raise/forbidden")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_not_found_handler(self, client):
        resp = await client.get("/raise/not_found")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "项目不存在"

    @pytest.mark.asyncio
    async def test_conflict_handler(self, client):
        resp = await client.get("/raise/conflict")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    @pytest.mark.asyncio
    async def test_guardrail_handler(self, client):
        resp = await client.get("/raise/guardrail")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "GUARDRAIL_BLOCKED"
        assert body["error"]["details"]["rule"] == "dose_exceeded"

    @pytest.mark.asyncio
    async def test_rate_limited_handler(self, client):
        resp = await client.get("/raise/rate_limited")
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert body["error"]["details"]["retry_after"] == 30

    @pytest.mark.asyncio
    async def test_upstream_handler(self, client):
        resp = await client.get("/raise/upstream")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["code"] == "UPSTREAM_ERROR"
        assert body["error"]["details"]["service"] == "mygene"

    @pytest.mark.asyncio
    async def test_http_exception_handler(self, client):
        """FastAPI HTTPException 应映射到信封"""
        resp = await client.get("/raise/http_exception")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"
        assert "HTTPException not found" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_unexpected_exception_handler(self, client):
        """未捕获异常应触发 INTERNAL_ERROR 信封处理器

        注意：Starlette ServerErrorMiddleware 在发送错误响应后会重新抛出异常，
        httpx ASGITransport 会传播该异常。我们通过验证日志来确认处理器被调用。
        """
        with patch("app.core.exceptions.logger") as mock_logger:
            with pytest.raises(RuntimeError):
                await client.get("/raise/unexpected")
            # 验证异常处理器被调用
            mock_logger.error.assert_called_once()
            log_msg = mock_logger.error.call_args[0][0]
            assert "未处理异常" in log_msg

    @pytest.mark.asyncio
    async def test_request_validation_error(self, client):
        """Pydantic 422 应转为 400 VALIDATION_ERROR 信封"""
        resp = await client.get("/validation_error_endpoint", params={"q": "not_an_int"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        # details 应包含字段错误
        assert body["error"]["details"] is not None


# ============================================================
# 5. EnvelopeMiddleware 测试
# ============================================================

class TestEnvelopeMiddleware:
    """信封中间件测试"""

    @pytest.fixture
    async def client(self):
        app = _build_test_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_request_id_header_injected(self, client):
        """响应应包含 X-Request-ID 头"""
        resp = await client.get("/success/dict")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    @pytest.mark.asyncio
    async def test_request_id_echoed_from_request(self, client):
        """请求带 X-Request-ID 时应回显"""
        custom_id = "my-custom-request-id-12345"
        resp = await client.get("/success/dict", headers={"X-Request-ID": custom_id})
        assert resp.headers["X-Request-ID"] == custom_id

    @pytest.mark.asyncio
    async def test_response_time_header_injected(self, client):
        """响应应包含 X-Response-Time-ms 头"""
        resp = await client.get("/success/dict")
        assert "X-Response-Time-ms" in resp.headers
        # 应是整数
        ms = int(resp.headers["X-Response-Time-ms"])
        assert ms >= 0

    @pytest.mark.asyncio
    async def test_duration_ms_injected_to_envelope(self, client):
        """对带 success 字段的 JSON 响应应注入 meta.duration_ms"""
        resp = await client.get("/success/dict")
        body = resp.json()
        assert body["success"] is True
        # 中间件应注入 meta.duration_ms（原 meta 有 request_id 时追加，无则新建）
        assert "meta" in body
        assert "duration_ms" in body["meta"]
        assert isinstance(body["meta"]["duration_ms"], int)
        assert body["meta"]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_list_response_not_modified(self, client):
        """裸 List 响应不应被注入 meta（不符合信封结构）"""
        resp = await client.get("/success/list")
        body = resp.json()
        # List 不是 dict，不应被修改
        assert body == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_streaming_response_not_modified(self, client):
        """流式响应不应被修改"""
        resp = await client.get("/stream")
        content = resp.content
        assert content == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_error_response_includes_request_id(self, client):
        """错误响应也应包含 X-Request-ID 头"""
        resp = await client.get("/raise/not_found")
        assert "X-Request-ID" in resp.headers
        body = resp.json()
        assert body["meta"]["request_id"] == resp.headers["X-Request-ID"]

    @pytest.mark.asyncio
    async def test_large_response_not_injected(self):
        """大于阈值的响应不注入 duration_ms"""
        # 构造一个超大响应的 App
        app = FastAPI()
        app.add_middleware(EnvelopeMiddleware, max_body_size=100)  # 100 bytes 阈值

        @app.get("/large")
        async def large_response():
            # 返回 > 100 字节的 dict
            return {"success": True, "data": "x" * 200, "meta": {"request_id": "r"}}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/large")
            body = resp.json()
            # 大响应不应注入 duration_ms（meta 保持原样）
            assert "duration_ms" not in body.get("meta", {})

    @pytest.mark.asyncio
    async def test_get_request_id_outside_context(self):
        """不在请求上下文中调用 get_request_id 应返回空字符串"""
        rid = get_request_id()
        assert rid == ""


# ============================================================
# 6. 现有 /health 端点不回归
# ============================================================

class TestHealthEndpointNoRegression:
    """验证现有 /health 端点不被中间件破坏"""

    @pytest.fixture
    async def client(self):
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        """/health 应返回 200"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["app"] == "precision-drug-design"

    @pytest.mark.asyncio
    async def test_health_has_request_id_header(self, client):
        """/health 响应应包含 X-Request-ID（即使无信封）"""
        resp = await client.get("/health")
        assert "X-Request-ID" in resp.headers

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """根路径应正常返回"""
        resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body
        assert "docs" in body
