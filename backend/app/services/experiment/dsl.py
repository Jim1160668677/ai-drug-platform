"""ExperimentDSL — 实验设计领域特定语言

JSON Schema 定义，用于描述实验设计。
支持变量/对照/重复/读出/预期结果的结构化定义。
"""
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class ExperimentVariable:
    name: str
    values: List[Any]
    unit: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ExperimentControl:
    name: str
    value: Any
    is_negative_control: bool = False
    description: Optional[str] = None


@dataclass
class ExperimentReadout:
    name: str
    type: str
    unit: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ExperimentDSL:
    """实验设计 DSL 结构"""
    exp_type: str
    variables: List[ExperimentVariable]
    controls: List[ExperimentControl]
    readouts: List[ExperimentReadout]
    replicates: int = 3
    expected_result: Optional[str] = None
    template_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentDSL":
        kwargs: Dict[str, Any] = {}
        for k, v in data.items():
            if k in ("variables", "controls", "readouts"):
                if isinstance(v, list):
                    class_map = {
                        "variables": ExperimentVariable,
                        "controls": ExperimentControl,
                        "readouts": ExperimentReadout,
                    }
                    target_cls = class_map[k]
                    kwargs[k] = [
                        target_cls(**item) if isinstance(item, dict) else item
                        for item in v
                    ]
                elif isinstance(v, dict):
                    class_map = {
                        "variables": ExperimentVariable,
                        "controls": ExperimentControl,
                        "readouts": ExperimentReadout,
                    }
                    target_cls = class_map[k]
                    kwargs[k] = target_cls(**v)
                else:
                    kwargs[k] = v
            else:
                kwargs[k] = v
        return cls(**kwargs)

    def validate(self) -> List[str]:
        """验证 DSL 完整性，返回错误列表"""
        errors = []
        if not self.exp_type:
            errors.append("exp_type 不能为空")
        if not self.variables:
            errors.append("至少需要一个变量")
        if not self.readouts:
            errors.append("至少需要一个读出")
        if self.replicates < 1:
            errors.append("重复数必须 >= 1")
        valid_types = {"continuous", "categorical", "survival"}
        for r in self.readouts:
            if r.type not in valid_types:
                errors.append(
                    f"读出 '{r.name}' 的类型 '{r.type}' 不合法，"
                    f"有效值: {valid_types}"
                )
        return errors


EXPERIMENT_TEMPLATES: Dict[str, ExperimentDSL] = {
    "cytotoxicity": ExperimentDSL(
        exp_type="cytotoxicity",
        variables=[
            ExperimentVariable(
                name="concentration",
                values=[0.01, 0.1, 1, 10, 100],
                unit="μM",
            )
        ],
        controls=[
            ExperimentControl(
                name="untreated",
                value=0,
                is_negative_control=True,
            )
        ],
        readouts=[
            ExperimentReadout(
                name="cell_viability",
                type="continuous",
                unit="%",
            )
        ],
        replicates=3,
        template_name="cytotoxicity",
    ),
    "docking_validation": ExperimentDSL(
        exp_type="docking_validation",
        variables=[
            ExperimentVariable(name="target", values=[])
        ],
        controls=[],
        readouts=[
            ExperimentReadout(
                name="binding_energy",
                type="continuous",
                unit="kcal/mol",
            )
        ],
        replicates=1,
        template_name="docking_validation",
    ),
}


def get_template(name: str) -> Optional[ExperimentDSL]:
    """获取预设模板"""
    return EXPERIMENT_TEMPLATES.get(name)


def list_templates() -> List[str]:
    """列出所有模板名称"""
    return list(EXPERIMENT_TEMPLATES.keys())