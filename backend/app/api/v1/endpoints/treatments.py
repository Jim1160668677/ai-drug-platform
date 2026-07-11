"""治疗方案端点 — 并行治疗方案设计"""
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
from app.models.project import Project
from app.models.treatment import Treatment
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

router = APIRouter()


class TreatmentCreate(BaseModel):
    project_id: str
    name: str
    therapy_type: str
    target_ids: Optional[List[str]] = None
    molecule_ids: Optional[List[str]] = None
    hypothesis_id: Optional[str] = None
    config: Optional[dict] = None


@router.get("", response_model=PagedResponse[Dict[str, Any]], summary="治疗方案列表")
async def list_treatments(
    project_id: UUID = Query(None),
    status: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取治疗方案列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的治疗方案。
    """
    skip = (page - 1) * page_size
    stmt = select(Treatment).offset(skip).limit(page_size).order_by(Treatment.created_at.desc())
    if project_id:
        stmt = stmt.where(Treatment.project_id == project_id)
    if status:
        stmt = stmt.where(Treatment.status == status)
    stmt = apply_project_visibility(stmt, current_user, Treatment.project_id)
    result = await db.execute(stmt)
    items = [{"id": str(t.id), "name": t.name, "therapy_type": t.therapy_type,
              "status": t.status, "efficacy_score": t.efficacy_score,
              "risk_score": t.risk_score} for t in result.scalars().all()]

    count_stmt = select(func.count()).select_from(Treatment)
    if project_id:
        count_stmt = count_stmt.where(Treatment.project_id == project_id)
    if status:
        count_stmt = count_stmt.where(Treatment.status == status)
    count_stmt = apply_project_visibility(count_stmt, current_user, Treatment.project_id)
    total = (await db.execute(count_stmt)).scalar() or 0

    # 空列表自动生成 — 根据靶点+分子自动匹配治疗方案
    if not items and not project_id and not status and page == 1:
        items = await _auto_generate_treatments(db, current_user)
        total = len(items)

    return paged_response(data=items, page=page, page_size=page_size, total=total)


async def _auto_generate_treatments(db: AsyncSession, current_user: User) -> list:
    """根据靶点+分子自动生成治疗方案

    策略：取用户首个项目的靶点和分子，为每个有获批药物的靶点生成一个治疗方案。
    """
    from app.models.target import Target
    from app.models.molecule import Molecule
    from app.models.treatment import TreatmentStatus, TreatmentType

    # 查找用户可见的首个项目
    if current_user.role not in (UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER):
        proj_stmt = select(Project).where(Project.owner_id == current_user.id).limit(1).order_by(Project.created_at.desc())
    else:
        proj_stmt = select(Project).limit(1).order_by(Project.created_at.desc())
    project = (await db.execute(proj_stmt)).scalars().first()
    if not project:
        return []

    # 查找该项目的靶点
    target_stmt = select(Target).where(Target.project_id == project.id).limit(5)
    targets = (await db.execute(target_stmt)).scalars().all()
    if not targets:
        return []

    # 查找该项目的分子
    mol_stmt = select(Molecule).limit(10)
    molecules = (await db.execute(mol_stmt)).scalars().all()

    treatments = []
    for target in targets:
        # 查找该靶点关联的分子
        target_mols = [m for m in molecules if m.target_id == target.id]
        mol_ids = [str(m.id) for m in target_mols] if target_mols else None

        # 根据靶点信息确定治疗类型
        gene = target.gene_symbol or "未知"
        approved_drugs = target.approved_drugs or []
        has_approved = len(approved_drugs) > 0

        if has_approved:
            therapy_name = f"{gene} 靶向治疗（获批药物）"
            therapy_type = TreatmentType.TARGETED
            drugs_info = ", ".join([d.get("name", "?") for d in approved_drugs[:3]])
            config = {
                "strategy": "approved_targeted",
                "drugs": approved_drugs,
                "mechanism": f"靶向 {gene} 通路",
            }
        elif target_mols:
            therapy_name = f"{gene} 候选分子治疗"
            therapy_type = TreatmentType.TARGETED
            config = {
                "strategy": "candidate_molecule",
                "molecules": [{"smiles": m.smiles, "name": m.name} for m in target_mols[:3]],
                "mechanism": f"靶向 {gene} 通路（实验性分子）",
            }
        else:
            therapy_name = f"{gene} 探索性治疗"
            therapy_type = TreatmentType.EXPERIMENTAL
            config = {
                "strategy": "exploratory",
                "mechanism": f"靶向 {gene} 通路（待验证）",
            }

        # 疗效和风险评分（基于证据等级和置信度）
        confidence = target.confidence_score or 0.5
        efficacy_score = min(0.95, confidence + (0.1 if has_approved else 0))
        risk_score = max(0.05, 1.0 - confidence - (0.1 if has_approved else 0))

        treatment = Treatment(
            project_id=project.id,
            name=therapy_name,
            therapy_type=therapy_type,
            status=TreatmentStatus.PROPOSED,
            target_ids=[str(target.id)],
            molecule_ids=mol_ids,
            config=config,
            efficacy_score=efficacy_score,
            risk_score=risk_score,
        )
        db.add(treatment)
        treatments.append(treatment)

    if treatments:
        await db.commit()
        for t in treatments:
            await db.refresh(t)

    return [{"id": str(t.id), "name": t.name, "therapy_type": t.therapy_type,
             "status": t.status, "efficacy_score": t.efficacy_score,
             "risk_score": t.risk_score} for t in treatments]


@router.post("", response_model=StandardResponse, summary="创建治疗方案")
async def create_treatment(
    payload: TreatmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    treatment = Treatment(
        project_id=UUID(payload.project_id),
        name=payload.name,
        therapy_type=payload.therapy_type,
        target_ids=payload.target_ids,
        molecule_ids=payload.molecule_ids,
        hypothesis_id=UUID(payload.hypothesis_id) if payload.hypothesis_id else None,
        config=payload.config,
    )
    db.add(treatment)
    await db.flush()
    return StandardResponse(message="治疗方案已创建", data={"id": str(treatment.id)})


@router.post("/optimize", response_model=StandardResponse, summary="多疗法组合优化（P3）")
async def optimize_treatments(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多疗法组合优化 — 强化学习（第三阶段）"""
    from app.services.optimizer.treatment_planner import TreatmentPlanner
    planner = TreatmentPlanner(db)
    result = await planner.optimize(project_id)
    return StandardResponse(message="组合优化完成", data=result)


@router.get("/{treatment_id}", response_model=ApiResponse[Dict[str, Any]], summary="治疗方案详情")
async def get_treatment(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取治疗方案详情"""
    t = await db.get(Treatment, treatment_id)
    if not t:
        raise NotFoundError("治疗方案不存在")
    project = await db.get(Project, t.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")
    return success_response({
        "id": str(t.id),
        "project_id": str(t.project_id),
        "name": t.name,
        "therapy_type": t.therapy_type,
        "target_ids": t.target_ids,
        "molecule_ids": t.molecule_ids,
        "hypothesis_id": str(t.hypothesis_id) if t.hypothesis_id else None,
        "status": t.status,
        "efficacy_score": t.efficacy_score,
        "risk_score": t.risk_score,
        "config": t.config,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    })


@router.post("/{treatment_id}/monitor", response_model=StandardResponse, summary="疗效监测（P3）")
async def monitor_efficacy(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """实时疗效监测（第三阶段）"""
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor
    monitor = EfficacyMonitor(db)
    result = await monitor.check(treatment_id)
    return success_response(result)
