"""统一异常体系 — 将业务异常映射到标准 HTTP 状态码与错误信封

设计来源：repowiki/zh/content/API参考文档/API概览与规范.md
           repowiki/zh/content/系统架构/后端架构设计/异常处理体系.md

错误码规范：
- VALIDATION_ERROR (400) — 请求参数校验失败
- UNAUTHORIZED (401) — 缺少或无效 token
- FORBIDDEN (403) — 权限不足
- NOT_FOUND (404) — 资源不存在
- CONFLICT (409) — 资源冲突
- GUARDRAIL_BLOCKED (422) — LLM 安全护栏拦截
- RATE_LIMITED (429) — 请求过多
- UPSTREAM_ERROR (502) — 外部服务不可用
- INTERNAL_ERROR (500) — 服务器内部错误
"""
import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_502_BAD_GATEWAY,
)

from app.core.middleware import get_request_id

logger = logging.getLogger(__name__)


# ========== 异常基类与子类 ==========

class AppException(Exception):
    """应用异常基类

    所有业务异常应继承此类，并定义默认的 code 与 status_code。
    """
    code: str = "INTERNAL_ERROR"
    status_code: int = HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "服务器内部错误"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[Any] = None,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        self.message = message or self.default_message
        self.details = details
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转换为字典（不含 envelope）"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(AppException):
    """请求参数校验失败"""
    code = "VALIDATION_ERROR"
    status_code = HTTP_400_BAD_REQUEST
    default_message = "请求参数校验失败"


class UnauthorizedError(AppException):
    """未认证 — 缺少或无效 token"""
    code = "UNAUTHORIZED"
    status_code = HTTP_401_UNAUTHORIZED
    default_message = "未认证或凭据无效"


class ForbiddenError(AppException):
    """权限不足"""
    code = "FORBIDDEN"
    status_code = HTTP_403_FORBIDDEN
    default_message = "权限不足"


class NotFoundError(AppException):
    """资源不存在"""
    code = "NOT_FOUND"
    status_code = HTTP_404_NOT_FOUND
    default_message = "资源不存在"


class ConflictError(AppException):
    """资源冲突"""
    code = "CONFLICT"
    status_code = HTTP_409_CONFLICT
    default_message = "资源冲突"


class GuardrailBlockedError(AppException):
    """LLM 安全护栏拦截"""
    code = "GUARDRAIL_BLOCKED"
    status_code = HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "内容被安全护栏拦截"

    def __init__(self, message: Optional[str] = None, *, rule: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", None) or {}
        if rule:
            details["rule"] = rule
        super().__init__(message, details=details, **kwargs)


class RateLimitedError(AppException):
    """请求过多 — 限流触发"""
    code = "RATE_LIMITED"
    status_code = HTTP_429_TOO_MANY_REQUESTS
    default_message = "请求过多，请稍后重试"

    def __init__(self, message: Optional[str] = None, *, retry_after: Optional[int] = None, **kwargs):
        details = kwargs.pop("details", None) or {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message, details=details, **kwargs)


class UpstreamError(AppException):
    """外部服务不可用"""
    code = "UPSTREAM_ERROR"
    status_code = HTTP_502_BAD_GATEWAY
    default_message = "外部服务不可用"

    def __init__(self, message: Optional[str] = None, *, service: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", None) or {}
        if service:
            details["service"] = service
        super().__init__(message, details=details, **kwargs)


# ========== 错误信封构造 ==========

def _error_envelope(
    code: str,
    message: str,
    details: Optional[Any] = None,
    request_id: str = "",
) -> dict:
    """构造统一错误响应信封

    Returns:
        {success: false, error: {code, message, details}, meta: {request_id}}
    """
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": {
            "request_id": request_id,
        },
    }


def _get_request_id_safe(request: Request) -> str:
    """安全获取 request_id（中间件未启用时回退到 header 或生成）"""
    try:
        rid = get_request_id()
        if rid:
            return rid
    except Exception:
        pass
    # 回退到请求头
    rid = request.headers.get("X-Request-ID")
    if rid:
        return rid
    # 最后回退到 scope state
    return getattr(request.scope.get("state", {}), "request_id", "") or ""


# ========== 异常处理器注册 ==========

def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，将所有异常映射到统一错误信封"""

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException):
        """处理 AppException 及其子类"""
        request_id = _get_request_id_safe(request)
        if exc.status_code >= 500:
            logger.error(f"AppException [{exc.code}]: {exc.message}", exc_info=True)
        else:
            logger.warning(f"AppException [{exc.code}]: {exc.message}")
        envelope = _error_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope,
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        """处理 Pydantic 校验错误（422 → 400 信封）"""
        request_id = _get_request_id_safe(request)
        logger.warning(f"Validation error: {exc.errors()}")
        envelope = _error_envelope(
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            details=exc.errors(),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content=envelope,
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException):
        """处理 FastAPI HTTPException，映射到错误信封"""
        request_id = _get_request_id_safe(request)
        # 根据状态码推断错误码
        code_map = {
            400: "VALIDATION_ERROR",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "GUARDRAIL_BLOCKED",
            429: "RATE_LIMITED",
            502: "UPSTREAM_ERROR",
        }
        code = code_map.get(exc.status_code, "INTERNAL_ERROR")
        envelope = _error_envelope(
            code=code,
            message=str(exc.detail),
            details=None,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope,
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        """兜底处理未捕获异常"""
        request_id = _get_request_id_safe(request)
        logger.error(f"未处理异常: {exc}", exc_info=True)
        envelope = _error_envelope(
            code="INTERNAL_ERROR",
            message="服务器内部错误",
            details={"type": type(exc).__name__},
            request_id=request_id,
        )
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope,
            headers={"X-Request-ID": request_id},
        )
