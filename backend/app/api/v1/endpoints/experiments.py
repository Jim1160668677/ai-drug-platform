"""实验端点 — 干湿闭环（Dry-Wet Loop）"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_project_visibility
from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.experiment import Experiment, ExperimentStatus
from app.models.project import Project
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

router = APIRouter()


class ExperimentCreate(BaseModel):
    project_id: str
    name: str
    exp_type: str
    target_id: Optional[str] = None
    molecule_id: Optional[str] = None
    treatment_id: Optional[str] = None
    config: Optional[dict] = None
    lab_source: Optional[str] = None


class ExperimentResultUpdate(BaseModel):
    result: dict
    success: bool
    notes: Optional[str] = None


@router.get("", response_model=PagedResponse[Dict[str, Any]], summary="实验列表")
async def list_experiments(
    project_id: UUID = Query(None),
    exp_type: str = Query(None),
    status: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取实验列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的实验。
    """
    skip = (page - 1) * page_size
    stmt = select(Experiment).offset(skip).limit(page_size).order_by(Experiment.created_at.desc())
    if project_id:
        stmt = stmt.where(Experiment.project_id == project_id)
    if exp_type:
        stmt = stmt.where(Experiment.exp_type == exp_type)
    if status:
        stmt = stmt.where(Experiment.status == status)
    stmt = apply_project_visibility(stmt, current_user, Experiment.project_id)
    result = await db.execute(stmt)
    items = [{"id": str(e.id), "name": e.name, "exp_type": e.exp_type,
              "status": e.status, "success": e.success, "iteration": e.iteration,
              "feedback_applied": e.feedback_applied} for e in result.scalars().all()]

    count_stmt = select(func.count()).select_from(Experiment)
    if project_id:
        count_stmt = count_stmt.where(Experiment.project_id == project_id)
    if exp_type:
        count_stmt = count_stmt.where(Experiment.exp_type == exp_type)
    if status:
        count_stmt = count_stmt.where(Experiment.status == status)
    count_stmt = apply_project_visibility(count_stmt, current_user, Experiment.project_id)
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("", response_model=StandardResponse, summary="创建实验")
async def create_experiment(
    payload: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exp = Experiment(
        project_id=UUID(payload.project_id),
        name=payload.name,
        exp_type=payload.exp_type,
        target_id=UUID(payload.target_id) if payload.target_id else None,
        molecule_id=UUID(payload.molecule_id) if payload.molecule_id else None,
        treatment_id=UUID(payload.treatment_id) if payload.treatment_id else None,
        config=payload.config,
        lab_source=payload.lab_source,
    )
    db.add(exp)
    await db.flush()
    return StandardResponse(message="实验已创建", data={"id": str(exp.id)})


@router.post("/{experiment_id}/result", response_model=StandardResponse, summary="提交实验结果")
async def submit_result(
    experiment_id: UUID,
    payload: ExperimentResultUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交湿实验结果 — 触发干湿闭环反馈"""
    exp = await db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError("实验不存在")

    exp.result = payload.result
    exp.success = payload.success
    exp.status = ExperimentStatus.COMPLETED
    exp.notes = payload.notes

    # 触发模型权重反馈（干湿闭环核心）
    from app.services.experiment.feedback_loop import FeedbackLoop
    loop = FeedbackLoop(db)
    feedback = await loop.apply_feedback(exp)

    return StandardResponse(message="实验结果已提交，模型反馈已触发", data=feedback)


@router.post("/lims-import", response_model=StandardResponse, summary="LIMS 数据导入")
async def import_lims(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从 LIMS 系统导入实验数据"""
    from app.services.experiment.lims_importer import LimsImporter
    importer = LimsImporter(db)
    result = await importer.import_data(payload)
    return StandardResponse(message=f"已导入 {result.get('count', 0)} 条实验数据", data=result)


@router.get("/loop-status", response_model=StandardResponse, summary="干湿闭环状态")
async def loop_status(
    project_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看干湿闭环迭代状态"""
    result = await db.execute(
        select(Experiment).where(Experiment.project_id == project_id)
        .order_by(Experiment.iteration.desc())
    )
    exps = result.scalars().all()
    return success_response({
        "total_experiments": len(exps),
        "completed": sum(1 for e in exps if e.status == ExperimentStatus.COMPLETED),
        "successful": sum(1 for e in exps if e.success),
        "feedback_applied": sum(1 for e in exps if e.feedback_applied),
        "max_iteration": max((e.iteration or 1 for e in exps), default=0),
    })


@router.get("/{experiment_id}", response_model=ApiResponse[Dict[str, Any]], summary="实验详情")
async def get_experiment(
    experiment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取实验详情"""
    exp = await db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError("实验不存在")
    project = await db.get(Project, exp.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")
    return success_response({
        "id": str(exp.id),
        "project_id": str(exp.project_id),
        "name": exp.name,
        "exp_type": exp.exp_type,
        "target_id": str(exp.target_id) if exp.target_id else None,
        "molecule_id": str(exp.molecule_id) if exp.molecule_id else None,
        "treatment_id": str(exp.treatment_id) if exp.treatment_id else None,
        "status": exp.status,
        "success": exp.success,
        "iteration": exp.iteration,
        "feedback_applied": exp.feedback_applied,
        "result": exp.result,
        "notes": exp.notes,
        "config": exp.config,
        "lab_source": exp.lab_source,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
    })
