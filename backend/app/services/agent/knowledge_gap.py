"""知识盲区检测器 — 连续无结果时自动触发网络搜索

设计来源：2026-07-28 Agent 增强（自主决策能力提升）

核心职责：
1. 跟踪最近 N 步的工具观察结果
2. 检测知识盲区模式（连续空结果/循环推理/结果与问题无关）
3. 生成网络搜索建议（自动触发 web_search 工具）
4. 支持启发式 + LLM 双模式检测

集成点：
- AgentEngine 每步工具调用后调用 detector.observe()
- 检测到盲区时返回 GapDetected，引擎注入 web_search 建议
"""
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.agent.prompts import KNOWLEDGE_GAP_DETECTION_PROMPT

logger = logging.getLogger(__name__)


class GapType(str, Enum):
    """知识盲区类型"""

    NONE = "none"                            # 无盲区
    NO_RESULTS = "no_results"                # 连续无结果
    IRRELEVANT_RESULTS = "irrelevant_results"  # 结果与问题无关
    CIRCULAR_REASONING = "circular_reasoning"  # 循环推理（兜圈子）


@dataclass
class ObservationRecord:
    """单步观察记录"""

    step: int
    tool: str
    success: bool
    data_summary: str   # 结果摘要（前 200 字符）
    error: Optional[str] = None

    @property
    def is_empty_result(self) -> bool:
        """是否为空结果"""
        if not self.success:
            return False  # 失败不算空结果
        if not self.data_summary:
            return True
        lower = self.data_summary.lower()
        # 检测空结果模式
        empty_indicators = [
            "0 条", "0 个", "无结果", "未找到", "未发现", "empty",
            "no result", "no data", "no match", "[]", "{}",
            "未检索到", "无相关",
            "total=0", "count=0", "total: 0", "count: 0",
        ]
        return any(ind in lower for ind in empty_indicators)


@dataclass
class GapDetectionResult:
    """盲区检测结果"""

    is_knowledge_gap: bool
    confidence: float
    reasoning: str
    gap_type: GapType = GapType.NONE
    suggested_search_query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_knowledge_gap": self.is_knowledge_gap,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "gap_type": self.gap_type.value,
            "suggested_search_query": self.suggested_search_query,
        }


class KnowledgeGapDetector:
    """知识盲区检测器

    Usage:
        detector = KnowledgeGapDetector(llm_router)

        # 每步工具调用后记录观察
        detector.observe(step=1, tool="search_literature", success=True, data=results)

        # 检测是否处于盲区
        result = await detector.detect(query="...", threshold=2)
        if result.is_knowledge_gap:
            # 注入 web_search 建议到 observation
            observation += f"\n\n建议: {result.suggested_search_query}"
    """

    def __init__(self, llm_router=None, window_size: Optional[int] = None):
        """
        Args:
            llm_router: LLMRouter（可选，提供时用 LLM 深度检测）
            window_size: 观察窗口大小（默认取 settings.AGENT_KNOWLEDGE_GAP_THRESHOLD）
        """
        self.llm_router = llm_router
        self.window_size = window_size or getattr(
            settings, "AGENT_KNOWLEDGE_GAP_THRESHOLD", 2
        )
        self._observations: List[ObservationRecord] = []

    def observe(
        self,
        step: int,
        tool: str,
        success: bool,
        data: Any = None,
        error: Optional[str] = None,
    ) -> None:
        """记录一步观察结果

        Args:
            step: 步骤序号
            tool: 工具名
            success: 是否成功
            data: 返回数据
            error: 错误信息
        """
        # 生成数据摘要
        if data is None:
            data_summary = ""
        elif isinstance(data, dict):
            # 提取关键字段
            total = data.get("total", data.get("count", None))
            if total is not None:
                data_summary = f"total={total}"
            else:
                data_summary = json.dumps(data, ensure_ascii=False, default=str)[:200]
        elif isinstance(data, list):
            data_summary = f"list[{len(data)}]"
        else:
            data_summary = str(data)[:200]

        record = ObservationRecord(
            step=step,
            tool=tool,
            success=success,
            data_summary=data_summary,
            error=error,
        )
        self._observations.append(record)

        # 保留最近 window_size * 2 条
        max_keep = max(self.window_size * 2, 10)
        if len(self._observations) > max_keep:
            self._observations = self._observations[-max_keep:]

    async def detect(
        self,
        query: str,
        threshold: Optional[int] = None,
    ) -> GapDetectionResult:
        """检测是否处于知识盲区

        Args:
            query: 用户原始问题
            threshold: 连续空结果触发阈值

        Returns:
            GapDetectionResult
        """
        if not self._observations:
            return GapDetectionResult(
                is_knowledge_gap=False,
                confidence=0.0,
                reasoning="无观察数据",
            )

        threshold = threshold or self.window_size

        # 启发式检测（无需 LLM，快速）
        heuristic = self._heuristic_detect(query, threshold)
        if heuristic and not heuristic.is_knowledge_gap:
            # 启发式明确判断无盲区，直接返回
            return heuristic

        # 启发式检测到盲区 → 用 LLM 确认并生成搜索建议
        if heuristic and heuristic.is_knowledge_gap:
            if self.llm_router is None:
                return heuristic
            # LLM 深度分析，生成更精准的搜索词
            try:
                llm_result = await self._llm_detect(query)
                # 若 LLM 解析成功且也判断为盲区，用 LLM 结果（搜索词更精准）
                if llm_result.is_knowledge_gap:
                    return llm_result
                # 若 LLM 判断无盲区，仍用启发式结果（保守策略）
                return heuristic
            except Exception as e:
                logger.warning(f"LLM 盲区检测失败，降级启发式: {e}")
                return heuristic

        # 启发式无法判断 → 用 LLM
        if self.llm_router is None:
            return GapDetectionResult(
                is_knowledge_gap=False,
                confidence=0.3,
                reasoning="数据不足，无法判断",
            )

        try:
            return await self._llm_detect(query)
        except Exception as e:
            logger.warning(f"LLM 盲区检测失败: {e}")
            return GapDetectionResult(
                is_knowledge_gap=False,
                confidence=0.0,
                reasoning=f"检测异常: {e}",
            )

    def _heuristic_detect(
        self,
        query: str,
        threshold: int,
    ) -> Optional[GapDetectionResult]:
        """启发式盲区检测

        检测模式：
        1. 连续 N 次空结果 → NO_RESULTS
        2. 重复调用同一工具 → CIRCULAR_REASONING
        3. 所有结果都是失败 → 无盲区（是工具问题，不是知识盲区）
        """
        recent = self._observations[-(threshold + 2):]  # 多取几步做上下文
        if len(recent) < threshold:
            return None

        # 模式 1：连续空结果
        last_n = recent[-threshold:]
        empty_count = sum(1 for r in last_n if r.is_empty_result)
        if empty_count >= threshold:
            # 生成搜索建议：从用户问题提取关键词
            search_query = self._extract_search_query(query)
            return GapDetectionResult(
                is_knowledge_gap=True,
                confidence=0.85,
                reasoning=f"连续 {empty_count}/{len(last_n)} 步返回空结果",
                gap_type=GapType.NO_RESULTS,
                suggested_search_query=search_query,
            )

        # 模式 2：循环推理（同一工具被重复调用 3+ 次且参数相似）
        if len(self._observations) >= 3:
            recent_tools = [r.tool for r in self._observations[-4:]]
            if len(recent_tools) >= 3 and recent_tools[-1] == recent_tools[-3]:
                # 连续调用同一工具，可能是循环
                if any(r.is_empty_result for r in last_n):
                    search_query = self._extract_search_query(query)
                    return GapDetectionResult(
                        is_knowledge_gap=True,
                        confidence=0.7,
                        reasoning=f"检测到循环调用工具 {recent_tools[-1]}",
                        gap_type=GapType.CIRCULAR_REASONING,
                        suggested_search_query=search_query,
                    )

        # 模式 3：所有工具都成功且有结果 → 无盲区
        all_success = all(r.success for r in last_n)
        any_data = any(
            not r.is_empty_result for r in last_n if r.success
        )
        if all_success and any_data:
            return GapDetectionResult(
                is_knowledge_gap=False,
                confidence=0.8,
                reasoning="最近步骤有有效结果，无盲区",
            )

        return None  # 无法判断

    def _extract_search_query(self, query: str) -> str:
        """从用户问题提取网络搜索查询词

        策略：
        1. 移除无意义词（的、了、是、请等）
        2. 提取关键词（基因名、药物名、疾病名）
        3. 限制长度
        """
        if not query:
            return ""

        # 移除常见无意义词
        stop_words = {
            "的", "了", "是", "请", "帮我", "帮忙", "什么", "怎么",
            "如何", "为什么", "哪些", "哪个", "有没有", "是不是",
            "可以", "能够", "应该", "需要", "一个", "这个", "那个",
            "查询", "一下", "请问", "帮", "我",
        }

        import re

        # 按空格和标点分词（同时处理中英文）
        # 使用 re.split 分割，然后逐字符过滤停用词
        raw_tokens = re.split(r"[\s,，。！？、；：()（）\[\]]+", query)
        tokens = [t for t in raw_tokens if t and t.strip()]

        keywords = []
        for token in tokens:
            # 对每个 token，移除其中的停用词字符
            cleaned = token
            for sw in stop_words:
                cleaned = cleaned.replace(sw, " ")
            # 重新分割清理后的 token
            sub_tokens = cleaned.split()
            for st in sub_tokens:
                if st and len(st) > 1 and st.lower() not in stop_words:
                    keywords.append(st)

        # 限制关键词数和长度
        search_query = " ".join(keywords[:5])
        return search_query[:200]

    async def _llm_detect(self, query: str) -> GapDetectionResult:
        """用 LLM 深度检测知识盲区"""
        # 构造观察摘要
        observations_text = "\n".join(
            f"- 步骤{r.step} {r.tool}: success={r.success}, "
            f"data={r.data_summary[:100]}, error={r.error or '无'}"
            for r in self._observations[-5:]
        )

        prompt = KNOWLEDGE_GAP_DETECTION_PROMPT.format(
            query=query[:500],
            window_size=self.window_size,
            observations=observations_text[:2000],
        )

        result = await self.llm_router.quick(
            prompt, system="你是知识盲区检测器。"
        )
        content = result.get("content", "")

        return self._parse_detection(content)

    def _parse_detection(self, content: str) -> GapDetectionResult:
        """解析 LLM 检测输出"""
        parsed = None
        if "```" in content:
            parts = content.split("```")
            for i, p in enumerate(parts):
                if i % 2 == 1:
                    p = p.strip()
                    if p.startswith("json"):
                        p = p[4:].strip()
                    try:
                        parsed = json.loads(p)
                        break
                    except json.JSONDecodeError:
                        continue
        if parsed is None:
            try:
                parsed = json.loads(content.strip())
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if 0 <= start < end:
                    try:
                        parsed = json.loads(content[start : end + 1])
                    except json.JSONDecodeError:
                        pass

        if not parsed or not isinstance(parsed, dict):
            logger.warning(f"盲区检测输出解析失败: {content[:200]}")
            return GapDetectionResult(
                is_knowledge_gap=False,
                confidence=0.2,
                reasoning="LLM 输出解析失败",
            )

        try:
            gap_type = GapType(parsed.get("gap_type", "none"))
        except (ValueError, TypeError):
            gap_type = GapType.NONE

        return GapDetectionResult(
            is_knowledge_gap=bool(parsed.get("is_knowledge_gap", False)),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("reasoning", ""),
            gap_type=gap_type,
            suggested_search_query=parsed.get("suggested_search_query", ""),
        )

    def reset(self) -> None:
        """重置观察记录（用于新任务）"""
        self._observations.clear()


__all__ = [
    "KnowledgeGapDetector",
    "GapDetectionResult",
    "GapType",
    "ObservationRecord",
]
