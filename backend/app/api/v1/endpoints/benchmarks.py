"""基准评测端点 — 对比 hybrid / traditional_supercompute / llm_only 三种模式

5 个端点：
- POST /benchmarks/run       — 单 case 单模式运行
- POST /benchmarks/compare    — 单 case 3 模式对比
- POST /benchmarks/run-all    — 9 个预设案例全量对比
- GET  /benchmarks           — BenchmarkReport 列表（分页）
- GET  /benchmarks/{id}      — BenchmarkReport 详情
"""
import logging
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role_or_function
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.benchmark_report import BenchmarkReport, BenchmarkMode
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.core.deps import get_active_llm_config, get_llm_client_with_config
from app.services.orchestrator.benchmark import BenchmarkRunner
from app.services.coscientist.hooks import on_benchmark_completed

logger = logging.getLogger(__name__)
router = APIRouter()

_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["target_discovery", "project_pi", "bioinformatics", "computational_biology"]


def _to_uuid(value):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


async def _build_runner(db: AsyncSession) -> BenchmarkRunner:
    """构建 BenchmarkRunner 实例（注入 LLM 客户端，可能为 None）"""
    try:
        llm_client = await get_llm_client_with_config(db)
        llm_config = await get_active_llm_config(db)
    except Exception as e:
        logger.warning(f"获取 LLM 客户端失败，降级为纯计算模式: {e}")
        llm_client, llm_config = None, None
    return BenchmarkRunner(db, llm_client=llm_client, llm_config=llm_config)


@router.post("/run", response_model=ApiResponse[Dict[str, Any]], summary="单 case 单模式运行")
async def run_case(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """单 case 单模式运行（body: {case_id, mode, smiles, target_pdb?, target_gene?}）

    mode 取值：hybrid / traditional_supercompute / llm_only
    返回 {case_id, mode, metrics: {7 指标}, report_id}
    """
    case_id = (payload or {}).get("case_id", "").strip()
    mode = (payload or {}).get("mode", "").strip()
    smiles = (payload or {}).get("smiles", "").strip()
    if not case_id or not mode or not smiles:
        raise ValidationError("case_id / mode / smiles 均不能为空")
    if mode not in (BenchmarkMode.HYBRID, BenchmarkMode.TRADITIONAL_SUPERCOMPUTE, BenchmarkMode.LLM_ONLY):
        raise ValidationError(f"mode 必须为 {BenchmarkMode.HYBRID}/{BenchmarkMode.TRADITIONAL_SUPERCOMPUTE}/{BenchmarkMode.LLM_ONLY}")

    target_pdb = payload.get("target_pdb", "")
    target_gene = payload.get("target_gene", "EGFR")

    runner = await _build_runner(db)
    result = await runner.run_case(
        case_id=case_id, mode=mode, smiles=smiles,
        target_pdb=target_pdb, user=current_user, target_gene=target_gene,
    )
    await db.commit()
    # Co-Scientist auto-trigger: benchmark completed
    await on_benchmark_completed(
        db=db, user=current_user, project_id=None,
        report_id=str(result.get("report_id", "")) if isinstance(result, dict) and result.get("report_id") else None,
        case_id=case_id,
    )
    return success_response(result)


@router.post("/compare", response_model=ApiResponse[Dict[str, Any]], summary="单 case 3 模式对比")
async def compare_modes(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """单 case 3 模式对比（body: {case_id, smiles, target_pdb?, target_gene?}）

    返回 {case_id, results: {hybrid, traditional_supercompute, llm_only}, comparison, winner}
    """
    case_id = (payload or {}).get("case_id", "").strip()
    smiles = (payload or {}).get("smiles", "").strip()
    if not case_id or not smiles:
        raise ValidationError("case_id / smiles 不能为空")

    target_pdb = payload.get("target_pdb", "")
    target_gene = payload.get("target_gene", "EGFR")

    runner = await _build_runner(db)
    result = await runner.compare_modes(
        case_id=case_id, smiles=smiles,
        target_pdb=target_pdb, user=current_user, target_gene=target_gene,
    )
    await db.commit()
    # Co-Scientist auto-trigger: benchmark completed
    await on_benchmark_completed(
        db=db, user=current_user, project_id=None,
        report_id=str(result.get("report_id", "")) if isinstance(result, dict) and result.get("report_id") else None,
        case_id=case_id,
    )
    return success_response(result)


@router.post("/run-all", response_model=ApiResponse[Dict[str, Any]], summary="9 个预设案例全量对比")
async def run_all_cases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """对 9 个预设案例跑 3 模式对比，生成汇总报告"""
    runner = await _build_runner(db)
    result = await runner.run_all_cases(user=current_user)
    await db.commit()
    return success_response(result)


@router.get("", response_model=PagedResponse[Dict[str, Any]], summary="基准报告列表")
async def list_reports(
    case_id: Optional[str] = Query(None, description="按 case 过滤"),
    mode: Optional[str] = Query(None, description="按模式过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取基准评测报告列表（分页）"""
    q = select(BenchmarkReport).where(BenchmarkReport.owner_id == current_user.id)
    if case_id:
        q = q.where(BenchmarkReport.case_id == case_id)
    if mode:
        q = q.where(BenchmarkReport.mode == mode)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(BenchmarkReport.created_at.desc())
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = [_serialize_report(r) for r in result.scalars().all()]
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/{report_id}", response_model=ApiResponse[Dict[str, Any]], summary="基准报告详情")
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = await db.get(BenchmarkReport, report_id)
    if not report or report.owner_id != current_user.id:
        raise NotFoundError("基准报告不存在")
    return success_response(_serialize_report(report))


def _serialize_report(r: BenchmarkReport) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "case_id": r.case_id,
        "mode": r.mode,
        "metrics": r.metrics,
        "summary": r.summary,
        "cost_usd": r.cost_usd,
        "duration_sec": r.duration_sec,
        "energy_kwh": r.energy_kwh,
        "cost_saving_pct": r.cost_saving_pct,
        "accuracy_change_pct": r.accuracy_change_pct,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
