"""Elo 锦标赛排名算法 — Co-Scientist 核心算法

基于 Nature 论文 Co-Scientist 的锦标赛式成对比较 + 动态 Elo 评分更新。

设计要点：
- 初始分 1000.0（参考国际象棋 Elo）
- K 因子动态：前 10 场 K=40（新手保护），10-30 场 K=32（标准），30+ 场 K=24（稳定）
- 调度策略：假设数 ≤ 8 全循环（n*(n-1)/2 场），> 8 瑞士制（2n 场）
- 成对比较通过 RankingAgent（LLM 判定胜者）
- Win/Loss 模式分析（可选 LLM 总结胜出特征）

参考论文：Section "Tournament-based ranking" + Extended Data Fig. 4
"""
import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """单场比赛结果"""
    hypothesis_a_id: str
    hypothesis_b_id: str
    winner: str  # "A" / "B" / "tie"
    confidence: float = 0.5
    reasoning: str = ""
    winning_criteria: List[str] = field(default_factory=list)


@dataclass
class TournamentResult:
    """锦标赛结果"""
    rankings: List[Dict[str, Any]]  # 按 Elo 排序的假设列表
    match_results: List[MatchResult]  # 所有比赛记录
    total_matches: int
    patterns: Optional[Dict[str, Any]] = None  # Win/Loss 模式分析


class EloTournament:
    """Elo 锦标赛排名算法

    用法：
        tournament = EloTournament()
        result = await tournament.run_tournament(hypotheses, ranking_agent)
        # result.rankings 按 Elo 降序排列
    """

    def __init__(
        self,
        initial_elo: float = 1000.0,
        k_factor: int = 32,
        k_provisional: int = 40,
        k_stable: int = 24,
        provisional_games: int = 10,
        stable_games: int = 30,
    ):
        self.initial_elo = initial_elo
        self.k_factor = k_factor
        self.k_provisional = k_provisional
        self.k_stable = k_stable
        self.provisional_games = provisional_games
        self.stable_games = stable_games

    def _get_k_factor(self, match_count: int) -> int:
        """根据比赛场数动态获取 K 因子

        Args:
            match_count: 该假设已参加的比赛场数
        Returns:
            K 因子（前 10 场 K=40，10-30 场 K=32，30+ 场 K=24）
        """
        if match_count < self.provisional_games:
            return self.k_provisional
        elif match_count < self.stable_games:
            return self.k_factor
        else:
            return self.k_stable

    def _expected_score(self, elo_a: float, elo_b: float) -> float:
        """计算 A 对 B 的预期胜率

        Elo 公式：expected_a = 1 / (1 + 10^((elo_b - elo_a) / 400))
        """
        return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

    def _update_elo(
        self,
        winner_elo: float,
        loser_elo: float,
        winner_match_count: int,
        loser_match_count: int,
        draw: bool = False,
    ) -> Tuple[float, float]:
        """更新 Elo 评分

        Args:
            winner_elo: 胜方当前 Elo
            loser_elo: 负方当前 Elo
            winner_match_count: 胜方已赛场数
            loser_match_count: 负方已赛场数
            draw: 是否平局
        Returns:
            (new_winner_elo, new_loser_elo)
        """
        expected_winner = self._expected_score(winner_elo, loser_elo)
        expected_loser = 1.0 - expected_winner

        if draw:
            actual_winner = 0.5
            actual_loser = 0.5
        else:
            actual_winner = 1.0
            actual_loser = 0.0

        k_winner = self._get_k_factor(winner_match_count)
        k_loser = self._get_k_factor(loser_match_count)

        new_winner_elo = winner_elo + k_winner * (actual_winner - expected_winner)
        new_loser_elo = loser_elo + k_loser * (actual_loser - expected_loser)

        return round(new_winner_elo, 2), round(new_loser_elo, 2)

    def _generate_pairs(
        self,
        hypotheses: List[Dict[str, Any]],
        swiss_threshold: int = 8,
    ) -> List[Tuple[int, int]]:
        """生成成对比较组合

        Args:
            hypotheses: 假设列表
            swiss_threshold: 超过此数量切换瑞士制
        Returns:
            索引对列表 [(i, j), ...]
        """
        n = len(hypotheses)
        if n < 2:
            return []

        if n <= swiss_threshold:
            # 全循环：n*(n-1)/2 场
            return list(combinations(range(n), 2))
        else:
            # 瑞士制：2n 场，优先匹配相近 Elo 的对
            return self._swiss_pairing(hypotheses, num_rounds=2)

    def _swiss_pairing(
        self,
        hypotheses: List[Dict[str, Any]],
        num_rounds: int = 2,
    ) -> List[Tuple[int, int]]:
        """瑞士制配对 — 每轮匹配相近 Elo 的对

        简化实现：按 Elo 排序后相邻配对，重复 num_rounds 轮
        （每轮打乱同分组的顺序避免重复）
        """
        n = len(hypotheses)
        # 按 Elo 降序排序
        indexed = list(enumerate(hypotheses))
        indexed.sort(
            key=lambda x: x[1].get("elo_score", self.initial_elo),
            reverse=True,
        )

        pairs = []
        played = set()

        for round_num in range(num_rounds):
            # 每轮按 Elo 分组配对
            available = list(range(len(indexed)))
            if round_num % 2 == 1:
                # 奇数轮打乱避免重复配对
                random.shuffle(available)

            used = set()
            for i in available:
                if i in used:
                    continue
                # 找最近的未配对对手
                for j in available:
                    if j == i or j in used:
                        continue
                    orig_i = indexed[i][0]
                    orig_j = indexed[j][0]
                    pair_key = (min(orig_i, orig_j), max(orig_i, orig_j))
                    if pair_key not in played:
                        pairs.append(pair_key)
                        played.add(pair_key)
                        used.add(i)
                        used.add(j)
                        break
                if i not in used:
                    # 找不到新对手，允许重复
                    for j in available:
                        if j == i or j in used:
                            continue
                        orig_i = indexed[i][0]
                        orig_j = indexed[j][0]
                        pairs.append((min(orig_i, orig_j), max(orig_i, orig_j)))
                        used.add(i)
                        used.add(j)
                        break

        return pairs


    async def run_tournament(
        self,
        hypotheses: List[Dict[str, Any]],
        ranking_agent: Any,
        research_goal: str = "",
        total_matches: Optional[int] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> TournamentResult:
        """运行 Elo 锦标赛

        Args:
            hypotheses: 假设列表（每个假设是 dict，含 id/name/description 等）
            ranking_agent: RankingAgent 实例（需有 compare_pair 方法）
            research_goal: 研究目标（传递给 ranking_agent）
            total_matches: 可选，限制总比赛数
            semaphore: 可选，并发控制信号量
        Returns:
            TournamentResult（含按 Elo 排序的 rankings + 比赛记录 + 模式分析）
        """
        if len(hypotheses) < 2:
            logger.warning("锦标赛需要至少 2 个假设，当前 %d 个", len(hypotheses))
            return TournamentResult(
                rankings=self._format_rankings(hypotheses),
                match_results=[],
                total_matches=0,
            )

        # 1. 初始化 Elo 评分
        elo_scores: Dict[str, float] = {}
        match_counts: Dict[str, int] = {}
        for hyp in hypotheses:
            hyp_id = str(hyp.get("id", hyp.get("name", "")))
            elo_scores[hyp_id] = float(hyp.get("elo_score", self.initial_elo))
            match_counts[hyp_id] = 0

        # 2. 生成成对组合
        pairs = self._generate_pairs(hypotheses)
        if total_matches and len(pairs) > total_matches:
            random.shuffle(pairs)
            pairs = pairs[:total_matches]

        logger.info(
            "Elo 锦标赛开始: %d 个假设, %d 场比赛",
            len(hypotheses), len(pairs),
        )

        # 3. 并发执行成对比较
        sem = semaphore or asyncio.Semaphore(3)

        async def _play_match(idx_a: int, idx_b: int) -> MatchResult:
            async with sem:
                hyp_a = hypotheses[idx_a]
                hyp_b = hypotheses[idx_b]
                try:
                    result = await ranking_agent.compare_pair(
                        hyp_a, hyp_b, research_goal
                    )
                    return result
                except Exception as e:
                    logger.warning("成对比较失败，默认平局: %s", e)
                    id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
                    id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
                    return MatchResult(
                        hypothesis_a_id=id_a,
                        hypothesis_b_id=id_b,
                        winner="tie",
                        confidence=0.0,
                        reasoning=f"比较失败: {e}",
                    )

        match_tasks = [_play_match(a, b) for a, b in pairs]
        match_results = await asyncio.gather(*match_tasks, return_exceptions=False)

        # 4. 动态更新 Elo（按比赛顺序）
        for match in match_results:
            id_a = match.hypothesis_a_id
            id_b = match.hypothesis_b_id

            if id_a not in elo_scores or id_b not in elo_scores:
                continue

            elo_a = elo_scores[id_a]
            elo_b = elo_scores[id_b]

            if match.winner == "A":
                new_a, new_b = self._update_elo(
                    elo_a, elo_b,
                    match_counts[id_a], match_counts[id_b],
                    draw=False,
                )
            elif match.winner == "B":
                new_a, new_b = self._update_elo(
                    elo_b, elo_a,
                    match_counts[id_b], match_counts[id_a],
                    draw=False,
                )
                new_a, new_b = new_b, new_a  # 交换回 A/B 顺序
            else:  # tie
                new_a, new_b = self._update_elo(
                    elo_a, elo_b,
                    match_counts[id_a], match_counts[id_b],
                    draw=True,
                )

            elo_scores[id_a] = new_a
            elo_scores[id_b] = new_b
            match_counts[id_a] += 1
            match_counts[id_b] += 1

        # 5. 产出排名
        rankings = self._format_rankings(hypotheses, elo_scores)

        logger.info(
            "Elo 锦标赛完成: Top Elo=%.2f, 总比赛=%d",
            rankings[0]["elo_score"] if rankings else 0,
            len(match_results),
        )

        return TournamentResult(
            rankings=rankings,
            match_results=match_results,
            total_matches=len(match_results),
            patterns=None,  # 模式分析可选，由 analyze_patterns 方法单独调用
        )

    def _format_rankings(
        self,
        hypotheses: List[Dict[str, Any]],
        elo_scores: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """格式化排名结果（按 Elo 降序）"""
        if elo_scores is None:
            # 无比赛时，按现有 elo_score 排序
            ranked = sorted(
                hypotheses,
                key=lambda h: float(h.get("elo_score", self.initial_elo)),
                reverse=True,
            )
        else:
            ranked = sorted(
                hypotheses,
                key=lambda h: elo_scores.get(
                    str(h.get("id", h.get("name", ""))),
                    self.initial_elo,
                ),
                reverse=True,
            )

        result = []
        for rank_idx, hyp in enumerate(ranked, 1):
            hyp_id = str(hyp.get("id", hyp.get("name", "")))
            result.append({
                **hyp,
                "id": hyp_id,
                "elo_score": elo_scores.get(hyp_id, float(hyp.get("elo_score", self.initial_elo))) if elo_scores else float(hyp.get("elo_score", self.initial_elo)),
                "rank": rank_idx,
            })
        return result

    async def analyze_patterns(
        self,
        match_results: List[MatchResult],
        hypotheses: List[Dict[str, Any]],
        llm_router: Any = None,
    ) -> Dict[str, Any]:
        """分析 Win/Loss 模式（可选 LLM 总结）

        无 LLM 时返回统计模式；有 LLM 时调用 LLM 深度分析。
        """
        # 统计每个假设的胜/负/平
        stats: Dict[str, Dict[str, int]] = {}
        for match in match_results:
            id_a = match.hypothesis_a_id
            id_b = match.hypothesis_b_id
            for hid in (id_a, id_b):
                if hid not in stats:
                    stats[hid] = {"wins": 0, "losses": 0, "ties": 0}

            if match.winner == "A":
                stats[id_a]["wins"] += 1
                stats[id_b]["losses"] += 1
            elif match.winner == "B":
                stats[id_b]["wins"] += 1
                stats[id_a]["losses"] += 1
            else:
                stats[id_a]["ties"] += 1
                stats[id_b]["ties"] += 1

        # 找出胜率最高和最低的假设
        win_rates = {}
        for hid, s in stats.items():
            total = s["wins"] + s["losses"] + s["ties"]
            if total > 0:
                win_rates[hid] = s["wins"] / total

        if win_rates:
            best_id = max(win_rates, key=win_rates.get)
            worst_id = min(win_rates, key=win_rates.get)
            patterns = {
                "win_rates": win_rates,
                "best_performer": best_id,
                "worst_performer": worst_id,
                "total_matches": len(match_results),
            }
        else:
            patterns = {
                "win_rates": {},
                "total_matches": len(match_results),
            }

        # LLM 深度分析（可选）
        if llm_router and match_results:
            try:
                patterns["llm_analysis"] = await self._llm_pattern_analysis(
                    match_results, hypotheses, llm_router
                )
            except Exception as e:
                logger.warning("LLM 模式分析失败: %s", e)
                patterns["llm_analysis"] = None

        return patterns

    async def _llm_pattern_analysis(
        self,
        match_results: List[MatchResult],
        hypotheses: List[Dict[str, Any]],
        llm_router: Any,
    ) -> str:
        """LLM 深度模式分析"""
        # 构造比赛摘要（取前 20 场避免 token 爆炸）
        match_summary = []
        for m in match_results[:20]:
            match_summary.append({
                "winner": m.winner,
                "confidence": m.confidence,
                "criteria": m.winning_criteria,
            })

        prompt = (
            "基于以下 Elo 锦标赛比赛结果，分析胜出假设的共同特征。\n\n"
            f"比赛结果摘要: {match_summary}\n\n"
            "输出 JSON: {\"winning_patterns\": [...], "
            "\"losing_patterns\": [...], "
            "\"feature_importance\": {\"novelty\": 0.3, ...}}"
        )
        result = await llm_router.quick(prompt)
        return result.get("content", "") if isinstance(result, dict) else str(result)
