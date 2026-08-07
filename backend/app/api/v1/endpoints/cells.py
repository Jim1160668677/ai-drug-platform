"""单细胞分析端点 — 集成 scGPT

3 个端点：
- POST /cells/perturbation  — 预测基因扰动效果
- POST /cells/annotate       — 细胞类型注释
- GET  /cells/engines        — 查询引擎状态
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, require_role_or_function
from app.core.exceptions import ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.services.compute import get_scgpt, list_available
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()

_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["target_discovery", "single_cell_analysis", "project_pi", "bioinformatics"]


@router.post("/perturbation", response_model=ApiResponse[Dict[str, Any]], summary="基因扰动预测")
async def predict_perturbation(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """调 scGPT 预测基因敲除/激活后的表达变化（body: {gene, cell_type?}）

    返回 {gene, cell_type, perturbation_score, affected_genes, direction, source}
    """
    gene = (payload or {}).get("gene", "").strip()
    if not gene:
        raise ValidationError("gene（基因符号）不能为空")
    cell_type = payload.get("cell_type", "")

    engine = get_scgpt(db)
    result = await engine.predict_perturbation(gene=gene, cell_type=cell_type)
    return success_response(result)


@router.post("/annotate", response_model=ApiResponse[Dict[str, Any]], summary="细胞类型注释")
async def annotate_cell_types(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """调 scGPT 注释细胞类型（body: {adata_path}）

    返回 {annotations, n_cells, source}
    """
    adata_path = (payload or {}).get("adata_path", "").strip()
    if not adata_path:
        raise ValidationError("adata_path（单细胞数据文件路径）不能为空")

    engine = get_scgpt(db)
    result = await engine.annotate_cell_types(adata_path=adata_path)
    return success_response(result)


@router.get("/engines", response_model=ApiResponse[Dict[str, Any]], summary="单细胞引擎状态")
async def get_engines_status(
    current_user: User = Depends(get_current_user),
):
    """查询 scGPT 引擎 Mock/Real 状态"""
    available = list_available()
    return success_response({"scgpt": available.get("scgpt", "unknown")})
