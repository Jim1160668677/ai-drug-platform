"""Meta-Review Agent — 元评审智能体

职责：对整个假设生成与进化过程进行综合评审，产出最终推荐和改进建议。
- 评估 Top-K 假设
- 评估整体质量分布和多样性
- 推荐后续实验验证路径
- 识别研究盲区

参考论文：Section "Meta-review agent" + Extended Data Fig. 6
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import (
    META_REVIEW_SYSTEM,
    META_REVIEW_USER,
    format_ranked_hypotheses,
)

logger = logging.getLogger(__name__)


class MetaReviewAgent(BaseAgent):
    """元评审智能体

    用法：
        agent = MetaReviewAgent(llm_client)
        result = await agent.run(
            ranked_hypotheses=[...],
            research_goal="目标",
            evolution_summary="辩论与进化摘要",
            expert_feedback="专家反馈",
        )
        # result = {"top_hypotheses": [...], "quality_summary": "...", ...}
    """

    agent_name = "meta_review"

    async def run(
        self,
        ranked_hypotheses: List[Dict[str, Any]],
        research_goal: str,
        evolution_summary: str = "",
        expert_feedback: str = "",
    ) -> Dict[str, Any]:
        """执行综合元评审

        Args:
            ranked_hypotheses: 按 Elo 排序的假设列表
            research_goal: 研究目标
            evolution_summary: 辩论与进化过程摘要
            expert_feedback: 专家反馈（如有）
        Returns:
            {"top_hypotheses": [{"id", "rank", "reason"}],
             "quality_summary": str, "diversity_assessment": str,
             "evolution_effectiveness": str, "recommended_experiments": [...],
             "research_gaps": [...], "final_recommendation": str,
             "confidence_level": float,
             "token_usage": {...}, "cost_usd": ...}
        """
        prompt = META_REVIEW_USER.format(
            research_goal=research_goal,
            ranked_hypotheses=format_ranked_hypotheses(ranked_hypotheses),
            evolution_summary=evolution_summary or "（无进化摘要）",
            expert_feedback=expert_feedback or "（无专家反馈）",
        )

        result = await self.quick(prompt, system=META_REVIEW_SYSTEM)
        parsed = self._parse_json(result["content"], default={})

        # 清理 top_hypotheses
        top_hyps = []
        for th in parsed.get("top_hypotheses", []):
            if not isinstance(th, dict):
                continue
            top_hyps.append({
                "id": str(th.get("id", "")),
                "rank": int(th.get("rank", 0)) if th.get("rank") else 0,
                "reason": str(th.get("reason", "")),
            })

        # 确保列表字段是 list
        recommended_experiments = parsed.get("recommended_experiments", [])
        if not isinstance(recommended_experiments, list):
            recommended_experiments = [str(recommended_experiments)]

        research_gaps = parsed.get("research_gaps", [])
        if not isinstance(research_gaps, list):
            research_gaps = [str(research_gaps)]

        # 解析 confidence_level
        try:
            confidence = float(parsed.get("confidence_level", 0.5))
        except (ValueError, TypeError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        logger.info(
            "[meta_review] 评审完成，Top %d 假设，置信度 %.2f (tokens=%d)",
            len(top_hyps), confidence, result["token_usage"]["total"],
        )

        return {
            "top_hypotheses": top_hyps,
            "quality_summary": str(parsed.get("quality_summary", "")),
            "diversity_assessment": str(parsed.get("diversity_assessment", "")),
            "evolution_effectiveness": str(parsed.get("evolution_effectiveness", "")),
            "recommended_experiments": recommended_experiments,
            "research_gaps": research_gaps,
            "final_recommendation": str(parsed.get("final_recommendation", "")),
            "confidence_level": confidence,
            "token_usage": result["token_usage"],
            "cost_usd": result["cost_usd"],
            "error": result.get("error"),
        }