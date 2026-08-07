"""ReasoningRunner — 推理执行服务（解除 auto_trigger 反向依赖）

设计来源：方向 A（管道嵌入+追溯）— 将 coscientist.py 端点层的
_run_supervisor / _persist_run_result / _mark_run_failed 三个函数下沉为服务，
使 auto_trigger 不再 from app.api.v1.endpoints.coscientist import _run_supervisor。

核心能力：
1. run：创建 Tracker + EvidenceCollector + Supervisor，执行多智能体推理
2. persist_result：持久化假设到 Hypothesis 表，更新 CoScientistRun 状态
3. mark_failed：标记运行失败
4. WS 广播解耦：通过 ws_broadcast_callback 注入，端点层传入，服务层不持有 WS 状态

依赖注入：
- EvidenceCollector：证据收集（替代端点层 _collect_project_evidence）
- ws_broadcast_callback：可选的 WS 推送回调（端点层注入，auto_trigger 传 None）
"""
import json as _json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from app.models.coscientist_run import CoScientistRun, RunStatus
from app.models.hypothesis import Hypothesis, HypothesisStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ReasoningRunner:
    """推理执行器 — 服务层封装 Supervisor 运行 + 持久化

    用法（端点层）：
        runner = ReasoningRunner()
        result = await runner.run(
            run_id=run_id, research_goal=goal, max_rounds=5,
            initial_count=5, case_type=None, llm_client=client,
            project_id=pid, ws_broadcast_callback=_ws_broadcast,
        )

    用法（auto_trigger，无 WS）：
        result = await runner.run(..., ws_broadcast_callback=None)
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self._db = db

    async def run(
        self,
        run_id: str,
        research_goal: str,
        max_rounds: int,
        initial_count: int,
        case_type: Optional[str],
        llm_client: Any,
        project_id: Optional[str] = None,
        ws_broadcast_callback: Optional[Callable] = None,
        extra_evidence: Optional[str] = None,
    ) -> Any:
        """后台运行 Supervisor（异步任务）

        Args:
            run_id: 运行 ID（字符串）
            research_goal: 研究目标
            max_rounds: 最大轮数
            initial_count: 初始假设数
            case_type: 案例类型
            llm_client: LLM 客户端
            project_id: 项目 ID（可选）
            ws_broadcast_callback: WS 广播回调 async fn(run_id, event_type, payload)
            extra_evidence: 额外证据（如触发实体的附加上下文）

        Returns:
            Supervisor 运行结果对象，失败返回 None
        """
        from app.services.coscientist.cases import get_case_adapter
        from app.services.coscientist.progress import ProgressTracker
        from app.services.coscientist.supervisor import Supervisor
        from app.services.intelligence.evidence_collector import EvidenceCollector

        # 1. 创建 Tracker，注入 WS 广播回调
        async def _tracker_callback(event):
            if ws_broadcast_callback is not None:
                try:
                    await ws_broadcast_callback(run_id, event.type, event.payload)
                except Exception as e:
                    logger.warning("[ReasoningRunner] WS 广播失败: %s", e)

        tracker = ProgressTracker(run_id=run_id, callback=_tracker_callback)

        # 2. 获取案例适配器
        case_adapter = get_case_adapter(case_type) if case_type else None
        generation_context = case_adapter.get_generation_context() if case_adapter else None
        initial_seeds = case_adapter.get_initial_seeds() if case_adapter else None

        # 3. 通过 EvidenceCollector 收集项目证据（替代端点层 _collect_project_evidence）
        project_evidence = ""
        if project_id:
            try:
                collector = EvidenceCollector()
                bundle = await collector.collect_evidence_bundle(
                    project_id=project_id, extra_evidence=extra_evidence,
                )
                project_evidence = bundle.text
                if project_evidence and ws_broadcast_callback is not None:
                    await ws_broadcast_callback(run_id, "evidence_collected", {
                        "project_id": project_id,
                        "evidence_length": len(project_evidence),
                        "total_items": bundle.total_items,
                    })
            except Exception as e:
                logger.warning("[ReasoningRunner] 收集项目证据失败（将使用空证据）: %s", e)

        # 4. 创建并运行 Supervisor
        supervisor = Supervisor(
            llm_client=llm_client,
            tracker=tracker,
            max_cost_usd=None,
            max_duration_sec=None,
            generation_context=generation_context,
            initial_seeds=initial_seeds,
        )

        try:
            result = await supervisor.run(
                research_goal=research_goal,
                max_rounds=max_rounds,
                initial_count=initial_count,
                case_type=case_type,
                evidence=project_evidence,
                feedback_mode="interactive",
            )
            # 5. 持久化结果
            await self.persist_result(run_id, result, project_id)
            return result
        except Exception as e:
            logger.exception("[ReasoningRunner] 运行 %s 失败: %s", run_id, e)
            await self.mark_failed(run_id, str(e))
            return None

    async def persist_result(
        self, run_id: str, result: Any, project_id: Optional[str],
    ) -> None:
        """持久化 Co-Scientist 运行结果到数据库

        - 将假设写入 Hypothesis 表（设置 coscientist_run_id）— 仅当有 project_id 时
        - 更新 CoScientistRun 的 final_rankings、meta_review、status、计量字段
        """
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            try:
                # 更新运行状态
                run = await db.get(CoScientistRun, uuid.UUID(run_id))
                if run:
                    run.status = RunStatus.COMPLETED
                    run.completed_at = datetime.now(timezone.utc)
                    run.final_rankings = result.final_rankings
                    run.meta_review = (
                        _json.dumps(result.meta_review, ensure_ascii=False, default=str)
                        if result.meta_review
                        else None
                    )
                    run.total_cost_usd = result.total_cost_usd
                    run.duration_sec = result.duration_sec
                    run.current_round = result.total_rounds

                # 持久化假设到 Hypothesis 表（仅当有 project_id）
                if project_id and result.all_hypotheses:
                    existing_result = await db.execute(
                        select(Hypothesis.id).where(
                            Hypothesis.coscientist_run_id == uuid.UUID(run_id)
                        )
                    )
                    existing_ids = {str(r[0]) for r in existing_result.fetchall()}

                    for hyp_dict in result.all_hypotheses:
                        hyp_id = hyp_dict.get("id")
                        if hyp_id and str(hyp_id) in existing_ids:
                            continue

                        hyp = Hypothesis(
                            project_id=uuid.UUID(project_id),
                            name=str(hyp_dict.get("name", "未命名假设"))[:200],
                            description=hyp_dict.get("description", ""),
                            mechanism=hyp_dict.get("mechanism", ""),
                            strategy=hyp_dict.get("strategy", ""),
                            status=HypothesisStatus.COMPLETED,
                            target_list=hyp_dict.get("target_list", []),
                            elo_score=hyp_dict.get("elo_score", 1000.0),
                            novelty_score=hyp_dict.get("novelty_score"),
                            plausibility_score=hyp_dict.get("plausibility_score"),
                            testability_score=hyp_dict.get("testability_score"),
                            safety_score=hyp_dict.get("safety_score"),
                            parent_ids=hyp_dict.get("parent_ids", []),
                            evolution_strategy=hyp_dict.get("evolution_strategy", "initial"),
                            evolution_history=hyp_dict.get("evolution_history", []),
                            debate_log=hyp_dict.get("debate_log", []),
                            critique_summary=hyp_dict.get("critique_summary"),
                            coscientist_run_id=uuid.UUID(run_id),
                            rank=hyp_dict.get("rank"),
                        )
                        db.add(hyp)

                await db.commit()
                logger.info(
                    "[ReasoningRunner] 运行 %s 持久化完成: %d 个假设",
                    run_id,
                    len(result.all_hypotheses) if result.all_hypotheses else 0,
                )
            except Exception as e:
                await db.rollback()
                logger.exception("[ReasoningRunner] 持久化运行 %s 结果失败: %s", run_id, e)

    async def mark_failed(self, run_id: str, error_msg: str) -> None:
        """标记运行失败"""
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            try:
                run = await db.get(CoScientistRun, uuid.UUID(run_id))
                if run:
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.now(timezone.utc)
                    run.error_message = error_msg[:500]
                    await db.commit()
            except Exception as e:
                await db.rollback()
                logger.exception("[ReasoningRunner] 标记运行失败状态时出错: %s", e)


__all__ = ["ReasoningRunner"]
