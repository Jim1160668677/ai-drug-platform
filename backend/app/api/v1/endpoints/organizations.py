"""机构端点 — 机构与职能维度

回应评委意见①：提供机构 CRUD、用户职能分配、职能×机构矩阵查询、
当前用户默认工作台路由，让靶点发现/分子设计/用药指导/实验验证各有专属入口。
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import paged_response, success_response
from app.services.org.function_matrix import (
    FUNCTION_DEFAULT_PERMISSIONS,
    FUNCTION_ORG_MATRIX,
    FUNCTION_WORKSPACE,
    get_workspace_entry,
    list_function_roles,
    list_org_types,
)
from app.services.org.org_service import OrgService

router = APIRouter()


class OrgCreate(BaseModel):
    name: str
    org_type: str
    license_no: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[dict] = None
    is_active: bool = True


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    org_type: Optional[str] = None
    license_no: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[dict] = None
    is_active: Optional[bool] = None


class AssignUserPayload(BaseModel):
    user_id: str
    function_role: Optional[str] = None
    title: Optional[str] = None


def _org_to_dict(org) -> dict:
    return {
        "id": str(org.id),
        "name": org.name,
        "org_type": org.org_type,
        "license_no": org.license_no,
        "contact_email": org.contact_email,
        "address": org.address,
        "capabilities": org.capabilities,
        "metadata": org.extra_metadata,
        "is_active": org.is_active,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("", summary="机构列表（分页）")
async def list_organizations(
    org_type: str = Query(None, description="按机构类型过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgService(db)
    res = await svc.list_orgs(org_type=org_type, page=page, page_size=page_size)
    return paged_response(
        data=[_org_to_dict(o) for o in res["items"]],
        page=res["page"],
        page_size=res["page_size"],
        total=res["total"],
    )


@router.post("", summary="创建机构")
async def create_organization(
    payload: OrgCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)
    ),
):
    svc = OrgService(db)
    org = await svc.create_org(payload.model_dump())
    return success_response(data=_org_to_dict(org))


@router.get("/function-matrix", summary="职能×机构矩阵")
async def get_function_matrix(
    current_user: User = Depends(get_current_user),
):
    """返回职能×机构合法性矩阵、默认工作台、默认权限"""
    return success_response(
        data={
            "matrix": FUNCTION_ORG_MATRIX,
            "workspaces": FUNCTION_WORKSPACE,
            "default_permissions": FUNCTION_DEFAULT_PERMISSIONS,
            "function_roles": list_function_roles(),
            "org_types": list_org_types(),
        }
    )


@router.get("/me/workspace", summary="当前用户默认工作台")
async def get_my_workspace(
    current_user: User = Depends(get_current_user),
):
    """根据当前用户 function_role 返回默认工作台路由"""
    workspace = (
        get_workspace_entry(current_user.function_role)
        if current_user.function_role
        else "/workbench"
    )
    return success_response(
        data={
            "workspace": workspace,
            "function_role": current_user.function_role,
            "org_id": str(current_user.org_id) if current_user.org_id else None,
        }
    )


@router.get("/{org_id}", summary="机构详情")
async def get_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = OrgService(db)
    org = await svc.get_org(org_id)
    return success_response(data=_org_to_dict(org))


@router.patch("/{org_id}", summary="更新机构")
async def update_organization(
    org_id: UUID,
    payload: OrgUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)
    ),
):
    svc = OrgService(db)
    org = await svc.update_org(org_id, payload.model_dump(exclude_unset=True))
    return success_response(data=_org_to_dict(org))


@router.get("/{org_id}/users", summary="机构下用户列表")
async def list_org_users(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.org_id == org_id))
    users = result.scalars().all()
    return success_response(
        data=[
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.name,
                "role": u.role.value,
                "function_role": u.function_role,
                "title": u.title,
                "is_active": u.is_active,
            }
            for u in users
        ]
    )


@router.post("/{org_id}/assign-user", summary="分配用户到机构+职能")
async def assign_user_to_org(
    org_id: UUID,
    payload: AssignUserPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """将用户分配到机构并设置职能角色（校验职能×机构合法性）"""
    svc = OrgService(db)
    user = await svc.assign_user_to_org(
        user_id=UUID(payload.user_id),
        org_id=org_id,
        function_role=payload.function_role,
        title=payload.title,
    )
    return success_response(
        data={
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role.value,
            "function_role": user.function_role,
            "org_id": str(user.org_id) if user.org_id else None,
            "title": user.title,
        }
    )
