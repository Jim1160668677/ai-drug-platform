"""实验设计工具 — 基于研究目标和假设自动生成 ExperimentDSL

工具列表：
- experiment_design: 输入研究目标 + Top 假设 → 输出 ExperimentDSL
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.security import UserRole
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)
from app.services.experiment.dsl import (
    EXPERIMENT_TEMPLATES,
    ExperimentControl,
    ExperimentDSL,
    ExperimentReadout,
    ExperimentVariable,
    get_template,
    list_templates,
)

logger = logging.getLogger(__name__)


class ExperimentDesignTool(AgentTool):
    """实验设计工具 — 基于研究目标和假设自动生成 ExperimentDSL

    根据研究目标和关联的 Top 假设，选择合适的实验类型模板，
    填充变量、对照、读出参数，生成结构化的 ExperimentDSL。

    支持的实验类型：
    - cytotoxicity: 细胞毒性测试
    - docking_validation: 分子对接验证
    - pdx: PDX 动物模型
    - pd: 药效学
    - pk: 药代动力学
    """

    name = "experiment_design"
    description = (
        "基于研究目标和 Top 假设，自动生成结构化的实验设计方案 (ExperimentDSL)。"
        "支持细胞毒性、分子对接验证、PDX、药效学、药代动力学等实验类型。"
        "输出包含变量、对照、读出、重复数等完整实验参数。"
    )
    parameters = [
        ToolParameter(
            "goal",
            "string",
            "研究目标（如 '验证 EGFR 抑制剂对 AML 细胞的杀伤效果'）",
            required=True,
        ),
        ToolParameter(
            "hypothesis_ids",
            "array",
            "关联的假设 ID 列表（可选，用于从假设中提取实验参数）",
            required=False,
            default=[],
        ),
        ToolParameter(
            "exp_type",
            "string",
            "实验类型（cytotoxicity/docking_validation/pdx/pd/pk）",
            required=False,
            default="cytotoxicity",
            enum=["cytotoxicity", "docking_validation", "pdx", "pd", "pk"],
        ),
        ToolParameter(
            "replicates",
            "integer",
            "重复数（默认 3）",
            required=False,
            default=3,
        ),
        ToolParameter(
            "custom_variables",
            "array",
            "自定义变量（可选，覆盖模板默认变量）",
            required=False,
        ),
        ToolParameter(
            "custom_controls",
            "array",
            "自定义对照（可选，覆盖模板默认对照）",
            required=False,
        ),
        ToolParameter(
            "custom_readouts",
            "array",
            "自定义读出（可选，覆盖模板默认读出）",
            required=False,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(
        self, params: Dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        goal = params["goal"]
        hypothesis_ids = params.get("hypothesis_ids") or []
        exp_type = params.get("exp_type", "cytotoxicity")
        replicates = params.get("replicates", 3)
        custom_variables = params.get("custom_variables")
        custom_controls = params.get("custom_controls")
        custom_readouts = params.get("custom_readouts")

        template = get_template(exp_type)
        if template is None:
            return ToolResult.fail(
                error=f"未知实验类型: {exp_type}。"
                f"支持的类型: {list_templates()}"
            )

        dsl = self._build_dsl(
            goal=goal,
            exp_type=exp_type,
            template=template,
            replicates=replicates,
            custom_variables=custom_variables,
            custom_controls=custom_controls,
            custom_readouts=custom_readouts,
        )

        errors = dsl.validate()
        if errors:
            return ToolResult.fail(
                error=f"实验设计验证失败: {'; '.join(errors)}",
                data={"dsl": dsl.to_dict(), "validation_errors": errors},
            )

        compiled = self._compile_dsl(dsl)

        result_data = {
            "dsl": dsl.to_dict(),
            "compiled": compiled,
            "hypothesis_ids": hypothesis_ids,
            "exp_type": exp_type,
            "template_used": dsl.template_name,
        }

        return ToolResult.ok(
            data=result_data,
            display={
                "type": "table",
                "payload": {
                    "title": f"实验设计方案 — {exp_type}",
                    "columns": ["类别", "名称", "值", "单位"],
                    "rows": self._build_display_rows(dsl),
                },
            },
        )

    def _build_dsl(
        self,
        goal: str,
        exp_type: str,
        template: ExperimentDSL,
        replicates: int,
        custom_variables: Optional[List[Dict[str, Any]]],
        custom_controls: Optional[List[Dict[str, Any]]],
        custom_readouts: Optional[List[Dict[str, Any]]],
    ) -> ExperimentDSL:
        variables = []
        if custom_variables:
            for cv in custom_variables:
                variables.append(ExperimentVariable(
                    name=cv["name"],
                    values=cv.get("values", []),
                    unit=cv.get("unit"),
                    description=cv.get("description"),
                ))
        else:
            variables = [
                ExperimentVariable(
                    name=v.name,
                    values=v.values,
                    unit=v.unit,
                    description=v.description,
                )
                for v in template.variables
            ]

        controls = []
        if custom_controls:
            for cc in custom_controls:
                controls.append(ExperimentControl(
                    name=cc["name"],
                    value=cc.get("value"),
                    is_negative_control=cc.get("is_negative_control", False),
                    description=cc.get("description"),
                ))
        else:
            controls = [
                ExperimentControl(
                    name=c.name,
                    value=c.value,
                    is_negative_control=c.is_negative_control,
                    description=c.description,
                )
                for c in template.controls
            ]

        readouts = []
        if custom_readouts:
            for cr in custom_readouts:
                readouts.append(ExperimentReadout(
                    name=cr["name"],
                    type=cr.get("type", "continuous"),
                    unit=cr.get("unit"),
                    description=cr.get("description"),
                ))
        else:
            readouts = [
                ExperimentReadout(
                    name=r.name,
                    type=r.type,
                    unit=r.unit,
                    description=r.description,
                )
                for r in template.readouts
            ]

        return ExperimentDSL(
            exp_type=exp_type,
            variables=variables,
            controls=controls,
            readouts=readouts,
            replicates=replicates,
            expected_result=goal,
            template_name=template.template_name or exp_type,
        )

    def _compile_dsl(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        try:
            from app.services.experiment.dsl_compiler import DSLCompiler

            compiler = DSLCompiler()
            return compiler.compile(dsl)
        except Exception as e:
            logger.warning("DSL 编译失败: %s", e)
            return {"error": str(e)}

    def _build_display_rows(
        self, dsl: ExperimentDSL
    ) -> List[List[Any]]:
        rows: List[List[Any]] = []

        for v in dsl.variables:
            rows.append([
                "变量",
                v.name,
                str(v.values),
                v.unit or "-",
            ])

        for c in dsl.controls:
            tag = " (阴性对照)" if c.is_negative_control else ""
            rows.append([
                "对照",
                c.name + tag,
                str(c.value),
                "-",
            ])

        for r in dsl.readouts:
            rows.append([
                "读出",
                r.name,
                r.type,
                r.unit or "-",
            ])

        rows.append([
            "重复数",
            str(dsl.replicates),
            "",
            "",
        ])

        return rows


__all__ = ["ExperimentDesignTool"]