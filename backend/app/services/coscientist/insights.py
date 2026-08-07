"""Co-Scientist 洞察管理服务 — 从推理运行提取洞察 + 查询/采纳/忽略

设计来源：Nature Co-Scientist 论文 Meta-review agent 的反馈propagate机制。
论文强调 Meta-review 会把反馈传播到所有agent；对应到产品层，
推理产出的高排名假设需转化为"AI 洞察"主动推送到业务页面。

核心职责：
1. extract_insights_from_run: 运行完成后，从高排名假设中提取洞察
2. list_insights: 按项目/实体/状态查询洞察
3. accept_insight: 采纳洞察→调用 promote 端点创建实体
4. dismiss_insight: 忽略洞察
5. mark_read: 标记已读
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coscientist_insight import (
    CoScientistInsight,
    EntityType,
    InsightStatus,
    InsightType,
    TriggerEvent,
    TRIGGER_TO_INSIGHT_TYPE,
)
from app.models.coscientist_run import CoScientistRun
from app.models.hypothesis import Hypothesis
from app.models.user import User

logger = logging.getLogger(__name__)


# ========== 1. 从运行结果提取洞察 ==========

async def extract_insights_from_run(
    db: AsyncSession,
    run_id: str,
    user: User,
    trigger_event: str,
    entity_id: Optional[str],
    entity_name: Optional[str],
    result: Any,
) -> List[CoScientistInsight]:
    """运行完成后，从高排名假设中提取 AI 洞察

    Args:
        db: 数据库会话
        run_id: 运行 ID
        user: 用户
        trigger_event: 触发事件
        entity_id: 关联实体 ID
        entity_name: 关联实体名称
        result: Supervisor 运行结果（含 all_hypotheses/final_rankings/meta_review）

    Returns:
        创建的洞察列表
    """
    insight_type = TRIGGER_TO_INSIGHT_TYPE.get(trigger_event, InsightType.RESEARCH_DIRECTION)
    entity_type_map = {
        TriggerEvent.DATA_PARSED: EntityType.DATASET,
        TriggerEvent.TARGETS_DISCOVERED: EntityType.TARGET,
        TriggerEvent.EXPERIMENT_COMPLETED: EntityType.EXPERIMENT,
        TriggerEvent.EXPERIMENT_FAILED: EntityType.EXPERIMENT,
        TriggerEvent.TREATMENT_GENERATED: EntityType.TREATMENT,
        TriggerEvent.MOLECULE_GENERATED: EntityType.MOLECULE,
        TriggerEvent.GENOME_INTERPRETED: EntityType.ASSESSMENT,
        TriggerEvent.DOCKING_COMPLETED: EntityType.DOCKING_JOB,
        TriggerEvent.STRUCTURE_PREDICTED: EntityType.STRUCTURE,
        TriggerEvent.BENCHMARK_COMPLETED: EntityType.BENCHMARK,
        TriggerEvent.SCREENING_COMPLETED: EntityType.SCREENING,
        TriggerEvent.VACCINE_DESIGNED: EntityType.VACCINE,
    }
    entity_type = entity_type_map.get(trigger_event, EntityType.PROJECT)

    # 获取运行记录（取 project_id）
    run = await db.get(CoScientistRun, uuid.UUID(run_id))
    project_id = run.project_id if run else None

    # 从假设中提取 Top N（按 Elo 排序）
    hypotheses = []
    if hasattr(result, "all_hypotheses") and result.all_hypotheses:
        sorted_hyps = sorted(
            result.all_hypotheses,
            key=lambda h: float(h.get("elo_score", 1000.0)),
            reverse=True,
        )
        hypotheses = sorted_hyps[:3]  # 取 Top 3

    if not hypotheses:
        # 若无假设，从 meta_review 生成单条洞察
        meta_text = ""
        if hasattr(result, "meta_review") and result.meta_review:
            meta_text = result.meta_review if isinstance(result.meta_review, str) else str(result.meta_review)
        if meta_text:
            insight = CoScientistInsight(
                user_id=user.id,
                project_id=project_id,
                source_run_id=uuid.UUID(run_id),
                trigger_event=trigger_event,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                insight_type=insight_type,
                title=f"AI 综合洞察：{entity_name or '项目'}",
                summary=meta_text[:1000],
                details={"meta_review": meta_text, "source": "meta_review_only"},
                status=InsightStatus.PENDING,
            )
            db.add(insight)
            await db.commit()
            await db.refresh(insight)
            return [insight]
        return []

    # 为每个 Top 假设创建洞察
    insights: List[CoScientistInsight] = []
    for idx, hyp in enumerate(hypotheses, 1):
        elo = float(hyp.get("elo_score", 1000.0))
        confidence = max(0.1, min(0.99, 0.5 + (elo - 1000.0) / 2000.0))

        # 洞察标题
        name = hyp.get("name", f"假设 {idx}")
        title = f"AI 洞察 {idx}：{name[:80]}"

        # 洞察摘要
        desc = hyp.get("description", "")
        mech = hyp.get("mechanism", "")
        summary_parts = []
        if desc:
            summary_parts.append(desc[:300])
        if mech:
            summary_parts.append(f"机制：{mech[:200]}")
        summary = "\n".join(summary_parts) or "推理产出的高排名假设"

        # 建议 promote 类型
        suggested_action, action_payload = _infer_suggested_action(
            insight_type, hyp, entity_id
        )

        insight = CoScientistInsight(
            user_id=user.id,
            project_id=project_id,
            source_run_id=uuid.UUID(run_id),
            trigger_event=trigger_event,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            insight_type=insight_type,
            title=title,
            summary=summary,
            details={
                "hypothesis_id": hyp.get("id"),
                "hypothesis_name": name,
                "elo_score": elo,
                "mechanism": mech,
                "strategy": hyp.get("strategy"),
                "target_list": hyp.get("target_list", []),
                "rank": idx,
            },
            suggested_action=suggested_action,
            action_payload=action_payload,
            status=InsightStatus.PENDING,
            confidence_score=confidence,
        )
        db.add(insight)
        insights.append(insight)

    await db.commit()
    for ins in insights:
        await db.refresh(ins)

    logger.info(
        "[insights] 从运行 %s 提取 %d 个洞察（事件 %s）",
        run_id, len(insights), trigger_event,
    )
    return insights


def _infer_suggested_action(
    insight_type: str,
    hypothesis: Dict[str, Any],
    entity_id: Optional[str],
) -> tuple[Optional[str], Optional[Dict]]:
    """根据洞察类型推断建议的 promote 操作

    Returns:
        (suggested_action, action_payload)
    """
    target_list = hypothesis.get("target_list") or []

    if insight_type == InsightType.DRUG_REPURPOSING and target_list:
        first = target_list[0]
        gene = first if isinstance(first, str) else (first.get("gene_symbol") or first.get("name"))
        if gene:
            return "promote_target", {"gene_symbol": gene}

    elif insight_type == InsightType.DRUGLIKENESS_OPT:
        return None, None  # 优化建议，不直接 promote

    elif insight_type == InsightType.COMBINATION_THERAPY:
        return "promote_treatment", {"therapy_type": "targeted_therapy"}

    elif insight_type == InsightType.HYPOTHESIS_VERIFICATION:
        return "promote_experiment", {"exp_type": "cytotoxicity"}

    elif insight_type == InsightType.PERSONALIZED_THERAPY:
        return "promote_treatment", {"therapy_type": "targeted_therapy"}

    return None, None


# ========== 2. 查询洞察 ==========

async def list_insights(
    db: AsyncSession,
    user: User,
    project_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """查询洞察列表（分页）

    支持按项目/实体/状态过滤。founder 可查所有，其他用户仅查自己的。
    """
    conditions = []
    if user.role != "founder":
        conditions.append(CoScientistInsight.user_id == user.id)

    if project_id:
        conditions.append(CoScientistInsight.project_id == uuid.UUID(project_id))
    if entity_type:
        conditions.append(CoScientistInsight.entity_type == entity_type)
    if entity_id:
        conditions.append(CoScientistInsight.entity_id == entity_id)
    if status:
        conditions.append(CoScientistInsight.status == status)

    where_clause = and_(*conditions) if conditions else None

    # 总数
    count_q = select(func.count()).select_from(CoScientistInsight)
    if where_clause is not None:
        count_q = count_q.where(where_clause)
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询
    q = select(CoScientistInsight).order_by(
        CoScientistInsight.created_at.desc()
    )
    if where_clause is not None:
        q = q.where(where_clause)
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    items = [_serialize_insight(i) for i in result.scalars().all()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_pending_count(
    db: AsyncSession,
    user: User,
    project_id: Optional[str] = None,
) -> int:
    """获取待处理洞察数量（用于前端徽章）"""
    conditions = [
        CoScientistInsight.status == InsightStatus.PENDING,
    ]
    if user.role != "founder":
        conditions.append(CoScientistInsight.user_id == user.id)
    if project_id:
        conditions.append(CoScientistInsight.project_id == uuid.UUID(project_id))

    q = select(func.count()).select_from(CoScientistInsight).where(and_(*conditions))
    return (await db.execute(q)).scalar() or 0


# ========== 3. 采纳洞察 ==========

async def accept_insight(
    db: AsyncSession,
    insight_id: uuid.UUID,
    user: User,
) -> Dict[str, Any]:
    """采纳洞察→调用 promote 端点创建实体

    根据 insight.suggested_action 调用对应的 promote 逻辑。
    """
    insight = await db.get(CoScientistInsight, insight_id)
    if not insight:
        return {"error": "洞察不存在"}
    if insight.user_id != user.id and user.role != "founder":
        return {"error": "无权操作"}

    if insight.status == InsightStatus.ACCEPTED:
        return {"error": "洞察已采纳", "accepted_entity_id": insight.accepted_entity_id}

    action = insight.suggested_action
    payload = insight.action_payload or {}
    result: Dict[str, Any] = {"insight_id": str(insight_id), "action": action}

    try:
        if action == "promote_target" and insight.source_run_id:
            # 调用 promote-target 逻辑
            from app.api.v1.endpoints.coscientist import _get_hypothesis_or_404
            from app.models.target import Target
            from app.models.hypothesis import Hypothesis

            # 从洞察详情取 hypothesis_id
            hyp_id = (insight.details or {}).get("hypothesis_id")
            if hyp_id:
                hyp = await db.get(Hypothesis, uuid.UUID(str(hyp_id)))
                if hyp and hyp.project_id:
                    gene = payload.get("gene_symbol", "")
                    confidence = insight.confidence_score or 0.6
                    target = Target(
                        project_id=hyp.project_id,
                        gene_symbol=str(gene)[:50],
                        gene_name=f"{gene} (AI洞察来源)",
                        confidence_score=confidence,
                        source="coscientist_insight",
                    )
                    db.add(target)
                    await db.flush()
                    result["target_id"] = str(target.id)
                    result["gene_symbol"] = gene
                    insight.accepted_entity_id = str(target.id)

        elif action == "promote_treatment" and insight.source_run_id:
            from app.models.treatment import Treatment
            from app.models.hypothesis import Hypothesis

            hyp_id = (insight.details or {}).get("hypothesis_id")
            if hyp_id:
                hyp = await db.get(Hypothesis, uuid.UUID(str(hyp_id)))
                if hyp and hyp.project_id:
                    treatment = Treatment(
                        project_id=hyp.project_id,
                        name=f"AI洞察方案-{insight.insight_type[:20]}",
                        therapy_type=payload.get("therapy_type", "targeted_therapy"),
                        hypothesis_id=hyp.id,
                        notes=insight.summary[:500],
                    )
                    db.add(treatment)
                    await db.flush()
                    result["treatment_id"] = str(treatment.id)
                    insight.accepted_entity_id = str(treatment.id)

        elif action == "promote_experiment" and insight.source_run_id:
            from app.models.experiment import Experiment, ExperimentStatus
            from app.models.hypothesis import Hypothesis

            hyp_id = (insight.details or {}).get("hypothesis_id")
            if hyp_id:
                hyp = await db.get(Hypothesis, uuid.UUID(str(hyp_id)))
                if hyp and hyp.project_id:
                    exp = Experiment(
                        project_id=hyp.project_id,
                        name=f"AI洞察实验-{insight.insight_type[:20]}",
                        exp_type=payload.get("exp_type", "cytotoxicity"),
                        status=ExperimentStatus.PLANNED,
                        hypothesis_id=hyp.id,
                        config={"source": "coscientist_insight", "insight_id": str(insight_id)},
                        notes=insight.summary[:500],
                    )
                    db.add(exp)
                    await db.flush()
                    result["experiment_id"] = str(exp.id)
                    insight.accepted_entity_id = str(exp.id)

        # 标记已采纳
        insight.status = InsightStatus.ACCEPTED
        insight.accepted_at = datetime.now(timezone.utc)
        await db.commit()

        result["success"] = True
        result["message"] = "洞察已采纳并创建实体"
        return result

    except Exception as e:
        logger.exception("[insights] 采纳洞察 %s 失败: %s", insight_id, e)
        await db.rollback()
        return {"error": f"采纳失败: {str(e)}"}


# ========== 4. 忽略/已读 ==========

async def dismiss_insight(
    db: AsyncSession,
    insight_id: uuid.UUID,
    user: User,
) -> Dict[str, Any]:
    """忽略洞察"""
    insight = await db.get(CoScientistInsight, insight_id)
    if not insight:
        return {"error": "洞察不存在"}
    if insight.user_id != user.id and user.role != "founder":
        return {"error": "无权操作"}

    insight.status = InsightStatus.DISMISSED
    await db.commit()
    return {"success": True, "message": "洞察已忽略"}


async def mark_insight_read(
    db: AsyncSession,
    insight_id: uuid.UUID,
    user: User,
) -> Dict[str, Any]:
    """标记洞察已读"""
    insight = await db.get(CoScientistInsight, insight_id)
    if not insight:
        return {"error": "洞察不存在"}
    if insight.user_id != user.id and user.role != "founder":
        return {"error": "无权操作"}

    if insight.status == InsightStatus.PENDING:
        insight.status = InsightStatus.READ
        await db.commit()
    return {"success": True}


async def bulk_mark_read(
    db: AsyncSession,
    user: User,
    project_id: Optional[str] = None,
    entity_type: Optional[str] = None,
) -> int:
    """批量标记已读（用于用户查看某页面后清空徽章）"""
    conditions = [
        CoScientistInsight.user_id == user.id,
        CoScientistInsight.status == InsightStatus.PENDING,
    ]
    if project_id:
        conditions.append(CoScientistInsight.project_id == uuid.UUID(project_id))
    if entity_type:
        conditions.append(CoScientistInsight.entity_type == entity_type)

    stmt = (
        update(CoScientistInsight)
        .where(and_(*conditions))
        .values(status=InsightStatus.READ)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


# ========== 序列化 ==========

def _serialize_insight(i: CoScientistInsight) -> Dict[str, Any]:
    return {
        "id": str(i.id),
        "user_id": str(i.user_id),
        "project_id": str(i.project_id) if i.project_id else None,
        "source_run_id": str(i.source_run_id) if i.source_run_id else None,
        "trigger_event": i.trigger_event,
        "entity_type": i.entity_type,
        "entity_id": i.entity_id,
        "entity_name": i.entity_name,
        "insight_type": i.insight_type,
        "title": i.title,
        "summary": i.summary,
        "details": i.details,
        "suggested_action": i.suggested_action,
        "action_payload": i.action_payload,
        "status": i.status,
        "accepted_entity_id": i.accepted_entity_id,
        "accepted_at": i.accepted_at.isoformat() if i.accepted_at else None,
        "confidence_score": i.confidence_score,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


__all__ = [
    "extract_insights_from_run",
    "list_insights",
    "get_pending_count",
    "accept_insight",
    "dismiss_insight",
    "mark_insight_read",
    "bulk_mark_read",
]
