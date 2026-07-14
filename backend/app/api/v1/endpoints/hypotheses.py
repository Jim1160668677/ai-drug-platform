"""假设端点 — 多假设并行管理（Hypothesis Sandbox）"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_project_visibility
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.hypothesis import Hypothesis, HypothesisStatus
from app.models.user import User
from app.api.v1.schemas import HypothesisCreate, HypothesisResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=PagedResponse[HypothesisResponse], summary="假设列表")
async def list_hypotheses(
    project_id: UUID = Query(None),
    status: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取假设列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的假设。
    """
    skip = (page - 1) * page_size
    stmt = select(Hypothesis).offset(skip).limit(page_size).order_by(Hypothesis.created_at.desc())
    if project_id:
        stmt = stmt.where(Hypothesis.project_id == project_id)
    if status:
        stmt = stmt.where(Hypothesis.status == status)
    stmt = apply_project_visibility(stmt, current_user, Hypothesis.project_id)
    result = await db.execute(stmt)
    items = [HypothesisResponse.model_validate(h).model_dump() for h in result.scalars().all()]

    count_stmt = select(func.count()).select_from(Hypothesis)
    if project_id:
        count_stmt = count_stmt.where(Hypothesis.project_id == project_id)
    if status:
        count_stmt = count_stmt.where(Hypothesis.status == status)
    count_stmt = apply_project_visibility(count_stmt, current_user, Hypothesis.project_id)
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("", response_model=HypothesisResponse, summary="创建假设")
async def create_hypothesis(
    project_id: UUID,
    payload: HypothesisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建平行宇宙假设 — 创始人可创建多个独立假设并行探索"""
    hyp = Hypothesis(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        mechanism=payload.mechanism,
        strategy=payload.strategy,
        analysis_config=payload.analysis_config,
        created_by=current_user.id,
    )
    db.add(hyp)
    await db.flush()
    return HypothesisResponse.model_validate(hyp)


@router.get("/compare", response_model=StandardResponse, summary="假设对比看板")
async def compare_hypotheses(
    project_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """并排对比不同假设的靶点/分子/疗效差异"""
    result = await db.execute(
        select(Hypothesis).where(Hypothesis.project_id == project_id)
        .where(Hypothesis.status.in_([HypothesisStatus.COMPLETED, HypothesisStatus.ANALYZING]))
    )
    hyps = result.scalars().all()
    comparison = []
    for h in hyps:
        comparison.append({
            "id": str(h.id), "name": h.name, "status": h.status,
            "targets": h.target_list, "result_summary": h.analysis_result,
            "forced": h.forced_deep_analysis,
        })
    return success_response({"hypotheses": comparison})


@router.get("/{hypothesis_id}", response_model=HypothesisResponse, summary="假设详情")
async def get_hypothesis(
    hypothesis_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hyp = await db.get(Hypothesis, hypothesis_id)
    if not hyp:
        raise NotFoundError("假设不存在")
    if current_user.role != UserRole.FOUNDER and hyp.created_by != current_user.id:
        raise ForbiddenError("无权访问此资源")
    return HypothesisResponse.model_validate(hyp)


@router.post("/{hypothesis_id}/analyze", response_model=StandardResponse, summary="执行并行分析")
async def analyze_hypothesis(
    hypothesis_id: UUID,
    tier: str = Query("fast_screen"),
    force_deep: bool = Query(False, description="创始人强制深度分析"),
    force_reason: str = Query(None, description="强制分析理由"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行假设分析 — 多线并行，可强制深度分析"""
    hyp = await db.get(Hypothesis, hypothesis_id)
    if not hyp:
        raise NotFoundError("假设不存在")

    hyp.status = HypothesisStatus.ANALYZING
    if force_deep:
        hyp.forced_deep_analysis = True
        hyp.force_reason = force_reason
        tier = "deep_insight"

    # 调用靶点发现引擎
    from app.services.analyzer.target_identifier import TargetIdentifier
    identifier = TargetIdentifier(db)
    result = await identifier.discover(
        project_id=hyp.project_id,
        tier=tier,
        hypothesis_id=hypothesis_id,
    )
    hyp.analysis_result = result
    hyp.target_list = [t.get("gene_symbol") for t in result.get("targets", [])]
    hyp.status = HypothesisStatus.COMPLETED
    return StandardResponse(message="假设分析完成", data=result)


@router.post("/{hypothesis_id}/merge", response_model=StandardResponse, summary="合并假设")
async def merge_hypothesis(
    hypothesis_id: UUID,
    target_hypothesis_id: UUID = Query(..., description="合并目标假设ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """合并两个假设"""
    hyp = await db.get(Hypothesis, hypothesis_id)
    target = await db.get(Hypothesis, target_hypothesis_id)
    if not hyp or not target:
        raise NotFoundError("假设不存在")
    hyp.status = HypothesisStatus.MERGED
    return StandardResponse(message=f"假设 {hyp.name} 已合并到 {target.name}")


@router.post("/{hypothesis_id}/run-analysis", response_model=ApiResponse[Dict[str, Any]], summary="运行假设分析")
async def run_analysis(
    hypothesis_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """运行假设分析 — 创建一条 HypothesisAnalysis 记录

    状态持久化：在 result_data 中存 status/started_at，便于后续状态机查询。
    """
    hypothesis = await db.get(Hypothesis, hypothesis_id)
    if not hypothesis:
        raise NotFoundError("假设不存在")
    from app.models.hypothesis import HypothesisAnalysis
    started_at = datetime.utcnow()
    analysis = HypothesisAnalysis(
        hypothesis_id=hypothesis_id,
        analysis_tier="deep",
        summary="analysis running",
        result_data={
            "status": "running",
            "started_at": started_at.isoformat(),
            "initiated_by": str(current_user.id),
        },
    )
    db.add(analysis)
    await db.commit()
    return success_response({
        "hypothesis_id": str(hypothesis_id),
        "analysis_id": str(analysis.id),
        "status": "running",
        "started_at": started_at.isoformat(),
    })


@router.post("/{hypothesis_id}/eliminate", response_model=ApiResponse[Dict[str, Any]], summary="淘汰假设")
async def eliminate_hypothesis(
    hypothesis_id: UUID,
    reason: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """淘汰假设（标记为 ELIMINATED）"""
    hypothesis = await db.get(Hypothesis, hypothesis_id)
    if not hypothesis:
        raise NotFoundError("假设不存在")
    hypothesis.status = HypothesisStatus.ELIMINATED
    hypothesis.analysis_result = {
        **(hypothesis.analysis_result or {}),
        "elimination_reason": reason,
    }
    await db.commit()
    return success_response({
        "hypothesis_id": str(hypothesis_id),
        "status": "eliminated",
        "reason": reason,
    })


@router.delete("/{hypothesis_id}", response_model=ApiResponse[Dict[str, Any]], summary="删除假设")
async def delete_hypothesis(
    hypothesis_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除假设（永久删除）"""
    hypothesis = await db.get(Hypothesis, hypothesis_id)
    if not hypothesis:
        raise NotFoundError("假设不存在")
    if current_user.role != UserRole.FOUNDER and hypothesis.created_by != current_user.id:
        raise ForbiddenError("无权删除此资源")
    await db.delete(hypothesis)
    await db.commit()
    return success_response({"id": str(hypothesis_id), "deleted": True})


@router.post("/auto-generate", response_model=ApiResponse[List[Dict[str, Any]]], summary="自动生成假设")
async def auto_generate_hypotheses(
    project_id: UUID = Body(..., embed=True, description="项目 ID"),
    max_hypotheses: int = Body(5, embed=True, description="最大假设数量"),
    context: dict = Body(None, embed=True, description="可选上下文数据"),
    use_llm: bool = Body(True, embed=True, description="是否启用 LLM 辅助生成（默认启用）"),
    mode: str = Body("hybrid", embed=True, description="生成模式: rule(仅规则)/llm(仅LLM)/hybrid(混合)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于前期分析结果自动生成研究假设

    系统提取并分析前面各模块产生的关键数据与结论，运用规则推理方法，
    自动生成科学合理的研究假设，包含假设描述、支持证据、预期验证方法等内容。

    数据源：
    - 差异表达分析结果
    - 通路富集结果
    - 分子设计结果
    - 治疗方案效果数据
    - 临床反馈数据

    可选功能：
    - use_llm=True: 启用 LLM 辅助生成更丰富的假设（需要 Agnes API 配置）
    - mode: rule(仅规则) / llm(仅 LLM) / hybrid(混合，默认)
    """
    from app.services.knowledge.hypothesis_generator import HypothesisGenerator
    generator = HypothesisGenerator(db)

    # 获取 LLM 客户端（如启用）
    llm_client = None
    if use_llm:
        try:
            from app.services.llm.client import get_llm_client_with_config
            llm_client, _ = await get_llm_client_with_config(db)
        except Exception as e:
            logger.warning(f"LLM 客户端获取失败，降级规则生成: {e}")

    hypotheses = await generator.generate(
        str(project_id), context, max_hypotheses,
        use_llm=use_llm, llm_client=llm_client, mode=mode,
    )
    return success_response(hypotheses)
