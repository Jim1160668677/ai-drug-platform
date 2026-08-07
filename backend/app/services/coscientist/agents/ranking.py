"""Ranking Agent — 假设排名智能体

职责：成对比较两个假设，判定优劣。供 EloTournament 调用。
参考论文：Section "Ranking agent" + Extended Data Fig. 4
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import RANKING_SYSTEM, RANKING_USER
from app.services.coscientist.algorithms.elo_tournament import MatchResult

logger = logging.getLogger(__name__)


class RankingAgent(BaseAgent):
    """假设排名智能体 — 成对比较

    用法：
        agent = RankingAgent(llm_client)
        # 单对比较
        result = await agent.compare_pair(hyp_a, hyp_b, research_goal)
        # result 是 MatchResult（winner=A/B/tie）

        # 批量评分
        scores = await agent.score_batch(hypotheses, research_goal)
    """

    agent_name = "ranking"

    async def compare_pair(
        self,
        hyp_a: Dict[str, Any],
        hyp_b: Dict[str, Any],
        research_goal: str = "",
    ) -> MatchResult:
        """成对比较两个假设

        Args:
            hyp_a: 假设 A
            hyp_b: 假设 B
            research_goal: 研究目标
        Returns:
            MatchResult（winner=A/B/tie + confidence + reasoning + winning_criteria）
        """
        id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
        id_b = str(hyp_b.get("id", hyp_b.get("name", "")))

        prompt = RANKING_USER.format(
            research_goal=research_goal or "（未指定）",
            a_name=hyp_a.get("name", "未命名"),
            a_description=hyp_a.get("description", ""),
            a_mechanism=hyp_a.get("mechanism", ""),
            b_name=hyp_b.get("name", "未命名"),
            b_description=hyp_b.get("description", ""),
            b_mechanism=hyp_b.get("mechanism", ""),
        )

        result = await self.quick(prompt, system=RANKING_SYSTEM)
        parsed = self._parse_json(result["content"], default={})

        # 解析 winner
        winner_raw = str(parsed.get("winner", "tie")).upper().strip()
        if winner_raw == "A":
            winner = "A"
        elif winner_raw == "B":
            winner = "B"
        else:
            winner = "tie"

        # 解析 confidence
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (ValueError, TypeError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        winning_criteria = parsed.get("winning_criteria", [])
        if not isinstance(winning_criteria, list):
            winning_criteria = [str(winning_criteria)]

        return MatchResult(
            hypothesis_a_id=id_a,
            hypothesis_b_id=id_b,
            winner=winner,
            confidence=confidence,
            reasoning=str(parsed.get("reasoning", "")),
            winning_criteria=winning_criteria,
        )

    async def run(
        self,
        hyp_a: Dict[str, Any],
        hyp_b: Dict[str, Any],
        research_goal: str = "",
    ) -> MatchResult:
        """BaseAgent.run 接口适配 — 转发到 compare_pair"""
        return await self.compare_pair(hyp_a, hyp_b, research_goal)

    async def score_batch(
        self,
        hypotheses: List[Dict[str, Any]],
        research_goal: str = "",
    ) -> Dict[str, Dict[str, float]]:
        """批量评估假设的绝对质量分（0-1）

        注意：此方法不用于 Elo 锦标赛（锦标赛用 compare_pair）。
        用于需要绝对质量分的场景（如初始化筛选）。

        Returns:
            {hypothesis_id: {"quality": 0-1, "novelty": 0-1, "plausibility": 0-1, ...}}
        """
        import asyncio

        sem = asyncio.Semaphore(3)

        async def _score_one(hyp):
            async with sem:
                return await self._score_single(hyp, research_goal)

        tasks = [_score_one(h) for h in hypotheses]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scores = {}
        for i, r in enumerate(results):
            hid = str(hypotheses[i].get("id", hypotheses[i].get("name", "")))
            if isinstance(r, Exception):
                logger.warning("[ranking] 假设 %s 评分失败: %s", hid, r)
                scores[hid] = {"quality": 0.5, "error": str(r)}
            else:
                scores[hid] = r

        return scores

    async def _score_single(
        self, hypothesis: Dict[str, Any], research_goal: str
    ) -> Dict[str, float]:
        """评估单个假设的绝对质量分"""
        system = (
            "你是科学假设质量评估专家。对给定假设进行绝对质量评分（0-1）。"
            "输出 JSON: {\"quality\": 0-1, \"novelty\": 0-1, \"plausibility\": 0-1, "
            "\"testability\": 0-1, \"safety\": 0-1, \"reasoning\": \"评分理由\"}"
        )
        prompt = (
            f"研究目标: {research_goal}\n\n"
            f"假设: {hypothesis.get('name', '')}\n"
            f"描述: {hypothesis.get('description', '')}\n"
            f"机制: {hypothesis.get('mechanism', '')}\n\n"
            "请评估此假设的质量。"
        )

        result = await self.quick(prompt, system=system)
        parsed = self._parse_json(result["content"], default={})

        def _safe_float(key, default=0.5):
            try:
                v = float(parsed.get(key, default))
                return max(0.0, min(1.0, v))
            except (ValueError, TypeError):
                return default

        return {
            "quality": _safe_float("quality"),
            "novelty": _safe_float("novelty"),
            "plausibility": _safe_float("plausibility"),
            "testability": _safe_float("testability"),
            "safety": _safe_float("safety"),
        }