"""知情同意端点 — GDPR/HIPAA 合规"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, success_response

router = APIRouter()


class ConsentGrantRequest(BaseModel):
    """授予同意请求"""
    project_id: str
    patient_pseudonym: str
    consent_type: str  # data_use / sharing / publication
    purpose: str
    expires_at: Optional[str] = None  # ISO 8601 格式
    constraints: Optional[dict] = None


class RevokeRequest(BaseModel):
    """撤回同意请求"""
    reason: Optional[str] = None


def _serialize_consent(consent) -> Dict[str, Any]:
    """序列化同意记录"""
    return {
        "id": str(consent.id),
        "project_id": consent.project_id,
        "patient_pseudonym": consent.patient_pseudonym,
        "consent_type": consent.consent_type,
        "status": consent.status,
        "granted_at": consent.granted_at.isoformat() if consent.granted_at else None,
        "expires_at": consent.expires_at.isoformat() if consent.expires_at else None,
        "revoked_at": consent.revoked_at.isoformat() if consent.revoked_at else None,
        "revoke_reason": consent.revoke_reason,
        "purpose": consent.purpose,
        "constraints": consent.constraints,
        "granted_by": consent.granted_by,
    }


@router.post("", response_model=StandardResponse, summary="授予知情同意")
async def grant_consent(
    req: ConsentGrantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """授予知情同意（需 doctor 以上角色）"""
    from app.services.consent.manager import ConsentManager

    if current_user.role not in (UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.DOCTOR):
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("仅 doctor 以上角色可授予知情同意")

    expires_at = None
    if req.expires_at:
        expires_at = datetime.fromisoformat(req.expires_at)

    manager = ConsentManager(db)
    consent = await manager.grant(
        project_id=req.project_id,
        patient_pseudonym=req.patient_pseudonym,
        consent_type=req.consent_type,
        purpose=req.purpose,
        expires_at=expires_at,
        constraints=req.constraints,
        granted_by=str(current_user.id),
    )
    return StandardResponse(message="知情同意已授予", data=_serialize_consent(consent))


@router.delete("/{consent_id}", response_model=StandardResponse, summary="撤回知情同意")
async def revoke_consent(
    consent_id: UUID,
    req: RevokeRequest = Body(default=RevokeRequest()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤回知情同意（需 doctor 以上角色）"""
    from app.services.consent.manager import ConsentManager

    if current_user.role not in (UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.DOCTOR):
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("仅 doctor 以上角色可撤回知情同意")

    manager = ConsentManager(db)
    consent = await manager.revoke(str(consent_id), reason=req.reason)
    return StandardResponse(message="知情同意已撤回", data=_serialize_consent(consent))


@router.get("", response_model=ApiResponse[List[Dict[str, Any]]], summary="同意列表")
async def list_consents(
    project_id: str = Query(..., description="项目 ID"),
    patient_pseudonym: str = Query(None, description="患者假名（可选过滤）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询同意列表"""
    from app.services.consent.manager import ConsentManager

    manager = ConsentManager(db)
    consents = await manager.list_consents(project_id, patient_pseudonym)
    return success_response([_serialize_consent(c) for c in consents])


@router.get("/check", response_model=ApiResponse[Dict[str, Any]], summary="校验同意状态")
async def check_consent(
    project_id: str = Query(..., description="项目 ID"),
    patient_pseudonym: str = Query(..., description="患者假名"),
    consent_type: str = Query(..., description="同意类型"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """校验同意状态（返回 granted=True/False）"""
    from app.services.consent.manager import ConsentManager

    manager = ConsentManager(db)
    granted = await manager.check(project_id, patient_pseudonym, consent_type)
    return success_response({
        "granted": granted,
        "project_id": project_id,
        "patient_pseudonym": patient_pseudonym,
        "consent_type": consent_type,
    })


@router.get("/{consent_id}", response_model=ApiResponse[Dict[str, Any]], summary="同意详情")
async def get_consent_detail(
    consent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取同意详情"""
    from app.services.consent.manager import ConsentManager

    manager = ConsentManager(db)
    consent = await manager.get_consent(str(consent_id))
    if not consent:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("同意记录不存在")
    return success_response(_serialize_consent(consent))
