"""Evolution Agent — 假设进化智能体

职责：根据 EvolutionStrategist 的决策，执行实际的假设进化操作。
- enhancement: 针对 flaws 增强假设
- combination: 融合两个假设
- simplification: 简化复杂假设

参考论文：Section "Evolution agent" + Extended Data Fig. 5
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import (
    EVOLUTION_SYSTEM,
    EVOLUTION_COMBINATION_USER,
    EVOLUTION_ENHANCEMENT_USER,
    EVOLUTION_SIMPLIFICATION_USER,
    format_flaws,
)

logger = logging.getLogger(__name__)


class EvolutionAgent(BaseAgent):
    """假设进化智能体

    用法：
        agent = EvolutionAgent(llm_client)
        # 单个进化
        result = await agent.run(
            hypothesis=hyp,
            plan=evolution_plan,
            research_goal="目标",
            partner_hypothesis=partner,  # combination 时
        )
        # result = {"evolved_hypothesis": {...}, "strategy": "...", ...}
    """

    agent_name = "evolution"

    async def run(
        self,
        hypothesis: Dict[str, Any],
        plan: Any,
        research_goal: str = "",
        partner_hypothesis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行假设进化

        Args:
            hypothesis: 待进化假设
            plan: EvolutionPlan 对象（含 strategy, flaws, complexity_issues, similarity, target_hypothesis_id）
            research_goal: 研究目标
            partner_hypothesis: 合并搭档假设（combination 策略时必需）
        Returns:
            {"evolved_hypothesis": {...}, "strategy": str, "parent_ids": [...],
             "token_usage": {...}, "cost_usd": ..., "error": ...}
        """
        strategy = getattr(plan, "strategy", "keep")
        hyp_id = str(hypothesis.get("id", hypothesis.get("name", "")))

        if strategy == "keep":
            # 无需进化，返回原假设
            return {
                "evolved_hypothesis": {**hypothesis, "evolution_strategy": "keep"},
                "strategy": "keep",
                "parent_ids": [hyp_id],
                "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                "cost_usd": 0.0,
                "error": None,
            }

        # 根据 strategy 选择 prompt
        if strategy == "enhancement":
            prompt = EVOLUTION_ENHANCEMENT_USER.format(
                research_goal=research_goal or "（未指定）",
                name=hypothesis.get("name", "未命名"),
                description=hypothesis.get("description", ""),
                mechanism=hypothesis.get("mechanism", ""),
                flaws=format_flaws(getattr(plan, "flaws", [])),
            )
        elif strategy == "combination":
            if not partner_hypothesis:
                logger.warning("[evolution] combination 策略需要 partner_hypothesis")
                return {
                    "evolved_hypothesis": {**hypothesis, "evolution_strategy": "combination_failed"},
                    "strategy": "combination",
                    "parent_ids": [hyp_id],
                    "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                    "cost_usd": 0.0,
                    "error": "missing_partner",
                }
            partner_id = str(partner_hypothesis.get("id", partner_hypothesis.get("name", "")))
            prompt = EVOLUTION_COMBINATION_USER.format(
                research_goal=research_goal or "（未指定）",
                a_name=hypothesis.get("name", "未命名"),
                a_description=hypothesis.get("description", ""),
                a_mechanism=hypothesis.get("mechanism", ""),
                b_name=partner_hypothesis.get("name", "未命名"),
                b_description=partner_hypothesis.get("description", ""),
                b_mechanism=partner_hypothesis.get("mechanism", ""),
                similarity=getattr(plan, "similarity", 0.0),
            )
        elif strategy == "simplification":
            complexity_issues = getattr(plan, "complexity_issues", [])
            issues_text = "\n".join(f"- {i}" for i in complexity_issues) if complexity_issues else "（无具体问题）"
            prompt = EVOLUTION_SIMPLIFICATION_USER.format(
                research_goal=research_goal or "（未指定）",
                name=hypothesis.get("name", "未命名"),
                description=hypothesis.get("description", ""),
                mechanism=hypothesis.get("mechanism", ""),
                complexity_issues=issues_text,
            )
        else:
            logger.warning("[evolution] 未知策略: %s", strategy)
            return {
                "evolved_hypothesis": {**hypothesis, "evolution_strategy": "keep"},
                "strategy": "keep",
                "parent_ids": [hyp_id],
                "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                "cost_usd": 0.0,
                "error": f"unknown_strategy: {strategy}",
            }

        # 调用 LLM 执行进化
        result = await self.quick(prompt, system=EVOLUTION_SYSTEM)
        parsed = self._parse_json(result["content"], default={})

        # 构造进化后假设
        parent_ids = [hyp_id]
        if strategy == "combination" and partner_hypothesis:
            parent_ids.append(str(partner_hypothesis.get("id", partner_hypothesis.get("name", ""))))

        evolved = {**hypothesis}
        # 清除旧 ID（进化后是新假设）
        evolved["id"] = None
        evolved["name"] = str(parsed.get("name", hypothesis.get("name", "进化假设")))
        evolved["description"] = str(parsed.get("description", hypothesis.get("description", "")))
        evolved["mechanism"] = str(parsed.get("mechanism", hypothesis.get("mechanism", "")))
        evolved["change_log"] = str(parsed.get("change_log", ""))
        evolved["parent_ids"] = parent_ids
        evolved["evolution_strategy"] = strategy

        # 更新评分
        for key in ("novelty", "plausibility", "testability", "safety"):
            if key in parsed:
                try:
                    evolved[f"{key}_score"] = float(parsed[key])
                except (ValueError, TypeError):
                    pass

        logger.info(
            "[evolution] 假设 %s 策略=%s (tokens=%d)",
            hyp_id, strategy, result["token_usage"]["total"],
        )

        return {
            "evolved_hypothesis": evolved,
            "strategy": strategy,
            "parent_ids": parent_ids,
            "token_usage": result["token_usage"],
            "cost_usd": result["cost_usd"],
            "error": result.get("error"),
        }

    async def run_batch(
        self,
        hypotheses: List[Dict[str, Any]],
        plans: List[Any],
        research_goal: str = "",
        hypothesis_map: Optional[Dict[str, Dict[str, Any]]] = None,
        max_concurrent: int = 3,
    ) -> List[Dict[str, Any]]:
        """批量执行进化

        Args:
            hypotheses: 假设列表（与 plans 一一对应）
            plans: EvolutionPlan 列表（与 hypotheses 一一对应）
            research_goal: 研究目标
            hypothesis_map: {hypothesis_id: hypothesis} 查找表（用于 combination 找搭档）
            max_concurrent: 最大并发
        Returns:
            进化结果列表
        """
        import asyncio

        sem = asyncio.Semaphore(max_concurrent)
        hypothesis_map = hypothesis_map or {str(h.get("id", h.get("name", ""))): h for h in hypotheses}

        async def _evolve_one(hyp, plan):
            async with sem:
                # combination 时查找搭档
                partner = None
                target_id = getattr(plan, "target_hypothesis_id", None)
                if target_id:
                    partner = hypothesis_map.get(target_id)
                return await self.run(hyp, plan, research_goal, partner_hypothesis=partner)

        tasks = [_evolve_one(h, p) for h, p in zip(hypotheses, plans)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning("[evolution] 假设 %d 进化失败: %s", i, r)
                final.append({
                    "evolved_hypothesis": {**hypotheses[i], "evolution_strategy": "failed"},
                    "strategy": "keep",
                    "parent_ids": [str(hypotheses[i].get("id", ""))],
                    "token_usage": {"total": 0},
                    "cost_usd": 0.0,
                    "error": str(r),
                })
            else:
                final.append(r)

        return final