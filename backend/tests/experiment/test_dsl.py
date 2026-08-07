"""ExperimentDSL + DSLCompiler — 单元测试

覆盖目标：
- ExperimentDSL 创建、to_dict/from_dict 序列化
- validate 校验逻辑
- 模板库（预设模板获取与列表）
- DSLCompiler 编译（Nextflow 参数 + LIMS CSV + 执行步骤）
- MockInstrumentAdapter 接口实现

测试策略：
- 纯数据类测试，不依赖数据库
- MockInstrumentAdapter 模拟异步方法
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============================================================
# ExperimentDSL 创建与序列化
# ============================================================


class TestExperimentDSLCreation:
    """ExperimentDSL 基本创建测试"""

    def test_create_minimal_dsl(self):
        """最小 DSL 创建（仅有一个变量和一个读出）"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(
                    name="concentration",
                    values=[1, 10],
                    unit="μM",
                )
            ],
            controls=[],
            readouts=[
                ExperimentReadout(
                    name="viability",
                    type="continuous",
                    unit="%",
                )
            ],
        )

        assert dsl.exp_type == "cytotoxicity"
        assert len(dsl.variables) == 1
        assert dsl.variables[0].name == "concentration"
        assert dsl.variables[0].values == [1, 10]
        assert dsl.replicates == 3
        assert dsl.expected_result is None
        assert dsl.template_name is None

    def test_create_full_dsl(self):
        """完整 DSL 创建（含变量、对照、读出、预期结果）"""
        from app.services.experiment.dsl import (
            ExperimentControl,
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="pdx",
            variables=[
                ExperimentVariable(
                    name="dose",
                    values=[50, 100, 200],
                    unit="mg/kg",
                    description="给药剂量",
                ),
            ],
            controls=[
                ExperimentControl(
                    name="vehicle",
                    value=0,
                    is_negative_control=True,
                    description="溶媒对照",
                ),
                ExperimentControl(
                    name="positive_drug",
                    value=100,
                    is_negative_control=False,
                    description="阳性药物对照",
                ),
            ],
            readouts=[
                ExperimentReadout(
                    name="tumor_volume",
                    type="continuous",
                    unit="mm³",
                ),
                ExperimentReadout(
                    name="survival",
                    type="survival",
                ),
            ],
            replicates=5,
            expected_result="肿瘤体积缩小 > 50%",
            template_name="pdx_default",
        )

        assert dsl.exp_type == "pdx"
        assert len(dsl.variables) == 1
        assert len(dsl.controls) == 2
        assert dsl.controls[0].is_negative_control is True
        assert dsl.controls[1].is_negative_control is False
        assert len(dsl.readouts) == 2
        assert dsl.replicates == 5
        assert dsl.expected_result == "肿瘤体积缩小 > 50%"
        assert dsl.template_name == "pdx_default"

    def test_to_dict(self):
        """to_dict 序列化"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1], unit="μM")
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous", unit="%")
            ],
        )

        result = dsl.to_dict()

        assert isinstance(result, dict)
        assert result["exp_type"] == "cytotoxicity"
        assert result["replicates"] == 3
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "conc"
        assert result["variables"][0]["values"] == [1]
        assert result["variables"][0]["unit"] == "μM"
        assert len(result["readouts"]) == 1

    def test_from_dict(self):
        """from_dict 反序列化"""
        from app.services.experiment.dsl import ExperimentDSL

        data = {
            "exp_type": "docking_validation",
            "variables": [
                {"name": "target", "values": ["EGFR"], "unit": None}
            ],
            "controls": [
                {"name": "reference", "value": -7.5, "is_negative_control": False}
            ],
            "readouts": [
                {"name": "binding_energy", "type": "continuous", "unit": "kcal/mol"}
            ],
            "replicates": 1,
            "expected_result": None,
            "template_name": "docking_validation",
        }

        dsl = ExperimentDSL.from_dict(data)

        assert dsl.exp_type == "docking_validation"
        assert len(dsl.variables) == 1
        assert dsl.variables[0].name == "target"
        assert dsl.variables[0].values == ["EGFR"]
        assert dsl.variables[0].unit is None
        assert len(dsl.controls) == 1
        assert dsl.controls[0].name == "reference"
        assert dsl.controls[0].value == -7.5
        assert dsl.controls[0].is_negative_control is False
        assert len(dsl.readouts) == 1
        assert dsl.replicates == 1

    def test_roundtrip_serialization(self):
        """to_dict → from_dict 往返一致性"""
        from app.services.experiment.dsl import (
            ExperimentControl,
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        original = ExperimentDSL(
            exp_type="pd",
            variables=[
                ExperimentVariable(
                    name="timepoint",
                    values=[0, 1, 4, 8, 24],
                    unit="h",
                ),
            ],
            controls=[
                ExperimentControl(
                    name="baseline",
                    value=0,
                    is_negative_control=True,
                ),
            ],
            readouts=[
                ExperimentReadout(
                    name="plasma_conc",
                    type="continuous",
                    unit="ng/mL",
                ),
            ],
            replicates=3,
            expected_result="Cmax > 100 ng/mL",
        )

        restored = ExperimentDSL.from_dict(original.to_dict())

        assert restored.exp_type == original.exp_type
        assert restored.replicates == original.replicates
        assert restored.expected_result == original.expected_result
        assert len(restored.variables) == len(original.variables)
        assert restored.variables[0].values == original.variables[0].values
        assert len(restored.controls) == len(original.controls)
        assert restored.controls[0].is_negative_control == original.controls[0].is_negative_control
        assert len(restored.readouts) == len(original.readouts)
        assert restored.readouts[0].type == original.readouts[0].type


# ============================================================
# validate 校验逻辑
# ============================================================


class TestDSLValidation:
    """validate 校验逻辑测试"""

    def test_valid_dsl_no_errors(self):
        """合法 DSL 无错误"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1], unit="μM")
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous", unit="%")
            ],
        )

        errors = dsl.validate()
        assert errors == []

    def test_missing_exp_type(self):
        """缺少 exp_type"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="",
            variables=[
                ExperimentVariable(name="conc", values=[1])
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous")
            ],
        )

        errors = dsl.validate()
        assert "exp_type 不能为空" in errors

    def test_no_variables(self):
        """无变量"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous")
            ],
        )

        errors = dsl.validate()
        assert "至少需要一个变量" in errors

    def test_no_readouts(self):
        """无读出"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1])
            ],
            controls=[],
            readouts=[],
        )

        errors = dsl.validate()
        assert "至少需要一个读出" in errors

    def test_invalid_replicates(self):
        """重复数 < 1"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1])
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous")
            ],
            replicates=0,
        )

        errors = dsl.validate()
        assert "重复数必须 >= 1" in errors

    def test_invalid_readout_type(self):
        """不合法读出类型"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1])
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="bad", type="invalid_type")
            ],
        )

        errors = dsl.validate()
        assert any("不合法" in e for e in errors)

    def test_multiple_errors(self):
        """多个错误同时返回"""
        from app.services.experiment.dsl import ExperimentDSL

        dsl = ExperimentDSL(
            exp_type="",
            variables=[],
            controls=[],
            readouts=[],
            replicates=-1,
        )

        errors = dsl.validate()
        assert len(errors) >= 4

    def test_all_valid_readout_types(self):
        """所有合法读出类型"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        valid_types = ["continuous", "categorical", "survival"]
        for vt in valid_types:
            dsl = ExperimentDSL(
                exp_type="test",
                variables=[
                    ExperimentVariable(name="v", values=[1])
                ],
                controls=[],
                readouts=[
                    ExperimentReadout(name="r", type=vt)
                ],
            )
            errors = dsl.validate()
            assert errors == [], f"type={vt} should be valid"


# ============================================================
# 预设模板库
# ============================================================


class TestExperimentTemplates:
    """预设模板库测试"""

    def test_list_templates(self):
        """列出模板"""
        from app.services.experiment.dsl import list_templates

        names = list_templates()
        assert "cytotoxicity" in names
        assert "docking_validation" in names

    def test_get_cytotoxicity_template(self):
        """获取 cytotoxicity 模板"""
        from app.services.experiment.dsl import get_template

        template = get_template("cytotoxicity")
        assert template is not None
        assert template.exp_type == "cytotoxicity"
        assert len(template.variables) == 1
        assert template.variables[0].name == "concentration"
        assert template.variables[0].values == [0.01, 0.1, 1, 10, 100]
        assert template.variables[0].unit == "μM"
        assert len(template.controls) == 1
        assert template.controls[0].name == "untreated"
        assert template.controls[0].is_negative_control is True
        assert len(template.readouts) == 1
        assert template.readouts[0].name == "cell_viability"
        assert template.readouts[0].type == "continuous"
        assert template.replicates == 3

    def test_get_docking_template(self):
        """获取 docking_validation 模板"""
        from app.services.experiment.dsl import get_template

        template = get_template("docking_validation")
        assert template is not None
        assert template.exp_type == "docking_validation"
        assert len(template.readouts) == 1
        assert template.readouts[0].name == "binding_energy"
        assert template.replicates == 1

    def test_get_unknown_template_returns_none(self):
        """未知模板返回 None"""
        from app.services.experiment.dsl import get_template

        assert get_template("nonexistent") is None

    def test_template_validation_passes(self):
        """模板通过验证"""
        from app.services.experiment.dsl import get_template

        for name in ["cytotoxicity", "docking_validation"]:
            template = get_template(name)
            errors = template.validate()
            assert errors == [], f"template '{name}' should be valid"


# ============================================================
# DSLCompiler 编译
# ============================================================


class TestDSLCompiler:
    """DSLCompiler 编译测试"""

    def _make_dsl(self, exp_type="cytotoxicity"):
        from app.services.experiment.dsl import (
            ExperimentControl,
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        return ExperimentDSL(
            exp_type=exp_type,
            variables=[
                ExperimentVariable(
                    name="concentration",
                    values=[0.1, 1, 10],
                    unit="μM",
                )
            ],
            controls=[
                ExperimentControl(
                    name="untreated",
                    value=0,
                    is_negative_control=True,
                ),
            ],
            readouts=[
                ExperimentReadout(
                    name="cell_viability",
                    type="continuous",
                    unit="%",
                ),
            ],
            replicates=3,
        )

    def test_compile_outputs_keys(self):
        """编译输出包含必要键"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)

        assert "steps" in result
        assert "nextflow_params" in result
        assert "lims_csv" in result
        assert "validation_errors" in result
        assert "is_valid" in result

    def test_compile_valid_dsl(self):
        """合法 DSL 编译 is_valid=True"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)

        assert result["is_valid"] is True
        assert result["validation_errors"] == []

    def test_compile_invalid_dsl_warnings(self):
        """非法 DSL 编译仍有输出但 is_valid=False"""
        from app.services.experiment.dsl import ExperimentDSL
        from app.services.experiment.dsl_compiler import DSLCompiler

        bad_dsl = ExperimentDSL(
            exp_type="",
            variables=[],
            controls=[],
            readouts=[],
            replicates=0,
        )
        compiler = DSLCompiler()
        result = compiler.compile(bad_dsl)

        assert result["is_valid"] is False
        assert len(result["validation_errors"]) >= 4

    def test_nextflow_params_structure(self):
        """Nextflow 参数结构"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        params = result["nextflow_params"]

        assert "pipeline" in params
        assert params["exp_type"] == "cytotoxicity"
        assert params["replicates"] == 3
        assert isinstance(params["variables"], str)
        assert isinstance(params["controls"], str)
        assert isinstance(params["readouts"], str)

    def test_nextflow_params_values_json(self):
        """Nextflow 参数中 variables 可解析"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        params = result["nextflow_params"]

        variables = json.loads(params["variables"])
        assert len(variables) == 1
        assert variables[0]["name"] == "concentration"
        assert variables[0]["values"] == [0.1, 1, 10]

    def test_lims_csv_contains_headers(self):
        """LIMS CSV 包含表头"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        csv_text = result["lims_csv"]

        lines = csv_text.strip().split("\n")
        assert len(lines) > 1
        headers = lines[0].split(",")
        assert "experiment_name" in headers
        assert "exp_type" in headers
        assert "variable_name" in headers
        assert "control_name" in headers

    def test_lims_csv_rows_count(self):
        """LIMS CSV 行数（变量 × 重复 × 读出 + 对照 × 重复 × 读出）"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        csv_text = result["lims_csv"]

        lines = csv_text.strip().split("\n")
        data_rows = len(lines) - 1  # 减去表头

        var_levels = 3  # 3 个浓度
        replicates = 3
        readouts = 1
        controls = 1
        expected_data_rows = (var_levels + controls) * replicates * readouts
        assert data_rows == expected_data_rows

    def test_execution_steps_order(self):
        """执行步骤按顺序"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        steps = result["steps"]

        assert len(steps) >= 5
        assert steps[0]["name"] == "validate_dsl"
        assert steps[0]["order"] == 1

    def test_execution_steps_contain_variable_steps(self):
        """执行步骤包含变量运行步骤"""
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = self._make_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl)
        steps = result["steps"]

        variable_steps = [s for s in steps if s["name"] == "run_variable"]
        assert len(variable_steps) == 1
        assert variable_steps[0]["variable"] == "concentration"
        assert variable_steps[0]["levels"] == 3
        assert variable_steps[0]["replicates"] == 3

    def test_compile_with_multiple_readouts(self):
        """多读出编译"""
        from app.services.experiment.dsl import (
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )
        from app.services.experiment.dsl_compiler import DSLCompiler

        dsl = ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(name="conc", values=[1])
            ],
            controls=[],
            readouts=[
                ExperimentReadout(name="viability", type="continuous"),
                ExperimentReadout(name="apoptosis", type="continuous"),
            ],
            replicates=2,
        )
        compiler = DSLCompiler()
        result = compiler.compile(dsl)

        lines = result["lims_csv"].strip().split("\n")
        data_rows = len(lines) - 1
        assert data_rows == 1 * 2 * 2  # 1 level × 2 rep × 2 readouts


# ============================================================
# MockInstrumentAdapter
# ============================================================


class TestMockInstrumentAdapter:
    """MockInstrumentAdapter 测试"""

    def _make_dsl(self):
        from app.services.experiment.dsl import (
            ExperimentControl,
            ExperimentDSL,
            ExperimentReadout,
            ExperimentVariable,
        )

        return ExperimentDSL(
            exp_type="cytotoxicity",
            variables=[
                ExperimentVariable(
                    name="concentration",
                    values=[0.1, 1, 10],
                    unit="μM",
                )
            ],
            controls=[
                ExperimentControl(
                    name="untreated",
                    value=0,
                    is_negative_control=True,
                ),
            ],
            readouts=[
                ExperimentReadout(
                    name="cell_viability",
                    type="continuous",
                    unit="%",
                ),
            ],
            replicates=3,
        )

    @pytest.mark.asyncio
    async def test_prepare(self):
        """prepare 返回正确结构"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        dsl = self._make_dsl()
        result = await adapter.prepare(dsl)

        assert result["exp_type"] == "cytotoxicity"
        assert result["replicates"] == 3
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "concentration"
        assert result["variables"][0]["values"] == [0.1, 1, 10]
        assert len(result["controls"]) == 1
        assert result["mock_run_id"].startswith("mock_")

    @pytest.mark.asyncio
    async def test_run_cytotoxicity(self):
        """run 返回细胞毒性 mock 数据"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        result = await adapter.run({"exp_type": "cytotoxicity", "replicates": 3})

        assert result["status"] == "completed"
        assert result["exp_type"] == "cytotoxicity"
        assert "cell_viability" in result
        viability_data = result["cell_viability"]
        assert len(viability_data) == 5

    @pytest.mark.asyncio
    async def test_run_docking(self):
        """run 返回对接 mock 数据"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        result = await adapter.run({"exp_type": "docking_validation"})

        assert result["status"] == "completed"
        assert "binding_energy" in result
        assert isinstance(result["binding_energy"], float)

    @pytest.mark.asyncio
    async def test_run_unknown_type(self):
        """run 未知类型仍返回 mock"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        result = await adapter.run({"exp_type": "unknown_type"})

        assert result["status"] == "completed"
        assert result["exp_type"] == "unknown_type"

    @pytest.mark.asyncio
    async def test_parse_result(self):
        """parse_result 标准化"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        raw = {"status": "completed", "data": [1, 2, 3]}
        result = await adapter.parse_result(raw)

        assert result["status"] == "parsed"
        assert result["normalized"] is True
        assert result["data"] == raw

    @pytest.mark.asyncio
    async def test_run_count_increments(self):
        """prepare 调用次数递增"""
        from app.services.experiment.dsl_compiler import MockInstrumentAdapter

        adapter = MockInstrumentAdapter()
        dsl = self._make_dsl()

        r1 = await adapter.prepare(dsl)
        r2 = await adapter.prepare(dsl)

        assert r1["mock_run_id"] != r2["mock_run_id"]