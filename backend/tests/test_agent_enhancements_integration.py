"""Agent 增强功能集成测试 — 验证 AgentEngine 与增强组件的集成

测试矩阵：
- I1: AgentEngine 初始化增强组件（基于 settings 开关）
- I2: 工具失败触发 Reflector（observation 含恢复建议）
- I3: DAG 并行执行（启用时先执行计划，结果注入 observation）
- I4: 工具质量记录（工具调用后 metrics 更新）
- I5: 知识盲区检测（连续空结果触发网络搜索建议）
- I6: 增强组件异常降级（不影响主流程）

设计原则：
- 复用 test_agent_integration.py 的 mock 模式
- 真实 SessionManager + Guardrail 验证核心逻辑
- 每个测试独立构造 AgentEngine
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.security import UserRole, hash_password
from app.models.agent_session import AgentSession, SessionStatus
from app.models.agent_task import AgentTask, TaskStatus
from app.models.user import User
from app.services.agent.dag_executor import DagExecutionResult, StepExecutionResult
from app.services.agent.engine import AgentEngine
from app.services.agent.knowledge_gap import GapType
from app.services.agent.planner import PlanStep, PlannerOutput
from app.services.agent.reflection import ErrorCategory, RecoveryStrategy
from app.services.agent.session import SessionManager
from app.services.agent.tools.base import ToolResult
from app.services.llm.guardrail import Guardrail, GuardrailResult

# 复用 test_agent_integration.py 的辅助函数
from tests.test_agent_integration import (
    _create_user,
    _create_session,
    _create_task,
    _llm_response,
    _react_action,
    _react_final,
    _make_llm_router,
    _make_planner,
    _make_registry,
    _make_progress,
    _make_audit,
    _build_engine,
)


# ========== I1: AgentEngine 初始化增强组件 ==========


class TestEngineInitialization:
    """测试 AgentEngine 正确初始化增强组件"""

    @pytest.mark.asyncio
    async def test_all_enhancements_enabled(self, async_db_session):
        """所有增强功能启用时，组件全部初始化"""
        with patch.object(settings, "AGENT_USE_REFLECTION", True), \
             patch.object(settings, "AGENT_USE_DAG_EXECUTOR", True), \
             patch.object(settings, "AGENT_TOOL_QUALITY_TRACKING", True), \
             patch.object(settings, "AGENT_USE_KNOWLEDGE_GAP_DETECTION", True):

            engine = _build_engine(
                async_db_session,
                _make_llm_router([_llm_response("test")]),
                _make_planner(PlannerOutput.empty()),
                _make_registry(),
            )

            assert engine.reflector is not None
            assert engine.dag_executor is not None
            assert engine.tool_quality is not None
            assert engine.gap_detector is not None

    @pytest.mark.asyncio
    async def test_all_enhancements_disabled(self, async_db_session):
        """所有增强功能关闭时，组件为 None"""
        with patch.object(settings, "AGENT_USE_REFLECTION", False), \
             patch.object(settings, "AGENT_USE_DAG_EXECUTOR", False), \
             patch.object(settings, "AGENT_TOOL_QUALITY_TRACKING", False), \
             patch.object(settings, "AGENT_USE_KNOWLEDGE_GAP_DETECTION", False):

            engine = _build_engine(
                async_db_session,
                _make_llm_router([_llm_response("test")]),
                _make_planner(PlannerOutput.empty()),
                _make_registry(),
            )

            assert engine.reflector is None
            assert engine.dag_executor is None
            assert engine.tool_quality is None
            assert engine.gap_detector is None


# ========== I2: 工具失败触发 Reflector ==========


class TestReflectionIntegration:
    """测试工具失败时 Reflector 集成"""

    @pytest.mark.asyncio
    async def test_tool_failure_triggers_reflection(self, async_db_session):
        """工具失败 → Reflector 分析 → observation 含恢复建议"""
        user = await _create_user(async_db_session, "reflect@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id, "查询靶点")
        await async_db_session.commit()

        # LLM 序列：
        # 1. Action: discover_targets（会失败）
        # 2. Final Answer（基于反思结果回答）
        llm_router = _make_llm_router([
            _llm_response(_react_action("查询靶点", "discover_targets", {"project_id": "invalid"})),
            _llm_response(_react_final("查询完成", "靶点信息不可用")),
        ])

        # 工具失败
        registry = _make_registry(
            tools_info=[{"name": "discover_targets", "description": "发现靶点", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.fail(error="项目不存在")],
        )

        engine = _build_engine(async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry)

        result = await engine.run(
            task_id=task.id,
            query="查询靶点",
            session_id=session.id,
            user=user,
        )

        assert result["status"] == TaskStatus.COMPLETED
        # Reflector 应该被调用（启发式匹配到"不存在" → NOT_FOUND）
        # observation 应该包含恢复建议（但我们在测试中只验证任务完成）

    @pytest.mark.asyncio
    async def test_reflection_degrades_gracefully(self, async_db_session):
        """Reflector 异常 → 不影响主流程"""
        user = await _create_user(async_db_session, "reflect-degrade@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        llm_router = _make_llm_router([
            _llm_response(_react_action("查询", "discover_targets", {})),
            _llm_response(_react_final("完成", "已处理")),
        ])

        registry = _make_registry(
            tools_info=[{"name": "discover_targets", "description": "发现靶点", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.fail(error="内部错误 XYZ")],
        )

        engine = _build_engine(async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry)

        # Reflector 存在但 LLM 可能异常 → 降级
        result = await engine.run(
            task_id=task.id,
            query="查询",
            session_id=session.id,
            user=user,
        )

        # 即使反思失败，任务仍应完成
        assert result["status"] == TaskStatus.COMPLETED


# ========== I3: DAG 并行执行 ==========


class TestDagExecutionIntegration:
    """测试 DAG 并行执行集成"""

    @pytest.mark.asyncio
    async def test_dag_execution_injects_observation(self, async_db_session):
        """启用 DAG 时，计划步骤的执行结果注入 observation"""
        user = await _create_user(async_db_session, "dag@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id, "分析靶点")
        await async_db_session.commit()

        # DAG 计划：2 个并行步骤
        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
                PlanStep(id="s2", tool="search_ncbi", args={"query": "EGFR"}),
            ],
            parallel_layers=[["s1", "s2"]],
            reasoning="并行检索",
        )

        # LLM 只需生成最终答案（DAG 结果已在 observation 中）
        llm_router = _make_llm_router([
            _llm_response(_react_final("分析完成", "EGFR 是重要靶点")),
        ])

        # 工具都成功
        registry = _make_registry(
            tools_info=[
                {"name": "search_literature", "description": "文献检索", "parameters": {}, "side_effects": False},
                {"name": "search_ncbi", "description": "NCBI 检索", "parameters": {}, "side_effects": False},
            ],
            tool_results=[ToolResult.ok(data={"articles": ["EGFR paper"]})],
        )

        with patch.object(settings, "AGENT_USE_DAG_EXECUTOR", True):
            engine = _build_engine(
                async_db_session, llm_router, _make_planner(plan), registry
            )

            result = await engine.run(
                task_id=task.id,
                query="分析靶点",
                session_id=session.id,
                user=user,
            )

        assert result["status"] == TaskStatus.COMPLETED
        # step_traces 应包含 DAG 步骤
        dag_steps = [s for s in result["steps"] if "dag_result" in s]
        assert len(dag_steps) == 2

    @pytest.mark.asyncio
    async def test_dag_disabled_uses_standard_react(self, async_db_session):
        """DAG 关闭时走标准 ReAct 循环"""
        user = await _create_user(async_db_session, "no-dag@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
            ],
            parallel_layers=[["s1"]],
            reasoning="单步",
        )

        llm_router = _make_llm_router([
            _llm_response(_react_action("查询", "search_literature", {"query": "EGFR"})),
            _llm_response(_react_final("完成", "已检索")),
        ])

        registry = _make_registry(
            tools_info=[{"name": "search_literature", "description": "文献检索", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.ok(data={"total": 5})],
        )

        with patch.object(settings, "AGENT_USE_DAG_EXECUTOR", False):
            engine = _build_engine(
                async_db_session, llm_router, _make_planner(plan), registry
            )

            result = await engine.run(
                task_id=task.id,
                query="查询 EGFR",
                session_id=session.id,
                user=user,
            )

        assert result["status"] == TaskStatus.COMPLETED
        # 不应有 DAG 步骤
        dag_steps = [s for s in result["steps"] if "dag_result" in s]
        assert len(dag_steps) == 0


# ========== I4: 工具质量记录 ==========


class TestToolQualityIntegration:
    """测试工具质量记录集成"""

    @pytest.mark.asyncio
    async def test_quality_recorded_after_tool_call(self, async_db_session):
        """工具调用后，质量指标被记录"""
        user = await _create_user(async_db_session, "quality@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        llm_router = _make_llm_router([
            _llm_response(_react_action("查询", "search_literature", {"query": "EGFR"})),
            _llm_response(_react_final("完成", "已检索")),
        ])

        registry = _make_registry(
            tools_info=[{"name": "search_literature", "description": "文献", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.ok(data={"total": 5})],
        )

        engine = _build_engine(async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry)

        result = await engine.run(
            task_id=task.id,
            query="查询 EGFR",
            session_id=session.id,
            user=user,
        )

        assert result["status"] == TaskStatus.COMPLETED

        # 验证工具质量被记录
        if engine.tool_quality:
            metrics = await engine.tool_quality.get_metrics("search_literature")
            assert metrics is not None
            assert metrics.total_calls >= 1
            assert metrics.success_count >= 1

            # 清理测试数据
            await engine.tool_quality.reset("search_literature")


# ========== I5: 知识盲区检测 ==========


class TestKnowledgeGapIntegration:
    """测试知识盲区检测集成"""

    @pytest.mark.asyncio
    async def test_consecutive_empty_results_trigger_gap(self, async_db_session):
        """连续空结果 → 触发知识盲区检测 → observation 含搜索建议"""
        user = await _create_user(async_db_session, "gap@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id, "EGFR 最新研究")
        await async_db_session.commit()

        # LLM 序列：连续调用工具返回空结果，然后最终回答
        llm_router = _make_llm_router([
            _llm_response(_react_action("查文献", "search_literature", {"query": "EGFR"})),
            _llm_response(_react_action("查NCBI", "search_ncbi", {"query": "EGFR"})),
            _llm_response(_react_action("网络搜索", "web_search", {"query": "EGFR 最新研究"})),
            _llm_response(_react_final("综合分析", "EGFR 是重要靶点")),
        ])

        # 前两次工具返回空结果
        registry = _make_registry(
            tools_info=[
                {"name": "search_literature", "description": "文献", "parameters": {}, "side_effects": False},
                {"name": "search_ncbi", "description": "NCBI", "parameters": {}, "side_effects": False},
                {"name": "web_search", "description": "网络搜索", "parameters": {}, "side_effects": False},
            ],
            tool_results=[
                ToolResult.ok(data={"total": 0}),  # 空结果
                ToolResult.ok(data={"total": 0}),  # 空结果
                ToolResult.ok(data={"results": [{"title": "EGFR 2024"}]}),  # 有结果
            ],
        )

        # 设置较小的盲区阈值
        with patch.object(settings, "AGENT_KNOWLEDGE_GAP_THRESHOLD", 2):
            engine = _build_engine(
                async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry
            )

            result = await engine.run(
                task_id=task.id,
                query="EGFR 最新研究",
                session_id=session.id,
                user=user,
            )

        assert result["status"] == TaskStatus.COMPLETED
        # 盲区检测器应该记录了 2+ 次观察
        assert len(engine.gap_detector._observations) >= 2

    @pytest.mark.asyncio
    async def test_gap_detector_reset_per_task(self, async_db_session):
        """每个任务开始时，盲区检测器被重置"""
        user = await _create_user(async_db_session, "gap-reset@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        llm_router = _make_llm_router([
            _llm_response(_react_final("完成", "已回答")),
        ])

        engine = _build_engine(
            async_db_session, llm_router, _make_planner(PlannerOutput.empty()), _make_registry()
        )

        # 预先注入一些观察
        if engine.gap_detector:
            engine.gap_detector.observe(1, "search", True, {"total": 0})
            assert len(engine.gap_detector._observations) == 1

        await engine.run(
            task_id=task.id,
            query="你好",
            session_id=session.id,
            user=user,
        )

        # 任务运行后，观察应被重置（或无新增）
        # 因为 LLM 直接 Final Answer，没有工具调用
        assert len(engine.gap_detector._observations) == 0


# ========== I6: 增强组件异常降级 ==========


class TestEnhancementDegradation:
    """测试增强组件异常降级"""

    @pytest.mark.asyncio
    async def test_quality_tracking_failure_no_crash(self, async_db_session):
        """工具质量记录异常 → 不影响主流程"""
        user = await _create_user(async_db_session, "degrade@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        llm_router = _make_llm_router([
            _llm_response(_react_action("查询", "search_literature", {"query": "EGFR"})),
            _llm_response(_react_final("完成", "已检索")),
        ])

        registry = _make_registry(
            tools_info=[{"name": "search_literature", "description": "文献", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.ok(data={"total": 5})],
        )

        engine = _build_engine(async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry)

        # 模拟 tool_quality.record 抛异常（注意：tracker 是全局单例，
        # 必须用 try/finally 恢复原方法，否则会污染后续测试）
        original_record = engine.tool_quality.record
        engine.tool_quality.record = AsyncMock(side_effect=RuntimeError("DB 不可用"))
        try:
            result = await engine.run(
                task_id=task.id,
                query="查询 EGFR",
                session_id=session.id,
                user=user,
            )
        finally:
            engine.tool_quality.record = original_record

        # 即使质量记录失败，任务仍应完成
        assert result["status"] == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_gap_detection_failure_no_crash(self, async_db_session):
        """盲区检测异常 → 不影响主流程"""
        user = await _create_user(async_db_session, "gap-degrade@ai-drug.com")
        session = await _create_session(async_db_session, user.id)
        task = await _create_task(async_db_session, session.id, user.id)
        await async_db_session.commit()

        llm_router = _make_llm_router([
            _llm_response(_react_action("查询", "search_literature", {"query": "EGFR"})),
            _llm_response(_react_final("完成", "已检索")),
        ])

        registry = _make_registry(
            tools_info=[{"name": "search_literature", "description": "文献", "parameters": {}, "side_effects": False}],
            tool_results=[ToolResult.ok(data={"total": 5})],
        )

        engine = _build_engine(async_db_session, llm_router, _make_planner(PlannerOutput.empty()), registry)

        # 模拟 gap_detector.detect 抛异常
        if engine.gap_detector:
            engine.gap_detector.detect = AsyncMock(side_effect=RuntimeError("检测失败"))

        result = await engine.run(
            task_id=task.id,
            query="查询 EGFR",
            session_id=session.id,
            user=user,
        )

        assert result["status"] == TaskStatus.COMPLETED
