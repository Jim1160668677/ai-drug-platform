"""IntentRouter — 意图路由层

设计来源：Nature Co-Scientist 论文的「自然语言接口」+ karpathy/autoresearch 的
「program.md 定义 agent 行为」理念。

两级路由策略：
1. Keyword 一级路由（零成本）：基于关键词规则快速匹配意图
2. LLM 二级路由（confidence < 阈值时触发）：用 LLM 精细分类

路由结果：
- chat: 简单问答（定义、解释、说明）
- reasoning: 科学推理（假设、辩论、排名、进化）
- agent: 工具调用（搜索、查询、上传、分析靶点）
- hybrid: 混合模式（需先调工具再推理）

autoresearch 整合：类似 program.md 定义 agent 行为，本路由器定义用户意图到模式的映射。
"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """意图路由结果"""
    mode: str          # chat / reasoning / agent / hybrid
    confidence: float  # 0-1
    reason: str        # 路由原因
    method: str        # keyword / llm / default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reason": self.reason,
            "method": self.method,
        }


class IntentRouter:
    """意图路由器 — keyword 一级 + LLM 二级

    用法：
        router = IntentRouter(llm_client)
        result = await router.route("帮我分析这个靶点的功能")
        # result.mode == "agent", result.confidence == 0.8
    """

    # ========== Keyword 规则（一级路由，零成本） ==========

    # reasoning 关键词：假设/推理/辩论/排名/进化/科学
    REASONING_KEYWORDS = {
        "假设", "推理", "辩论", "排名", "进化", "科学推理", "生成假设",
        "hypothesis", "reasoning", "debate", "ranking", "evolution",
        "elo", "tournament", "co-scientist", "多智能体",
    }

    # agent 关键词：搜索/查询/工具/上传/分析/发现
    AGENT_KEYWORDS = {
        "搜索", "查询", "查找", "工具", "上传", "解析", "分析靶点",
        "药物重定位", "分子设计", "对接", "docking", "靶点发现",
        "discover", "repurpose", "design", "search", "query",
        "上传数据", "解析数据", "质控", "差异表达", "聚类",
    }

    # chat 关键词：定义/解释/说明/什么是
    CHAT_KEYWORDS = {
        "什么是", "解释", "说明", "定义", "介绍一下", "区别",
        "what is", "explain", "describe", "define", "difference",
    }

    # hybrid 关键词：分析+假设（需先调工具再推理）
    HYBRID_KEYWORDS = {
        "分析并生成假设", "发现靶点并推理", "搜索并辩论",
    }

    def __init__(self, llm_client: Optional[Any] = None):
        """初始化意图路由器

        Args:
            llm_client: LLM 客户端（可选，用于二级路由。None 时仅用 keyword）
        """
        self.llm_client = llm_client
        self._threshold = getattr(settings, "INTELLIGENCE_INTENT_LLM_THRESHOLD", 0.7)

    async def route(
        self,
        message: str,
        force_mode: Optional[str] = None,
        chat_round_count: int = 0,
    ) -> IntentResult:
        """路由用户消息到合适的模式

        Args:
            message: 用户消息
            force_mode: 强制模式（用户手动切换时），跳过路由
            chat_round_count: 当前会话连续 chat 轮数（超过阈值自动建议升级 reasoning）

        Returns:
            IntentResult: 路由结果
        """
        # 0. 强制模式优先
        if force_mode and force_mode != "auto":
            return IntentResult(
                mode=force_mode,
                confidence=1.0,
                reason=f"用户强制指定模式: {force_mode}",
                method="force",
            )

        # 1. Keyword 一级路由
        result = self._keyword_route(message)

        # 2. 连续追问升级建议
        if (
            result.mode == "chat"
            and chat_round_count >= getattr(settings, "INTELLIGENCE_CHAT_UPGRADE_THRESHOLD", 3)
        ):
            return IntentResult(
                mode="reasoning",
                confidence=0.6,
                reason=f"连续 chat {chat_round_count} 轮，自动建议升级 reasoning",
                method="upgrade",
            )

        # 3. Keyword 置信度足够，直接返回
        if result.confidence >= self._threshold:
            return result

        # 4. LLM 二级路由（keyword 不确定时）
        if self.llm_client is not None:
            llm_result = await self._llm_route(message)
            if llm_result and llm_result.confidence >= self._threshold:
                return llm_result

        # 5. 降级为 chat（最安全的选择）
        return IntentResult(
            mode="chat",
            confidence=0.5,
            reason="keyword 和 LLM 路由均不确定，降级为 chat",
            method="default",
        )

    def _keyword_route(self, message: str) -> IntentResult:
        """Keyword 一级路由（零成本）"""
        msg_lower = message.lower()

        # 检查 hybrid（最高优先级）
        for kw in self.HYBRID_KEYWORDS:
            if kw in msg_lower:
                return IntentResult(
                    mode="hybrid",
                    confidence=0.85,
                    reason=f"匹配 hybrid 关键词: {kw}",
                    method="keyword",
                )

        # 检查 reasoning
        reasoning_hits = sum(1 for kw in self.REASONING_KEYWORDS if kw in msg_lower)
        if reasoning_hits > 0:
            return IntentResult(
                mode="reasoning",
                confidence=min(0.6 + reasoning_hits * 0.15, 0.95),
                reason=f"匹配 reasoning 关键词 {reasoning_hits} 个",
                method="keyword",
            )

        # 检查 agent
        agent_hits = sum(1 for kw in self.AGENT_KEYWORDS if kw in msg_lower)
        if agent_hits > 0:
            return IntentResult(
                mode="agent",
                confidence=min(0.6 + agent_hits * 0.15, 0.95),
                reason=f"匹配 agent 关键词 {agent_hits} 个",
                method="keyword",
            )

        # 检查 chat
        chat_hits = sum(1 for kw in self.CHAT_KEYWORDS if kw in msg_lower)
        if chat_hits > 0:
            return IntentResult(
                mode="chat",
                confidence=min(0.65 + chat_hits * 0.1, 0.9),
                reason=f"匹配 chat 关键词 {chat_hits} 个",
                method="keyword",
            )

        # 无匹配
        return IntentResult(
            mode="chat",
            confidence=0.3,
            reason="无 keyword 匹配，默认 chat",
            method="keyword",
        )

    async def _llm_route(self, message: str) -> Optional[IntentResult]:
        """LLM 二级路由（keyword 不确定时触发）

        用 LLM 对用户消息进行意图分类，返回 mode + confidence。
        """
        prompt = f"""请对以下用户消息进行意图分类，返回 JSON 格式。

用户消息：{message[:500]}

分类类别：
- chat: 简单问答（定义、解释、说明类问题）
- reasoning: 科学推理（需要生成假设、辩论、排名、进化等复杂推理）
- agent: 工具调用（需要搜索、查询数据库、上传数据、分析靶点等工具操作）
- hybrid: 混合模式（需要先调用工具获取数据，再进行推理分析）

请返回 JSON：
{{"mode": "chat|reasoning|agent|hybrid", "confidence": 0.0-1.0, "reason": "简短原因"}}"""

        try:
            from app.services.llm.router import LLMRouter
            router = LLMRouter(self.llm_client)
            response = await router.complete(
                messages=[{"role": "user", "content": prompt}],
                model=settings.LLM_MODEL_FAST,
                temperature=0.1,
                max_tokens=200,
            )

            content = response.content if hasattr(response, "content") else str(response)
            # 尝试解析 JSON
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            data = json.loads(content)
            mode = data.get("mode", "chat")
            confidence = float(data.get("confidence", 0.5))
            reason = data.get("reason", "LLM 二级路由")

            # 验证 mode 合法性
            if mode not in ("chat", "reasoning", "agent", "hybrid"):
                mode = "chat"
                confidence = 0.5

            return IntentResult(
                mode=mode,
                confidence=confidence,
                reason=f"LLM 路由: {reason}",
                method="llm",
            )
        except Exception as e:
            logger.warning("LLM 二级路由失败: %s", e)
            return None

    def suggest_tier(
        self,
        message: str,
        intent_mode: str,
        intent_confidence: float,
        force_tier: Optional[str] = None,
    ) -> str:
        """根据消息复杂度和意图模式推荐推理档位

        自动选择策略：
        - reasoning/hybrid + 高置信度 → deep
        - reasoning/hybrid + 中等置信度 → standard
        - agent → standard
        - chat → turbo
        - 用户显式指定 → 直接使用

        Args:
            message: 用户消息
            intent_mode: 意图模式
            intent_confidence: 意图置信度
            force_tier: 强制档位（覆盖自动选择）

        Returns:
            档位名 (turbo/standard/deep)
        """
        if force_tier and force_tier != "auto":
            valid = ("turbo", "standard", "deep")
            if force_tier in valid:
                return force_tier

        complexity_score = self._estimate_complexity(message)

        if intent_mode in ("reasoning", "hybrid"):
            if intent_confidence >= 0.85 and complexity_score >= 0.4:
                return "deep"
            return "standard"

        if intent_mode == "agent":
            return "standard"

        if complexity_score >= 0.7:
            return "standard"

        return "turbo"

    @staticmethod
    def _estimate_complexity(message: str) -> float:
        """估算消息复杂度（0-1）

        基于：
        - 消息长度
        - 问句数量
        - 多维度关键词
        - 专业术语密度

        Args:
            message: 用户消息

        Returns:
            复杂度分数 0-1
        """
        if not message:
            return 0.0

        score = 0.0

        length = len(message)
        if length > 500:
            score += 0.3
        elif length > 200:
            score += 0.15

        question_marks = message.count("?") + message.count("？")
        if question_marks >= 3:
            score += 0.25
        elif question_marks >= 1:
            score += 0.1

        multi_part = sum(1 for kw in ["并且", "同时", "以及", "另外", "然后", "此外", ";"] if kw in message)
        if multi_part >= 2:
            score += 0.2
        elif multi_part >= 1:
            score += 0.1

        domain_terms = sum(
            1 for term in ["靶点", "机制", "通路", "信号", "假设", "推理", "分析", "设计", "优化"]
            if term in message
        )
        if domain_terms >= 3:
            score += 0.25
        elif domain_terms >= 1:
            score += 0.1

        return min(1.0, score)

    @staticmethod
    def budget_aware_tier(
        suggested_tier: str,
        budget_remaining: Optional[float] = None,
        daily_budget_limit: float = 10.0,
    ) -> Tuple[str, Optional[str]]:
        """根据预算约束调整推荐档位（预算驱动的主动分级）

        当用户预算接近或触顶时，平滑降档而非硬中断。
        对应 v2.0 建议五：成本感知分级推理。

        降档策略：
        - 预算 > 50% 限额：保持推荐档位
        - 预算 20-50%：deep → standard，standard 不变
        - 预算 < 20%：deep → standard → turbo
        - 预算耗尽：仅 turbo 档可用

        Args:
            suggested_tier: suggest_tier() 推荐的档位
            budget_remaining: 用户剩余预算（美元），None 表示无限制
            daily_budget_limit: 日预算上限（美元）

        Returns:
            (最终档位, 预算提示信息或 None)
        """
        if budget_remaining is None:
            return suggested_tier, None

        budget_ratio = budget_remaining / daily_budget_limit if daily_budget_limit > 0 else 1.0

        if budget_ratio > 0.5:
            return suggested_tier, None

        if budget_ratio > 0.2:
            if suggested_tier == "deep":
                return "standard", f"预算提示：剩余 ${budget_remaining:.2f}（{budget_ratio:.0%}），已降为标准分析档"
            return suggested_tier, None

        # 预算 < 20%：强制降为 turbo 或 standard
        if suggested_tier in ("deep", "standard"):
            return "turbo", f"预算告警：剩余 ${budget_remaining:.2f}（{budget_ratio:.0%}），已降为快速筛查档"
        return "turbo", None
