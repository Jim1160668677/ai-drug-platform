"""疗效监测端点 — 疗效结局 / 不良事件 / RECIST / KM 生存分析 / 治疗方案优化

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/优化器服务层.md
           app/services/optimizer/{efficacy_monitor,treatment_planner,dynamic_adjuster}.py

封装疗效监测与治疗方案调整能力：
- EfficacyMonitor：疗效检查 / 结局记录 / 不良事件 / 全局汇总 / RECIST 1.1 / Kaplan-Meier
- TreatmentPlanner：多疗法组合优化（规则 / RL 框架）
- DynamicAdjuster：动态调整 / Q-learning 更新

所有端点遵循统一响应信封（success_response）与统一异常体系（AppException 子类）。
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.exceptions import NotFoundError, UpstreamError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import success_response

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 请求体模型 ==========


class RecordOutcomeRequest(BaseModel):
    """记录疗效结局请求体"""

    treatment_id: UUID = Field(..., description="治疗方案 ID")
    outcome: Dict[str, Any] = Field(
        ...,
        description="结局数据 {response, lesions, time, event}",
    )


class RecordAdverseEventRequest(BaseModel):
    """记录不良事件请求体"""

    treatment_id: UUID = Field(..., description="治疗方案 ID")
    event: Dict[str, Any] = Field(
        ...,
        description="事件数据 {symptom, severity, description}",
    )


class KaplanMeierRequest(BaseModel):
    """Kaplan-Meier 生存分析请求体"""

    events: List[Dict[str, Any]] = Field(
        ...,
        description="事件列表 [{time, event(1=死亡/进展, 0=删失)}, ...]",
    )


class OptimizeRequest(BaseModel):
    """治疗方案组合优化请求体"""

    project_id: UUID = Field(..., description="项目 ID")


class QUpdateRequest(BaseModel):
    """Q-learning 更新请求体"""

    state: str = Field(..., description="当前状态")
    action: str = Field(..., description="采取的动作")
    reward: float = Field(..., description="获得的奖励")
    alpha: float = Field(0.1, gt=0, le=1, description="学习率，默认 0.1")
    gamma: float = Field(0.9, ge=0, lt=1, description="折扣因子，默认 0.9")


class RecistClassifyRequest(BaseModel):
    """RECIST 1.1 分类请求体"""

    lesions: List[Dict[str, Any]] = Field(
        ...,
        description='病灶测量值列表 [{baseline_mm, current_mm}, ...]',
    )


# ========== 端点：疗效结局 / 不良事件 ==========


@router.post("/outcomes", summary="记录疗效结局")
async def record_outcome(
    payload: RecordOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录疗效结局

    若未提供 response 但提供了 lesions，将自动调用 RECIST 1.1 分类。
    """
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        monitor = EfficacyMonitor(db)
        result = await monitor.record_outcome(
            treatment_id=payload.treatment_id,
            outcome=payload.outcome,
        )
    except Exception as e:
        logger.error("记录疗效结局失败: %s", e, exc_info=True)
        raise UpstreamError(
            "记录疗效结局失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    return success_response(data=result)


@router.post("/adverse-events", summary="记录不良事件")
async def record_adverse_event(
    payload: RecordAdverseEventRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录不良事件并自动 CTCAE v5.0 分级（1-5 级）"""
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        monitor = EfficacyMonitor(db)
        result = await monitor.record_adverse_event(
            treatment_id=payload.treatment_id,
            event=payload.event,
        )
    except Exception as e:
        logger.error("记录不良事件失败: %s", e, exc_info=True)
        raise UpstreamError(
            "记录不良事件失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    return success_response(data=result)


@router.get("/summary", summary="疗效汇总")
async def efficacy_summary(
    treatment_id: UUID = Query(..., description="治疗方案 ID（必填）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询某治疗方案的疗效汇总（趋势 / 不良事件 / 推荐）"""
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        monitor = EfficacyMonitor(db)
        result = await monitor.check(treatment_id)
    except Exception as e:
        logger.error("疗效汇总失败: %s", e, exc_info=True)
        raise UpstreamError(
            "疗效汇总失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    if result.get("error"):
        raise NotFoundError(
            result["error"],
            details={"treatment_id": str(treatment_id)},
        )

    return success_response(data=result)


@router.get("/global-summary", summary="全局疗效汇总")
async def global_summary(
    project_id: Optional[UUID] = Query(
        None, description="按项目 ID 过滤（可选）"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """全局疗效汇总（ORR / DCR / AE 分级分布）"""
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        monitor = EfficacyMonitor(db)
        result = await monitor.global_summary(project_id=project_id)
    except Exception as e:
        logger.error("全局疗效汇总失败: %s", e, exc_info=True)
        raise UpstreamError(
            "全局疗效汇总失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    return success_response(data=result)

# ========== 端点：Kaplan-Meier / RECIST / 优化 / Q-learning ==========


@router.post("/kaplan-meier", summary="Kaplan-Meier 生存分析")
async def kaplan_meier(
    payload: KaplanMeierRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kaplan-Meier 生存估计

    输入事件列表 [{time, event(1=死亡/进展, 0=删失)}, ...]，
    返回生存曲线、中位生存期、总样本数与事件数。
    """
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        # _kaplan_meier 是同步方法，但需要实例化 monitor（与 db 解耦）
        monitor = EfficacyMonitor(db)
        result = monitor._kaplan_meier(payload.events)
    except Exception as e:
        logger.error("Kaplan-Meier 分析失败: %s", e, exc_info=True)
        raise UpstreamError(
            "Kaplan-Meier 分析失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    return success_response(data=result)


@router.post("/treatment-optimization/optimize", summary="治疗方案组合优化")
async def optimize_treatment(
    payload: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """多疗法组合优化（P3 强化学习 / 当前规则评分）

    基于证据等级 + 药物类药性搜索最优疗法组合，
    PyTorch 可用时切换为 RL 框架（当前降级为规则评分）。

    权限：仅 FOUNDER / CHIEF_RESEARCHER 可调用。
    """
    from app.services.optimizer.treatment_planner import TreatmentPlanner

    try:
        planner = TreatmentPlanner(db)
        result = await planner.optimize(payload.project_id)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("治疗方案优化失败: %s", e, exc_info=True)
        raise UpstreamError(
            "治疗方案优化失败（内部错误，详见日志）",
            service="treatment_planner",
        )

    return success_response(data=result)


@router.post("/treatment-optimization/q-update", summary="Q-learning Q 值更新")
async def q_update(
    payload: QUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """Q-learning Q 值更新

    Q(s,a) <- Q(s,a) + α [r + γ max_a' Q(s',a') - Q(s,a)]

    简化实现：无下一状态转移信息时，TD target = reward。
    返回更新后的 Q 值与完整 Q 表。
    """
    from app.services.optimizer.dynamic_adjuster import DynamicAdjuster

    try:
        adjuster = DynamicAdjuster()
        # DynamicAdjuster._q_update 修改 self._q_table 并返回 None
        adjuster._q_update(
            state=payload.state,
            action=payload.action,
            reward=payload.reward,
            alpha=payload.alpha,
            gamma=payload.gamma,
        )
        key = f"{payload.state}:{payload.action}"
        updated_q = adjuster._q_table.get(key, 0.0)
    except Exception as e:
        logger.error("Q-learning 更新失败: %s", e, exc_info=True)
        raise UpstreamError(
            "Q-learning 更新失败（内部错误，详见日志）",
            service="dynamic_adjuster",
        )

    return success_response(
        data={
            "state": payload.state,
            "action": payload.action,
            "reward": payload.reward,
            "alpha": payload.alpha,
            "gamma": payload.gamma,
            "updated_q_value": updated_q,
            "q_table_size": len(adjuster._q_table),
            "q_table": dict(adjuster._q_table),
        }
    )


@router.post("/recist-classify", summary="RECIST 1.1 响应分类")
async def recist_classify(
    payload: RecistClassifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """RECIST 1.1 响应分类

    输入目标病灶测量值 [{baseline_mm, current_mm}, ...]，
    返回 CR / PR / SD / PD 分类。

    - CR（完全缓解）：所有病灶消失
    - PR（部分缓解）：直径总和缩小 >= 30%
    - PD（进展）：直径总和增大 >= 20%
    - SD（稳定）：介于 PR 与 PD 之间
    """
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor

    try:
        monitor = EfficacyMonitor(db)
        classification = monitor._recist_classify(payload.lesions)
    except Exception as e:
        logger.error("RECIST 分类失败: %s", e, exc_info=True)
        raise UpstreamError(
            "RECIST 分类失败（内部错误，详见日志）",
            service="efficacy_monitor",
        )

    return success_response(
        data={
            "classification": classification,
            "lesions_count": len(payload.lesions),
            "lesions": payload.lesions,
        }
    )