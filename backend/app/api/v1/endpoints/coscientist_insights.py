"""Co-Scientist 洞察管理端点 — 嵌入式协作层的 API

设计来源：Nature Co-Scientist 论文 Meta-review 反馈propagate机制。
将推理产出的高排名假设转化为"AI 洞察"，主动推送到业务页面，
用户原地"采纳/忽略"，无需切换到独立页面。

8 个端点：
- GET    /insights                 洞察列表（支持 project/entity/status 过滤）
- GET    /insights/pending-count   待处理洞察数量（徽章）
- GET    /insights/{id}            洞察详情
- POST   /insights/{id}/accept     采纳洞察→创建实体
- POST   /insights/{id}/dismiss    忽略洞察
- POST   /insights/{id}/read       标记已读
- POST   /insights/bulk-read       批量标记已读
- POST   /quick-reason             就地轻推理（异步任务+轮询，复用Supervisor）
- GET    /suggested-goal           动态生成研究目标（基于项目数据）

注册方式：在 api/v1/router.py 中挂载到 /coscientist 前缀下。
"""
import logging
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response
from app.services.coscientist import insights as insights_service
from app.services.coscientist.auto_trigger import trigger_auto_reasoning

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== 请求/响应模型 ==========

class QuickReasonRequest(BaseModel):
    """就地轻推理请求"""
    project_id: Optional[str] = Field(None, description="项目 ID")
    entity_type: str = Field(..., description="实体类型：target/molecule/experiment/...")
    entity_id: str = Field(..., description="实体 ID")
    entity_name: Optional[str] = Field(None, description="实体名称")
    reason_type: str = Field(
        "auto",
        description="推理类型：auto(自动匹配)/drug_repurposing/mechanism/optimization/...",
    )
    extra_context: Optional[str] = Field(None, description="附加上下文")


class BulkReadRequest(BaseModel):
    """批量已读请求"""
    project_id: Optional[str] = None
    entity_type: Optional[str] = None


class AcceptResponse(BaseModel):
    insight_id: str
    success: bool
    message: str
    accepted_entity_id: Optional[str] = None


# ========== 洞察查询端点 ==========

@router.get("/insights", summary="洞察列表")
async def list_insights(
    project_id: Optional[UUID] = Query(None, description="按项目过滤"),
    entity_type: Optional[str] = Query(None, description="按实体类型过滤"),
    entity_id: Optional[str] = Query(None, description="按实体 ID 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤：pending/read/accepted/dismissed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询 AI 洞察列表（分页）

    支持按项目/实体/状态过滤。founder 可查所有用户，其他用户仅查自己的。
    用于业务页面顶部洞察提示条 + 浮窗洞察中心。
    """
    result = await insights_service.list_insights(
        db=db,
        user=user,
        project_id=str(project_id) if project_id else None,
        entity_type=entity_type,
        entity_id=entity_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return paged_response(
        data=result["items"],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
    )


@router.get("/insights/pending-count", summary="待处理洞察数量")
async def get_pending_count(
    project_id: Optional[UUID] = Query(None, description="按项目过滤"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取待处理（pending）洞察数量，用于前端徽章显示"""
    count = await insights_service.get_pending_count(
        db=db, user=user,
        project_id=str(project_id) if project_id else None,
    )
    return success_response({"pending_count": count})


@router.get("/insights/{insight_id}", summary="洞察详情")
async def get_insight(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取洞察详情"""
    from app.models.coscientist_insight import CoScientistInsight
    insight = await db.get(CoScientistInsight, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="洞察不存在")
    if insight.user_id != user.id and user.role != "founder":
        raise HTTPException(status_code=403, detail="无权访问")
    return success_response(insights_service._serialize_insight(insight))


# ========== 洞察操作端点 ==========

@router.post("/insights/{insight_id}/accept", summary="采纳洞察→创建实体")
async def accept_insight(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """采纳洞察，自动调用 promote 逻辑创建实体（靶点/分子/实验/治疗）

    根据 insight.suggested_action 决定创建哪种实体。
    采纳后洞察状态变为 accepted，记录 accepted_entity_id。
    """
    result = await insights_service.accept_insight(
        db=db, insight_id=insight_id, user=user,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return success_response(result)


@router.post("/insights/{insight_id}/dismiss", summary="忽略洞察")
async def dismiss_insight(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """忽略洞察（状态变为 dismissed）"""
    result = await insights_service.dismiss_insight(
        db=db, insight_id=insight_id, user=user,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return success_response(result)


@router.post("/insights/{insight_id}/read", summary="标记洞察已读")
async def mark_insight_read(
    insight_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """标记洞察已读（状态从 pending 变为 read）"""
    result = await insights_service.mark_insight_read(
        db=db, insight_id=insight_id, user=user,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return success_response(result)


@router.post("/insights/bulk-read", summary="批量标记已读")
async def bulk_mark_read(
    payload: BulkReadRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量标记洞察已读（用户查看某页面后清空徽章）"""
    count = await insights_service.bulk_mark_read(
        db=db, user=user,
        project_id=payload.project_id,
        entity_type=payload.entity_type,
    )
    return success_response({"marked_count": count})


# ========== 就地轻推理端点（异步任务+轮询） ==========

@router.post("/quick-reason", summary="就地轻推理（异步任务）")
async def quick_reason(
    payload: QuickReasonRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """各业务页面"原地推理"入口 — 异步任务+轮询模式

    复用完整多智能体辩论（保持论文质量），但后台异步执行：
    1. 根据 entity_type + reason_type 映射到 trigger_event
    2. 调用 trigger_auto_reasoning 创建后台运行
    3. 前端通过 /runs/{run_id}/progress 轮询进度
    4. 完成后洞察自动推送到对应页面

    与独立创建运行的区别：
    - 自动注入实体上下文（无需用户手写研究目标）
    - 标记 auto_triggered=True，完成后自动提取洞察
    - 前端通过浮窗查看进度，不跳转页面
    """
    # entity_type + reason_type → trigger_event 映射
    _TYPE_TO_TRIGGER = {
        ("target", "auto"): "targets_discovered",
        ("target", "drug_repurposing"): "targets_discovered",
        ("target", "mechanism"): "targets_discovered",
        ("molecule", "auto"): "molecule_generated",
        ("molecule", "optimization"): "molecule_generated",
        ("experiment", "auto"): "experiment_completed",
        ("experiment", "verification"): "experiment_completed",
        ("experiment", "failure_analysis"): "experiment_failed",
        ("treatment", "auto"): "treatment_generated",
        ("treatment", "synergy"): "treatment_generated",
        ("dataset", "auto"): "data_parsed",
        ("dataset", "research_direction"): "data_parsed",
        ("genome", "auto"): "genome_interpreted",
        ("assessment", "auto"): "genome_interpreted",
        ("assessment", "personalized_therapy"): "genome_interpreted",
        ("docking_job", "auto"): "docking_completed",
        ("docking_job", "binding_mode"): "docking_completed",
        ("structure", "auto"): "structure_predicted",
        ("structure", "allosteric_site"): "structure_predicted",
        ("benchmark", "auto"): "benchmark_completed",
        ("benchmark", "gap_analysis"): "benchmark_completed",
        ("screening", "auto"): "screening_completed",
        ("screening", "amplifier_mechanism"): "screening_completed",
        ("vaccine", "auto"): "vaccine_designed",
        ("vaccine", "immunogenicity"): "vaccine_designed",
    }

    trigger_event = _TYPE_TO_TRIGGER.get(
        (payload.entity_type, payload.reason_type),
        _TYPE_TO_TRIGGER.get((payload.entity_type, "auto")),
    )

    if not trigger_event:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的推理类型：entity_type={payload.entity_type}, reason_type={payload.reason_type}",
        )

    run_id = await trigger_auto_reasoning(
        db=db,
        user=user,
        trigger_event=trigger_event,
        project_id=payload.project_id,
        entity_id=payload.entity_id,
        entity_name=payload.entity_name,
        extra_evidence=payload.extra_context,
    )

    if not run_id:
        raise HTTPException(status_code=500, detail="触发推理失败")

    return success_response({
        "run_id": run_id,
        "trigger_event": trigger_event,
        "message": "推理已启动，可通过 /runs/{run_id}/progress 轮询进度",
        "poll_endpoint": f"/api/v1/coscientist/runs/{run_id}/progress",
    })


# ========== 动态研究目标生成端点 ==========

@router.get("/suggested-goal", summary="动态生成研究目标")
async def get_suggested_goal(
    project_id: Optional[UUID] = Query(None, description="项目 ID"),
    page: Optional[str] = Query(None, description="当前页面（workbench/targets/molecules/...）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """基于项目实际数据动态生成研究目标

    替代前端静态映射表 buildSuggestedGoal。
    复用 EvidenceCollector 收集的数据，结合当前页面上下文，
    生成更精准的研究目标建议。
    """
    from app.services.intelligence.evidence_collector import EvidenceCollector

    evidence = ""
    if project_id:
        try:
            evidence = await EvidenceCollector().collect_project_evidence(str(project_id))
        except Exception as e:
            logger.warning("收集项目证据失败: %s", e)

    # 页面上下文 → 研究方向提示
    _PAGE_HINTS = {
        "targets": "聚焦靶点发现与验证，重点关注新靶点的成药性评估与老药重定位潜力",
        "molecules": "聚焦分子设计优化，重点关注先导化合物的类药性改善与合成可行性",
        "experiments": "聚焦实验验证闭环，重点关注假设的实验验证设计与结果解读",
        "treatments": "聚焦治疗方案优化，重点关注组合疗法与协同效应挖掘",
        "data": "聚焦数据驱动发现，重点关注多组学整合分析与生物标志物识别",
        "genome": "聚焦个性化医疗，重点关注药物基因组学与个性化用药策略",
        "docking": "聚焦分子对接分析，重点关注结合模式优化与关键相互作用",
        "structures": "聚焦结构生物学，重点关注别构位点识别与可成药口袋评估",
        "benchmarks": "聚焦性能优化，重点关注混合架构优势与瓶颈识别",
        "screening": "聚焦高通量筛选，重点关注条件放大器机制与疫苗设计",
    }

    page_hint = _PAGE_HINTS.get(page or "", "")

    # 基于证据长度和页面生成目标
    if evidence and len(evidence) > 100:
        goal = (
            f"{page_hint}。基于项目已有数据（靶点 {evidence.count('靶点')} 项、"
            f"分子 {evidence.count('分子')} 项、实验 {evidence.count('实验')} 项），"
            "提出3个可验证的科学假设，并评估其可行性。"
        ) if page_hint else (
            "基于项目前期所有分析数据，整合多源证据，"
            "推理最有价值的研究方向，提出3个可验证的科学假设。"
        )
    else:
        goal = page_hint or "请描述您的研究目标，Co-Scientist 将基于多智能体辩论为您生成并优化科学假设。"

    return success_response({
        "goal": goal,
        "page": page,
        "has_evidence": bool(evidence),
        "evidence_length": len(evidence),
        "suggested_cases": _suggest_cases(page, evidence),
    })


def _suggest_cases(page: Optional[str], evidence: str) -> List[Dict[str, str]]:
    """根据页面和证据建议合适的案例模板"""
    suggestions = []
    if page == "targets":
        suggestions.append({"case_type": "aml", "reason": "靶点发现场景，适合药物重定位推理"})
    elif page == "data":
        suggestions.append({"case_type": "liver_fibrosis", "reason": "组学数据分析场景，适合表观遗传靶点发现"})
    elif page == "experiments":
        suggestions.append({"case_type": "custom", "reason": "实验验证场景，建议自定义研究目标"})
    else:
        suggestions.append({"case_type": "custom", "reason": "通用场景"})
    return suggestions


__all__ = ["router"]
