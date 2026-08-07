"""ExperimentDesignTool — Agent 工具单元测试

覆盖目标：
- ExperimentDesignTool 基本执行流程（goal + exp_type → DSL）
- 模板选择与参数覆盖
- 自定义变量/对照/读出
- 编译产物验证
- 非法实验类型错误
- 权限校验

测试策略：
- 构造 ToolContext（MagicMock + AsyncMock）
- 不依赖数据库和 LLM
- 验证 DSL 结构完整性和编译产物
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext, ToolResult
from app.services.agent.tools.experiment_design import ExperimentDesignTool


# ============================================================
# 测试数据工厂
# ============================================================


def _make_context(
    *,
    role=UserRole.RESEARCHER,
    user_id=None,
    project_id=None,
):
    """构造 ToolContext mock"""
    user = MagicMock()
    user.id = user_id or uuid4()
    user.role = role

    db = AsyncMock()

    return ToolContext(
        db=db,
        user=user,
        task_id=str(uuid4()),
        session_id=str(uuid4()),
        project_id=project_id,
    )


def _make_params(**overrides):
    """构造工具参数"""
    params = {
        "goal": "验证 EGFR 抑制剂对 AML 细胞的杀伤效果",
        "exp_type": "cytotoxicity",
        "hypothesis_ids": [],
        "replicates": 3,
    }
    params.update(overrides)
    return params


# ============================================================
# 基本执行流程
# ============================================================


class TestExperimentDesignBasic:
    """基本执行流程测试"""

    @pytest.mark.asyncio
    async def test_basic_cytotoxicity_design(self):
        """基本细胞毒性实验设计"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params()

        result = await tool.execute_safely(params, ctx)

        assert result.success is True
        assert result.error is None

        data = result.data
        assert "dsl" in data
        assert "compiled" in data
        assert data["exp_type"] == "cytotoxicity"
        assert data["template_used"] == "cytotoxicity"

        dsl = data["dsl"]
        assert dsl["exp_type"] == "cytotoxicity"
        assert len(dsl["variables"]) == 1
        assert dsl["variables"][0]["name"] == "concentration"
        assert dsl["variables"][0]["unit"] == "μM"
        assert len(dsl["controls"]) == 1
        assert dsl["controls"][0]["name"] == "untreated"
        assert dsl["controls"][0]["is_negative_control"] is True
        assert len(dsl["readouts"]) == 1
        assert dsl["readouts"][0]["name"] == "cell_viability"
        assert dsl["replicates"] == 3
        assert dsl["expected_result"] == "验证 EGFR 抑制剂对 AML 细胞的杀伤效果"

    @pytest.mark.asyncio
    async def test_basic_docking_design(self):
        """基本分子对接验证设计"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params(exp_type="docking_validation", replicates=1)

        result = await tool.execute_safely(params, ctx)

        assert result.success is True
        data = result.data
        assert data["exp_type"] == "docking_validation"

        dsl = data["dsl"]
        assert dsl["exp_type"] == "docking_validation"
        assert dsl["replicates"] == 1
        assert len(dsl["readouts"]) == 1
        assert dsl["readouts"][0]["name"] == "binding_energy"

    @pytest.mark.asyncio
    async def test_compiled_output(self):
        """编译产物结构验证"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params()

        result = await tool.execute_safely(params, ctx)
        compiled = result.data["compiled"]

        assert "steps" in compiled
        assert "nextflow_params" in compiled
        assert "lims_csv" in compiled
        assert "is_valid" in compiled
        assert compiled["is_valid"] is True
        assert compiled["validation_errors"] == []

    @pytest.mark.asyncio
    async def test_display_output(self):
        """前端展示数据"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params()

        result = await tool.execute_safely(params, ctx)

        assert result.display is not None
        assert result.display["type"] == "table"
        payload = result.display["payload"]
        assert "title" in payload
        assert "rows" in payload
        rows = payload["rows"]
        assert len(rows) >= 3  # 至少: 变量 + 对照 + 读出

    @pytest.mark.asyncio
    async def test_hypothesis_ids_passthrough(self):
        """hypothesis_ids 透传"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        h_ids = [str(uuid4()), str(uuid4())]
        params = _make_params(hypothesis_ids=h_ids)

        result = await tool.execute_safely(params, ctx)

        assert result.data["hypothesis_ids"] == h_ids


# ============================================================
# 自定义参数覆盖
# ============================================================


class TestExperimentDesignCustomParams:
    """自定义参数覆盖测试"""

    @pytest.mark.asyncio
    async def test_custom_replicates(self):
        """自定义重复数"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params(replicates=5)

        result = await tool.execute_safely(params, ctx)

        dsl = result.data["dsl"]
        assert dsl["replicates"] == 5

    @pytest.mark.asyncio
    async def test_custom_variables(self):
        """自定义变量"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        custom_vars = [
            {
                "name": "temperature",
                "values": [25, 30, 37, 42],
                "unit": "°C",
                "description": "培养温度",
            }
        ]
        params = _make_params(custom_variables=custom_vars)

        result = await tool.execute_safely(params, ctx)

        dsl = result.data["dsl"]
        assert len(dsl["variables"]) == 1
        assert dsl["variables"][0]["name"] == "temperature"
        assert dsl["variables"][0]["values"] == [25, 30, 37, 42]
        assert dsl["variables"][0]["unit"] == "°C"

    @pytest.mark.asyncio
    async def test_custom_controls(self):
        """自定义对照"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        custom_ctrls = [
            {
                "name": "blank",
                "value": "PBS",
                "is_negative_control": True,
            },
            {
                "name": "reference_drug",
                "value": 10,
                "is_negative_control": False,
            },
        ]
        params = _make_params(custom_controls=custom_ctrls)

        result = await tool.execute_safely(params, ctx)

        dsl = result.data["dsl"]
        assert len(dsl["controls"]) == 2
        assert dsl["controls"][0]["name"] == "blank"
        assert dsl["controls"][0]["is_negative_control"] is True
        assert dsl["controls"][1]["name"] == "reference_drug"
        assert dsl["controls"][1]["value"] == 10

    @pytest.mark.asyncio
    async def test_custom_readouts(self):
        """自定义读出"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        custom_reads = [
            {
                "name": "IC50",
                "type": "continuous",
                "unit": "μM",
            },
            {
                "name": "apoptosis_rate",
                "type": "categorical",
                "unit": "%",
            },
        ]
        params = _make_params(custom_readouts=custom_reads)

        result = await tool.execute_safely(params, ctx)

        dsl = result.data["dsl"]
        assert len(dsl["readouts"]) == 2
        assert dsl["readouts"][0]["name"] == "IC50"
        assert dsl["readouts"][0]["type"] == "continuous"
        assert dsl["readouts"][1]["name"] == "apoptosis_rate"
        assert dsl["readouts"][1]["type"] == "categorical"

    @pytest.mark.asyncio
    async def test_custom_variables_override_template(self):
        """自定义变量覆盖模板默认变量"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        custom_vars = [
            {
                "name": "cell_line",
                "values": ["HEPG2", "MCF7"],
                "unit": "",
            }
        ]
        params = _make_params(custom_variables=custom_vars)

        result = await tool.execute_safely(params, ctx)

        dsl = result.data["dsl"]
        assert len(dsl["variables"]) == 1
        assert dsl["variables"][0]["name"] == "cell_line"
        assert dsl["variables"][0]["values"] == ["HEPG2", "MCF7"]


# ============================================================
# 错误处理
# ============================================================


class TestExperimentDesignErrors:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_unknown_exp_type(self):
        """未知实验类型返回错误"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params(exp_type="invalid_type")

        result = await tool.execute_safely(params, ctx)

        assert result.success is False
        assert "未知实验类型" in result.error

    @pytest.mark.asyncio
    async def test_empty_goal_still_works(self):
        """空 goal 仍可执行（goal 只是 expected_result）"""
        tool = ExperimentDesignTool()
        ctx = _make_context()
        params = _make_params(goal="")

        result = await tool.execute_safely(params, ctx)

        assert result.success is True
        assert result.data["dsl"]["expected_result"] == ""

    @pytest.mark.asyncio
    async def test_validation_error_for_invalid_readout_type(self):
        """不合法读出类型时验证失败"""
        tool = ExperimentDesignTool()
        ctx = _make_context()

        custom_reads = [
            {
                "name": "bad_readout",
                "type": "invalid_type",
                "unit": "",
            }
        ]
        params = _make_params(custom_readouts=custom_reads)

        result = await tool.execute_safely(params, ctx)

        assert result.success is False
        assert "验证失败" in result.error


# ============================================================
# 工具元数据
# ============================================================


class TestExperimentDesignMetadata:
    """工具元数据测试"""

    def test_tool_name(self):
        """工具名称"""
        tool = ExperimentDesignTool()
        assert tool.name == "experiment_design"

    def test_tool_description(self):
        """工具描述"""
        tool = ExperimentDesignTool()
        assert len(tool.description) > 0

    def test_tool_parameters(self):
        """工具参数列表"""
        tool = ExperimentDesignTool()
        assert len(tool.parameters) >= 5

        param_names = [p.name for p in tool.parameters]
        assert "goal" in param_names
        assert "exp_type" in param_names
        assert "hypothesis_ids" in param_names
        assert "replicates" in param_names

    def test_tool_not_side_effects(self):
        """无副作用"""
        tool = ExperimentDesignTool()
        assert tool.side_effects is False

    def test_minimum_role(self):
        """最低角色为 RESEARCHER"""
        tool = ExperimentDesignTool()
        assert tool.required_role == UserRole.RESEARCHER

    def test_to_schema(self):
        """生成 JSON Schema"""
        tool = ExperimentDesignTool()
        schema = tool.to_schema()

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "goal" in schema["properties"]
        assert schema["properties"]["goal"]["type"] == "string"
        assert "required" in schema
        assert "goal" in schema["required"]

    def test_to_info(self):
        """生成工具信息"""
        tool = ExperimentDesignTool()
        info = tool.to_info()

        assert info["name"] == "experiment_design"
        assert info["side_effects"] is False
        assert "parameters" in info


# ============================================================
# 权限校验
# ============================================================


class TestExperimentDesignPermissions:
    """权限校验测试"""

    def test_researcher_has_permission(self):
        """RESEARCHER 有权限"""
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("experiment_design", UserRole.RESEARCHER) is True

    def test_founder_has_permission(self):
        """FOUNDER 有权限"""
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("experiment_design", UserRole.FOUNDER) is True

    def test_chief_researcher_has_permission(self):
        """CHIEF_RESEARCHER 有权限"""
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("experiment_design", UserRole.CHIEF_RESEARCHER) is True

    def test_doctor_no_permission(self):
        """DOCTOR 无权限"""
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("experiment_design", UserRole.DOCTOR) is False

    def test_data_engineer_no_permission(self):
        """DATA_ENGINEER 无权限"""
        from app.services.agent.tools.permissions import has_tool_permission

        assert has_tool_permission("experiment_design", UserRole.DATA_ENGINEER) is False