"""Reflector 单元测试 — 工具失败反思与重规划

测试矩阵：
- 启发式分类：参数错误/权限不足/网络异常/数据不存在/超时/未知错误
- LLM 反思：成功解析/解析失败降级/LLM 异常降级
- 重试次数限制：超过 max_retries 强制放弃
- 替代工具建议
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent.reflection import (
    ErrorCategory,
    RecoveryStrategy,
    ReflectionResult,
    Reflector,
)


# ========== 启发式分类测试 ==========


class TestReflectorHeuristic:
    """测试启发式错误分类（无需 LLM）"""

    @pytest.fixture
    def reflector(self):
        return Reflector(llm_router=None)

    @pytest.mark.asyncio
    async def test_permission_denied_not_retryable(self, reflector):
        """权限不足 → 不可重试，升级用户"""
        result = await reflector.reflect(
            query="查询靶点",
            tool_name="discover_targets",
            tool_args={},
            error="无权使用工具 discover_targets",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.PERMISSION_DENIED
        assert result.is_retryable is False
        assert result.recovery_strategy == RecoveryStrategy.ESCALATE_TO_USER
        assert "权限" in result.observation_for_llm

    @pytest.mark.asyncio
    async def test_param_error_retryable(self, reflector):
        """参数错误 → 可重试"""
        result = await reflector.reflect(
            query="查询靶点",
            tool_name="discover_targets",
            tool_args={"project_id": ""},
            error="缺少必填参数: project_id",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.PARAM_ERROR
        assert result.is_retryable is True
        assert result.recovery_strategy == RecoveryStrategy.RETRY_WITH_FIXED_PARAMS

    @pytest.mark.asyncio
    async def test_network_error_retryable(self, reflector):
        """网络异常 → 可重试"""
        result = await reflector.reflect(
            query="查询文献",
            tool_name="search_ncbi",
            tool_args={"query": "EGFR"},
            error="ConnectionError: failed to connect to NCBI server (503)",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.NETWORK_ERROR
        assert result.is_retryable is True

    @pytest.mark.asyncio
    async def test_not_found_suggests_alternative(self, reflector):
        """数据不存在 → 建议替代工具"""
        result = await reflector.reflect(
            query="EGFR 文献",
            tool_name="search_literature",
            tool_args={"query": "EGFR"},
            error="未找到相关文献",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.NOT_FOUND
        assert result.is_retryable is False
        assert result.recovery_strategy == RecoveryStrategy.SWITCH_TOOL
        assert result.suggested_tool == "search_ncbi"

    @pytest.mark.asyncio
    async def test_timeout_retryable(self, reflector):
        """超时 → 可重试"""
        result = await reflector.reflect(
            query="分析数据",
            tool_name="analyze_dataset",
            tool_args={},
            error="工具执行超时（30s）",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.TIMEOUT
        assert result.is_retryable is True
        assert "缩小查询范围" in result.observation_for_llm

    @pytest.mark.asyncio
    async def test_unknown_error_default(self, reflector):
        """未知错误 → 默认反思"""
        result = await reflector.reflect(
            query="查询",
            tool_name="unknown_tool",
            tool_args={},
            error="Some weird error message",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.UNKNOWN
        assert result.is_retryable is True  # 首次仍可重试


# ========== 重试次数限制测试 ==========


class TestReflectorRetryLimit:
    """测试重试次数限制"""

    @pytest.fixture
    def reflector(self):
        return Reflector(llm_router=None)

    @pytest.mark.asyncio
    async def test_exceed_max_retries_give_up(self, reflector):
        """超过最大重试次数 → 强制放弃"""
        result = await reflector.reflect(
            query="查询",
            tool_name="discover_targets",
            tool_args={},
            error="参数错误",
            recent_steps=[],
            available_tools=[],
            retry_count=reflector.max_retries,  # 达到上限
        )
        assert result.is_retryable is False
        assert result.recovery_strategy == RecoveryStrategy.GIVE_UP
        assert "最终答案" in result.observation_for_llm


# ========== 替代工具建议测试 ==========


class TestAlternativeToolSuggestion:
    """测试替代工具建议"""

    @pytest.fixture
    def reflector(self):
        return Reflector(llm_router=None)

    def test_search_literature_to_ncbi(self, reflector):
        alt = reflector._suggest_alternative_tool("search_literature")
        assert alt == "search_ncbi"

    def test_search_ncbi_to_web_search(self, reflector):
        alt = reflector._suggest_alternative_tool("search_ncbi")
        assert alt == "web_search"

    def test_query_knowledge_base_to_web_search(self, reflector):
        alt = reflector._suggest_alternative_tool("query_knowledge_base")
        assert alt == "web_search"

    def test_unknown_tool_no_alternative(self, reflector):
        alt = reflector._suggest_alternative_tool("unknown_tool")
        assert alt == ""


# ========== LLM 反思测试 ==========


class TestReflectorLLM:
    """测试 LLM 深度反思"""

    @pytest.fixture
    def llm_router(self):
        router = MagicMock()
        router.quick = AsyncMock()
        return router

    @pytest.fixture
    def reflector(self, llm_router):
        return Reflector(llm_router=llm_router)

    @pytest.mark.asyncio
    async def test_llm_reflect_success(self, reflector, llm_router):
        """LLM 成功返回反思结果"""
        llm_response = {
            "content": json.dumps({
                "failure_analysis": "内部处理逻辑异常导致工具失败",
                "error_category": "internal_error",
                "is_retryable": True,
                "recovery_strategy": "retry_with_fixed_params",
                "suggested_next_action": "修正内部状态后重试",
                "suggested_tool": "",
                "suggested_params_hint": "无需修改参数",
                "observation_for_llm": "工具内部处理异常，建议重试。",
            })
        }
        llm_router.quick.return_value = llm_response

        # 使用不匹配任何启发式模式的错误，确保 LLM 被调用
        result = await reflector.reflect(
            query="分析项目靶点",
            tool_name="discover_targets",
            tool_args={"project_id": "abc"},
            error="内部状态 XYZ 无效",
            recent_steps=[{"step": 1, "action": "discover_targets"}],
            available_tools=[{"name": "discover_targets", "description": "发现靶点"}],
            retry_count=0,
        )
        assert result.error_category == ErrorCategory.INTERNAL_ERROR
        assert result.is_retryable is True
        assert result.recovery_strategy == RecoveryStrategy.RETRY_WITH_FIXED_PARAMS
        assert "重试" in result.observation_for_llm

    @pytest.mark.asyncio
    async def test_llm_reflect_parse_failure_degrades(self, reflector, llm_router):
        """LLM 输出解析失败 → 降级默认"""
        llm_router.quick.return_value = {"content": "not a json"}

        result = await reflector.reflect(
            query="查询",
            tool_name="discover_targets",
            tool_args={},
            error="some error",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        # 降级到默认反思
        assert result.error_category == ErrorCategory.UNKNOWN
        assert result.is_retryable is True  # 首次仍可重试

    @pytest.mark.asyncio
    async def test_llm_reflect_exception_degrades(self, reflector, llm_router):
        """LLM 调用异常 → 降级启发式"""
        llm_router.quick.side_effect = Exception("LLM 不可用")

        # 启发式能处理的错误（权限）→ 降级启发式
        result = await reflector.reflect(
            query="查询",
            tool_name="discover_targets",
            tool_args={},
            error="无权使用工具 discover_targets",
            recent_steps=[],
            available_tools=[],
            retry_count=0,
        )
        # 启发式先匹配到权限不足，不调用 LLM
        assert result.error_category == ErrorCategory.PERMISSION_DENIED


# ========== ReflectionResult 数据类测试 ==========


class TestReflectionResult:
    """测试 ReflectionResult 数据类"""

    def test_to_dict(self):
        r = ReflectionResult(
            failure_analysis="参数错误",
            error_category=ErrorCategory.PARAM_ERROR,
            is_retryable=True,
            recovery_strategy=RecoveryStrategy.RETRY_WITH_FIXED_PARAMS,
            suggested_next_action="修正参数",
            suggested_tool="",
            suggested_params_hint="填入 project_id",
            observation_for_llm="请填入 project_id",
        )
        d = r.to_dict()
        assert d["error_category"] == "param_error"
        assert d["recovery_strategy"] == "retry_with_fixed_params"
        assert d["is_retryable"] is True
        assert d["suggested_next_action"] == "修正参数"
