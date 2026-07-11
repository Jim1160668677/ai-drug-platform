"""靶点端点 — AI 辅助靶点发现"""
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_project_visibility
from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.project import Project
from app.models.target import Target, EvidenceGrade
from app.models.user import User
from app.api.v1.schemas import TargetResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

router = APIRouter()


@router.post("/discover", response_model=StandardResponse, summary="靶点发现")
async def discover_targets(
    project_id: UUID,
    dataset_id: Optional[UUID] = Query(None, description="指定数据集分析"),
    tier: str = Query("fast_screen", description="分析层级: fast_screen/deep_insight"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从数据集中发现靶点 — 突变→注释→通路→证据分级"""
    from app.services.analyzer.target_identifier import TargetIdentifier
    identifier = TargetIdentifier(db)
    result = await identifier.discover(project_id=project_id, dataset_id=dataset_id, tier=tier)
    return StandardResponse(message=f"发现 {len(result.get('targets', []))} 个靶点", data=result)


@router.get("", response_model=PagedResponse[TargetResponse], summary="靶点列表")
async def list_targets(
    project_id: UUID = Query(None),
    evidence_grade: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取靶点列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的靶点。
    """
    skip = (page - 1) * page_size
    stmt = select(Target).offset(skip).limit(page_size).order_by(Target.confidence_score.desc().nullslast())
    if project_id:
        stmt = stmt.where(Target.project_id == project_id)
    if evidence_grade:
        stmt = stmt.where(Target.evidence_grade == evidence_grade)
    stmt = apply_project_visibility(stmt, current_user, Target.project_id)
    result = await db.execute(stmt)
    items = [TargetResponse.model_validate(t).model_dump() for t in result.scalars().all()]

    # 空列表自动发现 — 仅在第 1 页、无过滤时触发
    if not items and not project_id and not evidence_grade and page == 1:
        items = await _auto_discover_targets(db, current_user)

    count_stmt = select(func.count()).select_from(Target)
    if project_id:
        count_stmt = count_stmt.where(Target.project_id == project_id)
    if evidence_grade:
        count_stmt = count_stmt.where(Target.evidence_grade == evidence_grade)
    count_stmt = apply_project_visibility(count_stmt, current_user, Target.project_id)
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


async def _auto_discover_targets(db: AsyncSession, current_user: User) -> list:
    """空列表时自动发现靶点 — 取用户首个项目，调用 TargetIdentifier 自动分析"""
    from app.services.analyzer.target_identifier import TargetIdentifier
    from app.models.dataset import Dataset

    # 查找用户可见的首个项目
    proj_stmt = select(Project).limit(1).order_by(Project.created_at.desc())
    proj_stmt = apply_project_visibility(proj_stmt, current_user, Project.id)
    # 修正：apply_project_visibility 需要的是资源的 project_id 列，对 Project 本身用 owner_id
    if current_user.role not in (UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER):
        proj_stmt = select(Project).where(Project.owner_id == current_user.id).limit(1).order_by(Project.created_at.desc())
    project_result = await db.execute(proj_stmt)
    project = project_result.scalars().first()
    if not project:
        return []

    # 查找该项目的首个数据集
    ds_stmt = select(Dataset).where(Dataset.project_id == project.id).limit(1)
    ds_result = await db.execute(ds_stmt)
    dataset = ds_result.scalars().first()

    identifier = TargetIdentifier(db)
    try:
        result = await identifier.discover(
            project_id=project.id,
            dataset_id=dataset.id if dataset else None,
            tier="fast_screen",
        )
        # discover 内部已持久化靶点，返回结果中的 targets 是 dict 列表
        # 需要从数据库重新查询以获取完整 Target 对象
    except Exception:
        return []

    # 重新查询刚发现的靶点
    stmt = select(Target).where(Target.project_id == project.id).order_by(Target.confidence_score.desc().nullslast()).limit(10)
    result_stmt = await db.execute(stmt)
    return [TargetResponse.model_validate(t).model_dump() for t in result_stmt.scalars().all()]


@router.get("/{target_id}", response_model=TargetResponse, summary="靶点详情")
async def get_target(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await db.get(Target, target_id)
    if not target:
        raise NotFoundError("靶点不存在")
    project = await db.get(Project, target.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")
    return TargetResponse.model_validate(target)


@router.post("/{target_id}/repurpose", response_model=StandardResponse, summary="老药新用扫描")
async def repurpose_target(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """老药新用 — 扫描 ChEMBL 已获批药物"""
    target = await db.get(Target, target_id)
    if not target:
        raise NotFoundError("靶点不存在")

    from app.services.analyzer.drug_repurposer import DrugRepurposer
    repurposer = DrugRepurposer(db)
    result = await repurposer.repurpose(target)

    target.approved_drugs = result.get("candidates", [])
    target.evidence_grade = EvidenceGrade.LEVEL_I if result.get("candidates") else target.evidence_grade
    return StandardResponse(message=f"找到 {len(result.get('candidates', []))} 个候选药物", data=result)


@router.post("/{target_id}/evidence", response_model=StandardResponse, summary="构建证据链")
async def build_evidence_chain(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """构建靶点证据链"""
    target = await db.get(Target, target_id)
    if not target:
        raise NotFoundError("靶点不存在")

    from app.services.analyzer.evidence_chain import EvidenceChainBuilder
    builder = EvidenceChainBuilder(db)
    result = await builder.build(target)
    target.evidence_chain = result
    return StandardResponse(message="证据链已构建", data=result)


@router.post("/{target_id}/force-deep-analysis", response_model=ApiResponse[Dict[str, Any]], summary="强制深度分析")
async def force_deep_analysis(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """强制对靶点进行深度分析（deep_insight 模式）"""
    target = await db.get(Target, target_id)
    if not target:
        raise NotFoundError("靶点不存在")
    from app.services.analyzer.target_identifier import TargetIdentifier
    identifier = TargetIdentifier(db)
    result = await identifier.discover(
        project_id=target.project_id,
        dataset_id=None,
        tier="deep_insight",
    )
    # 过滤出与当前靶点相关的分析结果（按 gene_symbol 匹配）
    target_gene = getattr(target, "gene_symbol", None) or getattr(target, "gene", None)
    all_targets = result.get("targets", [])
    related = [t for t in all_targets if t.get("gene") == target_gene or t.get("gene_symbol") == target_gene]
    return success_response({
        "target_id": str(target_id),
        "target_gene": target_gene,
        "analysis": related[0] if related else result,
        "total_targets_in_project": len(all_targets),
    })


@router.post("/network", response_model=ApiResponse[Dict[str, Any]], summary="PPI 网络分析")
async def analyze_network(
    gene_list: List[str] = Body(..., embed=True),
    max_depth: int = Body(1, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PPI 网络分析"""
    from app.services.analyzer.network_modeler import NetworkModeler
    modeler = NetworkModeler(db)
    result = await modeler.analyze_ppi(gene_list, max_depth=max_depth)
    return success_response(result)


@router.post("/synergy", response_model=ApiResponse[Dict[str, Any]], summary="靶点协同预测")
async def predict_synergy(
    target_pairs: List[Tuple[str, str]] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """靶点协同效应预测"""
    from app.services.analyzer.network_modeler import NetworkModeler
    modeler = NetworkModeler(db)
    result = await modeler.predict_synergy(target_pairs)
    return success_response(result)
