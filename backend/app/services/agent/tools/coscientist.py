"""Co-Scientist 工具组 — Phase B6 新增 3 个工具

工具列表：
- generate_hypothesis      假设生成（委托 GenerationAgent，创建运行记录 + 生成初始假设）
- query_coscientist_run    运行查询（查询运行状态、排名、假设列表）
- scientific_debate        科学辩论查询（查询辩论日志、共识度分析）

设计原则：
- 遵循现有工具注册机制（AgentTool 基类 + ToolRegistry）
- generate_hypothesis 有副作用（创建 DB 记录 + 消耗 LLM tokens）
- query_coscientist_run / scientific_debate 只读，无副作用
- 所有工具都校验运行所有权（user_id == ctx.user.id 或 FOUNDER 角色）
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UserRole
from app.models.coscientist_run import CoScientistDebateLog, CoScientistRun, RunStatus
from app.models.hypothesis import Hypothesis, HypothesisStatus
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ========== 辅助函数 ==========


async def _check_run_access(ctx: ToolContext, run: CoScientistRun) -> bool:
    """校验运行访问权：FOUNDER 全权，其余通过 user_id 匹配"""
    if ctx.user.role == UserRole.FOUNDER:
        return True
    return run.user_id == ctx.user.id


async def _get_run(ctx: ToolContext, run_id: str) -> Optional[CoScientistRun]:
    """获取运行并校验访问权"""
    try:
        run = await ctx.db.get(CoScientistRun, UUID(run_id))
    except (ValueError, TypeError):
        return None
    if run is None:
        return None
    if not await _check_run_access(ctx, run):
        return None
    return run


# ========== 工具 1: generate_hypothesis ==========


class GenerateHypothesisTool(AgentTool):
    """假设生成工具 — 委托 GenerationAgent 生成初始科学假设

    创建 Co-Scientist 运行记录，调用 GenerationAgent 生成假设，
    将假设持久化到数据库，返回生成的假设列表。

    注意：此工具仅执行假设生成阶段（Generation），不运行完整的多智能体流水线。
    如需完整流水线（辩论、排名、进化），请通过 POST /coscientist/runs 端点启动。
    """

    name = "generate_hypothesis"
    description = (
        "基于研究目标生成科学假设。"
        "使用 Co-Scientist 多智能体引擎的 GenerationAgent 生成多个创新假设。"
        "返回假设列表（含名称、机制、评分维度）。"
        "注意：仅执行生成阶段，不包含辩论和排名。"
    )
    parameters = [
        ToolParameter(
            "research_goal", "string",
            "研究目标（自然语言描述，如 '发现 AML 的新治疗靶点'）",
            required=True,
        ),
        ToolParameter(
            "count", "integer",
            "生成假设数量（3-10）",
            required=False, default=5,
        ),
        ToolParameter(
            "case_type", "string",
            "案例类型",
            required=False,
            enum=["aml", "liver_fibrosis", "amr", "custom"],
        ),
        ToolParameter(
            "project_id", "string",
            "关联项目 ID（可选）",
            required=False,
        ),
        ToolParameter(
            "evidence", "string",
            "相关证据文本（可选，辅助假设生成）",
            required=False,
        ),
    ]
    side_effects = True
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.core.deps import get_llm_client_with_fallback
        from app.services.coscientist.agents.generation import GenerationAgent

        research_goal = params["research_goal"]
        count = min(max(params.get("count", 5), 3), 10)
        case_type = params.get("case_type", "custom")
        project_id = params.get("project_id")
        evidence = params.get("evidence", "")

        # 获取 LLM 客户端
        llm_client = await get_llm_client_with_fallback(ctx.db)
        if llm_client is None:
            return ToolResult.fail(error="无法获取 LLM 客户端")

        # 创建运行记录
        run = CoScientistRun(
            user_id=ctx.user.id,
            project_id=UUID(project_id) if project_id else None,
            research_goal=research_goal,
            case_type=case_type,
            status=RunStatus.RUNNING,
            current_round=0,
            max_rounds=1,
            current_phase="generation",
            started_at=datetime.now(timezone.utc),
        )
        ctx.db.add(run)
        await ctx.db.commit()
        await ctx.db.refresh(run)

        try:
            # 调用 GenerationAgent
            agent = GenerationAgent(llm_client, timeout=60.0)
            result = await agent.run(
                research_goal=research_goal,
                count=count,
                evidence=evidence,
            )

            hypotheses_data = result.get("hypotheses", [])
            if not hypotheses_data:
                run.status = RunStatus.FAILED
                run.error_message = "GenerationAgent 未生成任何假设"
                run.completed_at = datetime.now(timezone.utc)
                await ctx.db.commit()
                return ToolResult.fail(
                    error="假设生成失败：LLM 未返回有效假设",
                    data={"run_id": str(run.id)},
                )

            # 持久化假设到数据库
            saved_hypotheses: List[Dict[str, Any]] = []
            for h in hypotheses_data:
                hyp = Hypothesis(
                    project_id=UUID(project_id) if project_id else None,
                    coscientist_run_id=run.id,
                    name=h.get("name", "未命名假设"),
                    description=h.get("description", ""),
                    mechanism=h.get("mechanism", ""),
                    status=HypothesisStatus.DRAFT,
                    elo_score=1000.0,
                    novelty_score=h.get("novelty_score"),
                    plausibility_score=h.get("plausibility_score"),
                    testability_score=h.get("testability_score"),
                    safety_score=h.get("safety_score"),
                    evolution_strategy="initial",
                    created_by=ctx.user.id,
                )
                ctx.db.add(hyp)

            # 更新运行状态
            run.status = RunStatus.COMPLETED
            run.current_round = 1
            run.completed_at = datetime.now(timezone.utc)
            run.total_token_usage = result.get("token_usage", {})
            run.total_cost_usd = result.get("cost_usd", 0.0)
            if run.started_at and run.completed_at:
                run.duration_sec = (
                    run.completed_at - run.started_at
                ).total_seconds()

            await ctx.db.commit()
            await ctx.db.refresh(run)

            # 重新加载假设以获取 ID
            saved = (
                await ctx.db.execute(
                    select(Hypothesis)
                    .where(Hypothesis.coscientist_run_id == run.id)
                    .order_by(Hypothesis.created_at.asc())
                )
            ).scalars().all()

            for h in saved:
                saved_hypotheses.append({
                    "id": str(h.id),
                    "name": h.name,
                    "description": (h.description or "")[:200],
                    "mechanism": (h.mechanism or "")[:200],
                    "novelty_score": h.novelty_score,
                    "plausibility_score": h.plausibility_score,
                    "testability_score": h.testability_score,
                    "safety_score": h.safety_score,
                })

            return ToolResult.ok(
                data={
                    "run_id": str(run.id),
                    "hypotheses": saved_hypotheses,
                    "count": len(saved_hypotheses),
                    "token_usage": result.get("token_usage", {}),
                    "cost_usd": result.get("cost_usd", 0.0),
                },
                display={
                    "type": "table",
                    "payload": {
                        "title": f"生成的假设 ({len(saved_hypotheses)} 个)",
                        "columns": ["名称", "新颖性", "可信度", "可测性", "安全性"],
                        "rows": [
                            [
                                h["name"],
                                f"{h['novelty_score']:.1f}" if h.get("novelty_score") else "-",
                                f"{h['plausibility_score']:.1f}" if h.get("plausibility_score") else "-",
                                f"{h['testability_score']:.1f}" if h.get("testability_score") else "-",
                                f"{h['safety_score']:.1f}" if h.get("safety_score") else "-",
                            ]
                            for h in saved_hypotheses
                        ],
                    },
                },
            )

        except Exception as e:
            logger.error("generate_hypothesis 工具执行失败: %s", e, exc_info=True)
            # 标记运行失败
            run.status = RunStatus.FAILED
            run.error_message = str(e)
            run.completed_at = datetime.now(timezone.utc)
            await ctx.db.commit()
            return ToolResult.fail(
                error=f"假设生成失败: {type(e).__name__}: {e}",
                data={"run_id": str(run.id)},
            )


# ========== 工具 2: query_coscientist_run ==========


class QueryRunTool(AgentTool):
    """运行查询工具 — 查询 Co-Scientist 运行状态和结果

    只读工具，返回运行详情、Top N 假设（按排名排序）和运行统计。
    """

    name = "query_coscientist_run"
    description = (
        "查询 Co-Scientist 运行的状态、排名和假设。"
        "返回运行详情、Top N 假设列表（含 Elo 评分和排名）及资源消耗。"
    )
    parameters = [
        ToolParameter("run_id", "string", "Co-Scientist 运行 ID", required=True),
        ToolParameter(
            "top_n", "integer",
            "返回前 N 个假设（1-50）",
            required=False, default=10,
        ),
        ToolParameter(
            "include_debates", "boolean",
            "是否包含辩论摘要",
            required=False, default=False,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        run_id = params["run_id"]
        top_n = min(max(params.get("top_n", 10), 1), 50)
        include_debates = params.get("include_debates", False)

        run = await _get_run(ctx, run_id)
        if run is None:
            return ToolResult.fail(error=f"运行不存在或无权访问: {run_id}")

        # 查询假设（按 rank 排序）
        hypotheses = (
            await ctx.db.execute(
                select(Hypothesis)
                .where(Hypothesis.coscientist_run_id == run.id)
                .order_by(
                    Hypothesis.rank.asc().nullslast(),
                    Hypothesis.elo_score.desc().nullslast(),
                )
                .limit(top_n)
            )
        ).scalars().all()

        hyp_list: List[Dict[str, Any]] = []
        for h in hypotheses:
            hyp_list.append({
                "id": str(h.id),
                "name": h.name,
                "rank": h.rank,
                "elo_score": h.elo_score,
                "status": h.status,
                "evolution_strategy": h.evolution_strategy or "initial",
                "novelty_score": h.novelty_score,
                "plausibility_score": h.plausibility_score,
                "testability_score": h.testability_score,
                "safety_score": h.safety_score,
            })

        result_data: Dict[str, Any] = {
            "run_id": str(run.id),
            "status": run.status,
            "case_type": run.case_type,
            "research_goal": run.research_goal,
            "current_round": run.current_round,
            "max_rounds": run.max_rounds,
            "current_phase": run.current_phase,
            "hypotheses": hyp_list,
            "hypothesis_count": len(hyp_list),
            "total_cost_usd": run.total_cost_usd,
            "total_token_usage": run.total_token_usage,
            "duration_sec": run.duration_sec,
        }

        if run.meta_review:
            result_data["meta_review"] = run.meta_review[:500]

        # 可选：辩论摘要
        if include_debates:
            debates = (
                await ctx.db.execute(
                    select(CoScientistDebateLog)
                    .where(CoScientistDebateLog.run_id == run.id)
                    .order_by(CoScientistDebateLog.round_num.asc())
                )
            ).scalars().all()

            debate_list: List[Dict[str, Any]] = []
            for d in debates:
                debate_list.append({
                    "round": d.round_num,
                    "consensus_score": d.consensus_score,
                    "mechanism_agreed": d.mechanism_agreed,
                    "judge_assessment": (d.judge_assessment or "")[:200],
                })
            result_data["debates"] = debate_list

        return ToolResult.ok(
            data=result_data,
            display={
                "type": "table",
                "payload": {
                    "title": f"运行 {str(run.id)[:8]} — Top {len(hyp_list)} 假设",
                    "columns": ["排名", "名称", "Elo", "策略", "状态"],
                    "rows": [
                        [
                            f"#{h['rank']}" if h.get("rank") else "N/A",
                            h["name"],
                            f"{h['elo_score']:.0f}" if h.get("elo_score") else "N/A",
                            h.get("evolution_strategy", "initial"),
                            h.get("status", ""),
                        ]
                        for h in hyp_list
                    ],
                },
            },
        )


# ========== 工具 3: scientific_debate ==========


class ScientificDebateTool(AgentTool):
    """科学辩论查询工具 — 查询辩论日志和共识度分析

    只读工具，返回运行中所有辩论记录，包含正反方论据、裁判评估和共识度。
    """

    name = "scientific_debate"
    description = (
        "查询 Co-Scientist 运行的科学辩论记录。"
        "返回每轮辩论的正反方论据、裁判评估、共识度和机制一致性。"
        "用于了解假设的论证过程和演化历史。"
    )
    parameters = [
        ToolParameter("run_id", "string", "Co-Scientist 运行 ID", required=True),
        ToolParameter(
            "round_num", "integer",
            "指定轮次（可选，不传则返回所有轮次）",
            required=False,
        ),
        ToolParameter(
            "summary_only", "boolean",
            "仅返回摘要（不含完整论据文本）",
            required=False, default=False,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        run_id = params["run_id"]
        round_num = params.get("round_num")
        summary_only = params.get("summary_only", False)

        run = await _get_run(ctx, run_id)
        if run is None:
            return ToolResult.fail(error=f"运行不存在或无权访问: {run_id}")

        # 构建查询
        query = (
            select(CoScientistDebateLog)
            .where(CoScientistDebateLog.run_id == run.id)
            .order_by(CoScientistDebateLog.round_num.asc())
        )
        if round_num is not None:
            query = query.where(CoScientistDebateLog.round_num == round_num)

        debates = (await ctx.db.execute(query)).scalars().all()

        if not debates:
            return ToolResult.ok(
                data={
                    "run_id": str(run.id),
                    "debates": [],
                    "total_rounds": 0,
                    "message": "暂无辩论记录",
                },
            )

        debate_list: List[Dict[str, Any]] = []
        consensus_scores: List[float] = []
        agreed_count = 0

        for d in debates:
            entry: Dict[str, Any] = {
                "round": d.round_num,
                "hypothesis_id": str(d.hypothesis_id),
                "consensus_score": d.consensus_score,
                "mechanism_agreed": d.mechanism_agreed,
            }

            if d.consensus_score is not None:
                consensus_scores.append(d.consensus_score)
            if d.mechanism_agreed:
                agreed_count += 1

            if not summary_only:
                entry["proponent_argument"] = (d.proponent_argument or "")[:500]
                entry["opponent_argument"] = (d.opponent_argument or "")[:500]
                entry["judge_assessment"] = (d.judge_assessment or "")[:500]
                entry["refined_hypothesis"] = (d.refined_hypothesis or "")[:500]

            debate_list.append(entry)

        # 统计分析
        avg_consensus = (
            sum(consensus_scores) / len(consensus_scores)
            if consensus_scores
            else 0.0
        )
        agreement_rate = len(debates) > 0 and agreed_count / len(debates) or 0.0

        return ToolResult.ok(
            data={
                "run_id": str(run.id),
                "debates": debate_list,
                "total_rounds": len(debates),
                "analysis": {
                    "avg_consensus_score": round(avg_consensus, 3),
                    "agreement_rate": round(agreement_rate, 3),
                    "agreed_count": agreed_count,
                    "disputed_count": len(debates) - agreed_count,
                },
            },
            display={
                "type": "table",
                "payload": {
                    "title": f"辩论记录 ({len(debates)} 轮)",
                    "columns": ["轮次", "共识度", "机制一致", "评估摘要"],
                    "rows": [
                        [
                            d["round"],
                            f"{d['consensus_score']:.3f}" if d.get("consensus_score") is not None else "N/A",
                            "✓" if d.get("mechanism_agreed") else "✗",
                            d.get("judge_assessment", "")[:80] if not summary_only else "(摘要模式)",
                        ]
                        for d in debate_list
                    ],
                },
            },
        )


__all__ = [
    "GenerateHypothesisTool",
    "QueryRunTool",
    "ScientificDebateTool",
]
