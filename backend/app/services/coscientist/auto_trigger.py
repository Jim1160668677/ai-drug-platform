"""Co-Scientist 自动推理触发服务 — 业务事件驱动的自动化协作层

设计来源：Nature Co-Scientist 论文 "scientist-in-the-loop" 协作范式。
用户要求："实现自动化，降低使用门槛，不要老是自己动手"。

核心机制：
1. 业务模块完成关键事件（数据解析/靶点发现/实验完成/对接完成/结构预测/评测完成/
   筛选完成/疫苗设计/基因组解读）后，调用 trigger_auto_reasoning()
2. 服务自动收集项目证据 + 实体上下文，创建后台推理运行（标记 auto_triggered=True）
3. 运行完成后，由 insights.py 服务从高排名假设中提取 AI 洞察
4. 洞察主动推送到对应业务页面，用户原地"采纳/忽略"

异步非阻塞：业务流程不等待推理完成，推理在后台异步执行。
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coscientist_insight import (
    CoScientistInsight,
    EntityType,
    InsightStatus,
    InsightType,
    TriggerEvent,
    TRIGGER_TO_INSIGHT_TYPE,
)
from app.models.coscientist_run import CaseType, CoScientistRun, RunStatus
from app.models.user import User

logger = logging.getLogger(__name__)


# ========== 触发事件 → 研究目标模板映射 ==========

_TRIGGER_GOAL_TEMPLATES: Dict[str, str] = {
    TriggerEvent.DATA_PARSED: (
        "基于刚完成解析的数据集（含差异基因、富集通路、细胞亚群分析结果），"
        "推理后续最有价值的研究方向，提出3个可验证的科学假设。"
        "重点关注：①关键通路与疾病的关联 ②潜在生物标志物 ③可干预靶点。"
    ),
    TriggerEvent.TARGETS_DISCOVERED: (
        "基于项目已发现的靶点列表，推理每个高置信度靶点的老药重定位潜力，"
        "识别已上市药物中可能对该靶点产生调节作用的候选，"
        "并提出验证实验设计建议。重点关注成药性、安全性与协同机会。"
    ),
    TriggerEvent.EXPERIMENT_COMPLETED: (
        "基于刚完成的实验结果（含疗效指标/抑制率/RECIST响应），"
        "推理该结果对项目已有假设的验证或证伪程度，"
        "评估假设的可信度变化，并提出下一步验证方向。"
    ),
    TriggerEvent.EXPERIMENT_FAILED: (
        "基于刚失败的实验（含配置/预期/实际结果），推理可能的失败原因，"
        "包括：①机制假设错误 ②实验设计缺陷 ③样本/试剂问题 ④剂量/时机不当。"
        "提出修正后的假设与改进实验方案。"
    ),
    TriggerEvent.TREATMENT_GENERATED: (
        "基于项目已有的治疗方案与靶点-分子映射，推理潜在的协同组合治疗方案，"
        "重点识别：①作用于互补通路的组合 ②可降低单药剂量的协同 ③可克服耐药的序贯方案。"
    ),
    TriggerEvent.MOLECULE_GENERATED: (
        "基于刚生成的候选分子（含 SMILES/性质评分/类药性），推理其成药性优化方向，"
        "包括：①骨架跃迁建议 ②取代基优化 ③ADMET 性质改善 ④合成可行性。"
    ),
    TriggerEvent.GENOME_INTERPRETED: (
        "基于个人基因组风险评估结果（含性状/风险位点/风险等级），"
        "推理个性化治疗策略建议，包括：①药物基因组学用药调整 ②剂量优化 ③"
        "不良反应风险预警 ④与项目疾病的关联分析。"
    ),
    TriggerEvent.DOCKING_COMPLETED: (
        "基于刚完成的分子对接结果（含结合模式/亲和力/关键残基），"
        "推理：①结合模式合理性 ②关键相互作用分析 ③与已知活性化合物的比较 ④优化方向。"
    ),
    TriggerEvent.STRUCTURE_PREDICTED: (
        "基于刚预测的蛋白结构（含 pLDDT/结合位点/配体坐标），"
        "推理：①别构位点识别 ②可成药口袋评估 ③结构漂变与功能关系 ④分子设计策略。"
    ),
    TriggerEvent.BENCHMARK_COMPLETED: (
        "基于刚完成的基准评测（含7项指标/3模式对比/成本节省/精度变化），"
        "推理：①性能瓶颈识别 ②混合架构优势场景 ③优化建议 ④下一轮评测重点。"
    ),
    TriggerEvent.SCREENING_COMPLETED: (
        "基于双上下文筛选结果（含条件放大器/上下文响应差异），"
        "推理：①条件放大器的分子机制 ②上下文特异性应用场景 ③下游验证方向 ④潜在毒性。"
    ),
    TriggerEvent.VACCINE_DESIGNED: (
        "基于刚设计的 mRNA 疫苗（含新抗原/表位/MHC 结合），"
        "推理：①免疫原性优化 ②表位覆盖度提升 ③递送系统建议 ④与项目疾病的匹配度。"
    ),
}


# ========== 触发事件 → 关联实体类型映射 ==========

_TRIGGER_ENTITY_TYPE: Dict[str, str] = {
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


async def trigger_auto_reasoning(
    db: AsyncSession,
    user: User,
    trigger_event: str,
    project_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    extra_evidence: Optional[str] = None,
) -> Optional[str]:
    """业务事件自动触发推理（异步非阻塞）

    Args:
        db: 数据库会话（用于创建运行记录）
        user: 触发用户
        trigger_event: 触发事件类型（见 TriggerEvent）
        project_id: 项目 ID（可选，项目级事件必填）
        entity_id: 关联实体 ID（可选）
        entity_name: 关联实体名称（可选，用于洞察展示）
        extra_evidence: 额外证据文本（可选，如对接报告/结构摘要）

    Returns:
        run_id: 创建的运行 ID（字符串），失败返回 None

    设计要点：
    - 同步创建运行记录（快速返回，不阻塞业务流程）
    - 异步启动 Supervisor（后台执行多智能体辩论）
    - 运行完成后由 _on_run_completed 自动提取洞察
    """
    if trigger_event not in _TRIGGER_GOAL_TEMPLATES:
        logger.warning("[auto_trigger] 未知触发事件: %s", trigger_event)
        return None

    research_goal = _TRIGGER_GOAL_TEMPLATES[trigger_event]
    entity_type = _TRIGGER_ENTITY_TYPE.get(trigger_event, EntityType.PROJECT)

    try:
        # 创建运行记录（标记 auto_triggered）
        run = CoScientistRun(
            user_id=user.id,
            project_id=uuid.UUID(project_id) if project_id else None,
            research_goal=research_goal,
            case_type=CaseType.CUSTOM,
            max_rounds=3,  # 自动触发用较少轮数，降低成本
            status=RunStatus.PENDING,
            config={
                "auto_triggered": True,
                "trigger_event": trigger_event,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "initial_hypothesis_count": 5,
            },
        )
        db.add(run)
        await db.flush()  # 获取 run.id，但不 commit（由调用方控制事务）

        run_id_str = str(run.id)

        # 异步启动 Supervisor（不等待）
        asyncio.create_task(_run_auto_supervisor(
            run_id=run_id_str,
            research_goal=research_goal,
            trigger_event=trigger_event,
            project_id=project_id,
            entity_id=entity_id,
            entity_name=entity_name,
            extra_evidence=extra_evidence,
            user_id=str(user.id),
        ))

        logger.info(
            "[auto_trigger] 触发事件 %s 已启动推理运行 %s（实体 %s/%s）",
            trigger_event, run_id_str, entity_type, entity_id or "N/A",
        )
        return run_id_str

    except Exception as e:
        logger.exception("[auto_trigger] 触发推理失败: %s", e)
        return None


async def _run_auto_supervisor(
    run_id: str,
    research_goal: str,
    trigger_event: str,
    project_id: Optional[str],
    entity_id: Optional[str],
    entity_name: Optional[str],
    extra_evidence: Optional[str],
    user_id: str,
):
    """后台执行自动推理运行（异步任务）

    重构（方向 A）：解除对端点层的反向依赖。
    - 证据收集：使用 EvidenceCollector（替代 _collect_project_evidence / _collect_entity_context）
    - 推理执行：使用 ReasoningRunner（替代 _run_supervisor），不依赖端点层 WS 状态
    完成后自动提取洞察。
    """
    from app.db.session import async_session_factory
    from app.core.deps import get_llm_client_with_fallback
    from app.services.intelligence.evidence_collector import EvidenceCollector
    from app.services.intelligence.reasoning_runner import ReasoningRunner
    from app.services.coscientist.insights import extract_insights_from_run

    try:
        # 1. 通过 EvidenceCollector 组合收集证据（项目证据 + 实体上下文 + 额外证据）
        collector = EvidenceCollector()
        evidence_bundle = await collector.collect_evidence_bundle(
            trigger_event=trigger_event,
            project_id=project_id,
            entity_id=entity_id,
            extra_evidence=extra_evidence,
        )
        combined_evidence = evidence_bundle.text

        # 2. 获取 LLM 客户端
        async with async_session_factory() as db:
            llm_client = await get_llm_client_with_fallback(db)

        # 3. 通过 ReasoningRunner 执行 Supervisor（无 WS 广播，auto_trigger 静默执行）
        runner = ReasoningRunner()
        result = await runner.run(
            run_id=run_id,
            research_goal=research_goal,
            max_rounds=3,
            initial_count=5,
            case_type=None,
            llm_client=llm_client,
            project_id=project_id,
            ws_broadcast_callback=None,
        )

        if result is None:
            logger.warning("[auto_trigger] 运行 %s 失败，不提取洞察", run_id)
            return

        # 4. 自动提取洞察
        async with async_session_factory() as db:
            from app.models.user import User as UserModel
            user = await db.get(UserModel, uuid.UUID(user_id))
            if user:
                insights = await extract_insights_from_run(
                    db=db,
                    run_id=run_id,
                    user=user,
                    trigger_event=trigger_event,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    result=result,
                )
                logger.info(
                    "[auto_trigger] 运行 %s 完成，提取 %d 个洞察",
                    run_id, len(insights),
                )

    except Exception as e:
        logger.exception("[auto_trigger] 后台运行 %s 异常: %s", run_id, e)


async def _collect_entity_context(
    trigger_event: str,
    entity_id: Optional[str],
    project_id: Optional[str],
) -> str:
    """收集触发实体的上下文证据（向后兼容包装 — 委托 EvidenceCollector）

    重构（方向 A）：原 120 行内联实现已下沉到
    EvidenceCollector.collect_entity_context，本函数保留为薄包装兼容历史调用方。
    """
    from app.services.intelligence.evidence_collector import EvidenceCollector
    collector = EvidenceCollector()
    return await collector.collect_entity_context(trigger_event, entity_id, project_id)


__all__ = [
    "trigger_auto_reasoning",
]
