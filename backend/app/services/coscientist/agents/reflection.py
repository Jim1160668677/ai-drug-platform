"""Reflection Agent — 假设反思/批判智能体

职责：对给定假设进行批判性分析，找出逻辑漏洞、证据不足、机制缺陷等。
输出 flaws 列表（含 severity），供 EvolutionStrategist 决策。
参考论文：Section "Reflection agent" + Extended Data Fig. 2b
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import REFLECTION_SYSTEM, REFLECTION_USER

logger = logging.getLogger(__name__)


class ReflectionAgent(BaseAgent):
    """假设反思智能体

    用法：
        agent = ReflectionAgent(llm_client)
        result = await agent.run(
            hypothesis={"id": "1", "name": "...", "description": "...", "mechanism": "..."},
            research_goal="研究目标",
            evidence="相关证据",
        )
        # result = {"flaws": [...], "strengths": [...], "overall_assessment": "...", ...}
    """

    agent_name = "reflection"

    async def run(
        self,
        hypothesis: Dict[str, Any],
        research_goal: str,
        evidence: str = "",
    ) -> Dict[str, Any]:
        """对单个假设进行批判性审查

        Args:
            hypothesis: 待审查假设（含 name/description/mechanism）
            research_goal: 研究目标
            evidence: 相关证据文本
        Returns:
            {"hypothesis_id": str, "flaws": [{"description", "severity", "category", "suggestion"}],
             "strengths": [...], "overall_assessment": str, "improvement_priority": [...],
             "token_usage": {...}, "cost_usd": ...}
        """
        hyp_id = str(hypothesis.get("id", hypothesis.get("name", "")))

        prompt = REFLECTION_USER.format(
            research_goal=research_goal,
            name=hypothesis.get("name", "未命名"),
            description=hypothesis.get("description", ""),
            mechanism=hypothesis.get("mechanism", ""),
            evidence=evidence or "（无具体证据）",
        )

        result = await self.quick(prompt, system=REFLECTION_SYSTEM)

        parsed = self._parse_json(result["content"], default={})

        # 清理 flaws 列表
        flaws = []
        for f in parsed.get("flaws", []):
            if not isinstance(f, dict):
                continue
            try:
                severity = int(f.get("severity", 5))
            except (ValueError, TypeError):
                severity = 5
            flaws.append({
                "description": str(f.get("description", "")),
                "severity": max(1, min(10, severity)),
                "category": str(f.get("category", "unknown")),
                "suggestion": str(f.get("suggestion", "")),
            })

        strengths = parsed.get("strengths", [])
        if not isinstance(strengths, list):
            strengths = [str(strengths)]

        improvement_priority = parsed.get("improvement_priority", [])
        if not isinstance(improvement_priority, list):
            improvement_priority = [str(improvement_priority)]

        logger.info(
            "[reflection] 假设 %s: 发现 %d 个缺陷（%d 个严重）(tokens=%d)",
            hyp_id, len(flaws),
            sum(1 for f in flaws if f["severity"] >= 7),
            result["token_usage"]["total"],
        )

        return {
            "hypothesis_id": hyp_id,
            "flaws": flaws,
            "strengths": strengths,
            "overall_assessment": str(parsed.get("overall_assessment", "")),
            "improvement_priority": improvement_priority,
            "token_usage": result["token_usage"],
            "cost_usd": result["cost_usd"],
            "error": result.get("error"),
        }

    async def run_batch(
        self,
        hypotheses: List[Dict[str, Any]],
        research_goal: str,
        evidence: str = "",
        max_concurrent: int = 3,
    ) -> List[Dict[str, Any]]:
        """批量反思多个假设

        Args:
            hypotheses: 假设列表
            research_goal: 研究目标
            evidence: 共享证据
            max_concurrent: 最大并发数
        Returns:
            反思结果列表（每个假设一个）
        """
        import asyncio

        sem = asyncio.Semaphore(max_concurrent)

        async def _reflect_one(hyp):
            async with sem:
                return await self.run(hyp, research_goal, evidence)

        tasks = [_reflect_one(h) for h in hypotheses]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 异常容错
        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning("[reflection] 假设 %d 反思失败: %s", i, r)
                final.append({
                    "hypothesis_id": str(hypotheses[i].get("id", "")),
                    "flaws": [],
                    "strengths": [],
                    "overall_assessment": "",
                    "improvement_priority": [],
                    "token_usage": {"total": 0},
                    "cost_usd": 0.0,
                    "error": str(r),
                })
            else:
                final.append(r)

        return final