"""靶点端点 — AI 辅助靶点发现"""
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_project_visibility
from app.core.deps import get_current_user
from app.core.exceptions import AppException, ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.project import Project
from app.models.target import Target, EvidenceGrade
from app.models.user import User
from app.api.v1.schemas import TargetResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.coscientist.hooks import on_targets_discovered

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/discover", response_model=StandardResponse, summary="靶点发现")
async def discover_targets(
    project_id: UUID,
    dataset_id: Optional[UUID] = Query(None, description="指定数据集分析"),
    tier: str = Query("fast_screen", description="分析层级: fast_screen/deep_insight"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从数据集中发现靶点 — 突变→注释→通路→证据分级"""
    # 权限校验：非 FOUNDER 必须是项目拥有者，防止越权触发他人项目的靶点发现
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if current_user.role != UserRole.FOUNDER and project.owner_id != current_user.id:
        raise ForbiddenError("无权操作此项目")
    from app.services.analyzer.target_identifier import TargetIdentifier
    identifier = TargetIdentifier(db)
    try:
        result = await identifier.discover(project_id=project_id, dataset_id=dataset_id, tier=tier)
        # Co-Scientist auto-trigger hook
        _disc_targets = result.get("targets", []) if isinstance(result, dict) else []
        if _disc_targets:
            _dt0 = _disc_targets[0]
            await on_targets_discovered(
                db=db, user=current_user, project_id=str(project_id),
                target_id=str(_dt0.get("id")) if _dt0.get("id") else None,
                gene_symbol=_dt0.get("gene_symbol") or _dt0.get("gene"),
            )
        return StandardResponse(message=f"发现 {len(result.get('targets', []))} 个靶点", data=result)
    except AppException:
        raise
    except Exception as e:
        logger.error(f"靶点发现失败: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message=f"靶点发现失败: {str(e)}",
            data={"project_id": str(project_id), "tier": tier, "error": str(e)},
        )


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


@router.get("/{target_id}/protein-sequence", response_model=ApiResponse[Dict[str, Any]], summary="查询靶点蛋白氨基酸序列（UniProt）")
async def get_target_protein_sequence(
    target_id: UUID,
    refresh: bool = Query(False, description="强制刷新缓存，重新查询 UniProt"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从 UniProt 数据库查询靶点对应基因的 canonical 蛋白序列

    - 缓存写入 target.annotation（dict 类型），键：protein_sequence / uniprot_id / protein_name
      注：variant_info 在历史数据中可能是 list（变异列表），不能直接当 dict 用
    - refresh=True 时强制重新查询 UniProt
    """
    target = await db.get(Target, target_id)
    if not target:
        raise NotFoundError("靶点不存在")
    project = await db.get(Project, target.project_id)
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")

    # annotation 字段是 dict 类型，可安全用作缓存容器
    annotation = target.annotation if isinstance(target.annotation, dict) else {}

    # 命中缓存且未强制刷新
    cached_seq = annotation.get("protein_sequence") if isinstance(annotation, dict) else None
    if not refresh and cached_seq:
        return success_response({
            "uniprot_id": annotation.get("uniprot_id", ""),
            "gene_symbol": target.gene_symbol,
            "protein_name": annotation.get("protein_name", ""),
            "sequence": cached_seq,
            "sequence_length": len(cached_seq),
            "source": "cache",
        })

    # 实时查询 UniProt
    try:
        from app.services.external.uniprot_client import fetch_canonical_sequence
        result = await fetch_canonical_sequence(target.gene_symbol)
    except Exception as e:
        logger.warning(f"UniProt 客户端调用失败 target={target_id}: {e}")
        return success_response({
            "source": "error",
            "error": f"UniProt 查询失败: {e}",
            "gene_symbol": target.gene_symbol,
        })

    # 命中后写缓存到 annotation（不阻塞响应）
    if result.get("source") == "uniprot" and result.get("sequence"):
        try:
            # 合并原 annotation（避免覆盖 entrez_id/pathway 等已有信息）
            merged = dict(annotation) if isinstance(annotation, dict) else {}
            merged["protein_sequence"] = result["sequence"]
            merged["uniprot_id"] = result.get("uniprot_id", "")
            merged["protein_name"] = result.get("protein_name", "")
            target.annotation = merged
            db.add(target)
            await db.commit()
        except Exception as e:
            logger.warning(f"蛋白序列缓存写入失败 target={target_id}: {e}")
            await db.rollback()

    return success_response(result)


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
    # 权限校验：与 get_target 一致
    project = await db.get(Project, target.project_id) if target.project_id else None
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")

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
    # 权限校验：与 get_target 一致
    project = await db.get(Project, target.project_id) if target.project_id else None
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")

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
    # 权限校验：与 get_target 一致（target→project→owner），防止越权触发他人项目深度分析
    project = await db.get(Project, target.project_id) if target.project_id else None
    if current_user.role != UserRole.FOUNDER and (not project or project.owner_id != current_user.id):
        raise ForbiddenError("无权访问此资源")
    from app.services.analyzer.target_identifier import TargetIdentifier
    identifier = TargetIdentifier(db)
    try:
        result = await identifier.discover(
            project_id=target.project_id,
            dataset_id=None,
            tier="deep_insight",
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"强制深度分析失败: {e}", exc_info=True)
        return success_response({
            "target_id": str(target_id),
            "error": f"深度分析失败: {str(e)}",
            "analysis": None,
        })
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
