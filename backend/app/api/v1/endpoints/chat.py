"""自然语言问答端点 — 分级分析路由"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_llm_client_with_config, get_active_llm_config
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.api.v1.schemas import ChatRequest, ChatResponse, StandardResponse
from app.schemas.common import ApiResponse, success_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=ChatResponse, summary="自然语言问答")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自然语言问答 — 复现 Sid 团队做法：研究者提问，AI 自动执行分析并返回报告

    分级路由：
    - fast_screen: 快速筛查 (<$5/<5min) — 统计分析+规则引擎+小模型
    - deep_insight: 深度洞察 (<$20/<30min) — LLM+RAG+网络分析+分子建模
    """
    from app.services.llm.orchestrator import LLMOrchestrator
    llm_config = await get_active_llm_config(db)
    llm_client = await get_llm_client_with_config(db)
    orchestrator = LLMOrchestrator(db, llm_client, llm_config=llm_config)
    result = await orchestrator.route(
        message=payload.message,
        project_id=payload.project_id,
        tier=payload.tier,
        user=current_user,
    )

    # 写入审计日志，供 /history 查询（action=chat, entity=chat_session）
    try:
        log = AuditLog(
            actor=str(current_user.id),
            role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            action="chat",
            entity="chat_session",
            entity_id=payload.project_id,
            detail=payload.message[:500],
            after_val={
                "tier": result.get("tier"),
                "model": result.get("model"),
                "cost_usd": result.get("cost_usd"),
                "duration_sec": result.get("duration_sec"),
            },
        )
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning("聊天审计日志写入失败（不影响主流程）: %s", e)
        await db.rollback()

    return ChatResponse(**result)


@router.post("/analyze", response_model=StandardResponse, summary="自然语言驱动数据分析")
async def analyze_with_nl(
    message: str,
    project_id: str,
    tier: str = "deep_insight",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复现 Sid 团队核心能力：自然语言→文献检索→提出假设→设计分析框架→运行分析→返回报告

    报告包含：结论、交互式图表、AI 生成的分析代码（Python）
    """
    from app.services.llm.orchestrator import LLMOrchestrator
    llm_config = await get_active_llm_config(db)
    llm_client = await get_llm_client_with_config(db)
    orchestrator = LLMOrchestrator(db, llm_client, llm_config=llm_config)
    result = await orchestrator.full_analysis(
        message=message,
        project_id=project_id,
        tier=tier,
        user=current_user,
    )
    return StandardResponse(message="分析完成", data=result)


@router.get("/tiers", response_model=StandardResponse, summary="分析层级说明")
async def list_tiers(
    current_user: User = Depends(get_current_user),
):
    """分级分析策略说明"""
    from app.core.config import settings
    return success_response({
        "tiers": [
            {
                "name": "fast_screen",
                "label": "快速筛查",
                "tech_stack": "统计分析 + 规则引擎 + 小模型",
                "use_case": "靶点初筛、批量数据扫描",
                "max_cost_usd": settings.FAST_SCREEN_MAX_COST_USD,
                "max_duration_sec": settings.FAST_SCREEN_MAX_DURATION_SEC,
            },
            {
                "name": "deep_insight",
                "label": "深度洞察",
                "tech_stack": "LLM + RAG + 网络分析 + 分子建模",
                "use_case": "候选靶点深度分析、分子设计",
                "max_cost_usd": settings.DEEP_INSIGHT_MAX_COST_USD,
                "max_duration_sec": settings.DEEP_INSIGHT_MAX_DURATION_SEC,
            },
        ]
    })


@router.get("/history", response_model=ApiResponse[Dict[str, Any]], summary="聊天历史")
async def get_history(
    project_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取聊天历史记录

    数据来源：AuditLog 中 action='chat' 且 actor=当前用户的记录。
    每个 chat 调用写入审计后，此处可查询历史。
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.action == "chat")
        .where(AuditLog.actor == str(current_user.id))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    if project_id:
        stmt = stmt.where(AuditLog.entity_id == project_id)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    history = [
        {
            "id": str(log.id),
            "message": log.detail or "",
            "project_id": log.entity_id,
            "tier": (log.after_val or {}).get("tier"),
            "model": (log.after_val or {}).get("model"),
            "cost_usd": (log.after_val or {}).get("cost_usd"),
            "duration_sec": (log.after_val or {}).get("duration_sec"),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return success_response({
        "history": history,
        "total": len(history),
        "limit": limit,
    })


@router.get("/cost-summary", response_model=ApiResponse[Dict[str, Any]], summary="成本汇总")
async def get_cost_summary(current_user: User = Depends(get_current_user)):
    """获取 LLM 成本汇总（当日）"""
    from app.services.llm.cost_tracker import get_cost_tracker
    tracker = get_cost_tracker()
    if tracker:
        summary = tracker.today_summary()
    else:
        summary = {"total_cost_usd": 0, "by_model": {}, "request_count": 0}
    return success_response(summary)
