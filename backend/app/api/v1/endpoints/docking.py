"""分子对接端点 — Uni-Mol + Vina + Hybrid 三模式

5 个端点：
- POST /docking/unimol      — Uni-Mol 粗筛对接
- POST /docking/vina          — Vina 精修对接
- POST /docking/hybrid        — LLM+计算混合对接（HybridOrchestrator）
- GET  /docking/jobs          — ComputeJob 列表（对接类型）
- GET  /docking/jobs/{id}     — ComputeJob 详情
"""
import logging
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_active_llm_config, get_current_user, get_llm_client_with_config, require_role_or_function
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.compute_job import ComputeJob, ComputeJobStatus, ComputeJobType
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.compute import get_unimol, get_vina
from app.services.orchestrator.hybrid_orchestrator import HybridOrchestrator
from app.services.coscientist.hooks import on_docking_completed

logger = logging.getLogger(__name__)
router = APIRouter()

_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["molecule_design", "target_discovery", "project_pi", "computational_chemistry"]


def _to_uuid(value):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


@router.post("/unimol", response_model=ApiResponse[Dict[str, Any]], summary="Uni-Mol 粗筛对接")
async def unimol_dock(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """Uni-Mol AI 对接（body: {smiles, target_pdb?, target_name?}）

    返回 {rmsd, affinity, confidence, binding_pose, source}
    """
    smiles = (payload or {}).get("smiles", "").strip()
    if not smiles:
        raise ValidationError("smiles 不能为空")
    target_pdb = payload.get("target_pdb", "")
    target_name = payload.get("target_name", "")

    docker = get_unimol(db)
    result = await docker.dock(smiles=smiles, target_pdb=target_pdb, target_name=target_name)
    return success_response(result)


@router.post("/vina", response_model=ApiResponse[Dict[str, Any]], summary="Vina 精修对接")
async def vina_dock(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """Vina 物理对接（body: {smiles, receptor_pdbqt?, box?, exhaustiveness?, num_poses?}）

    box 格式: {center: [x,y,z], size: [x,y,z]}
    exhaustiveness: 搜索深度（1-32，默认 8）
    num_poses: 输出构象数（1-20，默认 10）

    返回 {affinity, rmsd, ki, ligand_efficiency, binding_pose, pose, source}
    """
    smiles = (payload or {}).get("smiles", "").strip()
    if not smiles:
        raise ValidationError("smiles 不能为空")
    receptor_pdbqt = payload.get("receptor_pdbqt", "")
    box = payload.get("box") or {}

    # 提取 Vina 对接参数（可独立传入，与 box 合并）
    exhaustiveness = payload.get("exhaustiveness")
    num_poses = payload.get("num_poses")
    if exhaustiveness is not None:
        box["exhaustiveness"] = int(exhaustiveness)
    if num_poses is not None:
        box["num_poses"] = int(num_poses)

    docker = get_vina(db)
    result = await docker.dock(smiles=smiles, receptor_pdbqt=receptor_pdbqt, box=box)
    return success_response(result)


@router.post("/hybrid", response_model=ApiResponse[Dict[str, Any]], summary="LLM+计算混合对接")
async def hybrid_dock(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """HybridOrchestrator.llm_driven_docking（body: {project_id, target_id, smiles_list, top_k?}）

    5 步流程：LLM 假设 → Uni-Mol 粗筛 → LLM 重排序 → Vina 精修 → LLM 报告
    返回 {final_ranking, docking_results, report, cost_usd, duration_sec, steps_completed, truncated}
    """
    project_id = (payload or {}).get("project_id")
    target_id = (payload or {}).get("target_id")
    smiles_list = (payload or {}).get("smiles_list", [])
    if not target_id or not smiles_list or not isinstance(smiles_list, list):
        raise ValidationError("target_id 和 smiles_list（数组）不能为空")
    top_k = payload.get("top_k", 20)

    try:
        llm_client = await get_llm_client_with_config(db)
        llm_config = await get_active_llm_config(db)
    except Exception as e:
        logger.warning(f"获取 LLM 客户端失败，降级纯计算: {e}")
        llm_client, llm_config = None, None

    orchestrator = HybridOrchestrator(db, llm_client=llm_client, llm_config=llm_config)
    result = await orchestrator.llm_driven_docking(
        project_id=project_id, target_id=target_id,
        smiles_list=smiles_list, user=current_user, top_k=top_k,
    )
    await db.commit()
    # Co-Scientist auto-trigger: docking completed
    await on_docking_completed(
        db=db, user=current_user,
        project_id=str(project_id) if project_id else None,
        job_id=str(result.get("job_id", "")) if isinstance(result, dict) and result.get("job_id") else None,
        job_name=f"hybrid-{target_id or ''}",
    )
    return success_response(result)


@router.get("/jobs", response_model=PagedResponse[Dict[str, Any]], summary="对接任务列表")
async def list_docking_jobs(
    status: Optional[str] = Query(None, description="按状态过滤"),
    engine: Optional[str] = Query(None, description="按引擎过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对接类 ComputeJob 列表（分页）"""
    q = select(ComputeJob).where(
        ComputeJob.owner_id == current_user.id,
        ComputeJob.job_type == ComputeJobType.DOCKING,
    )
    if status:
        q = q.where(ComputeJob.status == status)
    if engine:
        q = q.where(ComputeJob.engine == engine)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(ComputeJob.created_at.desc())
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = [_serialize_job(j) for j in result.scalars().all()]
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/jobs/{job_id}", response_model=ApiResponse[Dict[str, Any]], summary="对接任务详情")
async def get_docking_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.get(ComputeJob, job_id)
    if not job or job.owner_id != current_user.id:
        raise NotFoundError("计算任务不存在")
    return success_response(_serialize_job(job))


def _serialize_job(j: ComputeJob) -> Dict[str, Any]:
    return {
        "id": str(j.id),
        "job_type": j.job_type,
        "engine": j.engine,
        "mode": j.mode,
        "status": j.status,
        "cost_usd": j.cost_usd,
        "duration_sec": j.duration_sec,
        "energy_kwh": j.energy_kwh,
        "token_count": j.token_count,
        "error_message": j.error_message,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }
