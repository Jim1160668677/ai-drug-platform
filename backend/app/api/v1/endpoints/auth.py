"""认证端点 — 登录/注册"""
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.limiter import limiter, login_limit_string
from app.core.security import (
    UserRole,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.api.v1.schemas import TokenResponse, UserCreate, UserResponse
from app.schemas.common import ApiResponse, success_response

router = APIRouter()


class LoginRequest(BaseModel):
    """登录请求体（避免密码走 query string 暴露在 URL/日志）"""
    email: str
    password: str


@router.post("/login", response_model=TokenResponse, summary="用户登录")
@limiter.limit(login_limit_string)
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户登录（OAuth2 兼容）

    返回 access_token（30 分钟）+ refresh_token（7 天）。
    限流：每个 IP 每分钟最多 5 次登录尝试，防止暴力破解。
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("邮箱或密码错误")
    if not user.is_active:
        raise ForbiddenError("账户已禁用")

    access_token = create_access_token(subject=str(user.id), role=user.role)
    refresh_token = create_refresh_token(subject=str(user.id), role=user.role)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role.value,
        name=user.name,
        email=user.email,
    )


@router.post("/register", response_model=UserResponse, summary="用户注册")
async def register(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """用户注册

    安全策略：公开注册端点强制角色为 RESEARCHER，忽略客户端传入的 role 字段。
    提权操作必须由 FOUNDER 通过 /users/{id}/role 端点完成。
    """
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise ConflictError("邮箱已注册")

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        role=UserRole.RESEARCHER,
        organization=payload.organization,
    )
    db.add(user)
    await db.flush()
    return UserResponse.model_validate(user)


@router.get("/me", response_model=UserResponse, summary="获取当前用户")
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/refresh", response_model=ApiResponse[Dict[str, Any]], summary="刷新 Token")
async def refresh_token(
    refresh_token: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """刷新 JWT access token

    使用 refresh_token（type=refresh）换取新的 access_token。
    安全策略：
    - 验证 refresh_token 的 type 声明为 refresh（拒绝 access token 刷新）
    - 查询 DB 验证用户仍 active 且角色未变更，防止被禁用用户继续访问
    """
    try:
        payload = decode_token(refresh_token)
    except Exception as exc:
        raise UnauthorizedError("刷新令牌无效") from exc

    # 验证 token 类型 — 必须为 refresh token
    if payload.get("type") != "refresh":
        raise UnauthorizedError("无效的刷新令牌类型")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("刷新令牌缺少必要字段")

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError) as exc:
        raise UnauthorizedError("刷新令牌主体无效") from exc

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("用户不存在或已禁用")

    new_access_token = create_access_token(subject=str(user.id), role=user.role)
    return success_response({
        "access_token": new_access_token,
        "token_type": "bearer",
    })
