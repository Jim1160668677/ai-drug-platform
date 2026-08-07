"""DagExecutor 单元测试 — DAG 并行执行

测试矩阵：
- 单层执行（多个无依赖步骤并行）
- 多层执行（依赖链 A → B → C）
- 参数模板替换（${step_id.field}）
- 工具失败处理
- 异常容错
- 结果聚合与 observation 生成
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent.dag_executor import (
    DagExecutor,
    DagExecutionResult,
    StepExecutionResult,
)
from app.services.agent.planner import PlanStep, PlannerOutput
from app.services.agent.tools.base import ToolResult


# ========== 辅助函数 ==========


def _make_registry(tool_results=None):
    """构造 mock ToolRegistry"""
    registry = MagicMock()
    if tool_results is None:
        tool_results = [ToolResult.ok(data={"result": "ok"})]

    if len(tool_results) == 1:
        registry.execute_tool = AsyncMock(return_value=tool_results[0])
    else:
        registry.execute_tool = AsyncMock(side_effect=list(tool_results))
    return registry


def _make_user():
    """构造 mock User"""
    from app.core.security import UserRole
    user = MagicMock()
    user.id = "test-user-id"
    user.role = UserRole.RESEARCHER
    return user


# ========== 单层并行执行测试 ==========


class TestDagSingleLayer:
    """测试单层（多步骤并行）"""

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """同层 3 个步骤并发执行"""
        registry = _make_registry()
        # 记录调用顺序，验证并发
        call_times = []

        async def _track_execute(*args, **kwargs):
            call_times.append(("start", kwargs.get("tool_name"), asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)  # 模拟耗时
            call_times.append(("end", kwargs.get("tool_name"), asyncio.get_event_loop().time()))
            return ToolResult.ok(data={"tool": kwargs.get("tool_name")})

        registry.execute_tool = AsyncMock(side_effect=_track_execute)

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
                PlanStep(id="s2", tool="search_ncbi", args={"query": "EGFR"}),
                PlanStep(id="s3", tool="web_search", args={"query": "EGFR"}),
            ],
            parallel_layers=[["s1", "s2", "s3"]],
            reasoning="并行检索",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is True
        assert len(result.results) == 3
        assert all(r.success for r in result.results)
        # 验证 3 个工具都被调用
        assert registry.execute_tool.await_count == 3

    @pytest.mark.asyncio
    async def test_empty_plan(self):
        """空计划 → 空结果"""
        registry = _make_registry()
        plan = PlannerOutput(steps=[], parallel_layers=[], reasoning="空计划")

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is True
        assert len(result.results) == 0


# ========== 多层依赖执行测试 ==========


class TestDagMultiLayer:
    """测试多层（依赖链）"""

    @pytest.mark.asyncio
    async def test_sequential_layers(self):
        """3 层串行：s1 → s2 → s3"""
        call_order = []

        async def _track(*args, **kwargs):
            tool_name = kwargs.get("tool_name")
            call_order.append(tool_name)
            return ToolResult.ok(data={"step": tool_name})

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=_track)

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
                PlanStep(id="s2", tool="discover_targets", args={}, depends_on=["s1"]),
                PlanStep(id="s3", tool="design_molecules", args={}, depends_on=["s2"]),
            ],
            parallel_layers=[["s1"], ["s2"], ["s3"]],
            reasoning="链式依赖",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is True
        assert call_order == ["search_literature", "discover_targets", "design_molecules"]

    @pytest.mark.asyncio
    async def test_mixed_parallel_sequential(self):
        """混合：层 1 并行 2 个，层 2 依赖层 1"""
        call_order = []

        async def _track(*args, **kwargs):
            tool_name = kwargs.get("tool_name")
            call_order.append(tool_name)
            await asyncio.sleep(0.01)
            return ToolResult.ok(data={"tool": tool_name})

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=_track)

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
                PlanStep(id="s2", tool="search_ncbi", args={"query": "EGFR"}),
                PlanStep(id="s3", tool="discover_targets", args={}, depends_on=["s1", "s2"]),
            ],
            parallel_layers=[["s1", "s2"], ["s3"]],
            reasoning="先并行检索，再发现靶点",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is True
        # s3 必须在 s1 和 s2 之后
        assert call_order.index("discover_targets") > call_order.index("search_literature")
        assert call_order.index("discover_targets") > call_order.index("search_ncbi")


# ========== 参数模板替换测试 ==========


class TestDagParamResolution:
    """测试参数模板 ${step_id.field} 替换"""

    @pytest.mark.asyncio
    async def test_template_resolution(self):
        """后续步骤引用前序步骤的结果"""
        captured_args = []

        async def _capture(*args, **kwargs):
            captured_args.append(kwargs.get("params", {}))
            tool_name = kwargs.get("tool_name")
            if tool_name == "search_ncbi":
                return ToolResult.ok(data={"gene_symbol": "EGFR", "pmid": "12345"})
            elif tool_name == "discover_targets":
                return ToolResult.ok(data={"target": "EGFR"})
            return ToolResult.ok(data={})

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=_capture)

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_ncbi", args={"query": "EGFR"}),
                PlanStep(
                    id="s2",
                    tool="discover_targets",
                    args={"target_gene": "${s1.gene_symbol}"},
                    depends_on=["s1"],
                ),
            ],
            parallel_layers=[["s1"], ["s2"]],
            reasoning="先查基因，再发现靶点",
        )

        executor = DagExecutor(registry=registry)
        await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        # s2 的参数应该被替换为 EGFR
        assert len(captured_args) == 2
        assert captured_args[1]["target_gene"] == "EGFR"

    def test_resolve_value_string_template(self):
        """字符串中的模板变量替换"""
        registry = _make_registry()
        executor = DagExecutor(registry=registry)

        completed = {
            "s1": StepExecutionResult(
                step_id="s1",
                tool="search_ncbi",
                args={},
                success=True,
                data={"gene": "EGFR"},
            )
        }

        result = executor._resolve_value("基因是 ${s1.gene}", completed)
        assert result == "基因是 EGFR"

    def test_resolve_value_pure_template(self):
        """纯模板变量返回原始类型"""
        registry = _make_registry()
        executor = DagExecutor(registry=registry)

        completed = {
            "s1": StepExecutionResult(
                step_id="s1",
                tool="search_ncbi",
                args={},
                success=True,
                data={"count": 42},
            )
        }

        result = executor._resolve_value("${s1.count}", completed)
        assert result == 42  # int 类型，非字符串

    def test_resolve_value_missing_step(self):
        """引用不存在的步骤 → 返回默认值"""
        registry = _make_registry()
        executor = DagExecutor(registry=registry)

        result = executor._resolve_value("${nonexistent.field}", {})
        assert result == ""  # 默认值

    def test_resolve_value_nested_dict(self):
        """嵌套字典中的模板替换"""
        registry = _make_registry()
        executor = DagExecutor(registry=registry)

        completed = {
            "s1": StepExecutionResult(
                step_id="s1",
                tool="search_ncbi",
                args={},
                success=True,
                data={"gene": "KRAS"},
            )
        }

        value = {"filter": {"gene": "${s1.gene}", "limit": 10}}
        result = executor._resolve_value(value, completed)
        assert result["filter"]["gene"] == "KRAS"
        assert result["filter"]["limit"] == 10


# ========== 失败处理测试 ==========


class TestDagFailureHandling:
    """测试工具失败处理"""

    @pytest.mark.asyncio
    async def test_tool_failure_recorded(self):
        """工具失败被正确记录"""
        registry = MagicMock()
        registry.execute_tool = AsyncMock(
            return_value=ToolResult.fail(error="网络不可达")
        )

        plan = PlannerOutput(
            steps=[PlanStep(id="s1", tool="search_ncbi", args={"query": "EGFR"})],
            parallel_layers=[["s1"]],
            reasoning="单步",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is False
        assert "s1" in result.failed_steps
        assert result.results[0].error == "网络不可达"

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self):
        """部分步骤失败不影响其他步骤"""
        # 使用 side_effect 列表：按调用顺序返回
        # s1 (search_literature) 失败，s2 (search_ncbi) 成功
        # 注意：并行执行时顺序不保证，用工具名映射更可靠
        call_results = {}

        original_results = {
            "search_literature": ToolResult.fail(error="知识库为空"),
            "search_ncbi": ToolResult.ok(data={"articles": []}),
        }

        async def _execute(**kwargs):
            tool_name = kwargs.get("tool_name", "")
            # 记录调用
            call_results[tool_name] = original_results.get(
                tool_name, ToolResult.ok(data={})
            )
            return call_results[tool_name]

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=_execute)

        plan = PlannerOutput(
            steps=[
                PlanStep(id="s1", tool="search_literature", args={"query": "EGFR"}),
                PlanStep(id="s2", tool="search_ncbi", args={"query": "EGFR"}),
            ],
            parallel_layers=[["s1", "s2"]],
            reasoning="并行检索",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is False  # 有失败
        assert "s1" in result.failed_steps
        assert "s2" not in result.failed_steps  # s2 成功

    @pytest.mark.asyncio
    async def test_exception_caught(self):
        """工具抛异常被捕获"""
        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=RuntimeError("意外错误"))

        plan = PlannerOutput(
            steps=[PlanStep(id="s1", tool="search_ncbi", args={"query": "EGFR"})],
            parallel_layers=[["s1"]],
            reasoning="单步",
        )

        executor = DagExecutor(registry=registry)
        result = await executor.execute(
            plan=plan,
            user=_make_user(),
            task_id="task-1",
            session_id="session-1",
        )

        assert result.success is False
        assert "执行异常" in result.results[0].error


# ========== 结果聚合测试 ==========


class TestDagResultAggregation:
    """测试结果聚合与 observation 生成"""

    def test_to_observation_success(self):
        """成功结果生成 observation"""
        results = [
            StepExecutionResult(
                step_id="s1",
                tool="search_ncbi",
                args={"query": "EGFR"},
                success=True,
                data={"articles": [{"title": "EGFR in NSCLC"}]},
                duration_ms=100,
            ),
            StepExecutionResult(
                step_id="s2",
                tool="discover_targets",
                args={},
                success=True,
                data={"targets": ["EGFR"]},
                duration_ms=200,
            ),
        ]
        dag_result = DagExecutionResult(
            success=True,
            results=results,
            failed_steps=[],
            total_duration_ms=300,
        )

        obs = dag_result.to_observation()
        assert "DAG 执行结果" in obs
        assert "search_ncbi" in obs
        assert "discover_targets" in obs
        assert "✓" in obs

    def test_to_observation_with_failure(self):
        """含失败的结果生成 observation"""
        results = [
            StepExecutionResult(
                step_id="s1",
                tool="search_literature",
                args={"query": "EGFR"},
                success=False,
                error="知识库为空",
                duration_ms=50,
            ),
        ]
        dag_result = DagExecutionResult(
            success=False,
            results=results,
            failed_steps=["s1"],
            total_duration_ms=50,
        )

        obs = dag_result.to_observation()
        assert "✗" in obs
        assert "知识库为空" in obs
        assert "s1" in obs

    def test_get_step_result(self):
        """按 step_id 查找结果"""
        results = [
            StepExecutionResult(step_id="s1", tool="tool1", args={}, success=True),
            StepExecutionResult(step_id="s2", tool="tool2", args={}, success=True),
        ]
        dag_result = DagExecutionResult(success=True, results=results)

        found = dag_result.get_step_result("s2")
        assert found is not None
        assert found.tool == "tool2"

        not_found = dag_result.get_step_result("s3")
        assert not_found is None
