"""Co-Scientist 专家反馈处理器

处理科学家通过自然语言交互提供的反馈，影响假设生成方向。

反馈类型（参考论文 Section "Expert feedback loop"）：
1. directional: 方向性反馈 — 影响下一轮 Generation 的 prompt
2. veto: 否决 — 标记假设为 eliminated_by_expert
3. elo_adjustment: Elo 调整 — 奖励或惩罚假设
4. refinement: 精化 — 要求对特定假设进行改进

设计要点：
- 反馈通过 LLM 解析为结构化指令
- 方向性反馈累积到 context，影响下一轮生成
- 否决的假设不参与后续进化/排名
- Elo 调整立即生效
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass
class FeedbackInstruction:
    """结构化反馈指令"""
    feedback_type: str  # directional / veto / elo_adjustment / refinement
    target_hypothesis_id: Optional[str] = None
    direction: str = ""  # directional 时的方向描述
    elo_delta: float = 0.0  # elo_adjustment 时的分值变化
    refinement_note: str = ""  # refinement 时的改进说明
    raw_feedback: str = ""  # 原始反馈文本


FEEDBACK_SYSTEM = """你是科学研究的专家反馈分析助手。你的任务是将科学家的自然语言反馈解析为结构化指令。

反馈类型：
1. directional: 方向性反馈 — 科学家指出应探索的新方向或调整研究重点
2. veto: 否决 — 科学家明确否决某个假设（不应继续探索）
3. elo_adjustment: Elo 调整 — 科学家对某假设评分进行调整（奖励或惩罚）
4. refinement: 精化 — 科学家要求对特定假设进行特定改进

输出 JSON:
{"instructions": [{"feedback_type": "directional|veto|elo_adjustment|refinement", "target_hypothesis_id": "假设ID（如适用）", "direction": "方向描述（directional时）", "elo_delta": 数字（elo_adjustment时，正=奖励/负=惩罚）, "refinement_note": "改进说明（refinement时）"}]}"""

FEEDBACK_USER = """研究目标: {research_goal}

当前假设列表（ID + 名称 + Elo）:
{hypotheses_list}

专家反馈:
{feedback}

请将反馈解析为结构化指令。"""


class FeedbackProcessor(BaseAgent):
    """专家反馈处理器

    用法：
        processor = FeedbackProcessor(llm_client)
        instructions = await processor.parse_feedback(
            feedback="假设1的机制不成立，应该探索表观遗传方向",
            hypotheses=hypotheses,
            research_goal="目标",
        )
        # instructions = [FeedbackInstruction(...), ...]

        # 应用指令到假设
        updated_hypotheses, context = processor.apply_instructions(
            instructions, hypotheses, context,
        )
    """

    agent_name = "feedback"

    async def parse_feedback(
        self,
        feedback: str,
        hypotheses: List[Dict[str, Any]],
        research_goal: str = "",
    ) -> List[FeedbackInstruction]:
        """解析自然语言反馈为结构化指令

        Args:
            feedback: 专家自然语言反馈
            hypotheses: 当前假设列表
            research_goal: 研究目标
        Returns:
            FeedbackInstruction 列表
        """
        hyp_list = "\n".join(
            f"- ID={h.get('id', '?')}: {h.get('name', '未命名')} (Elo={h.get('elo_score', 1000)})"
            for h in hypotheses
        )

        prompt = FEEDBACK_USER.format(
            research_goal=research_goal or "（未指定）",
            hypotheses_list=hyp_list or "（无假设）",
            feedback=feedback,
        )

        result = await self.quick(prompt, system=FEEDBACK_SYSTEM)
        parsed = self._parse_json(result["content"], default={})

        instructions = []
        for inst in parsed.get("instructions", []):
            if not isinstance(inst, dict):
                continue
            try:
                feedback_type = str(inst.get("feedback_type", "directional"))
                if feedback_type not in ("directional", "veto", "elo_adjustment", "refinement"):
                    feedback_type = "directional"

                try:
                    elo_delta = float(inst.get("elo_delta", 0))
                except (ValueError, TypeError):
                    elo_delta = 0.0

                instructions.append(FeedbackInstruction(
                    feedback_type=feedback_type,
                    target_hypothesis_id=str(inst.get("target_hypothesis_id", "")) or None,
                    direction=str(inst.get("direction", "")),
                    elo_delta=elo_delta,
                    refinement_note=str(inst.get("refinement_note", "")),
                    raw_feedback=feedback,
                ))
            except Exception as e:
                logger.warning("[feedback] 指令解析失败: %s", e)

        logger.info("[feedback] 解析 %d 条指令", len(instructions))
        return instructions

    def apply_instructions(
        self,
        instructions: List[FeedbackInstruction],
        hypotheses: List[Dict[str, Any]],
        context: str = "",
    ) -> tuple:
        """应用反馈指令到假设列表

        Args:
            instructions: 结构化指令列表
            hypotheses: 当前假设列表
            context: 累积的方向性上下文
        Returns:
            (updated_hypotheses, updated_context)
        """
        updated = []
        vetoed_ids = set()
        elo_deltas = {}
        direction_notes = []
        refinement_notes = {}  # {hypothesis_id: note}

        for inst in instructions:
            if inst.feedback_type == "veto" and inst.target_hypothesis_id:
                vetoed_ids.add(inst.target_hypothesis_id)
            elif inst.feedback_type == "elo_adjustment" and inst.target_hypothesis_id:
                elo_deltas[inst.target_hypothesis_id] = elo_deltas.get(inst.target_hypothesis_id, 0) + inst.elo_delta
            elif inst.feedback_type == "directional" and inst.direction:
                direction_notes.append(inst.direction)
            elif inst.feedback_type == "refinement" and inst.target_hypothesis_id:
                refinement_notes[inst.target_hypothesis_id] = inst.refinement_note

        # 应用到假设
        for hyp in hypotheses:
            hyp_id = str(hyp.get("id", hyp.get("name", "")))
            new_hyp = {**hyp}

            if hyp_id in vetoed_ids:
                new_hyp["status"] = "eliminated_by_expert"
                new_hyp["expert_vetoed"] = True

            if hyp_id in elo_deltas:
                current_elo = float(new_hyp.get("elo_score", 1000))
                new_hyp["elo_score"] = current_elo + elo_deltas[hyp_id]
                new_hyp["elo_adjusted_by_expert"] = elo_deltas[hyp_id]

            if hyp_id in refinement_notes:
                new_hyp["refinement_request"] = refinement_notes[hyp_id]

            updated.append(new_hyp)

        # 累积方向性上下文
        updated_context = context
        if direction_notes:
            new_directions = "\n".join(f"- 专家反馈: {d}" for d in direction_notes)
            updated_context = f"{context}\n{new_directions}" if context else new_directions

        return updated, updated_context

    def filter_active_hypotheses(self, hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤掉被否决的假设"""
        return [
            h for h in hypotheses
            if h.get("status") != "eliminated_by_expert"
            and not h.get("expert_vetoed", False)
        ]

    async def run(self, feedback: str, hypotheses: List[Dict], research_goal: str = "") -> List[FeedbackInstruction]:
        """BaseAgent.run 接口适配"""
        return await self.parse_feedback(feedback, hypotheses, research_goal)