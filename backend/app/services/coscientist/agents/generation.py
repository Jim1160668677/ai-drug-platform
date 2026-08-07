"""Generation Agent — 假设生成智能体

职责：基于研究目标和证据，生成多个多样化、创新的科学假设。
参考论文：Section "Generation agent" + Extended Data Fig. 2a

增强（v2.0 建议二+四+五）：
- 集成 WrongPathAvoider：生成前查询失败知识库，注入规避建议
- 支持证据片段溯源：将 snippets_kept 注入 evidence
- 支持预算感知：根据可用预算调整生成策略
"""
import logging
from typing import Any, Dict, List, Optional

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import (
    GENERATION_SYSTEM,
    GENERATION_USER,
    format_existing_hypotheses,
)

logger = logging.getLogger(__name__)


class GenerationAgent(BaseAgent):
    """假设生成智能体

    用法：
        agent = GenerationAgent(llm_client)
        result = await agent.run(
            research_goal="研究目标",
            count=5,
            existing_hypotheses=[...],
            evidence="相关证据",
        )
        # result = {"hypotheses": [...], "token_usage": {...}, "cost_usd": ...}

    v2.0 增强：
        result = await agent.run(
            ...,
            project_id="xxx",      # 启用失败知识查询
            target_id="yyy",        # 可选：按靶点过滤失败记录
            budget_remaining=2.0,   # 可选：剩余预算（美元），影响生成策略
        )
    """

    agent_name = "generation"

    # 预算阈值常量（美元）
    BUDGET_LOW_THRESHOLD = 1.0   # 低于此值切换为 turbo 模式
    BUDGET_CRITICAL_THRESHOLD = 0.3  # 低于此值只生成 2 个假设

    async def run(
        self,
        research_goal: str,
        count: int = 5,
        existing_hypotheses: Optional[List[Dict[str, Any]]] = None,
        evidence: str = "",
        context: str = "",
        project_id: Optional[str] = None,
        target_id: Optional[str] = None,
        budget_remaining: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成科学假设

        Args:
            research_goal: 研究目标（自然语言）
            count: 生成假设数量（3-10）
            existing_hypotheses: 已有假设列表（避免重复）
            evidence: 相关证据文本
            context: 额外上下文（如工具检索结果）
            project_id: 项目 ID（启用失败知识查询）
            target_id: 靶点 ID（按靶点过滤失败记录）
            budget_remaining: 剩余预算美元数，用于自适应调整
        Returns:
            {"hypotheses": [...], "token_usage": {...}, "cost_usd": ...}
        """
        existing_hypotheses = existing_hypotheses or []

        # ---- 预算感知自适应调整 ----
        effective_count = count
        budget_notice = ""
        if budget_remaining is not None:
            if budget_remaining <= self.BUDGET_CRITICAL_THRESHOLD:
                effective_count = min(count, 2)
                budget_notice = f"[预算告警] 剩余预算 ${budget_remaining:.2f}，已自动降至 {effective_count} 个假设"
            elif budget_remaining <= self.BUDGET_LOW_THRESHOLD:
                effective_count = min(count, 3)
                budget_notice = f"[预算提示] 剩余预算 ${budget_remaining:.2f}，已调整为 {effective_count} 个假设"

        # ---- 失败知识查询（WrongPathAvoider 集成）----
        failure_context = ""
        if project_id:
            try:
                failure_context = await self._query_failure_knowledge(
                    project_id, target_id
                )
            except Exception as e:
                logger.warning("[generation] 失败知识查询失败: %s", e)

        # 合并 evidence 和 context
        full_evidence = evidence
        if failure_context:
            full_evidence = (
                f"{full_evidence}\n\n⚠ 历史失败记录（此路不通）:\n{failure_context}"
                if full_evidence
                else f"⚠ 历史失败记录（此路不通）:\n{failure_context}"
            )
        if context:
            full_evidence = f"{full_evidence}\n\n额外上下文:\n{context}" if full_evidence else context
        if budget_notice:
            full_evidence = (
                f"{budget_notice}\n\n{full_evidence}" if full_evidence else budget_notice
            )

        prompt = GENERATION_USER.format(
            research_goal=research_goal,
            existing_hypotheses=format_existing_hypotheses(existing_hypotheses),
            evidence=full_evidence or "（无具体证据）",
            count=count,
        )

        result = await self.quick(prompt, system=GENERATION_SYSTEM)

        parsed = self._parse_json(result["content"], default={})
        hypotheses = parsed.get("hypotheses", []) if isinstance(parsed, dict) else []

        # 确保每个假设有必要字段
        cleaned = []
        for h in hypotheses:
            if not isinstance(h, dict):
                continue
            cleaned.append({
                "name": h.get("name", "未命名假设"),
                "description": h.get("description", ""),
                "mechanism": h.get("mechanism", ""),
                "novelty_score": float(h.get("novelty", 5.0)),
                "plausibility_score": float(h.get("plausibility", 5.0)),
                "testability_score": float(h.get("testability", 5.0)),
                "safety_score": float(h.get("safety", 8.0)),
                "key_evidence": h.get("key_evidence", []),
                "evolution_strategy": "initial",
            })

        logger.info(
            "[generation] 生成 %d/%d 个假设 (tokens=%d, cost=$%.4f, budget=%.2f)",
            len(cleaned), effective_count,
            result["token_usage"]["total"], result["cost_usd"],
            budget_remaining or 0.0,
        )

        return {
            "hypotheses": cleaned,
            "token_usage": result["token_usage"],
            "cost_usd": result["cost_usd"],
            "error": result.get("error"),
            "budget_notice": budget_notice,
            "failure_context_included": bool(failure_context),
        }

    async def _query_failure_knowledge(
        self,
        project_id: str,
        target_id: Optional[str] = None,
    ) -> str:
        """查询项目相关的失败知识，返回规避建议文本

        集成 WrongPathAvoider：在假设生成前检索历史失败记录，
        将高置信度的失败模式注入生成上下文，避免重蹈覆辙。

        Args:
            project_id: 项目 ID
            target_id: 可选，靶点 ID 过滤

        Returns:
            格式化的失败建议文本，无失败记录时返回空字符串
        """
        from uuid import UUID as UUIDType
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        try:
            db = getattr(self, '_db', None)
            if db is None:
                return ""

            avoider = WrongPathAvoider(db)
            suggestions = await avoider.query_failures(
                project_id=UUIDType(project_id),
                target_id=UUIDType(target_id) if target_id else None,
            )

            if not suggestions:
                return ""

            # 只取 Top-3 高价值建议
            top = suggestions[:3]
            lines = []
            for i, s in enumerate(top, 1):
                lines.append(f"  {i}. [{s['failure_reason']}] {s['suggestion']}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning("[generation] _query_failure_knowledge 异常: %s", e)
            return ""