"""工具失败反思器 — 分析失败原因并生成恢复建议

设计来源：2026-07-28 Agent 增强（自主决策能力提升）

核心职责：
1. 当工具调用失败时，分析失败原因（参数错误/权限/网络/数据不存在/超时）
2. 通过 LLM 生成恢复策略（重试/切换工具/放弃/升级用户）
3. 生成简洁的 observation 文本传给下一步 ReAct
4. 跟踪反思次数，防止死循环（默认最大 2 次）

集成点：AgentEngine.run() 工具调用失败后调用 Reflector.reflect()
"""
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.agent.prompts import REFLECTION_PROMPT

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """工具失败错误分类"""

    PARAM_ERROR = "param_error"            # 参数错误（必填缺失/类型不符/值非法）
    PERMISSION_DENIED = "permission_denied"  # 权限不足
    NETWORK_ERROR = "network_error"        # 网络异常（超时/连接失败/HTTP 5xx）
    NOT_FOUND = "not_found"                # 数据不存在（空结果/ID 无效）
    INTERNAL_ERROR = "internal_error"      # 工具内部逻辑错误
    TIMEOUT = "timeout"                    # 执行超时
    VALIDATION_ERROR = "validation_error"  # 业务校验失败（如类药性不达标）
    UNKNOWN = "unknown"                    # 未知错误


class RecoveryStrategy(str, Enum):
    """恢复策略"""

    RETRY_WITH_FIXED_PARAMS = "retry_with_fixed_params"  # 用修正后的参数重试
    SWITCH_TOOL = "switch_tool"                         # 切换到替代工具
    GIVE_UP = "give_up"                                  # 放弃，生成最终答案
    ESCALATE_TO_USER = "escalate_to_user"               # 升级给用户（如权限不足）


@dataclass
class ReflectionResult:
    """反思结果"""

    failure_analysis: str
    error_category: ErrorCategory
    is_retryable: bool
    recovery_strategy: RecoveryStrategy
    suggested_next_action: str
    suggested_tool: str = ""
    suggested_params_hint: str = ""
    observation_for_llm: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_analysis": self.failure_analysis,
            "error_category": self.error_category.value,
            "is_retryable": self.is_retryable,
            "recovery_strategy": self.recovery_strategy.value,
            "suggested_next_action": self.suggested_next_action,
            "suggested_tool": self.suggested_tool,
            "suggested_params_hint": self.suggested_params_hint,
            "observation_for_llm": self.observation_for_llm,
        }


class Reflector:
    """工具失败反思器

    Usage:
        reflector = Reflector(llm_router)
        result = await reflector.reflect(
            query="...",
            tool_name="discover_targets",
            tool_args={"project_id": "xxx"},
            error="项目不存在",
            recent_steps=[...],
            available_tools=[...],
            retry_count=0,
        )
        if result.recovery_strategy == RecoveryStrategy.RETRY_WITH_FIXED_PARAMS:
            # 用建议的参数重试
            ...
    """

    def __init__(self, llm_router=None):
        """
        Args:
            llm_router: LLMRouter 实例（可选）；为 None 时走启发式规则
        """
        self.llm_router = llm_router
        self.max_retries = getattr(settings, "AGENT_REFLECTION_MAX_RETRIES", 2)

    async def reflect(
        self,
        query: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        error: str,
        recent_steps: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]],
        retry_count: int = 0,
    ) -> ReflectionResult:
        """分析工具失败并生成恢复建议

        Args:
            query: 用户原始问题
            tool_name: 失败的工具名
            tool_args: 调用参数
            error: 错误信息
            recent_steps: 最近的推理步骤（用于上下文）
            available_tools: 可用工具列表
            retry_count: 当前已重试次数

        Returns:
            ReflectionResult
        """
        # 超过最大重试次数直接放弃
        if retry_count >= self.max_retries:
            return ReflectionResult(
                failure_analysis=f"已超过最大重试次数 {self.max_retries}，放弃重试",
                error_category=ErrorCategory.UNKNOWN,
                is_retryable=False,
                recovery_strategy=RecoveryStrategy.GIVE_UP,
                suggested_next_action="放弃重试，基于现有信息生成最终答案",
                observation_for_llm=(
                    f"工具 {tool_name} 已连续失败 {retry_count + 1} 次，"
                    f"最后错误: {error[:200]}。请基于已有信息直接给出最终答案。"
                ),
            )

        # 优先用启发式规则快速分类（无需 LLM 调用，降低延迟）
        heuristic = self._heuristic_classify(tool_name, tool_args, error)
        if heuristic is not None and heuristic.is_retryable is False:
            # 不可重试的错误直接返回（如权限不足）
            return heuristic

        # 无 LLM 或启发式无法判断 → 走启发式
        if self.llm_router is None:
            return heuristic or self._default_reflection(
                tool_name, tool_args, error, retry_count
            )

        # 用 LLM 深度分析
        try:
            result = await self._llm_reflect(
                query=query,
                tool_name=tool_name,
                tool_args=tool_args,
                error=error,
                recent_steps=recent_steps,
                available_tools=available_tools,
                retry_count=retry_count,
            )
            return result
        except Exception as e:
            logger.warning(f"LLM 反思失败，降级到启发式: {e}")
            return heuristic or self._default_reflection(
                tool_name, tool_args, error, retry_count
            )

    def _heuristic_classify(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        error: str,
    ) -> Optional[ReflectionResult]:
        """启发式错误分类（无需 LLM）

        基于 error 文本模式匹配快速分类常见错误。

        Returns:
            ReflectionResult 或 None（无法判断时）
        """
        if not error:
            return None

        error_lower = error.lower()

        # 1. 权限不足 — 不可重试
        if any(kw in error_lower for kw in (
            "无权使用", "权限", "permission", "forbidden", "unauthorized"
        )):
            return ReflectionResult(
                failure_analysis=f"用户权限不足，无法使用工具 {tool_name}",
                error_category=ErrorCategory.PERMISSION_DENIED,
                is_retryable=False,
                recovery_strategy=RecoveryStrategy.ESCALATE_TO_USER,
                suggested_next_action="提示用户当前角色无权使用该工具",
                observation_for_llm=(
                    f"工具 {tool_name} 因权限不足被拒绝。"
                    f"请在最终答案中告知用户需要更高权限（如研究员角色）。"
                ),
            )

        # 2. 参数缺失/类型错误 — 可重试
        if any(kw in error_lower for kw in (
            "缺少必填参数", "参数类型错误", "参数", "param", "required"
        )):
            return ReflectionResult(
                failure_analysis=f"参数错误: {error[:100]}",
                error_category=ErrorCategory.PARAM_ERROR,
                is_retryable=True,
                recovery_strategy=RecoveryStrategy.RETRY_WITH_FIXED_PARAMS,
                suggested_next_action="修正参数后重试",
                suggested_params_hint="检查参数类型和必填字段",
                observation_for_llm=(
                    f"工具 {tool_name} 参数校验失败: {error[:200]}。"
                    f"请检查参数格式并重试。"
                ),
            )

        # 3. 超时（在"网络异常"之前检查，因为超时可能含 timeout 关键词）
        if any(kw in error_lower for kw in (
            "超时", "timeout", "timed out", "execution timeout"
        )):
            return ReflectionResult(
                failure_analysis=f"工具执行超时: {error[:100]}",
                error_category=ErrorCategory.TIMEOUT,
                is_retryable=True,
                recovery_strategy=RecoveryStrategy.RETRY_WITH_FIXED_PARAMS,
                suggested_next_action="减少数据量或缩小查询范围后重试",
                suggested_params_hint="减少 retmax/limit 参数",
                observation_for_llm=(
                    f"工具 {tool_name} 执行超时: {error[:200]}。"
                    f"建议缩小查询范围（如减少返回数量）后重试。"
                ),
            )

        # 4. 网络异常 — 可重试（排除超时类关键词）
        if any(kw in error_lower for kw in (
            "connection", "connect", "network",
            "503", "502", "500", "connectionerror", "networkerror"
        )):
            return ReflectionResult(
                failure_analysis=f"网络异常: {error[:100]}",
                error_category=ErrorCategory.NETWORK_ERROR,
                is_retryable=True,
                recovery_strategy=RecoveryStrategy.RETRY_WITH_FIXED_PARAMS,
                suggested_next_action="网络异常，稍后重试或切换数据源",
                suggested_params_hint="无需修改参数，直接重试",
                observation_for_llm=(
                    f"工具 {tool_name} 因网络异常失败: {error[:200]}。"
                    f"可重试或改用其他工具（如 search_ncbi 替代 search_literature）。"
                ),
            )

        # 5. 数据不存在 — 不可重试，建议切换工具
        if any(kw in error_lower for kw in (
            "不存在", "未找到", "not found", "未发现", "空结果", "no result", "empty"
        )):
            # 根据工具类型建议替代方案
            alt_tool = self._suggest_alternative_tool(tool_name)
            strategy = (
                RecoveryStrategy.SWITCH_TOOL
                if alt_tool
                else RecoveryStrategy.GIVE_UP
            )
            return ReflectionResult(
                failure_analysis=f"数据不存在: {error[:100]}",
                error_category=ErrorCategory.NOT_FOUND,
                is_retryable=False,
                recovery_strategy=strategy,
                suggested_next_action=(
                    f"切换到替代工具 {alt_tool}" if alt_tool else "放弃该路径，基于已有信息回答"
                ),
                suggested_tool=alt_tool,
                observation_for_llm=(
                    f"工具 {tool_name} 返回空结果: {error[:200]}。"
                    + (f"建议尝试 {alt_tool} 获取信息。" if alt_tool else "本地无相关数据。")
                ),
            )

        return None  # 无法判断，交给 LLM

    def _suggest_alternative_tool(self, failed_tool: str) -> str:
        """为失败工具建议替代工具

        基于工具功能相似性的人工映射表。
        """
        alternatives = {
            "search_literature": "search_ncbi",       # 本地 RAG → NCBI
            "search_ncbi": "web_search",              # NCBI → 网络搜索
            "query_knowledge_base": "web_search",     # 知识库 → 网络搜索
            "discover_targets": "search_ncbi",        # 靶点发现 → NCBI 文献
            "find_approved_drugs": "search_ncbi",     # 老药新用 → NCBI
            "web_search": "search_ncbi",              # 网络搜索 → NCBI（权威性更高）
        }
        return alternatives.get(failed_tool, "")

    def _default_reflection(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        error: str,
        retry_count: int,
    ) -> ReflectionResult:
        """默认反思（无 LLM 时的兜底）"""
        return ReflectionResult(
            failure_analysis=f"工具 {tool_name} 执行失败: {error[:200]}",
            error_category=ErrorCategory.UNKNOWN,
            is_retryable=retry_count < self.max_retries,
            recovery_strategy=(
                RecoveryStrategy.RETRY_WITH_FIXED_PARAMS
                if retry_count < self.max_retries
                else RecoveryStrategy.GIVE_UP
            ),
            suggested_next_action="重试或基于现有信息回答",
            observation_for_llm=(
                f"工具 {tool_name} 失败: {error[:200]}。"
                + ("请尝试其他方法。" if retry_count < self.max_retries
                   else "已多次失败，请直接给出最终答案。")
            ),
        )

    async def _llm_reflect(
        self,
        query: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        error: str,
        recent_steps: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]],
        retry_count: int,
    ) -> ReflectionResult:
        """用 LLM 深度分析失败原因"""
        from app.services.agent.prompts import build_tools_description

        # 压缩 recent_steps（避免 prompt 过长）
        steps_summary = json.dumps(
            recent_steps[-3:],  # 只取最近 3 步
            ensure_ascii=False,
            default=str,
        )[:1500]

        tools_desc = build_tools_description(available_tools[:10])

        prompt = REFLECTION_PROMPT.format(
            query=query[:500],
            tool_name=tool_name,
            tool_args=json.dumps(tool_args, ensure_ascii=False, default=str)[:500],
            error=error[:500],
            recent_steps=steps_summary,
            available_tools=tools_desc,
        )

        result = await self.llm_router.quick(
            prompt, system="你是工具失败分析专家。"
        )
        content = result.get("content", "")

        return self._parse_reflection(content, tool_name, error, retry_count)

    def _parse_reflection(
        self,
        content: str,
        tool_name: str,
        error: str,
        retry_count: int,
    ) -> ReflectionResult:
        """解析 LLM 反思输出"""
        parsed = None
        # 尝试从代码块解析
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
            logger.warning(f"反思输出解析失败，降级默认: {content[:200]}")
            return self._default_reflection(tool_name, {}, error, retry_count)

        # 安全解析枚举
        try:
            category = ErrorCategory(parsed.get("error_category", "unknown"))
        except (ValueError, TypeError):
            category = ErrorCategory.UNKNOWN

        try:
            strategy = RecoveryStrategy(
                parsed.get("recovery_strategy", "give_up")
            )
        except (ValueError, TypeError):
            strategy = RecoveryStrategy.GIVE_UP

        is_retryable = bool(parsed.get("is_retryable", False))
        # 超过最大重试次数强制不可重试
        if retry_count >= self.max_retries:
            is_retryable = False
            strategy = RecoveryStrategy.GIVE_UP

        return ReflectionResult(
            failure_analysis=parsed.get("failure_analysis", ""),
            error_category=category,
            is_retryable=is_retryable,
            recovery_strategy=strategy,
            suggested_next_action=parsed.get("suggested_next_action", ""),
            suggested_tool=parsed.get("suggested_tool", ""),
            suggested_params_hint=parsed.get("suggested_params_hint", ""),
            observation_for_llm=parsed.get("observation_for_llm", ""),
            raw=parsed,
        )


__all__ = [
    "Reflector",
    "ReflectionResult",
    "ErrorCategory",
    "RecoveryStrategy",
]
