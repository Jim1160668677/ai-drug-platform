"""蛋白结构预测端点 — 集成 ESMFold 与 Protenix

4 个端点：
- POST /structures/predict  — 调 ESMFoldPredictor 预测蛋白结构（仅蛋白）
- POST /structures/predict-complex  — 调 ProtenixPredictor 预测蛋白-配体复合物结构（含结合位点）
- GET  /structures          — 列表（支持 target_id 过滤、分页）
- GET  /structures/{id}     — 详情
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
from app.models.protein_structure import (
    ProteinStructure,
    ProteinStructureSource,
    ProteinStructureStatus,
)
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.compute import get_esmfold, get_protenix
from app.services.coscientist.hooks import on_structure_predicted

logger = logging.getLogger(__name__)
router = APIRouter()

# 写操作：founder/chief/researcher/doctor OR target_discovery/molecule_design/project_pi
_WRITE_ROLES = [UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.RESEARCHER, UserRole.DOCTOR]
_WRITE_FUNCS = ["target_discovery", "molecule_design", "project_pi", "structural_biology"]


def _to_uuid(value):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


@router.post("/predict", response_model=ApiResponse[Dict[str, Any]], summary="预测蛋白结构")
async def predict_structure(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """调 ESMFold 预测蛋白结构（body: {sequence, target_id?, ligand_smiles?, engine?}）

    - engine="esmfold"（默认）：仅预测蛋白结构
    - engine="protenix" 或提供 ligand_smiles：调 Protenix 预测蛋白-配体复合物结构，
      返回 ligand_coordinates 和 binding_site_residues 用于结合位点可视化

    返回 {pdb_text, plddt_mean, source, structure_id, ligand_coordinates?, binding_site_residues?}
    """
    sequence = (payload or {}).get("sequence", "").strip()
    if not sequence:
        raise ValidationError("sequence（氨基酸序列）不能为空")
    target_id = payload.get("target_id")
    ligand_smiles = (payload.get("ligand_smiles") or "").strip() or None
    engine = (payload.get("engine") or "").strip().lower()

    # 引擎选择：传入 ligand_smiles 或显式指定 protenix 时走 Protenix
    use_protenix = engine == "protenix" or (ligand_smiles and engine != "esmfold")

    if use_protenix:
        predictor = get_protenix(db)
        result = await predictor.predict_structure(
            sequence=sequence,
            target_id=target_id or "",
            ligand_smiles=ligand_smiles,
        )
    else:
        predictor = get_esmfold(db)
        result = await predictor.predict_structure(sequence=sequence, target_id=target_id or "")

    # 持久化 ProteinStructure 记录
    try:
        source_str = result.get("source", "mock")
        if "protenix" in str(source_str):
            prediction_source = ProteinStructureSource.ESMFOLD  # 复用枚举（暂无 PROTENIX 枚举）
            model_name = result.get("model_name", "protenix_v1")
        elif source_str == "mock":
            prediction_source = (
                ProteinStructureSource.MOCK
                if hasattr(ProteinStructureSource, "MOCK")
                else ProteinStructureSource.ESMFOLD
            )
            model_name = result.get("model_name", "esmfold_v1_mock")
        else:
            prediction_source = ProteinStructureSource.ESMFOLD
            model_name = result.get("model_name", "esmfold_v1")

        structure = ProteinStructure(
            owner_id=current_user.id,
            target_id=_to_uuid(target_id) if target_id else None,
            sequence=sequence,
            storage_path=result.get("storage_path", ""),
            plddt_mean=result.get("plddt_mean", 0.0),
            plddt_per_residue=result.get("confidence_per_residue", []),
            prediction_source=prediction_source,
            model_name=model_name,
            status=ProteinStructureStatus.COMPLETED,
            error_message=None,
        )
        db.add(structure)
        await db.flush()
        result["structure_id"] = str(structure.id)
    except Exception as e:
        logger.warning(f"持久化 ProteinStructure 失败（不影响主流程）: {e}")
        await db.rollback()

    # Co-Scientist auto-trigger: structure predicted
    if isinstance(result, dict) and result.get("structure_id"):
        await on_structure_predicted(
            db=db, user=current_user,
            project_id=str(structure.project_id) if hasattr(structure, 'project_id') and structure.project_id else None,
            structure_id=str(result.get("structure_id")),
            structure_name=f"{result.get('source', 'esmfold')}-structure",
        )
    return success_response(result)


@router.post("/predict-complex", response_model=ApiResponse[Dict[str, Any]], summary="预测蛋白-配体复合物结构（Protenix）")
async def predict_complex(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_or_function(_WRITE_ROLES, _WRITE_FUNCS)),
):
    """调 Protenix 预测蛋白-配体复合物结构（body: {sequence, ligand_smiles, target_id?}）

    返回 {pdb_text, plddt_mean, source, structure_id,
          ligand_coordinates: [[x,y,z], ...],
          binding_site_residues: [res_seq, ...]}
    """
    sequence = (payload or {}).get("sequence", "").strip()
    if not sequence:
        raise ValidationError("sequence（氨基酸序列）不能为空")
    ligand_smiles = (payload.get("ligand_smiles") or "").strip()
    if not ligand_smiles:
        raise ValidationError("ligand_smiles（配体 SMILES）不能为空")
    target_id = payload.get("target_id")

    predictor = get_protenix(db)
    result = await predictor.predict_complex(
        sequence=sequence,
        ligand_smiles=ligand_smiles,
        target_id=target_id or "",
    )

    # 持久化（复用 predict_structure 的持久化逻辑）
    try:
        structure = ProteinStructure(
            owner_id=current_user.id,
            target_id=_to_uuid(target_id) if target_id else None,
            sequence=sequence,
            storage_path=result.get("storage_path", ""),
            plddt_mean=result.get("plddt_mean", 0.0),
            plddt_per_residue=result.get("confidence_per_residue", []),
            prediction_source=ProteinStructureSource.ESMFOLD,
            model_name=result.get("model_name", "protenix_v1"),
            status=ProteinStructureStatus.COMPLETED,
            error_message=None,
        )
        db.add(structure)
        await db.flush()
        result["structure_id"] = str(structure.id)
    except Exception as e:
        logger.warning(f"持久化 ProteinStructure 失败（不影响主流程）: {e}")
        await db.rollback()

    return success_response(result)


@router.get("", response_model=PagedResponse[Dict[str, Any]], summary="蛋白结构列表")
async def list_structures(
    target_id: Optional[UUID] = Query(None, description="按靶点过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取蛋白结构预测列表（分页）"""
    q = select(ProteinStructure).where(ProteinStructure.owner_id == current_user.id)
    if target_id is not None:
        q = q.where(ProteinStructure.target_id == target_id)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(ProteinStructure.created_at.desc())
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = [_serialize_structure(s) for s in result.scalars().all()]
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/{structure_id}", response_model=ApiResponse[Dict[str, Any]], summary="蛋白结构详情")
async def get_structure(
    structure_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    structure = await db.get(ProteinStructure, structure_id)
    if not structure or structure.owner_id != current_user.id:
        raise NotFoundError("蛋白结构记录不存在")
    return success_response(_serialize_structure(structure))


def _serialize_structure(s: ProteinStructure) -> Dict[str, Any]:
    return {
        "id": str(s.id),
        "target_id": str(s.target_id) if s.target_id else None,
        "sequence": s.sequence[:100] + "..." if len(s.sequence) > 100 else s.sequence,
        "plddt_mean": s.plddt_mean,
        "prediction_source": s.prediction_source,
        "model_name": s.model_name,
        "status": s.status,
        "storage_path": s.storage_path,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
