"""项目端点 — 患者/研究项目管理"""
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import is_leadership_role
from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.api.v1.schemas import ProjectCreate, ProjectResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

router = APIRouter()


@router.get("", response_model=PagedResponse[ProjectResponse], summary="获取项目列表")
async def list_projects(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目列表（分页，PagedResponse 信封）

    可见性：领导角色（FOUNDER / CHIEF_RESEARCHER）可见全部项目；
    其余角色仅可见自己拥有的项目。
    """
    skip = (page - 1) * page_size
    stmt = select(Project).offset(skip).limit(page_size).order_by(Project.created_at.desc())
    count_stmt = select(func.count()).select_from(Project)
    if not is_leadership_role(current_user.role):
        stmt = stmt.where(Project.owner_id == current_user.id)
        count_stmt = count_stmt.where(Project.owner_id == current_user.id)
    result = await db.execute(stmt)
    items = [ProjectResponse.model_validate(p).model_dump() for p in result.scalars().all()]
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("", response_model=ProjectResponse, summary="创建项目")
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        name=payload.name,
        patient_pseudonym=payload.patient_pseudonym,
        cancer_type=payload.cancer_type,
        stage=payload.stage,
        description=payload.description,
        owner_id=current_user.id,
    )
    db.add(project)
    await db.flush()
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse, summary="获取项目详情")
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if current_user.role != UserRole.FOUNDER and project.owner_id != current_user.id:
        raise ForbiddenError("无权访问此资源")
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}/status", response_model=StandardResponse, summary="更新项目状态")
async def update_status(
    project_id: UUID,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if current_user.role != UserRole.FOUNDER and project.owner_id != current_user.id:
        raise ForbiddenError("无权修改此项目")
    project.status = status
    return StandardResponse(message=f"项目状态已更新为 {status}")


@router.patch("/{project_id}", response_model=ApiResponse[Dict[str, Any]], summary="更新项目")
async def update_project(
    project_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新项目信息（部分字段）"""
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if current_user.role != UserRole.FOUNDER and project.owner_id != current_user.id:
        raise ForbiddenError("无权修改此项目")
    # 白名单更新 — 防止修改 owner_id/created_at 等敏感字段
    ALLOWED_UPDATE_FIELDS = {"name", "description", "cancer_type", "stage", "status", "patient_pseudonym"}
    update_data = {k: v for k, v in payload.items() if k in ALLOWED_UPDATE_FIELDS}
    for key, value in update_data.items():
        setattr(project, key, value)
    await db.commit()
    return success_response({
        "id": str(project.id),
        "name": project.name,
        "status": project.status,
        "updated_fields": list(update_data.keys()),
    })


@router.delete("/{project_id}", response_model=ApiResponse[Dict[str, Any]], summary="删除项目")
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除项目（软删除：status 改为 archived）"""
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if current_user.role != UserRole.FOUNDER and project.owner_id != current_user.id:
        raise ForbiddenError("无权删除此项目")
    project.status = ProjectStatus.ARCHIVED
    await db.commit()
    return success_response({"id": str(project.id), "status": "archived"})
