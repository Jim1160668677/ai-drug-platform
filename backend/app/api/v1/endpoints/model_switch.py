"""模型切换监控端点 — 切换日志查询 + 性能健康度 + 手动测试

满足需求：
- 保留完整的切换日志，记录切换时间、原因及模型性能指标
- 实现模型性能监控，定期评估并优化切换触发条件
"""
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.security import UserRole
from app.db.session import get_db
from app.models.model_switch_log import ModelSwitchLog, SwitchTriggerType
from app.models.user import User
from app.schemas.common import paged_response, success_response

router = APIRouter()


# ========== 切换日志查询 ==========

@router.get("/logs")
async def list_switch_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    from_model: Optional[str] = Query(None, description="按源模型筛选"),
    to_model: Optional[str] = Query(None, description="按目标模型筛选"),
    trigger_type: Optional[SwitchTriggerType] = Query(None, description="按触发类型筛选"),
    start_date: Optional[datetime] = Query(None, description="起始时间"),
    end_date: Optional[datetime] = Query(None, description="结束时间"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询模型切换日志（分页 + 多条件筛选）"""
    conditions = []
    if from_model:
        conditions.append(ModelSwitchLog.from_model == from_model)
    if to_model:
        conditions.append(ModelSwitchLog.to_model == to_model)
    if trigger_type:
        conditions.append(ModelSwitchLog.trigger_type == trigger_type)
    if start_date:
        conditions.append(ModelSwitchLog.created_at >= start_date)
    if end_date:
        conditions.append(ModelSwitchLog.created_at <= end_date)

    # 总数
    count_q = select(func.count(ModelSwitchLog.id))
    for cond in conditions:
        count_q = count_q.where(cond)
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询
    q = select(ModelSwitchLog).order_by(desc(ModelSwitchLog.created_at))
    for cond in conditions:
        q = q.where(cond)
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    logs = result.scalars().all()

    return paged_response(
        data=[
            {
                "id": str(log.id),
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "from_model": log.from_model,
                "to_model": log.to_model,
                "trigger_type": log.trigger_type.value if log.trigger_type else None,
                "reason": log.reason,
                "latency_ms": log.latency_ms,
                "content_length": log.content_length,
                "success_rate": log.success_rate,
                "http_status": log.http_status,
                "fallback_succeeded": log.fallback_succeeded,
                "fallback_latency_ms": log.fallback_latency_ms,
                "user_id": str(log.user_id) if log.user_id else None,
                "request_id": log.request_id,
                "performance_metrics": log.performance_metrics,
            }
            for log in logs
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


# ========== 性能健康度 ==========

@router.get("/health")
async def get_model_health(
    current_user: User = Depends(get_current_user),
):
    """获取所有模型的性能健康度总览

    返回滚动窗口指标：成功率、P95 延迟、健康/不健康模型列表。
    用于定期评估并优化切换触发条件。
    """
    from app.core.llm.performance import get_performance_monitor

    monitor = get_performance_monitor()
    return success_response(data=monitor.get_health_snapshot())


# ========== 切换统计摘要 ==========

@router.get("/stats")
async def get_switch_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取切换统计摘要（按模型/触发类型聚合）"""
    # 按触发类型统计
    trigger_q = (
        select(
            ModelSwitchLog.trigger_type,
            func.count(ModelSwitchLog.id).label("count"),
        )
        .group_by(ModelSwitchLog.trigger_type)
    )
    trigger_result = await db.execute(trigger_q)
    by_trigger = {
        row.trigger_type.value if row.trigger_type else "unknown": row.count
        for row in trigger_result
    }

    # 按源模型统计
    from_q = (
        select(
            ModelSwitchLog.from_model,
            func.count(ModelSwitchLog.id).label("count"),
        )
        .group_by(ModelSwitchLog.from_model)
    )
    from_result = await db.execute(from_q)
    by_from_model = {row.from_model: row.count for row in from_result}

    # 按目标模型统计
    to_q = (
        select(
            ModelSwitchLog.to_model,
            func.count(ModelSwitchLog.id).label("count"),
        )
        .group_by(ModelSwitchLog.to_model)
    )
    to_result = await db.execute(to_q)
    by_to_model = {row.to_model: row.count for row in to_result}

    # 降级成功率
    total_q = select(func.count(ModelSwitchLog.id))
    total = (await db.execute(total_q)).scalar() or 0
    success_q = select(func.count(ModelSwitchLog.id)).where(
        ModelSwitchLog.fallback_succeeded == True  # noqa: E712
    )
    success_count = (await db.execute(success_q)).scalar() or 0

    return success_response(data={
        "total_switches": total,
        "fallback_success_count": success_count,
        "fallback_success_rate": round(success_count / total, 4) if total > 0 else 0.0,
        "by_trigger_type": by_trigger,
        "by_from_model": by_from_model,
        "by_to_model": by_to_model,
    })


# ========== 手动测试降级（管理员） ==========

@router.post("/test")
async def test_fallback(
    message: str = "请简述 EGFR 在非小细胞肺癌中的作用。",
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """手动测试降级链路（仅管理员）

    使用主模型发送一条测试消息，观察是否触发降级。
    返回主模型响应 + 降级信息（如触发）。
    """
    from app.core.llm.fallback import FallbackLLMClient, QualityAssessor
    from app.core.llm.performance import get_performance_monitor
    from app.core.deps import get_llm_client, get_zhipu_client
    from app.core.config import settings

    monitor = get_performance_monitor()
    monitor.reset()  # 清空旧指标，确保测试结果干净

    if settings.is_mock:
        return success_response(data={
            "message": "Mock 模式下不执行真实降级测试",
            "mock_mode": True,
        })

    if not settings.ZHIPU_API_KEY:
        return success_response(data={
            "message": "智谱 API Key 未配置，无法测试降级",
            "configured": False,
        })

    primary = get_llm_client()
    fallback_client = get_zhipu_client()
    client = FallbackLLMClient(primary_client=primary, fallback_client=fallback_client)

    messages = [{"role": "user", "content": message}]
    response = await client.chat(messages, user_id=current_user.id)

    return success_response(data={
        "response_content": response.get("content", "")[:500],
        "response_model": response.get("model"),
        "usage": response.get("usage", {}),
        "health_snapshot": monitor.get_health_snapshot(),
        "duration_sec": response.get("duration_sec"),
    })
