"""任务规划器测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agent.planner import (
    PlanStep,
    PlannerInput,
    PlannerOutput,
    TaskPlanner,
)


class TestPlannerParseJSON:
    def test_parse_plain_json(self):
        result = TaskPlanner._parse_json('{"steps": [], "reasoning": "test"}')
        assert result == {"steps": [], "reasoning": "test"}

    def test_parse_json_in_code_block(self):
        content = '```json\n{"steps": [{"id": "s1", "tool": "x"}]}\n```'
        result = TaskPlanner._parse_json(content)
        assert result is not None
        assert len(result["steps"]) == 1
        assert result["steps"][0]["id"] == "s1"

    def test_parse_json_in_code_block_without_lang(self):
        content = '```\n{"steps": []}\n```'
        result = TaskPlanner._parse_json(content)
        assert result == {"steps": []}

    def test_parse_json_embedded_in_text(self):
        content = '这是规划：\n{"steps": [{"id": "s1", "tool": "discover_targets"}]}\n以上'
        result = TaskPlanner._parse_json(content)
        assert result is not None
        assert result["steps"][0]["tool"] == "discover_targets"

    def test_parse_invalid_json_returns_none(self):
        result = TaskPlanner._parse_json("纯文本无 JSON")
        assert result is None

    def test_parse_empty_string(self):
        result = TaskPlanner._parse_json("")
        assert result is None


class TestTopologicalLayers:
    def test_empty_steps(self):
        assert TaskPlanner._topological_layers([]) == []

    def test_single_step(self):
        step = PlanStep(id="s1", tool="t", args={})
        layers = TaskPlanner._topological_layers([step])
        assert layers == [["s1"]]

    def test_parallel_independent_steps(self):
        """3 个无依赖步骤应在同一层"""
        steps = [
            PlanStep(id="s1", tool="t1", args={}),
            PlanStep(id="s2", tool="t2", args={}),
            PlanStep(id="s3", tool="t3", args={}),
        ]
        layers = TaskPlanner._topological_layers(steps)
        assert len(layers) == 1
        assert set(layers[0]) == {"s1", "s2", "s3"}

    def test_sequential_chain(self):
        """s1 → s2 → s3 串行依赖，应分 3 层"""
        steps = [
            PlanStep(id="s1", tool="t1", args={}),
            PlanStep(id="s2", tool="t2", args={}, depends_on=["s1"]),
            PlanStep(id="s3", tool="t3", args={}, depends_on=["s2"]),
        ]
        layers = TaskPlanner._topological_layers(steps)
        assert len(layers) == 3
        assert layers[0] == ["s1"]
        assert layers[1] == ["s2"]
        assert layers[2] == ["s3"]

    def test_diamond_dependency(self):
        """钻石依赖：s1 → (s2, s3) → s4"""
        steps = [
            PlanStep(id="s1", tool="t1", args={}),
            PlanStep(id="s2", tool="t2", args={}, depends_on=["s1"]),
            PlanStep(id="s3", tool="t3", args={}, depends_on=["s1"]),
            PlanStep(id="s4", tool="t4", args={}, depends_on=["s2", "s3"]),
        ]
        layers = TaskPlanner._topological_layers(steps)
        assert len(layers) == 3
        assert layers[0] == ["s1"]
        assert set(layers[1]) == {"s2", "s3"}
        assert layers[2] == ["s4"]

    def test_circular_dependency_fallback(self):
        """循环依赖时降级处理，剩余节点平铺到最后一层"""
        steps = [
            PlanStep(id="s1", tool="t1", args={}, depends_on=["s2"]),
            PlanStep(id="s2", tool="t2", args={}, depends_on=["s1"]),
        ]
        layers = TaskPlanner._topological_layers(steps)
        # 不会卡死，循环节点平铺
        assert len(layers) >= 1
        flat = sum(layers, [])
        assert set(flat) == {"s1", "s2"}

    def test_nonexistent_dependency_ignored(self):
        """依赖不存在的 step_id 时忽略"""
        steps = [
            PlanStep(id="s1", tool="t1", args={}, depends_on=["ghost"]),
        ]
        layers = TaskPlanner._topological_layers(steps)
        assert layers == [["s1"]]


@pytest.mark.asyncio
async def test_plan_no_llm_returns_empty():
    """无 LLM 时返回空计划"""
    planner = TaskPlanner(llm_router=None)
    inp = PlannerInput(query="测试", available_tools=[{"name": "t1"}])
    output = await planner.plan(inp)
    assert output.steps == []
    assert output.parallel_layers == []
    assert "无 LLM" in output.reasoning


@pytest.mark.asyncio
async def test_plan_no_tools_returns_empty():
    """无可用工具时返回空计划"""
    llm_router = MagicMock()
    planner = TaskPlanner(llm_router=llm_router)
    inp = PlannerInput(query="测试", available_tools=[])
    output = await planner.plan(inp)
    assert output.steps == []
    assert "无可用工具" in output.reasoning


@pytest.mark.asyncio
async def test_plan_llm_failure_returns_empty():
    """LLM 调用失败时降级为空计划"""
    llm_router = MagicMock()
    llm_router.quick = AsyncMock(side_effect=Exception("LLM 不可用"))
    planner = TaskPlanner(llm_router=llm_router)
    inp = PlannerInput(
        query="测试",
        available_tools=[{"name": "t1", "description": "测试工具"}],
    )
    output = await planner.plan(inp)
    assert output.steps == []
    assert "规划失败" in output.reasoning


@pytest.mark.asyncio
async def test_plan_valid_output():
    """LLM 返回合法计划时正确解析"""
    llm_router = MagicMock()
    llm_router.quick = AsyncMock(
        return_value={
            "content": '```json\n{"steps": [{"id": "s1", "tool": "t1", "args": {"x": 1}, "depends_on": []}], "reasoning": "test"}\n```'
        }
    )
    planner = TaskPlanner(llm_router=llm_router)
    inp = PlannerInput(
        query="测试",
        available_tools=[{"name": "t1", "description": "测试工具"}],
    )
    output = await planner.plan(inp)
    assert len(output.steps) == 1
    assert output.steps[0].id == "s1"
    assert output.steps[0].tool == "t1"
    assert output.steps[0].args == {"x": 1}
    assert output.parallel_layers == [["s1"]]


@pytest.mark.asyncio
async def test_plan_skips_unknown_tools():
    """LLM 返回未知工具时跳过"""
    llm_router = MagicMock()
    llm_router.quick = AsyncMock(
        return_value={
            "content": '{"steps": [{"id": "s1", "tool": "known_tool", "args": {}}, {"id": "s2", "tool": "unknown_tool", "args": {}}]}'
        }
    )
    planner = TaskPlanner(llm_router=llm_router)
    inp = PlannerInput(
        query="测试",
        available_tools=[{"name": "known_tool", "description": "已知工具"}],
    )
    output = await planner.plan(inp)
    assert len(output.steps) == 1
    assert output.steps[0].tool == "known_tool"


def test_planner_output_to_dict():
    """PlannerOutput.to_dict 序列化正确"""
    out = PlannerOutput(
        steps=[PlanStep(id="s1", tool="t1", args={"x": 1})],
        parallel_layers=[["s1"]],
        reasoning="test",
    )
    d = out.to_dict()
    assert d["steps"][0]["id"] == "s1"
    assert d["parallel_layers"] == [["s1"]]
    assert d["reasoning"] == "test"


def test_planner_output_empty_factory():
    """PlannerOutput.empty 工厂方法"""
    out = PlannerOutput.empty(reasoning="降级")
    assert out.steps == []
    assert out.parallel_layers == []
    assert out.reasoning == "降级"
