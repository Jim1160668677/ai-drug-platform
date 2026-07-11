"""审计端点 — 不可篡改的操作日志"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import success_response

router = APIRouter()


def _extract_client_ip(request: Optional[Request]) -> Optional[str]:
    """从 Request 提取客户端 IP（支持反向代理）"""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _extract_user_agent(request: Optional[Request]) -> Optional[str]:
    """从 Request 提取 User-Agent"""
    if request is None:
        return None
    return request.headers.get("user-agent")


@router.get("/logs", response_model=StandardResponse, summary="审计日志查询")
async def list_audit_logs(
    actor: str = Query(None),
    action: str = Query(None),
    entity: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:read")),
):
    """查询审计日志 — 仅创始人/首席研究员可访问"""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return success_response({
        "total": len(logs),
        "logs": [{
            "id": log.id, "actor": log.actor, "role": log.role,
            "action": log.action, "entity": log.entity, "entity_id": log.entity_id,
            "ip_address": log.ip_address, "user_agent": log.user_agent,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "detail": log.detail,
        } for log in logs]
    })


async def log_action(
    db: AsyncSession,
    actor: str,
    role: str,
    action: str,
    entity: str = None,
    entity_id: str = None,
    before_val: dict = None,
    after_val: dict = None,
    detail: str = None,
    request: Optional[Request] = None,
):
    """记录审计日志（供其他模块调用）

    Args:
        request: 可选的 FastAPI Request 对象，用于提取 IP 和 User-Agent
    """
    log = AuditLog(
        actor=actor, role=role, action=action, entity=entity,
        entity_id=entity_id, before_val=before_val, after_val=after_val, detail=detail,
        ip_address=_extract_client_ip(request),
        user_agent=_extract_user_agent(request),
    )
    db.add(log)
    await db.flush()
    return log
