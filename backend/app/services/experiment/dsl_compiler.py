"""DSL 编译器 — 将 ExperimentDSL 编译为可执行步骤

输出：
1. Nextflow 流水线参数（computational 实验）
2. LIMS CSV 批量导入（湿实验）
3. 仪器适配器抽象接口 + Mock 实现
"""
import csv
import io
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.services.experiment.dsl import (
    ExperimentControl,
    ExperimentDSL,
    ExperimentReadout,
    ExperimentVariable,
)

logger = logging.getLogger(__name__)


class InstrumentAdapter(ABC):
    """仪器适配器抽象接口

    不同实验类型对应不同仪器：
    - cytotoxicity: 酶标仪 (MicroplateReader)
    - docking_validation: GPU 集群
    - pdx: 动物实验平台
    - pd/pk: 药代动力学平台
    """

    @abstractmethod
    async def prepare(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        """准备实验：生成运行参数"""
        ...

    @abstractmethod
    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行实验：返回结果数据"""
        ...

    @abstractmethod
    async def parse_result(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """解析原始结果为标准化格式"""
        ...


class MockInstrumentAdapter(InstrumentAdapter):
    """Mock 仪器适配器 — 用于测试和开发

    返回模拟数据，不连接真实仪器。
    """

    def __init__(self):
        self._run_count = 0

    async def prepare(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        self._run_count += 1
        variable_specs = []
        for v in dsl.variables:
            variable_specs.append({
                "name": v.name,
                "values": v.values,
                "unit": v.unit,
            })
        control_specs = []
        for c in dsl.controls:
            control_specs.append({
                "name": c.name,
                "value": c.value,
                "is_negative_control": c.is_negative_control,
            })
        return {
            "exp_type": dsl.exp_type,
            "variables": variable_specs,
            "controls": control_specs,
            "replicates": dsl.replicates,
            "readout_count": len(dsl.readouts),
            "mock_run_id": f"mock_{dsl.exp_type}_{self._run_count}",
        }

    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        import random

        exp_type = params.get("exp_type", "unknown")
        mock_data: Dict[str, Any] = {
            "status": "completed",
            "exp_type": exp_type,
        }

        if exp_type == "cytotoxicity":
            mock_data["cell_viability"] = [
                {
                    "concentration": v,
                    "viability": round(random.uniform(30, 100), 2),
                    "replicates": [
                        round(random.uniform(25, 105), 2)
                        for _ in range(params.get("replicates", 3))
                    ],
                }
                for v in [0.01, 0.1, 1, 10, 100]
            ]
        elif exp_type == "docking_validation":
            mock_data["binding_energy"] = round(
                random.uniform(-12, -4), 2
            )
        else:
            mock_data["result"] = "mock_data"

        return mock_data

    async def parse_result(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "parsed",
            "data": raw_result,
            "normalized": True,
        }


class DSLCompiler:
    """DSL 编译器 — 将 ExperimentDSL 编译为可执行步骤列表

    编译产物：
    - nextflow_params: Nextflow 流水线参数（用于计算实验）
    - lims_csv: LIMS CSV 批量导入（用于湿实验）
    - steps: 可执行步骤列表
    """

    EXP_TYPE_NEXTFLOW_MAP: Dict[str, str] = {
        "docking_validation": "docking_pipeline.nf",
        "cytotoxicity": "cell_viability_pipeline.nf",
        "pdx": "pdx_analysis.nf",
        "pd": "pd_analysis.nf",
        "pk": "pk_analysis.nf",
    }

    def __init__(self, instrument_adapter: Optional[InstrumentAdapter] = None):
        self.instrument = instrument_adapter or MockInstrumentAdapter()

    def compile(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        """编译 DSL → 生成可执行步骤列表

        Returns:
            {
                steps: [...],
                nextflow_params: {...},
                lims_csv: "..."
            }
        """
        errors = dsl.validate()
        if errors:
            logger.warning("DSL 验证失败: %s", errors)

        nextflow_params = self._build_nextflow_params(dsl)
        lims_csv = self._build_lims_csv(dsl)
        steps = self._build_execution_steps(dsl)

        return {
            "steps": steps,
            "nextflow_params": nextflow_params,
            "lims_csv": lims_csv,
            "validation_errors": errors,
            "is_valid": len(errors) == 0,
        }

    def _build_nextflow_params(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        """生成 Nextflow 流水线参数"""
        pipeline = self.EXP_TYPE_NEXTFLOW_MAP.get(
            dsl.exp_type, "generic_pipeline.nf"
        )
        variables_json = json.dumps(
            [
                {"name": v.name, "values": v.values, "unit": v.unit}
                for v in dsl.variables
            ]
        )
        controls_json = json.dumps(
            [
                {
                    "name": c.name,
                    "value": c.value,
                    "is_negative": c.is_negative_control,
                }
                for c in dsl.controls
            ]
        )
        readouts_json = json.dumps(
            [
                {"name": r.name, "type": r.type, "unit": r.unit}
                for r in dsl.readouts
            ]
        )
        return {
            "pipeline": pipeline,
            "exp_type": dsl.exp_type,
            "replicates": dsl.replicates,
            "variables": variables_json,
            "controls": controls_json,
            "readouts": readouts_json,
        }

    def _build_lims_csv(self, dsl: ExperimentDSL) -> str:
        """生成 LIMS CSV 批量导入数据"""
        output = io.StringIO()
        writer = csv.writer(output)

        headers = [
            "experiment_name",
            "exp_type",
            "variable_name",
            "variable_value",
            "variable_unit",
            "control_name",
            "control_value",
            "is_negative_control",
            "replicate",
            "readout_name",
            "readout_type",
            "readout_unit",
        ]
        writer.writerow(headers)

        for var in dsl.variables:
            for val in var.values:
                for rep in range(1, dsl.replicates + 1):
                    for readout in dsl.readouts:
                        row = [
                            f"{dsl.exp_type}_{var.name}_{val}_rep{rep}",
                            dsl.exp_type,
                            var.name,
                            val,
                            var.unit or "",
                            "",
                            "",
                            "",
                            rep,
                            readout.name,
                            readout.type,
                            readout.unit or "",
                        ]
                        writer.writerow(row)

        for ctrl in dsl.controls:
            for rep in range(1, dsl.replicates + 1):
                for readout in dsl.readouts:
                    row = [
                        f"{dsl.exp_type}_ctrl_{ctrl.name}_rep{rep}",
                        dsl.exp_type,
                        "",
                        "",
                        "",
                        ctrl.name,
                        ctrl.value,
                        ctrl.is_negative_control,
                        rep,
                        readout.name,
                        readout.type,
                        readout.unit or "",
                    ]
                    writer.writerow(row)

        return output.getvalue()

    def _build_execution_steps(self, dsl: ExperimentDSL) -> List[Dict[str, Any]]:
        """生成可执行步骤列表"""
        steps: List[Dict[str, Any]] = []

        steps.append({
            "order": 1,
            "name": "validate_dsl",
            "description": "验证实验设计 DSL 完整性",
            "status": "pending",
        })

        steps.append({
            "order": 2,
            "name": "prepare_instrument",
            "description": f"准备仪器: {dsl.exp_type}",
            "status": "pending",
        })

        variable_steps = self._build_variable_steps(dsl)
        steps.extend(variable_steps)

        if dsl.controls:
            steps.append({
                "order": len(steps) + 1,
                "name": "run_controls",
                "description": f"运行对照实验: {len(dsl.controls)} 个对照",
                "status": "pending",
            })

        steps.append({
            "order": len(steps) + 1,
            "name": "collect_readouts",
            "description": f"采集读出: {len(dsl.readouts)} 个指标",
            "status": "pending",
        })

        steps.append({
            "order": len(steps) + 1,
            "name": "parse_and_store",
            "description": "解析原始数据并存储",
            "status": "pending",
        })

        return steps

    def _build_variable_steps(self, dsl: ExperimentDSL) -> List[Dict[str, Any]]:
        """为每个变量生成实验步骤"""
        steps: List[Dict[str, Any]] = []
        order = 3

        for var in dsl.variables:
            steps.append({
                "order": order,
                "name": "run_variable",
                "description": (
                    f"运行变量 '{var.name}': "
                    f"{len(var.values)} 个水平"
                    f"{' (含 ' + str(dsl.replicates) + ' 个重复)' if dsl.replicates > 1 else ''}"
                ),
                "status": "pending",
                "variable": var.name,
                "levels": len(var.values),
                "replicates": dsl.replicates,
            })
            order += 1

        return steps