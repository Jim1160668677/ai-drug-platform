"""Scientific Debate 科学辩论机制 — Co-Scientist 核心算法

基于 Nature 论文 Co-Scientist 的自博弈正反方辩论机制。

设计要点：
- 三角色 LLM 调用：正方（支持假设）、反方（质疑假设）、裁判（判定共识度）
- 收敛条件：共识度 >= 阈值（默认 0.85）或 达到最大轮数 或 双方核心机制一致
- 每轮：正方陈述 → 反方反驳 → 裁判判定
- 收敛后综合辩论结果产出修正假设

参考论文：Section "Self-play-based scientific debate" + Extended Data Fig. 3
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DebateTurn:
    """辩论单回合记录"""
    round_num: int
    proponent_argument: str  # 正方论据
    opponent_argument: str   # 反方论据
    judge_assessment: str    # 裁判评估
    consensus_score: float   # 共识度 0-1
    mechanism_agreed: bool   # 核心机制是否一致


@dataclass
class DebateResult:
    """辩论结果"""
    hypothesis_id: str
    original_hypothesis: Dict[str, Any]
    refined_hypothesis: Optional[Dict[str, Any]] = None  # 修正后的假设
    turns: List[DebateTurn] = field(default_factory=list)
    final_consensus: float = 0.0
    converged: bool = False
    total_rounds: int = 0
    token_usage: Dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    cost_usd: float = 0.0
    error: Optional[str] = None


class ScientificDebate:
    """科学辩论机制 — 自博弈正反方辩论

    用法：
        debate = ScientificDebate(llm_router)
        result = await debate.conduct_debate(hypothesis, research_goal)
        # result.refined_hypothesis 是辩论后修正的假设
    """

    def __init__(
        self,
        llm_router: Any,
        max_rounds: int = 3,
        convergence_threshold: float = 0.85,
        semaphore: Optional[asyncio.Semaphore] = None,
    ):
        self.llm_router = llm_router
        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self.semaphore = semaphore or asyncio.Semaphore(1)

    async def conduct_debate(
        self,
        hypothesis: Dict[str, Any],
        research_goal: str,
        evidence: str = "",
        max_rounds_override: Optional[int] = None,
    ) -> DebateResult:
        """执行完整辩论流程

        Args:
            hypothesis: 待辩论的假设 {id, name, description, mechanism, ...}
            research_goal: 研究目标
            evidence: 相关证据文本
            max_rounds_override: 覆盖默认辩论轮数
        Returns:
            DebateResult（含修正假设 + 辩论记录）
        """
        hyp_id = str(hypothesis.get("id", hypothesis.get("name", "")))
        result = DebateResult(
            hypothesis_id=hyp_id,
            original_hypothesis=hypothesis,
        )

        hyp_text = self._format_hypothesis(hypothesis)
        effective_max_rounds = max_rounds_override or self.max_rounds

        try:
            async with self.semaphore:
                prev_proponent = ""
                prev_opponent = ""

                for round_num in range(1, effective_max_rounds + 1):
                    logger.info(
                        "辩论轮次 %d/%d: 假设 %s",
                        round_num, self.max_rounds, hyp_id,
                    )

                    # 正方回合
                    proponent_arg = await self._proponent_turn(
                        hyp_text, research_goal, evidence,
                        prev_opponent, round_num,
                    )
                    result.token_usage["total"] += proponent_arg.get("token_usage", {}).get("total", 0)
                    result.cost_usd += proponent_arg.get("cost_usd", 0.0)

                    # 反方回合
                    opponent_arg = await self._opponent_turn(
                        hyp_text, research_goal, evidence,
                        proponent_arg["argument"], round_num,
                    )
                    result.token_usage["total"] += opponent_arg.get("token_usage", {}).get("total", 0)
                    result.cost_usd += opponent_arg.get("cost_usd", 0.0)

                    # 裁判判定
                    judgment = await self._judge_convergence(
                        hyp_text, research_goal,
                        proponent_arg["argument"],
                        opponent_arg["argument"],
                        round_num,
                    )
                    result.token_usage["total"] += judgment.get("token_usage", {}).get("total", 0)
                    result.cost_usd += judgment.get("cost_usd", 0.0)

                    turn = DebateTurn(
                        round_num=round_num,
                        proponent_argument=proponent_arg["argument"],
                        opponent_argument=opponent_arg["argument"],
                        judge_assessment=judgment["assessment"],
                        consensus_score=judgment["consensus_score"],
                        mechanism_agreed=judgment["mechanism_agreed"],
                    )
                    result.turns.append(turn)

                    prev_proponent = proponent_arg["argument"]
                    prev_opponent = opponent_arg["argument"]

                    result.final_consensus = judgment["consensus_score"]

                    # 收敛检查
                    if (
                        judgment["consensus_score"] >= self.convergence_threshold
                        or judgment["mechanism_agreed"]
                    ):
                        result.converged = True
                        result.total_rounds = round_num
                        logger.info(
                            "辩论收敛: 轮次 %d, 共识度 %.2f",
                            round_num, judgment["consensus_score"],
                        )
                        break

                result.total_rounds = len(result.turns)

                # 综合辩论结果，产出修正假设
                if result.turns:
                    refined = await self._synthesize_refined_hypothesis(
                        hypothesis, research_goal, result.turns,
                    )
                    result.refined_hypothesis = refined
                    result.token_usage["total"] += refined.get("token_usage", {}).get("total", 0)
                    result.cost_usd += refined.get("cost_usd", 0.0)

        except Exception as e:
            logger.exception("辩论失败: 假设 %s: %s", hyp_id, e)
            result.error = str(e)

        return result

    def _format_hypothesis(self, hypothesis: Dict[str, Any]) -> str:
        """格式化假设为文本"""
        parts = []
        if hypothesis.get("name"):
            parts.append(f"标题: {hypothesis['name']}")
        if hypothesis.get("description"):
            parts.append(f"描述: {hypothesis['description']}")
        if hypothesis.get("mechanism"):
            parts.append(f"机制: {hypothesis['mechanism']}")
        return "\n".join(parts) if parts else str(hypothesis)


    async def _proponent_turn(
        self,
        hypothesis: str,
        research_goal: str,
        evidence: str,
        prev_opponent_critique: str,
        round_num: int,
    ) -> Dict[str, Any]:
        """正方回合：支持假设，回应批判"""
        system = (
            "你是科学研究假设的辩护者。你的任务是基于证据论证假设的合理性，"
            "回应反方的质疑，补充支持证据。"
            "在合理的情况下可以修正假设（而非盲目辩护）。"
        )
        prompt = (
            f"研究目标: {research_goal}\n\n"
            f"待辩论假设:\n{hypothesis}\n\n"
        )
        if evidence:
            prompt += f"相关证据:\n{evidence}\n\n"
        if prev_opponent_critique and round_num > 1:
            prompt += f"反方上轮质疑:\n{prev_opponent_critique}\n\n"
            prompt += "请回应反方质疑，并补充支持论据。"
        else:
            prompt += "请陈述支持该假设的论据。"

        prompt += (
            "\n\n输出 JSON: {\"argument\": \"你的论据\", "
            "\"evidence\": [\"证据1\", ...], "
            "\"concessions\": [\"让步点\", ...], "
            "\"refined_hypothesis\": \"修正后的假设（可选）\"}"
        )

        result = await self.llm_router.quick(prompt, system=system)
        return self._parse_debate_response(result)

    async def _opponent_turn(
        self,
        hypothesis: str,
        research_goal: str,
        evidence: str,
        proponent_argument: str,
        round_num: int,
    ) -> Dict[str, Any]:
        """反方回合：质疑假设，找逻辑漏洞"""
        system = (
            "你是科学假设的严格质疑者。你的任务是寻找假设的逻辑漏洞，"
            "提出反例和矛盾证据，质疑实验设计的可行性，指出潜在的安全风险。"
        )
        prompt = (
            f"研究目标: {research_goal}\n\n"
            f"待质疑假设:\n{hypothesis}\n\n"
            f"正方论据:\n{proponent_argument}\n\n"
        )
        if evidence:
            prompt += f"已知证据:\n{evidence}\n\n"

        prompt += (
            "请质疑该假设，寻找逻辑漏洞和反例。"
            "\n\n输出 JSON: {\"argument\": \"你的质疑\", "
            "\"counterexamples\": [\"反例1\", ...], "
            "\"safety_concerns\": [\"安全风险\", ...], "
            "\"fatal_flaws\": [\"致命缺陷（如有）\"]}"
        )

        result = await self.llm_router.quick(prompt, system=system)
        return self._parse_debate_response(result)

    async def _judge_convergence(
        self,
        hypothesis: str,
        research_goal: str,
        proponent_argument: str,
        opponent_argument: str,
        round_num: int,
    ) -> Dict[str, Any]:
        """裁判判定共识度"""
        system = (
            "你是中立的科学裁判。基于正反方论据，评估双方在核心观点上的一致程度。"
        )
        prompt = (
            f"研究目标: {research_goal}\n\n"
            f"待评估假设:\n{hypothesis}\n\n"
            f"正方论据:\n{proponent_argument}\n\n"
            f"反方质疑:\n{opponent_argument}\n\n"
            "请评估:\n"
            "1. 共识度(0-1): 双方在核心观点上的一致程度\n"
            "2. 机制认同: 双方是否就核心机制达成一致\n"
            "3. 综合质量评估\n"
            "\n输出 JSON: {\"consensus_score\": 0.0, "
            "\"mechanism_agreed\": false, "
            "\"assessment\": \"评估文本\", "
            "\"quality_score\": 0.0}"
        )

        result = await self.llm_router.quick(prompt, system=system)
        parsed = self._parse_debate_response(result)

        # 确保字段存在且有默认值
        return {
            "consensus_score": float(parsed.get("consensus_score", 0.0)),
            "mechanism_agreed": bool(parsed.get("mechanism_agreed", False)),
            "assessment": str(parsed.get("assessment", parsed.get("argument", ""))),
            "quality_score": float(parsed.get("quality_score", 0.0)),
            "token_usage": parsed.get("token_usage", {}),
            "cost_usd": parsed.get("cost_usd", 0.0),
        }

    async def _synthesize_refined_hypothesis(
        self,
        original: Dict[str, Any],
        research_goal: str,
        turns: List[DebateTurn],
    ) -> Dict[str, Any]:
        """综合辩论结果，产出修正假设"""
        debate_summary = "\n\n".join(
            f"轮次 {t.round_num}:\n"
            f"  正方: {t.proponent_argument[:200]}...\n"
            f"  反方: {t.opponent_argument[:200]}...\n"
            f"  裁判: {t.judge_assessment[:200]}...\n"
            f"  共识度: {t.consensus_score}"
            for t in turns
        )

        system = "你是科学假设综合修正专家。基于辩论记录，产出修正后的假设。"
        prompt = (
            f"研究目标: {research_goal}\n\n"
            f"原始假设:\n{self._format_hypothesis(original)}\n\n"
            f"辩论记录:\n{debate_summary}\n\n"
            "基于辩论结果，产出修正后的假设。保留原假设的核心优势，"
            "解决反方提出的合理质疑。"
            "\n\n输出 JSON: {\"name\": \"修正标题\", "
            "\"description\": \"修正描述\", "
            "\"mechanism\": \"修正机制\", "
            "\"change_log\": \"变更说明\", "
            "\"novelty\": 0-10, \"plausibility\": 0-10, "
            "\"testability\": 0-10, \"safety\": 0-10}"
        )

        result = await self.llm_router.quick(prompt, system=system)
        parsed = self._parse_debate_response(result)

        # 合并原始假设和修正内容
        refined = {**original}
        for key in ("name", "description", "mechanism"):
            if key in parsed:
                refined[key] = parsed[key]
        for key in ("novelty", "plausibility", "testability", "safety"):
            if key in parsed:
                refined[f"{key}_score"] = float(parsed[key])
        refined["debate_refined"] = True
        refined["change_log"] = parsed.get("change_log", "")
        refined["token_usage"] = parsed.get("token_usage", {})
        refined["cost_usd"] = parsed.get("cost_usd", 0.0)

        return refined

    def _parse_debate_response(self, result: Any) -> Dict[str, Any]:
        """解析 LLM 响应为 JSON（容错处理）"""
        if isinstance(result, dict):
            content = result.get("content", "")
            token_usage = result.get("token_usage", {})
            cost_usd = result.get("cost_usd", 0.0)
        else:
            content = str(result)
            token_usage = {}
            cost_usd = 0.0

        # 尝试解析 JSON
        parsed = {"argument": content, "token_usage": token_usage, "cost_usd": cost_usd}
        try:
            # 提取 JSON 块
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            # 找到第一个 { 和最后一个 }
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                json_str = content[start:end + 1]
                data = json.loads(json_str)
                parsed.update(data)
                # argument 字段兼容
                if "argument" not in parsed and "assessment" in data:
                    parsed["argument"] = data["assessment"]
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("辩论响应 JSON 解析失败，使用原始文本: %s", e)

        return parsed
