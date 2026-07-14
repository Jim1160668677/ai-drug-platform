"""治疗方案端点 — 并行治疗方案设计"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
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
    """获取治疗方案详情（含关联靶点、分子、监测数据、配置等完整报告）"""
    from app.models.target import Target
    from app.models.molecule import Molecule
    t = await db.get(Treatment, treatment_id)
    if not t:
        raise NotFoundError("治疗方案不存在")
    project = await db.get(Project, t.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")

    # 查询关联靶点详情
    target_ids = t.target_ids or []
    targets_info = []
    if target_ids:
        tgt_result = await db.execute(select(Target).where(Target.id.in_([UUID(tid) for tid in target_ids])))
        for tgt in tgt_result.scalars().all():
            targets_info.append({
                "id": str(tgt.id),
                "gene_symbol": tgt.gene_symbol,
                "gene_name": tgt.gene_name,
                "evidence_grade": tgt.evidence_grade,
                "confidence_score": tgt.confidence_score,
                "approved_drugs": tgt.approved_drugs,
            })

    # 查询关联分子详情
    molecule_ids = t.molecule_ids or []
    molecules_info = []
    if molecule_ids:
        mol_result = await db.execute(select(Molecule).where(Molecule.id.in_([UUID(mid) for mid in molecule_ids])))
        for mol in mol_result.scalars().all():
            molecules_info.append({
                "id": str(mol.id),
                "name": mol.name,
                "smiles": mol.smiles,
                "molecular_weight": mol.molecular_weight,
                "logp": mol.logp,
                "is_approved": mol.is_approved,
                "source": mol.source,
            })

    # 治疗类型中文映射
    therapy_type_map = {
        "targeted": "靶向治疗",
        "immuno": "免疫治疗",
        "chemo": "化疗",
        "radio": "放疗",
        "combination": "组合疗法",
        "vaccine": "mRNA 肿瘤疫苗",
        "experimental": "探索性治疗",
    }
    status_map = {
        "proposed": "已提出",
        "testing": "测试中",
        "effective": "有效",
        "ineffective": "无效",
        "deprecated": "已废弃",
    }

    return success_response({
        "id": str(t.id),
        "project_id": str(t.project_id),
        "name": t.name,
        "therapy_type": t.therapy_type,
        "therapy_type_label": therapy_type_map.get(t.therapy_type, t.therapy_type),
        "target_ids": t.target_ids,
        "molecule_ids": t.molecule_ids,
        "targets": targets_info,
        "molecules": molecules_info,
        "hypothesis_id": str(t.hypothesis_id) if t.hypothesis_id else None,
        "status": t.status,
        "status_label": status_map.get(t.status, t.status),
        "efficacy_score": t.efficacy_score,
        "risk_score": t.risk_score,
        "confidence": t.confidence,
        "config": t.config,
        "monitoring_data": t.monitoring_data,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    })


@router.delete("/{treatment_id}", response_model=ApiResponse[Dict[str, Any]], summary="删除治疗方案")
async def delete_treatment(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除治疗方案（仅 FOUNDER 或所属项目拥有者可删除）"""
    t = await db.get(Treatment, treatment_id)
    if not t:
        raise NotFoundError("治疗方案不存在")
    project = await db.get(Project, t.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权删除此资源")
    await db.delete(t)
    await db.commit()
    return success_response({"id": str(treatment_id), "deleted": True})


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


class DDICheckRequest(BaseModel):
    """药物相互作用检查请求"""
    drug_list: List[str]
    target_list: Optional[List[str]] = None


@router.post("/{treatment_id}/ddi-check", response_model=StandardResponse, summary="药物相互作用检查")
async def check_ddi(
    treatment_id: UUID,
    payload: DDICheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查治疗方案中的药物相互作用（DDI）

    基于 v3.0 文档第 7 章五大关键深化能力。
    使用规则表 + 靶点重合度算法，返回风险等级和相互作用详情。
    """
    from app.services.analyzer.ddi_checker import get_ddi_checker
    checker = get_ddi_checker()
    result = checker.check(payload.drug_list, payload.target_list)
    return success_response(result)


@router.post("/ddi-check", response_model=StandardResponse, summary="药物相互作用检查（无需治疗方案 ID）")
async def check_ddi_standalone(
    payload: DDICheckRequest,
    current_user: User = Depends(get_current_user),
):
    """药物相互作用检查（独立端点，无需关联治疗方案）

    用法：POST /treatments/ddi-check
    Body: {"drug_list": ["warfarin", "aspirin"], "target_list": ["VKORC1"]}
    """
    from app.services.analyzer.ddi_checker import get_ddi_checker
    checker = get_ddi_checker()
    result = checker.check(payload.drug_list, payload.target_list)
    return success_response(result)


@router.post("/{treatment_id}/clinical-feedback", response_model=ApiResponse[Dict[str, Any]], summary="录入临床反馈")
async def create_clinical_feedback(
    treatment_id: UUID,
    feedback_data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """录入患者用药结果反馈 — 用药方案/治疗效果/不良反应"""
    from app.models.treatment import ClinicalFeedback
    from app.services.experiment.feedback_loop import FeedbackLoop

    fb = ClinicalFeedback(
        treatment_id=str(treatment_id),
        patient_code=feedback_data.get("patient_code"),
        age=feedback_data.get("age"),
        gender=feedback_data.get("gender"),
        dosage=feedback_data.get("dosage"),
        duration_days=feedback_data.get("duration_days"),
        efficacy=feedback_data.get("efficacy"),
        adverse_reactions=feedback_data.get("adverse_reactions"),
        biomarker_changes=feedback_data.get("biomarker_changes"),
        notes=feedback_data.get("notes"),
    )
    db.add(fb)

    loop = FeedbackLoop(db)
    loop_result = await loop.apply_clinical_feedback(feedback_data, str(treatment_id))

    await db.commit()
    return success_response({
        "id": str(fb.id),
        "treatment_id": str(treatment_id),
        "loop_analysis": loop_result,
    })


@router.get("/{treatment_id}/clinical-feedbacks", response_model=ApiResponse[List[Dict[str, Any]]], summary="临床反馈列表")
async def list_clinical_feedbacks(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取治疗方案的所有临床反馈"""
    from app.models.treatment import ClinicalFeedback
    stmt = select(ClinicalFeedback).where(ClinicalFeedback.treatment_id == str(treatment_id))
    result = await db.execute(stmt)
    items = [{
        "id": str(f.id), "patient_code": f.patient_code, "age": f.age,
        "gender": f.gender, "efficacy": f.efficacy,
        "adverse_reactions": f.adverse_reactions,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in result.scalars().all()]
    return success_response(items)
