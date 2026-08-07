"""合成规划端点 — 集成 AiZynthFinder + SAscore + SCScore

7 个端点：
- POST /synthesis/plan              — 完整合成规划（路线+可行性+成本）
- GET  /synthesis/plans              — 合成规划列表（分页）
- GET  /synthesis/plans/{plan_id}    — 合成规划详情
- POST /synthesis/routes              — 单独生成合成路线
- POST /synthesis/feasibility         — 单独预测可行性
- POST /synthesis/cost                — 单独估算成本
- GET  /synthesis/engines             — 合成引擎状态
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
from app.models.synthesis_plan import SynthesisPlan
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.synthesis import (
    FeasibilityPredictor,
    SynthesisCostEstimator,
    SynthesisPlanner,
    SynthesisRouteGenerator,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["molecule_design", "project_pi", "medicinal_chemistry", "process_chemistry"]


def _to_uuid(value):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


async def _get_llm(db: AsyncSession):
    try:
        llm_client = await get_llm_client_with_config(db)
        llm_config = await get_active_llm_config(db)
        return llm_client, llm_config
    except Exception as e:
        logger.warning(f"获取 LLM 客户端失败: {e}")
        return None, None


@router.post("/plan", response_model=ApiResponse[Dict[str, Any]], summary="完整合成规划")
async def create_plan(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """SynthesisPlanner.plan（body: {smiles, max_routes?, target_scale_grams?, molecule_id?, project_id?}）

    编排 RouteGenerator → FeasibilityPredictor → CostEstimator → 持久化。
    返回 {plan_id, routes, feasibility, cost, recommendation}
    """
    smiles = (payload or {}).get("smiles", "").strip()
    if not smiles:
        raise ValidationError("smiles 不能为空")
    max_routes = payload.get("max_routes", 5)
    target_scale_grams = payload.get("target_scale_grams", 10.0)
    molecule_id = payload.get("molecule_id")
    project_id = payload.get("project_id")

    llm_client, llm_config = await _get_llm(db)
    planner = SynthesisPlanner(db, llm_client=llm_client, llm_config=llm_config)
    result = await planner.plan(
        smiles=smiles, user=current_user,
        max_routes=max_routes, target_scale_grams=target_scale_grams,
        molecule_id=molecule_id, project_id=project_id,
    )
    await db.commit()
    return success_response(result)


@router.get("/plans", response_model=PagedResponse[Dict[str, Any]], summary="合成规划列表")
async def list_plans(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的合成规划列表（分页）"""
    planner = SynthesisPlanner(db)
    result = await planner.list_plans(user=current_user, page=page, page_size=page_size)
    return paged_response(
        data=result.get("items", []),
        page=page, page_size=page_size, total=result.get("total", 0),
    )


@router.get("/plans/{plan_id}", response_model=ApiResponse[Dict[str, Any]], summary="合成规划详情")
async def get_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    planner = SynthesisPlanner(db)
    plan = await planner.get_plan(str(plan_id))
    if not plan or plan.owner_id != current_user.id:
        raise NotFoundError("合成规划不存在")
    return success_response(_serialize_plan(plan))


@router.post("/routes", response_model=ApiResponse[Dict[str, Any]], summary="单独生成合成路线")
async def generate_routes(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """RouteGenerator.generate_routes（body: {smiles, max_routes?}）

    返回 {routes, n_routes, source}
    """
    smiles = (payload or {}).get("smiles", "").strip()
    if not smiles:
        raise ValidationError("smiles 不能为空")
    max_routes = payload.get("max_routes", 5)

    generator = SynthesisRouteGenerator(db)
    result = await generator.generate_routes(smiles=smiles, max_routes=max_routes)
    return success_response(result)


@router.post("/feasibility", response_model=ApiResponse[Dict[str, Any]], summary="单独预测可行性")
async def predict_feasibility(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """FeasibilityPredictor.predict（body: {smiles, routes}）

    返回 {sa_score, sc_score, feasibility_label, challenges, source}
    """
    smiles = (payload or {}).get("smiles", "").strip()
    routes = (payload or {}).get("routes", {})
    if not smiles:
        raise ValidationError("smiles 不能为空")

    predictor = FeasibilityPredictor(db)
    result = await predictor.predict(smiles=smiles, routes=routes)
    return success_response(result)


@router.post("/cost", response_model=ApiResponse[Dict[str, Any]], summary="单独估算成本")
async def estimate_cost(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """CostEstimator.estimate（body: {routes, sa_score?, target_scale_grams?}）

    返回 {total_cost_usd, cost_per_gram, breakdown, is_cost_effective}
    """
    routes = (payload or {}).get("routes", {})
    if not routes:
        raise ValidationError("routes 不能为空")
    sa_score = payload.get("sa_score", 5.0)
    target_scale_grams = payload.get("target_scale_grams", 10.0)

    estimator = SynthesisCostEstimator(db)
    result = await estimator.estimate(routes=routes, sa_score=sa_score, target_scale_grams=target_scale_grams)
    return success_response(result)


@router.get("/engines", response_model=ApiResponse[Dict[str, Any]], summary="合成引擎状态")
async def get_engines_status(
    current_user: User = Depends(get_current_user),
):
    """查询 AiZynthFinder 引擎 Mock/Real 状态"""
    from app.core.config import settings
    return success_response({
        "aizynthfinder": "mock" if getattr(settings, "AIZYNTH_USE_MOCK", True) else "real",
        "rdkit": "available",  # RDKit 始终可用
    })


def _serialize_plan(p: SynthesisPlan) -> Dict[str, Any]:
    return {
        "id": str(p.id),
        "molecule_id": str(p.molecule_id) if p.molecule_id else None,
        "smiles": p.smiles,
        "routes": p.routes,
        "n_routes": p.n_routes,
        "sa_score": p.sa_score,
        "sc_score": p.sc_score,
        "feasibility_label": p.feasibility_label,
        "total_cost_usd": p.total_cost_usd,
        "cost_breakdown": p.cost_breakdown,
        "challenges": p.challenges,
        "source_engine": p.source_engine,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
