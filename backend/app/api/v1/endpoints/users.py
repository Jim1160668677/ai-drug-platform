"""用户管理端点 — admin 角色专用"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.api.v1.schemas import UserListResponse, UserResponse, UserUpdateRole, UserUpdateStatus

router = APIRouter()


@router.get("", response_model=UserListResponse, summary="用户列表（admin）")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    role: str = Query(None, description="按角色过滤"),
    is_active: bool = Query(None, description="按状态过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """获取用户列表（仅 founder 可访问）"""
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if role:
        try:
            role_enum = UserRole(role)
        except ValueError as exc:
            raise ValidationError(f"无效角色: {role}") from exc
        stmt = stmt.where(User.role == role_enum)
        count_stmt = count_stmt.where(User.role == role_enum)

    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
        count_stmt = count_stmt.where(User.is_active == is_active)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.patch("/{user_id}/role", response_model=UserResponse, summary="修改用户角色（admin）")
async def update_user_role(
    user_id: UUID,
    payload: UserUpdateRole,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """修改用户角色（仅 founder 可操作）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("用户不存在")

    if user.id == current_user.id:
        raise ValidationError("不能修改自己的角色")

    try:
        new_role = UserRole(payload.role)
    except ValueError as exc:
        raise ValidationError(f"无效角色: {payload.role}") from exc

    if new_role == UserRole.FOUNDER:
        raise ValidationError("不能将用户提升为 founder")

    user.role = new_role
    await db.flush()
    return UserResponse.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserResponse, summary="启用/禁用用户（admin）")
async def update_user_status(
    user_id: UUID,
    payload: UserUpdateStatus,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """启用/禁用用户（仅 founder 可操作）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("用户不存在")

    if user.id == current_user.id and not payload.is_active:
        raise ValidationError("不能禁用自己的账户")

    if user.role == UserRole.FOUNDER and not payload.is_active:
        raise ValidationError("不能禁用 founder 账户")

    user.is_active = payload.is_active
    await db.flush()
    return UserResponse.model_validate(user)
