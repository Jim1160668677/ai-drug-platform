"""统一响应信封 — 所有 API 端点遵循的标准响应格式

设计来源：repowiki/zh/content/API参考文档/API概览与规范.md

响应规范：
- 成功响应：ApiResponse{success: true, data: T, meta: {request_id, duration_ms}}
- 分页响应：PagedResponse{success: true, data: List[T], meta: {page, page_size, total, total_pages, request_id, duration_ms}}
- 错误响应：{success: false, error: {code, message, details}, meta: {request_id}}
"""
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """响应元数据"""
    request_id: str = Field(..., description="请求追踪 ID，来自 X-Request-ID 头或自动生成")
    duration_ms: Optional[int] = Field(None, description="服务端处理耗时（毫秒），由中间件注入")


class PagedMeta(ResponseMeta):
    """分页响应元数据"""
    page: int = Field(1, ge=1, description="当前页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=200, description="每页条数")
    total: int = Field(0, ge=0, description="总记录数")
    total_pages: int = Field(0, ge=0, description="总页数")


class ApiResponse(BaseModel, Generic[T]):
    """统一成功响应信封"""
    success: bool = Field(True, description="是否成功")
    data: Optional[T] = Field(None, description="业务数据")
    meta: Optional[ResponseMeta] = Field(None, description="响应元数据")

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class PagedResponse(BaseModel, Generic[T]):
    """统一分页响应信封"""
    success: bool = Field(True, description="是否成功")
    data: List[T] = Field(default_factory=list, description="业务数据列表")
    meta: Optional[PagedMeta] = Field(None, description="分页元数据")

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class ErrorDetail(BaseModel):
    """错误详情"""
    code: str = Field(..., description="错误码，如 VALIDATION_ERROR/UNAUTHORIZED 等")
    message: str = Field(..., description="人类可读的错误描述")
    details: Optional[Any] = Field(None, description="附加错误详情（如字段级错误列表）")


class ErrorResponse(BaseModel):
    """统一错误响应信封"""
    success: bool = Field(False, description="始终为 false")
    error: ErrorDetail = Field(..., description="错误详情")
    meta: Optional[ResponseMeta] = Field(None, description="响应元数据")


def success_response(
    data: Any = None,
    request_id: str = "",
    duration_ms: Optional[int] = None,
) -> dict:
    """构造成功响应字典（供端点直接 return）"""
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "duration_ms": duration_ms,
        },
    }


def paged_response(
    data: List[Any],
    page: int,
    page_size: int,
    total: int,
    request_id: str = "",
    duration_ms: Optional[int] = None,
) -> dict:
    """构造分页响应字典"""
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request_id,
            "duration_ms": duration_ms,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def error_response(
    code: str,
    message: str,
    details: Any = None,
    request_id: str = "",
) -> dict:
    """构造错误响应字典"""
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
