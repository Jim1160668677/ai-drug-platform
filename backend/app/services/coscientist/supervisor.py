"""Co-Scientist Supervisor 协调器

编排整个多智能体科学推理流程：
1. Generation → 生成初始假设
2. Reflection → 批判每个假设
3. Proximity → 分析假设相似度
4. Evolution → 决策+执行进化策略
5. Debate → 科学辩论优化假设
6. Ranking → Elo 锦标赛排名
7. Meta-Review → 综合元评审

支持专家反馈循环：每轮结束后可暂停等待专家反馈。

参考论文：Section "Supervisor agent" + Extended Data Fig. 1
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.core.config import settings
from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.evolution import EvolutionAgent
from app.services.coscientist.agents.generation import GenerationAgent
from app.services.coscientist.agents.meta_review import MetaReviewAgent
from app.services.coscientist.agents.proximity import ProximityAgent
from app.services.coscientist.agents.ranking import RankingAgent
from app.services.coscientist.agents.reflection import ReflectionAgent
from app.services.coscientist.algorithms.debate import ScientificDebate
from app.services.coscientist.algorithms.elo_tournament import EloTournament
from app.services.coscientist.algorithms.evolution_strategies import EvolutionStrategist
from app.services.coscientist.feedback import FeedbackProcessor
from app.services.coscientist.progress import ProgressTracker
from app.services.coscientist.response_cache import ResponseCache


TOP_K_HYPOTHESES_KEEP = 6
MAX_CONTEXT_EVICTED_CHARS = 1200


def _compact_evicted_hypotheses(evicted: List[Dict]) -> str:
    if not evicted:
        return ""
    lines = []
    for h in evicted:
        name = h.get("name", "未命名")
        elo = h.get("elo_score", 0)
        nv = h.get("novelty_score", 0)
        pl = h.get("plausibility_score", 0)
        ts = h.get("testability_score", 0)
        mech_raw = (h.get("mechanism") or "")
        mech = mech_raw[:60] + ("…" if len(mech_raw) > 60 else "")
        lines.append(
            f"- {name} [ELO={float(elo):.0f}, N={float(nv):.1f}, P={float(pl):.1f}, T={float(ts):.1f}] 机制: {mech}"
        )
    return "已淘汰假设摘要（仅提供背景参考，不再进入演化池）：\n" + "\n".join(lines)

logger = logging.getLogger(__name__)


@dataclass
class CoScientistResult:
    """Co-Scientist 运行结果"""
    run_id: str
    research_goal: str
    final_rankings: List[Dict[str, Any]] = field(default_factory=list)
    meta_review: Optional[Dict[str, Any]] = None
    total_rounds: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_sec: float = 0.0
    converged: bool = False
    error: Optional[str] = None
    all_hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    evolution_summary: str = ""
    experiment_dsl: Optional[Dict[str, Any]] = None  # Auto-generated experiment design DSL
    experiment_schedule_id: Optional[str] = None  # Schedule ID from ExperimentScheduler


class Supervisor:
    """Co-Scientist 多智能体协调器

    用法：
        supervisor = Supervisor(llm_client)
        result = await supervisor.run(
            research_goal="发现某疾病的新治疗靶点和候选药物",
            max_rounds=5,
            initial_count=5,
        )
        # result.final_rankings 是按 Elo 排序的假设
    """

    def __init__(
        self,
        llm_client: Any,
        tracker: Optional[ProgressTracker] = None,
        max_cost_usd: Optional[float] = None,
        max_duration_sec: Optional[int] = None,
        debate_top_k: int = 3,
        max_concurrent: int = 3,
        generation_context: Optional[str] = None,
        initial_seeds: Optional[list] = None,
        context_store: Optional[Any] = None,
        trace_store: Optional[Any] = None,
    ):
        """
        Args:
            llm_client: LLM 客户端实例（FallbackLLMClient）
            tracker: 进度追踪器（None 则创建无回调的）
            max_cost_usd: 成本上限（超过则停止）
            max_duration_sec: 时长上限（秒）
            debate_top_k: 每轮辩论的 Top-K 假设数
            max_concurrent: Agent 并发上限
            context_store: ContextMemoryStore 实例（可选，用于快照+故障重启）
            trace_store: ReasoningTraceStore 实例（可选，用于推理追溯）
        """
        self.llm_client = llm_client
        self.tracker = tracker or ProgressTracker(run_id="internal")
        self.response_cache = ResponseCache(maxsize=256, run_id=str(getattr(self.tracker, "run_id", "")))
        self.max_cost_usd = max_cost_usd or getattr(settings, "COSCIENTIST_MAX_COST_USD", 5.0)
        self.max_duration_sec = max_duration_sec or getattr(settings, "COSCIENTIST_MAX_DURATION_SEC", 600)
        self.debate_top_k = debate_top_k
        self.max_concurrent = max_concurrent
        # 案例适配器提供的背景知识和初始假设种子
        self.generation_context = generation_context
        self.initial_seeds = initial_seeds or []
        # 统一智能系统注入的存储层（可选）
        self.context_store = context_store
        self.trace_store = trace_store

        sem = asyncio.Semaphore(max_concurrent)

        # 初始化 6 个 Agent
        self.generation_agent = GenerationAgent(llm_client, semaphore=sem)
        self.reflection_agent = ReflectionAgent(llm_client, semaphore=sem)
        self.ranking_agent = RankingAgent(llm_client, semaphore=sem)
        self.proximity_agent = ProximityAgent(llm_client, semaphore=sem)
        self.evolution_agent = EvolutionAgent(llm_client, semaphore=sem)
        self.meta_review_agent = MetaReviewAgent(llm_client, semaphore=sem)
        self.feedback_processor = FeedbackProcessor(llm_client, semaphore=sem)

        # 初始化算法
        self.elo_tournament = EloTournament(
            initial_elo=getattr(settings, "COSCIENTIST_ELO_INITIAL", 1000.0),
            k_factor=getattr(settings, "COSCIENTIST_ELO_K_FACTOR", 32),
        )
        self.evolution_strategist = EvolutionStrategist()
        self.debate = ScientificDebate(
            llm_router=BaseAgent(llm_client, agent_name="debate", semaphore=sem),
            max_rounds=getattr(settings, "COSCIENTIST_DEBATE_ROUNDS", 3),
            convergence_threshold=getattr(settings, "COSCIENTIST_DEBATE_CONVERGENCE_THRESHOLD", 0.85),
        )

        # 专家反馈同步
        self._feedback_event = asyncio.Event()
        self._pending_feedback: Optional[str] = None

    async def run(
        self,
        research_goal: str,
        max_rounds: int = 5,
        initial_count: int = 5,
        case_type: Optional[str] = None,
        evidence: str = "",
        feedback_mode: str = "auto",
        existing_context: str = "",
        reasoning_mode: str = "standard",
        round_timeout_sec: Optional[float] = None,
    ) -> CoScientistResult:
        """执行完整 Co-Scientist 流程

        Args:
            research_goal: 研究目标（自然语言）
            max_rounds: 最大迭代轮数（1-10）
            initial_count: 初始假设数量（3-10）
            case_type: 案例类型
            evidence: 初始证据文本
            feedback_mode: "auto"（不等待反馈）或 "interactive"（每轮等待）
            existing_context: 已有上下文（如专家方向性反馈）
            reasoning_mode: "fast" (1-2轮, 简化Debate/Ranking) / "standard" (3-5轮) / "deep" (5+轮, 完整)
            round_timeout_sec: 单轮超时（秒），超时后截断当前轮并进入收敛
        Returns:
            CoScientistResult
        """
        import time
        start_time = time.time()

        # ========== 根据 reasoning_mode 动态调整参数 ==========
        # fast: 1-2轮, 简化 Debate (1轮) 和 Ranking (仅 Top-3)
        # standard: 3-5轮, 完整流水线
        # deep: 5+轮, 启用全部特性
        if reasoning_mode == "fast":
            effective_max_rounds = min(max_rounds, 2)
            effective_initial_count = min(initial_count, 3)
            effective_debate_rounds = 0
            effective_debate_top_k = 0
            effective_ranking_top_n = 3
        elif reasoning_mode == "deep":
            effective_max_rounds = min(max_rounds, 3)
            effective_initial_count = min(initial_count, 4)
            effective_debate_rounds = min(getattr(settings, "COSCIENTIST_DEBATE_ROUNDS", 3), 2)
            effective_debate_top_k = min(self.debate_top_k, 2)
            effective_ranking_top_n = None
        else:
            effective_max_rounds = min(max_rounds, 3)
            effective_initial_count = initial_count
            effective_debate_rounds = min(getattr(settings, "COSCIENTIST_DEBATE_ROUNDS", 3), 2)
            effective_debate_top_k = min(self.debate_top_k, 3)
            effective_ranking_top_n = None

        # 单轮超时默认值：fast=120s, standard=300s, deep=600s
        if round_timeout_sec is None:
            _mode_timeouts = {"fast": 120.0, "standard": 300.0, "deep": 600.0}
            round_timeout_sec = _mode_timeouts.get(reasoning_mode, 300.0)

        logger.info(
            "[supervisor] reasoning_mode=%s max_rounds=%d initial_count=%d "
            "debate_rounds=%d debate_top_k=%d round_timeout=%.0fs",
            reasoning_mode, effective_max_rounds, effective_initial_count,
            effective_debate_rounds, effective_debate_top_k, round_timeout_sec,
        )

        await self.tracker.emit_run_started(
            research_goal, effective_max_rounds, effective_initial_count
        )
        await self.tracker.emit("reasoning_mode_config", {
            "mode": reasoning_mode,
            "max_rounds": effective_max_rounds,
            "initial_count": effective_initial_count,
            "debate_rounds": effective_debate_rounds,
            "debate_top_k": effective_debate_top_k,
            "round_timeout_sec": round_timeout_sec,
        })

        try:
            # ========== 故障恢复检查（autoresearch 整合：夜间自主实验不中断） ==========
            # 若 context_store 已注入且存在历史快照，从最近快照恢复
            recovered_hypotheses: Optional[list] = None
            start_round = 1
            if self.context_store is not None:
                try:
                    snapshot = await self.context_store.get_last_snapshot(self.tracker.run_id)
                    if snapshot and snapshot.get("hypotheses"):
                        recovered_hypotheses = snapshot["hypotheses"]
                        start_round = snapshot.get("round", 0) + 1
                        logger.info(
                            "[supervisor] 故障恢复: 从快照恢复 round=%d hypotheses=%d",
                            start_round - 1, len(recovered_hypotheses),
                        )
                        await self.tracker.emit("recovered_from_snapshot", {
                            "recovered_round": start_round - 1,
                            "hypotheses_count": len(recovered_hypotheses),
                        })
                except Exception as e:
                    logger.warning("[supervisor] 快照恢复失败（继续正常流程）: %s", e)

            if recovered_hypotheses is not None:
                # 从快照恢复，跳过生成阶段
                hypotheses = recovered_hypotheses
            else:
                # ========== 阶段 1: 初始假设生成 ==========
                await self.tracker.emit_phase_started("generation", 0)
                await self.tracker.emit_dag_node_status("generation", round_num=0, status="running")
                t_phase = time.time()
                # Inject case context from CaseAdapter
                case_context = existing_context or ""
                if self.generation_context:
                    case_context = (case_context + "\n\n" if case_context else "") + self.generation_context
                seed_hypotheses = self.initial_seeds or None
                gen_result = await self.generation_agent.run(
                    research_goal=research_goal,
                    count=effective_initial_count,
                    existing_hypotheses=seed_hypotheses,
                    evidence=evidence,
                    context=case_context,
                )
                hypotheses = gen_result["hypotheses"]
                gen_tokens = 0
                gen_cost = 0.0
                try:
                    gen_tokens = int((gen_result.get("token_usage") or {}).get("total", 0))
                except Exception:
                    gen_tokens = 0
                try:
                    gen_cost = float(gen_result.get("cost_usd", 0) or 0)
                except Exception:
                    gen_cost = 0.0
                await self.tracker.emit_phase_completed("generation", 0, {
                    "hypothesis_count": len(hypotheses),
                    "token_usage": gen_result["token_usage"],
                    "cost_usd": gen_result["cost_usd"],
                })
                await self.tracker.emit_dag_node_status(
                    "generation", round_num=0, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=gen_tokens,
                    cost_usd=gen_cost,
                    extra={"hypothesis_count": len(hypotheses)},
                )
                await self.tracker.emit_hypothesis_generated(len(hypotheses), 0)

                if not hypotheses:
                    raise RuntimeError("初始假设生成失败：无假设产出")

            # 累积上下文（专家反馈方向）
            context = existing_context
            evolution_history = []

            # ========== 迭代进化 ==========
            for round_num in range(start_round, effective_max_rounds + 1):
                await self.tracker.emit_round_started(round_num)
                round_start_time = time.time()

                # 成本/时长检查
                elapsed = time.time() - start_time
                if self.tracker.total_cost_usd >= self.max_cost_usd:
                    await self.tracker.emit_cost_warning(self.tracker.total_cost_usd, self.max_cost_usd)
                    logger.warning("[supervisor] 成本超限，停止迭代")
                    break
                if elapsed >= self.max_duration_sec:
                    logger.warning("[supervisor] 总时长超限，停止迭代")
                    break
                if elapsed >= self.max_duration_sec * 0.8:
                    remaining_budget = self.max_duration_sec - elapsed
                    logger.warning(
                        "[supervisor] 已用 %.0fs / %.0fs (80%%)，剩余预算 %.0fs。启用快速收敛模式",
                        elapsed, self.max_duration_sec, remaining_budget,
                    )
                    await self.tracker.emit("budget_critical", {
                        "elapsed": elapsed,
                        "budget": self.max_duration_sec,
                        "remaining": remaining_budget,
                        "action": "fast_convergence",
                    })

                # 过滤掉被否决的假设
                active_hypotheses = self.feedback_processor.filter_active_hypotheses(hypotheses)
                if not active_hypotheses:
                    logger.warning("[supervisor] 所有假设被否决，停止迭代")
                    break

                # 每轮超时检查：已耗时超过 round_timeout_sec 则跳过当前轮后续阶段
                _round_elapsed = time.time() - round_start_time
                if _round_elapsed > round_timeout_sec:
                    logger.warning(
                        "[supervisor] round %d 已耗时 %.0fs > 超时 %.0fs，跳过后续阶段",
                        round_num, _round_elapsed, round_timeout_sec,
                    )
                    await self.tracker.emit("round_timeout", {
                        "round": round_num,
                        "elapsed": _round_elapsed,
                        "timeout": round_timeout_sec,
                        "action": "skip_to_next_round",
                    })
                    continue

                # ========== 阶段 2: Reflection ==========
                await self.tracker.emit_phase_started("reflection", round_num)
                await self.tracker.emit_dag_node_status("reflection", round_num=round_num, status="running")
                t_phase = time.time()
                ckey = self.response_cache.build_key(
                    "reflection",
                    hypotheses=[h.get("name", "") for h in active_hypotheses],
                    evidence=(evidence or "")[:500],
                    research_goal=research_goal,
                    round=round_num,
                )
                cached = self.response_cache.get(ckey)
                ref_tokens = 0
                ref_cost = 0.0
                if cached:
                    critiques = cached["value"]
                else:
                    critiques = await self.reflection_agent.run_batch(
                        active_hypotheses, research_goal, evidence
                    )
                    try:
                        for c in critiques:
                            ref_tokens += int((c.get("token_usage") or {}).get("total", 0))
                            ref_cost += float(c.get("cost_usd", 0) or 0)
                    except Exception:
                        pass
                    self.response_cache.put(ckey, {"value": critiques})
                await self.tracker.emit_phase_completed("reflection", round_num, {
                    "critique_count": len(critiques),
                })
                await self.tracker.emit_dag_node_status(
                    "reflection", round_num=round_num, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=ref_tokens,
                    cost_usd=ref_cost,
                    extra={"critique_count": len(critiques), "cache_hit": cached is not None},
                )

                # ========== 阶段 3: Proximity ==========
                await self.tracker.emit_phase_started("proximity", round_num)
                await self.tracker.emit_dag_node_status("proximity", round_num=round_num, status="running")
                t_phase = time.time()
                proximity_result = await self.proximity_agent.run(
                    active_hypotheses, research_goal
                )
                prox_tokens = 0
                prox_cost = 0.0
                try:
                    prox_tokens = int((proximity_result.get("token_usage") or {}).get("total", 0))
                    prox_cost = float(proximity_result.get("cost_usd", 0) or 0)
                except Exception:
                    pass
                await self.tracker.emit_phase_completed("proximity", round_num, {
                    "pair_count": proximity_result["total_pairs"],
                })
                await self.tracker.emit_dag_node_status(
                    "proximity", round_num=round_num, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=prox_tokens,
                    cost_usd=prox_cost,
                    extra={"pair_count": proximity_result["total_pairs"]},
                )

                # ========== 阶段 4: Evolution 策略决策 + 执行（合并为 evolution 阶段）==========
                await self.tracker.emit_phase_started("evolution_strategy", round_num)
                plans = self.evolution_strategist.decide_strategies(
                    active_hypotheses, critiques, proximity_result
                )
                await self.tracker.emit_phase_completed("evolution_strategy", round_num, {
                    "strategy_summary": self.evolution_strategist.summarize_plans(plans),
                })

                # ========== 阶段 5: 执行 Evolution ==========
                await self.tracker.emit_phase_started("evolution", round_num)
                await self.tracker.emit_dag_node_status("evolution", round_num=round_num, status="running")
                t_phase = time.time()
                hyp_map = {str(h.get("id", h.get("name", ""))): h for h in active_hypotheses}
                evolution_results = await self.evolution_agent.run_batch(
                    active_hypotheses, plans, research_goal, hyp_map
                )
                evo_tokens = 0
                evo_cost = 0.0
                try:
                    for r in evolution_results:
                        evo_tokens += int((r.get("token_usage") or {}).get("total", 0))
                        evo_cost += float(r.get("cost_usd", 0) or 0)
                except Exception:
                    pass
                evolved_count = sum(1 for r in evolution_results if r["strategy"] != "keep")
                # 合并进化后的假设（keep 的保留原假设，其他用进化后的）
                evolved_hypotheses = self._merge_evolved(active_hypotheses, evolution_results)
                await self.tracker.emit_phase_completed("evolution", round_num, {
                    "evolved_count": evolved_count,
                })
                await self.tracker.emit_dag_node_status(
                    "evolution", round_num=round_num, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=evo_tokens,
                    cost_usd=evo_cost,
                    extra={"evolved_count": evolved_count,
                           "strategy_summary": self.evolution_strategist.summarize_plans(plans)},
                )
                await self.tracker.emit_hypothesis_evolved(evolved_count, round_num)

                evolution_history.append({
                    "round": round_num,
                    "strategies": self.evolution_strategist.summarize_plans(plans),
                })

                # ========== 阶段 6: Debate（Top-K 假设）==========
                await self.tracker.emit_phase_started("debate", round_num)
                await self.tracker.emit_dag_node_status("debate", round_num=round_num, status="running")
                t_phase = time.time()
                top_for_debate = evolved_hypotheses[:effective_debate_top_k]
                deb_tokens = 0
                deb_cost = 0.0
                debate_cache_hit = True

                # fast 模式或超时检查：跳过 Debate
                _round_elapsed = time.time() - round_start_time
                if effective_debate_top_k == 0 or _round_elapsed > round_timeout_sec * 0.7:
                    logger.warning(
                        "[supervisor] round %d Debate 阶段跳过（已耗时 %.0fs，超时 %.0fs）",
                        round_num, _round_elapsed, round_timeout_sec,
                    )
                    await self.tracker.emit("debate_skipped", {
                        "round": round_num,
                        "reason": "round_timeout",
                        "elapsed": _round_elapsed,
                    })
                else:
                    for hyp in top_for_debate:
                        try:
                            dkey = self.response_cache.build_key(
                                "debate",
                                hyp_name=hyp.get("name", ""),
                                hyp_mechanism=(hyp.get("mechanism") or "")[:200],
                                evidence=(evidence or "")[:500],
                                research_goal=research_goal,
                                round=round_num,
                            )
                            cached_debate = self.response_cache.get(dkey)
                            if cached_debate:
                                debate_result = cached_debate["value"]
                            else:
                                debate_cache_hit = False
                                debate_result = await self.debate.conduct_debate(
                                    hyp, research_goal, evidence,
                                    max_rounds_override=effective_debate_rounds,
                                )
                                try:
                                    deb_tokens += int((debate_result.token_usage or {}).get("total", 0))
                                    deb_cost += float(getattr(debate_result, "cost_usd", 0) or 0)
                                except Exception:
                                    pass
                                self.response_cache.put(dkey, {"value": debate_result})
                            if debate_result.refined_hypothesis and not debate_result.error:
                                hyp.update(debate_result.refined_hypothesis)
                        except Exception as e:
                            logger.warning("[supervisor] 辩论失败: %s", e)
                await self.tracker.emit_phase_completed("debate", round_num, {
                    "debated_count": len(top_for_debate),
                })
                await self.tracker.emit_dag_node_status(
                    "debate", round_num=round_num, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=deb_tokens,
                    cost_usd=deb_cost,
                    extra={"debated_count": len(top_for_debate), "all_cached": debate_cache_hit},
                )

                # ========== 阶段 7: Ranking（Elo 锦标赛）==========
                await self.tracker.emit_phase_started("ranking", round_num)
                await self.tracker.emit_dag_node_status("ranking", round_num=round_num, status="running")
                t_phase = time.time()
                tournament_result = None

                # Ranking 简化：fast 模式始终简化，超时也简化
                _round_elapsed = time.time() - round_start_time
                if effective_debate_top_k == 0 or _round_elapsed > round_timeout_sec * 0.8:
                    logger.warning(
                        "[supervisor] round %d Ranking 阶段简化处理（已耗时 %.0fs）",
                        round_num, _round_elapsed,
                    )
                    hypotheses = sorted(
                        evolved_hypotheses,
                        key=lambda h: float(h.get("elo_score", 0)),
                        reverse=True,
                    )[:(effective_ranking_top_n or len(evolved_hypotheses))]
                    await self.tracker.emit("ranking_simplified", {
                        "round": round_num,
                        "reason": "fast_mode" if effective_debate_top_k == 0 else "round_timeout",
                        "hypothesis_count": len(hypotheses),
                    })
                else:
                    rank_input = (
                        evolved_hypotheses[:effective_ranking_top_n]
                        if effective_ranking_top_n
                        else evolved_hypotheses
                    )
                    tournament_result = await self.elo_tournament.run_tournament(
                        rank_input, self.ranking_agent, research_goal
                    )
                    hypotheses = tournament_result.rankings
                rank_tokens = 0
                rank_cost = 0.0
                match_count = 0
                if tournament_result is not None:
                    try:
                        rank_tokens = int((getattr(tournament_result, "token_usage", None) or {}).get("total", 0))
                        rank_cost = float(getattr(tournament_result, "cost_usd", 0) or 0)
                        match_count = getattr(tournament_result, "total_matches", 0) or 0
                    except Exception:
                        pass
                await self.tracker.emit_phase_completed("ranking", round_num, {
                    "match_count": match_count,
                })
                await self.tracker.emit_dag_node_status(
                    "ranking", round_num=round_num, status="done",
                    duration_ms=int((time.time() - t_phase) * 1000),
                    tokens=rank_tokens,
                    cost_usd=rank_cost,
                    extra={"match_count": match_count,
                           "top_elo": hypotheses[0].get("elo_score", 0) if hypotheses else 0},
                )
                await self.tracker.emit_ranking_updated(hypotheses, round_num)

                if len(hypotheses) > TOP_K_HYPOTHESES_KEEP:
                    hypotheses.sort(
                        key=lambda h: float(h.get("elo_score", 0)),
                        reverse=True,
                    )
                    kept = hypotheses[:TOP_K_HYPOTHESES_KEEP]
                    evicted = hypotheses[TOP_K_HYPOTHESES_KEEP:]
                    evicted_text = _compact_evicted_hypotheses(evicted)
                    if evicted_text:
                        before_chars = sum(
                            len((e.get("description") or "") + (e.get("mechanism") or ""))
                            for e in evicted
                        )
                        evicted_compressed_char_count = 0
                        new_item = f"\n\n[round_{round_num} 淘汰摘要]\n{evicted_text}"
                        if evicted_compressed_char_count + len(new_item) > MAX_CONTEXT_EVICTED_CHARS:
                            context_items = [c for c in context.split("\n\n[round_") if c]
                            new_item = new_item[:MAX_CONTEXT_EVICTED_CHARS]
                        context = (context or "") + new_item
                        hypotheses = kept
                        after_chars = len(new_item)
                        await self.tracker.emit(
                            "hypotheses_compacted",
                            {
                                "round": round_num,
                                "kept": TOP_K_HYPOTHESES_KEEP,
                                "evicted": len(evicted),
                                "total_before": TOP_K_HYPOTHESES_KEEP + len(evicted),
                                "saved_chars_estimate": before_chars - after_chars,
                                "cache_stats": self.response_cache.stats(),
                            },
                        )
                        await self.tracker.emit_compression_stats(
                            stage="round_compact",
                            before_chars=before_chars,
                            after_chars=after_chars,
                            details={
                                "round": round_num,
                                "kept": TOP_K_HYPOTHESES_KEEP,
                                "evicted": len(evicted),
                            },
                        )

                # ========== 专家反馈循环 ==========
                if feedback_mode == "interactive" and round_num < effective_max_rounds:
                    await self.tracker.emit_awaiting_feedback(round_num, hypotheses)
                    # 等待外部注入反馈，超时降级为 auto 模式避免挂起
                    try:
                        await asyncio.wait_for(self._feedback_event.wait(), timeout=15.0)
                        self._feedback_event.clear()
                        if self._pending_feedback:
                            await self.tracker.emit_feedback_received("expert", self._pending_feedback)
                            instructions = await self.feedback_processor.parse_feedback(
                                self._pending_feedback, hypotheses, research_goal
                            )
                            hypotheses, context = self.feedback_processor.apply_instructions(
                                instructions, hypotheses, context
                            )
                            self._pending_feedback = None
                    except asyncio.TimeoutError:
                        logger.info(
                            "[supervisor] interactive 模式等待反馈超时 (15s)，降级为 auto 模式继续"
                        )
                        await self.tracker.emit(
                            "feedback_timeout",
                            {"round": round_num, "action": "fallback_to_auto"},
                        )

                await self.tracker.emit_round_completed(round_num, {
                    "active_hypotheses": len(self.feedback_processor.filter_active_hypotheses(hypotheses)),
                    "top_elo": hypotheses[0].get("elo_score", 0) if hypotheses else 0,
                })

                # 保存快照（autoresearch 整合：等价于记录每次实验结果，支持故障重启）
                if self.context_store is not None:
                    try:
                        await self.context_store.save_snapshot(
                            run_id=self.tracker.run_id,
                            round_num=round_num,
                            phase="round_completed",
                            hypotheses=hypotheses,
                            context_summary=context[:500] if context else "",
                        )
                    except Exception as e:
                        logger.warning("[supervisor] 保存快照失败（不影响主流程）: %s", e)

            # ========== 阶段 8: Meta-Review ==========
            await self.tracker.emit_phase_started("meta_review", effective_max_rounds)
            await self.tracker.emit_dag_node_status("meta_review", round_num=effective_max_rounds, status="running")
            t_phase = time.time()
            evolution_summary = self._format_evolution_summary(evolution_history)
            meta_review = await self.meta_review_agent.run(
                hypotheses, research_goal, evolution_summary, context
            )
            mr_tokens = 0
            mr_cost = 0.0
            try:
                mr_tokens = int((meta_review.get("token_usage") or {}).get("total", 0))
                mr_cost = float(meta_review.get("cost_usd", 0) or 0)
            except Exception:
                pass
            top_count = len(meta_review.get("top_hypotheses", []))
            await self.tracker.emit_phase_completed("meta_review", max_rounds, {
                "top_count": top_count,
            })
            await self.tracker.emit_dag_node_status(
                "meta_review", round_num=max_rounds, status="done",
                duration_ms=int((time.time() - t_phase) * 1000),
                tokens=mr_tokens,
                cost_usd=mr_cost,
                extra={"top_count": top_count},
            )

            duration = time.time() - start_time
            await self.tracker.emit_run_completed(hypotheses, meta_review)

            result = CoScientistResult(
                run_id=self.tracker.run_id,
                research_goal=research_goal,
                final_rankings=hypotheses,
                meta_review=meta_review,
                total_rounds=len(evolution_history),
                total_tokens=self.tracker.total_tokens,
                total_cost_usd=round(self.tracker.total_cost_usd, 6),
                duration_sec=round(duration, 2),
                converged=len(evolution_history) < max_rounds,
                all_hypotheses=hypotheses,
                evolution_summary=evolution_summary,
            )

            # 新增: 自动生成实验设计 (controlled by settings)
            if result.final_rankings and getattr(settings, "COSCIENTIST_AUTO_EXPERIMENT_DESIGN", False):
                dsl = await self._auto_generate_dsl(
                    result.final_rankings[:3],
                    result.research_goal,
                )
                if dsl:
                    result.experiment_dsl = dsl.to_dict()

            return result

        except Exception as e:
            logger.exception("[supervisor] 运行失败: %s", e)
            await self.tracker.emit_run_failed(str(e))
            return CoScientistResult(
                run_id=self.tracker.run_id,
                research_goal=research_goal,
                error=str(e),
                duration_sec=round(time.time() - start_time, 2),
            )

    def inject_feedback(self, feedback: str) -> None:
        """注入专家反馈（用于 interactive 模式）

        在 awaiting_feedback 状态后调用此方法，Supervisor 将继续运行。
        """
        self._pending_feedback = feedback
        self._feedback_event.set()

    def _merge_evolved(
        self,
        original: List[Dict[str, Any]],
        evolution_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """合并进化结果到假设列表

        按 hypothesis ID 匹配，而非位置。
        keep 策略：保留原假设
        其他策略：用进化后的假设替换（保留原 ID 用于追踪）
        """
        # 构建 ID → evolved hypothesis 映射
        evolved_by_id = {}
        for result in evolution_results:
            hyp_id = result.get("hypothesis_id") or result.get("id")
            if hyp_id:
                evolved_by_id[hyp_id] = result.get("evolved_hypothesis", result.get("hypothesis", {}))

        merged = []
        for orig in original:
            orig_id = orig.get("id")
            if orig_id and orig_id in evolved_by_id:
                merged.append(evolved_by_id[orig_id])
            else:
                merged.append(orig)

        # 记录不匹配的进化结果
        if len(evolution_results) != len(merged):
            logger.warning(
                "[supervisor] 进化结果数量 (%d) 与原假设数量 (%d) 不匹配",
                len(evolution_results), len(original),
            )

        return merged

    def _format_evolution_summary(self, history: List[Dict]) -> str:
        """格式化进化历史摘要"""
        if not history:
            return "（无进化记录）"
        lines = []
        for h in history:
            strategies = h.get("strategies", {})
            lines.append(
                f"轮次{h['round']}: 增强={strategies.get('enhancement', 0)}, "
                f"合并={strategies.get('combination', 0)}, "
                f"简化={strategies.get('simplification', 0)}, "
                f"保持={strategies.get('keep', 0)}"
            )
        return "\n".join(lines)

    async def _auto_generate_dsl(
        self,
        top_hypotheses: List[Dict[str, Any]],
        research_goal: str,
    ) -> Optional[Any]:
        """调用 ExperimentDesignTool 生成 DSL"""
        if not top_hypotheses:
            return None

        try:
            from app.services.agent.tools.experiment_design import ExperimentDesignTool
            from app.services.experiment.dsl import ExperimentDSL
            from unittest.mock import MagicMock

            tool = ExperimentDesignTool()
            ctx = MagicMock()
            ctx.llm_client = None

            result = await tool.execute({
                "goal": research_goal,
                "hypothesis_ids": [h.get("id") for h in top_hypotheses[:3] if h.get("id")],
                "exp_type": "cytotoxicity",
            }, ctx=ctx)

            if result.ok():
                dsl_data = result.data.get("dsl", {})
                return ExperimentDSL.from_dict(dsl_data)
        except Exception as e:
            logger.warning("[supervisor] DSL generation failed: %s", e)

        return None

    async def _auto_schedule(
        self,
        dsl: Any,
        project_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """调用 ExperimentScheduler 调度实验"""
        if dsl is None:
            return None

        try:
            from app.services.experiment.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            return scheduler.schedule(dsl, str(project_id))
        except Exception as e:
            logger.warning("[supervisor] Scheduling failed: %s", e)
            return None

    def get_agent_stats(self) -> Dict[str, Dict]:
        """获取所有 Agent 的统计"""
        return {
            "generation": self.generation_agent.get_stats(),
            "reflection": self.reflection_agent.get_stats(),
            "ranking": self.ranking_agent.get_stats(),
            "proximity": self.proximity_agent.get_stats(),
            "evolution": self.evolution_agent.get_stats(),
            "meta_review": self.meta_review_agent.get_stats(),
            "feedback": self.feedback_processor.get_stats(),
        }
