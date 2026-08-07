"""干湿闭环验证端点 — 回应评委"抑制/过表达是否影响疾病需湿试验验证"

7 个端点：
- POST   /validations                      创建验证任务
- GET    /validations                      列表（支持 project_id / status / task_type 过滤、分页）
- GET    /validations/{task_id}             任务详情
- PATCH  /validations/{task_id}            更新任务字段
- POST   /validations/{task_id}/link-experiment   关联湿实验
- POST   /validations/{task_id}/result      记录实验结果（actual_result/conclusion/next_action）
- POST   /validations/{task_id}/apply-feedback   触发反馈到 AI 模型置信度
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role_or_function
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.models.validation import ValidationTask
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.validation import ValidationOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

# 写操作权限：职级 founder/chief/researcher/doctor OR 职能 experiment_validation/project_pi/target_discovery/molecule_design/clinical_guidance
# 过渡期兼容两种维度（职级 OR 职能任一满足即可）
_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = [
    "experiment_validation",
    "project_pi",
    "target_discovery",
    "molecule_design",
    "clinical_guidance",
]


@router.post("", response_model=ApiResponse[Dict[str, Any]], summary="创建验证任务")
async def create_validation(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """创建验证任务（body: project_id/target_id/molecule_id/task_type/hypothesis/prediction）"""
    svc = ValidationOrchestrator(db)
    task = await svc.submit_task(payload)
    return success_response(_serialize_task(task))


@router.get("", response_model=PagedResponse[Dict[str, Any]], summary="验证任务列表")
async def list_validations(
    project_id: Optional[UUID] = Query(None, description="按项目过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    task_type: Optional[str] = Query(None, description="按任务类型过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取验证任务列表（分页，支持多维度过滤）"""
    q = select(ValidationTask)
    if project_id is not None:
        q = q.where(ValidationTask.project_id == project_id)
    if status:
        q = q.where(ValidationTask.status == status)
    if task_type:
        q = q.where(ValidationTask.task_type == task_type)

    # 总数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # 分页查询（按创建时间倒序）
    q = q.order_by(ValidationTask.created_at.desc())
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = [_serialize_task(t) for t in result.scalars().all()]
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/{task_id}", response_model=ApiResponse[Dict[str, Any]], summary="验证任务详情")
async def get_validation(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = await db.get(ValidationTask, task_id)
    if not task:
        raise NotFoundError("验证任务不存在")
    return success_response(_serialize_task(task))


@router.patch("/{task_id}", response_model=ApiResponse[Dict[str, Any]], summary="更新验证任务")
async def update_validation(
    task_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """更新任务可编辑字段（hypothesis/prediction/notes/next_action/partner_id）"""
    task = await db.get(ValidationTask, task_id)
    if not task:
        raise NotFoundError("验证任务不存在")
    for k in ("hypothesis", "prediction", "notes", "next_action", "partner_id"):
        if k in payload:
            setattr(task, k, payload[k])
    await db.commit()
    await db.refresh(task)
    return success_response(_serialize_task(task))


@router.post(
    "/{task_id}/link-experiment",
    response_model=ApiResponse[Dict[str, Any]],
    summary="关联湿实验",
)
async def link_experiment(
    task_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """把验证任务关联到具体湿实验记录（状态 → in_progress）"""
    experiment_id = payload.get("experiment_id")
    if not experiment_id:
        raise ValidationError("experiment_id 不能为空")
    svc = ValidationOrchestrator(db)
    task = await svc.link_experiment(str(task_id), str(experiment_id))
    return success_response(_serialize_task(task))


@router.post(
    "/{task_id}/result",
    response_model=ApiResponse[Dict[str, Any]],
    summary="记录实验结果",
)
async def record_result(
    task_id: UUID,
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """记录实验结果与结论（actual_result/conclusion/next_action）"""
    actual_result = payload.get("actual_result")
    conclusion = payload.get("conclusion")
    if not actual_result or not conclusion:
        raise ValidationError("actual_result 和 conclusion 不能为空")
    svc = ValidationOrchestrator(db)
    task = await svc.record_result(
        str(task_id), actual_result, conclusion, payload.get("next_action")
    )
    return success_response(_serialize_task(task))


@router.post(
    "/{task_id}/apply-feedback",
    response_model=ApiResponse[Dict[str, Any]],
    summary="触发反馈到 AI 模型",
)
async def apply_feedback(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """把验证结论反馈到靶点/分子置信度（validated +0.1 / refuted -0.2 / inconclusive 不变，幂等）"""
    svc = ValidationOrchestrator(db)
    result = await svc.apply_feedback(str(task_id))
    return success_response(result)


# ========== 序列化函数 ==========

def _serialize_task(t: ValidationTask) -> Dict[str, Any]:
    return {
        "id": str(t.id),
        "project_id": str(t.project_id),
        "target_id": str(t.target_id) if t.target_id else None,
        "molecule_id": str(t.molecule_id) if t.molecule_id else None,
        "treatment_id": str(t.treatment_id) if t.treatment_id else None,
        "task_type": t.task_type,
        "hypothesis": t.hypothesis,
        "prediction": t.prediction,
        "status": t.status,
        "experiment_id": str(t.experiment_id) if t.experiment_id else None,
        "partner_id": str(t.partner_id) if t.partner_id else None,
        "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
        "result_received_at": t.result_received_at.isoformat() if t.result_received_at else None,
        "actual_result": t.actual_result,
        "conclusion": t.conclusion,
        "feedback_applied": t.feedback_applied,
        "next_action": t.next_action,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
