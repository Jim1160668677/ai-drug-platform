"""工作流端点 — Nextflow 任务调度"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.workflow_run import WorkflowRun, WorkflowStatus
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import success_response

router = APIRouter()


class WorkflowRunRequest(BaseModel):
    project_id: str
    pipeline_name: str  # scrna_pipeline / rna_seq_pipeline / variant_annotation
    params: Optional[dict] = None


@router.get("", summary="工作流运行列表")
async def list_workflows(
    project_id: UUID = Query(None),
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
    if project_id:
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    result = await db.execute(stmt)
    return [{"id": str(w.id), "pipeline_name": w.pipeline_name, "status": w.status,
             "run_id": w.run_id, "duration_sec": w.duration_sec} for w in result.scalars().all()]


@router.post("/run", response_model=StandardResponse, summary="触发工作流")
async def run_workflow(
    payload: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发 Nextflow 工作流"""
    from app.services.workflow.nextflow_runner import NextflowRunner
    runner = NextflowRunner(db)

    wf = WorkflowRun(
        project_id=UUID(payload.project_id),
        pipeline_name=payload.pipeline_name,
        params=payload.params,
        status=WorkflowStatus.SUBMITTED,
        triggered_by=current_user.id,
    )
    db.add(wf)
    await db.flush()

    result = await runner.run(wf)
    return StandardResponse(message=f"工作流 {payload.pipeline_name} 已触发", data=result)


@router.get("/{workflow_id}", response_model=StandardResponse, summary="工作流详情")
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf = await db.get(WorkflowRun, workflow_id)
    if not wf:
        raise NotFoundError("工作流不存在")
    return success_response({
        "id": str(wf.id), "pipeline_name": wf.pipeline_name, "status": wf.status,
        "run_id": wf.run_id, "trace_url": wf.trace_url, "output_path": wf.output_path,
        "params": wf.params, "error": wf.error, "duration_sec": wf.duration_sec,
    })


@router.get("/pipelines/available", response_model=StandardResponse, summary="可用管道")
async def list_pipelines(
    current_user: User = Depends(get_current_user),
):
    """列出可用的 Nextflow 管道"""
    return success_response({"pipelines": [
        {"name": "scrna_pipeline", "description": "单细胞测序数据处理（Scanpy）", "phase": "P0"},
        {"name": "rna_seq_pipeline", "description": "RNA-seq 定量与差异表达", "phase": "P0"},
        {"name": "variant_annotation", "description": "WES/WGS 变异注释", "phase": "P2"},
    ]})
