"""合作方与转化路径端点 — 回应评委"临床转化需集成哪些资源"

9 个端点：
- 合作方 CRUD：GET/POST /translations/partners, GET/PATCH /translations/partners/{id}
- 转化阶段 CRUD：GET/POST /translations/projects/{project_id}/stages, PATCH /translations/stages/{id}
- 时间线汇总：GET /translations/projects/{project_id}/timeline
- 委托合作方：POST /translations/stages/{id}/assign-partner
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.exceptions import NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.translation import PartnerService, TranslationStageService

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== 合作方 ==========

@router.get("/partners", response_model=PagedResponse[Dict[str, Any]], summary="合作方列表")
async def list_partners(
    partner_type: Optional[str] = Query(None, description="按类型过滤：cro/cdmo/hospital/testing_lab/registry"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取合作方列表（分页，支持按类型过滤）"""
    svc = PartnerService(db)
    partners, total = await svc.list_partners(partner_type, page, page_size)
    items = [_serialize_partner(p) for p in partners]
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("/partners", response_model=ApiResponse[Dict[str, Any]], summary="创建合作方")
async def create_partner(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """创建合作方（需 FOUNDER 或 CHIEF_RESEARCHER）"""
    svc = PartnerService(db)
    partner = await svc.create_partner(payload)
    return success_response(_serialize_partner(partner))


@router.get("/partners/{partner_id}", response_model=ApiResponse[Dict[str, Any]], summary="合作方详情")
async def get_partner(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = PartnerService(db)
    partner = await svc.get_partner(str(partner_id))
    return success_response(_serialize_partner(partner))


@router.patch("/partners/{partner_id}", response_model=ApiResponse[Dict[str, Any]], summary="更新合作方")
async def update_partner(
    partner_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    svc = PartnerService(db)
    partner = await svc.update_partner(str(partner_id), payload)
    return success_response(_serialize_partner(partner))


# ========== 转化阶段 ==========

@router.get(
    "/projects/{project_id}/stages",
    response_model=ApiResponse[List[Dict[str, Any]]],
    summary="项目转化阶段列表",
)
async def list_stages(
    project_id: UUID,
    molecule_id: Optional[UUID] = Query(None, description="按分子过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TranslationStageService(db)
    stages = await svc.list_stages(str(project_id), str(molecule_id) if molecule_id else None)
    return success_response([_serialize_stage(s) for s in stages])


@router.post(
    "/projects/{project_id}/stages",
    response_model=ApiResponse[Dict[str, Any]],
    summary="创建转化阶段",
)
async def create_stage(
    project_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR)
    ),
):
    svc = TranslationStageService(db)
    data = {**payload, "project_id": str(project_id)}
    stage = await svc.create_stage(data)
    return success_response(_serialize_stage(stage))


@router.patch("/stages/{stage_id}", response_model=ApiResponse[Dict[str, Any]], summary="更新转化阶段")
async def update_stage(
    stage_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR)
    ),
):
    svc = TranslationStageService(db)
    stage = await svc.update_stage(str(stage_id), payload)
    return success_response(_serialize_stage(stage))


@router.get(
    "/projects/{project_id}/timeline",
    response_model=ApiResponse[Dict[str, Any]],
    summary="转化时间线汇总",
)
async def get_timeline(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """时间线汇总：累计成本/时长/完成百分比"""
    svc = TranslationStageService(db)
    timeline = await svc.get_timeline(str(project_id))
    return success_response(timeline)


@router.post(
    "/stages/{stage_id}/assign-partner",
    response_model=ApiResponse[Dict[str, Any]],
    summary="委托合作方",
)
async def assign_partner(
    stage_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR)
    ),
):
    """把转化阶段委托给合作方"""
    partner_id = payload.get("partner_id")
    if not partner_id:
        raise NotFoundError("partner_id 不能为空")
    svc = TranslationStageService(db)
    stage = await svc.assign_partner(str(stage_id), str(partner_id))
    return success_response(_serialize_stage(stage))


# ========== 序列化函数 ==========

def _serialize_partner(p) -> Dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "partner_type": p.partner_type,
        "org_id": str(p.org_id) if p.org_id else None,
        "capabilities": p.capabilities or [],
        "contact_name": p.contact_name,
        "contact_email": p.contact_email,
        "contact_phone": p.contact_phone,
        "lead_time_days": p.lead_time_days,
        "cost_per_unit_usd": p.cost_per_unit_usd,
        "quality_rating": p.quality_rating,
        "is_active": p.is_active,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _serialize_stage(s) -> Dict[str, Any]:
    return {
        "id": str(s.id),
        "project_id": str(s.project_id),
        "molecule_id": str(s.molecule_id) if s.molecule_id else None,
        "stage_type": s.stage_type,
        "stage_name": s.stage_name,
        "description": s.description,
        "status": s.status,
        "partner_id": str(s.partner_id) if s.partner_id else None,
        "partner_name": (s.partner.name if s.partner and s.partner.name else None),
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "estimated_end_date": s.estimated_end_date.isoformat() if s.estimated_end_date else None,
        "actual_end_date": s.actual_end_date.isoformat() if s.actual_end_date else None,
        "cost_usd": s.cost_usd,
        "duration_days": s.duration_days,
        "exit_criteria": s.exit_criteria or [],
        "exit_criteria_met": s.exit_criteria_met,
        "findings": s.findings,
        "go_no_go": s.go_no_go,
        "order_index": s.order_index,
    }
