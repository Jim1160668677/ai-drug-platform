"""流水线端点 — 端到端药物发现自动化

一键串联靶点发现 → 分子生成+评估 → 治疗方案匹配 → 假设生成（+ 自定义步骤）。
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.session import get_db
from app.models.dataset import Dataset
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.models.treatment import Treatment
from app.models.pipeline_run import PipelineRun, PipelineRunStatus, StepStatus
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, success_response

router = APIRouter()


class HypothesisConfig(BaseModel):
    """假设生成配置"""
    use_llm: bool = Field(False, description="是否启用 LLM 辅助生成")
    mode: str = Field("hybrid", description="生成模式: rule/llm/hybrid")
    max_hypotheses: int = Field(5, ge=1, le=20, description="最大假设数量")
    context: Optional[Dict[str, Any]] = Field(None, description="可选上下文数据")


class CustomStep(BaseModel):
    """自定义步骤"""
    name: str = Field(..., description="步骤名称")
    type: str = Field(..., description="步骤类型: assess/dock/analyze/feedback/custom")
    config: Optional[Dict[str, Any]] = Field(None, description="步骤配置")


class PipelineRunRequest(BaseModel):
    """流水线运行请求"""
    project_id: str = Field(..., description="项目 ID")
    dataset_id: Optional[str] = Field(None, description="指定数据集（可选）")
    tier: str = Field("fast_screen", description="分析层级: fast_screen/deep_insight")
    max_targets: int = Field(5, ge=1, le=20, description="分子生成处理的靶点上限")
    molecules_per_target: int = Field(15, ge=1, le=50, description="每靶点生成分子数")
    molecule_strategy: str = Field("fragment", description="生成策略: fragment/optimization/random")
    skip_existing: bool = Field(True, description="是否跳过已有结果的步骤")
    enable_hypothesis: bool = Field(True, description="是否启用 Step 4 假设生成")
    hypothesis_config: Optional[HypothesisConfig] = Field(None, description="假设生成配置")
    custom_steps: Optional[List[CustomStep]] = Field(None, description="自定义步骤列表")
    resume_from_step: Optional[str] = Field(
        None,
        description="从指定步骤恢复（跳过之前的步骤）: target_discovery/molecule_generation/treatment_matching/hypothesis_generation",
    )
    skip_steps: Optional[List[str]] = Field(None, description="跳过指定步骤列表")


@router.post("/run", response_model=StandardResponse, summary="运行端到端流水线")
async def run_pipeline(
    payload: PipelineRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一键运行端到端药物发现流水线

    串联四个步骤：
    1. 靶点发现 — 从项目数据集自动发现候选靶点
    2. 分子生成+评估 — 对发现的靶点生成候选分子并评估类药性/ADMET/可解释性
    3. 治疗方案匹配 — 根据靶点+分子自动匹配治疗方案
    4. 假设生成 — 基于前序结果自动生成研究假设（规则/LLM/混合模式）

    可选：自定义步骤 — 在内置步骤后执行用户自定义操作

    幂等：重复运行不会产生重复数据
    容错：单步失败不中断整个流水线
    """
    from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

    project_id = UUID(payload.project_id)

    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")

    pipeline = DiscoveryPipeline(db)
    result = await pipeline.run(
        project_id=project_id,
        dataset_id=UUID(payload.dataset_id) if payload.dataset_id else None,
        tier=payload.tier,
        max_targets=payload.max_targets,
        molecules_per_target=payload.molecules_per_target,
        molecule_strategy=payload.molecule_strategy,
        skip_existing=payload.skip_existing,
        current_user=current_user,
        enable_hypothesis=payload.enable_hypothesis,
        hypothesis_config=payload.hypothesis_config.model_dump() if payload.hypothesis_config else None,
        custom_steps=[s.model_dump() for s in payload.custom_steps] if payload.custom_steps else None,
        resume_from_step=payload.resume_from_step,
        skip_steps=payload.skip_steps,
    )

    return StandardResponse(message="流水线执行完成", data=result)


@router.get(
    "/status/{project_id}",
    response_model=ApiResponse[Dict[str, Any]],
    summary="查询项目流水线状态",
)
async def get_pipeline_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询项目的流水线数据完整性状态（各模块数据量）"""
    targets_count = (await db.execute(
        select(func.count()).select_from(Target).where(Target.project_id == project_id)
    )).scalar() or 0

    datasets_count = (await db.execute(
        select(func.count()).select_from(Dataset).where(Dataset.project_id == project_id)
    )).scalar() or 0

    molecules_count = (await db.execute(
        select(func.count()).select_from(Molecule)
        .join(Target, Molecule.target_id == Target.id)
        .where(Target.project_id == project_id)
    )).scalar() or 0

    treatments_count = (await db.execute(
        select(func.count()).select_from(Treatment).where(Treatment.project_id == project_id)
    )).scalar() or 0

    return success_response({
        "project_id": str(project_id),
        "datasets": datasets_count,
        "targets": targets_count,
        "molecules": molecules_count,
        "treatments": treatments_count,
        "pipeline_ready": datasets_count > 0,
        "pipeline_complete": targets_count > 0 and treatments_count > 0,
    })


@router.get(
    "/pipeline-runs/{project_id}",
    response_model=ApiResponse[List[Dict[str, Any]]],
    summary="查询项目的流水线运行列表",
)
async def list_pipeline_runs(
    project_id: UUID,
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询项目的流水线运行列表（仅返回当前用户触发的运行记录）"""
    query = select(PipelineRun).where(
        PipelineRun.project_id == project_id,
        PipelineRun.triggered_by == current_user.id,
    )
    if status:
        query = query.where(PipelineRun.status == status)
    query = query.order_by(PipelineRun.started_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    runs = result.scalars().all()

    items = [
        {
            "id": str(r.id),
            "project_id": str(r.project_id),
            "status": r.status,
            "tier": r.tier,
            "current_step": r.current_step,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_sec": r.duration_sec,
            "error_message": r.error_message,
        }
        for r in runs
    ]
    return success_response(items)


@router.get(
    "/pipeline-runs/detail/{run_id}",
    response_model=ApiResponse[Dict[str, Any]],
    summary="查询单个流水线运行详情（含日志）",
)
async def get_pipeline_run_detail(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询单个流水线运行的完整详情，包含步骤状态、摘要和日志"""
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise NotFoundError("流水线运行记录不存在")
    if run.triggered_by != current_user.id:
        raise ForbiddenError("无权访问该流水线运行记录")

    data = {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "tier": run.tier,
        "max_targets": run.max_targets,
        "molecules_per_target": run.molecules_per_target,
        "molecule_strategy": run.molecule_strategy,
        "skip_existing": run.skip_existing,
        "enable_hypothesis": run.enable_hypothesis,
        "current_step": run.current_step,
        "steps_status": run.steps_status or {},
        "completed_steps": run.completed_steps or [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_sec": run.duration_sec,
        "summary": run.summary,
        "error_message": run.error_message,
        "logs": run.logs or [],
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
    }
    return success_response(data)


@router.get(
    "/pipeline-runs/latest/{project_id}",
    response_model=ApiResponse[Dict[str, Any]],
    summary="查询项目最新流水线运行",
)
async def get_latest_pipeline_run(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询项目最新的一条流水线运行记录"""
    query = select(PipelineRun).where(
        PipelineRun.project_id == project_id,
        PipelineRun.triggered_by == current_user.id,
    ).order_by(PipelineRun.started_at.desc()).limit(1)
    result = await db.execute(query)
    run = result.scalar_one_or_none()

    if not run:
        raise NotFoundError("该项目暂无流水线运行记录")

    data = {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "tier": run.tier,
        "current_step": run.current_step,
        "steps_status": run.steps_status or {},
        "completed_steps": run.completed_steps or [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_sec": run.duration_sec,
        "summary": run.summary,
        "error_message": run.error_message,
    }
    return success_response(data)


@router.post(
    "/pipeline-runs/{run_id}/resume",
    response_model=StandardResponse,
    summary="从断点恢复流水线运行",
)
async def resume_pipeline_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从断点恢复流水线运行

    基于历史运行记录的 steps_status 推断恢复点，跳过已成功的步骤，
    从首个未完成的步骤继续执行。
    """
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise NotFoundError("流水线运行记录不存在")
    if run.triggered_by != current_user.id:
        raise ForbiddenError("无权操作该流水线运行记录")

    terminal_statuses = {PipelineRunStatus.COMPLETED, PipelineRunStatus.CANCELLED}
    if run.status in terminal_statuses:
        raise ConflictError(f"流水线已处于终态 '{run.status}'，无法恢复")

    resume_point = run.get_resume_point()
    if not resume_point:
        return StandardResponse(
            message="流水线所有步骤已完成，无需恢复",
            data={"run_id": str(run.id), "status": run.status, "resume_point": None},
        )

    from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

    pipeline = DiscoveryPipeline(db)
    result = await pipeline.run(
        project_id=run.project_id,
        dataset_id=None,
        tier=run.tier,
        max_targets=run.max_targets,
        molecules_per_target=run.molecules_per_target,
        molecule_strategy=run.molecule_strategy,
        skip_existing=run.skip_existing,
        current_user=current_user,
        enable_hypothesis=run.enable_hypothesis,
        resume_from_step=resume_point,
    )

    return StandardResponse(
        message=f"流水线已从 '{resume_point}' 步骤恢复执行",
        data=result,
    )
