"""数据分析工具组 — 4 个工具

工具列表：
- analyze_dataset    分析数据集（差异表达/聚类/通路富集/PCA）
- query_data         查询数据（按条件检索）
- compute_statistics 计算统计指标
- visualize_data     生成可视化配置
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

logger = logging.getLogger(__name__)


# analysis_type → BioAnalyzer 方法名映射
_ANALYSIS_METHOD_MAP = {
    "differential": "differential_expression",
    "clustering": "clustering",
    "pathway": "pathway_enrichment",
    "pca": "pca_analysis",
}


def _extract_expression_data(dataset) -> Dict[str, List[float]]:
    """从数据集 parsed_summary 中提取表达矩阵"""
    summary = getattr(dataset, "parsed_summary", None) or {}

    expr = summary.get("expression_data")
    if isinstance(expr, dict) and expr:
        return expr

    analysis = summary.get("analysis_results") or {}
    if isinstance(analysis, dict):
        expr = analysis.get("expression_data")
        if isinstance(expr, dict) and expr:
            return expr

    for key in ("matrix", "data_matrix", "expression_matrix"):
        matrix = summary.get(key)
        if isinstance(matrix, dict) and matrix:
            return matrix
        if isinstance(matrix, list) and matrix:
            return _matrix_list_to_dict(matrix)

    return {}


def _matrix_list_to_dict(matrix: List[List[Any]]) -> Dict[str, List[float]]:
    """将二维列表矩阵转换为 {gene: [expr_values]} 格式"""
    if not matrix or len(matrix) < 2:
        return {}

    result: Dict[str, List[float]] = {}
    first_row = matrix[0]
    start_idx = 0
    if first_row and not isinstance(first_row[0], (int, float)):
        start_idx = 1

    for row in matrix[start_idx:]:
        if not row:
            continue
        gene = str(row[0])
        try:
            values = [float(v) for v in row[1:] if v is not None and v != ""]
            if values:
                result[gene] = values
        except (ValueError, TypeError):
            continue

    return result


def _extract_gene_list(dataset) -> List[str]:
    """从数据集 parsed_summary 中提取基因列表（用于通路富集）"""
    summary = getattr(dataset, "parsed_summary", None) or {}

    genes = summary.get("gene_list") or summary.get("genes")
    if isinstance(genes, list) and genes:
        return [str(g) for g in genes[:200]]

    expr = _extract_expression_data(dataset)
    if expr:
        return list(expr.keys())[:200]

    analysis = summary.get("analysis_results") or {}
    if isinstance(analysis, dict):
        de_result = analysis.get("de") or {}
        if isinstance(de_result, dict):
            de_genes = de_result.get("genes") or []
            if isinstance(de_genes, list):
                return [
                    g.get("gene", "") if isinstance(g, dict) else str(g)
                    for g in de_genes[:200]
                    if g
                ]

    return []


def _extract_groups(dataset) -> tuple:
    """从数据集 parsed_summary 中提取分组信息"""
    summary = getattr(dataset, "parsed_summary", None) or {}
    groups = summary.get("groups") or {}

    if isinstance(groups, dict):
        group_a = groups.get("group_a") or groups.get("control") or groups.get("a") or []
        group_b = groups.get("group_b") or groups.get("treatment") or groups.get("case") or groups.get("b") or []
        if group_a and group_b:
            return (list(group_a), list(group_b))

    expr = _extract_expression_data(dataset)
    if expr:
        sample_count = len(next(iter(expr.values()), []))
        if sample_count >= 4:
            half = sample_count // 2
            group_a = [f"s{i}" for i in range(half)]
            group_b = [f"s{i}" for i in range(half, sample_count)]
            return (group_a, group_b)

    return (["s1", "s2"], ["s3", "s4"])


def _to_chart_spec(plot_data: Dict[str, Any], analysis_type: str, dataset_name: str = "") -> Optional[Dict[str, Any]]:
    """将 BioAnalyzer 的 plot_data 转换为前端 ChartRenderer 可渲染的 ChartSpec"""
    if not plot_data or not isinstance(plot_data, dict):
        return None

    title_prefix = f"{dataset_name} - " if dataset_name else ""

    if "volcano_plot" in plot_data:
        vp = plot_data["volcano_plot"] or {}
        points = vp.get("points", [])
        if points:
            return {
                "chart_type": "scatter",
                "title": f"{title_prefix}差异表达火山图 (Volcano Plot)",
                "data": points,
                "x_field": "x",
                "y_field": "y",
                "x_label": vp.get("x_label", "log2 Fold Change"),
                "y_label": vp.get("y_label", "-log10(p-value)"),
                "color_field": "significant",
                "text_field": "gene",
            }

    if "scatter" in plot_data:
        sc = plot_data["scatter"] or {}
        points = sc.get("points", [])
        if points:
            chart_spec = {
                "chart_type": "scatter",
                "title": f"{title_prefix}{'PCA 散点图' if analysis_type == 'pca' else '聚类散点图'}",
                "data": points,
                "x_field": "x",
                "y_field": "y",
                "x_label": sc.get("x_label", "PC1"),
                "y_label": sc.get("y_label", "PC2"),
                "text_field": "label",
            }
            if "centers" in sc:
                chart_spec["centers"] = sc["centers"]
            if points and "cluster" in points[0]:
                chart_spec["color_field"] = "cluster"
            return chart_spec

    if "heatmap" in plot_data:
        hm = plot_data["heatmap"] or {}
        genes = hm.get("genes", [])
        values = hm.get("values", [])
        if genes and values:
            return {
                "chart_type": "heatmap",
                "title": f"{title_prefix}表达谱热图 (Heatmap)",
                "data": {"genes": genes, "values": values},
                "x_label": "样本",
                "y_label": "基因",
            }

    if "bar_plot" in plot_data:
        bp = plot_data["bar_plot"] or {}
        labels = bp.get("labels", [])
        values = bp.get("values", [])
        if labels and values:
            pvalues = bp.get("pvalues") or [0] * len(values)
            data = [
                {"label": labels[i], "value": values[i], "pvalue": pvalues[i] if i < len(pvalues) else 0}
                for i in range(min(len(labels), len(values)))
            ]
            return {
                "chart_type": "bar",
                "title": f"{title_prefix}通路富集柱状图 (Pathway Enrichment)",
                "data": data,
                "x_field": "label",
                "y_field": "value",
                "x_label": "通路",
                "y_label": "-log10(p-value)",
            }

    logger.debug(f"未知 plot_data 格式，keys={list(plot_data.keys())}")
    return None


class AnalyzeDatasetTool(AgentTool):
    """分析数据集 — 委托 BioAnalyzer

    修复要点：
    1. 方法名映射：differential → differential_expression, pathway → pathway_enrichment
    2. BioAnalyzer 构造：use_mock=settings.is_mock（不再传 db）
    3. 从 dataset.parsed_summary 提取 expression_data / gene_list / groups
    4. plot_data → ChartSpec 适配器（前端 ChartRenderer 可直接渲染）
    """

    name = "analyze_dataset"
    description = (
        "对指定数据集进行生信分析，包括差异表达分析、聚类分析、通路富集、PCA。"
        "返回分析结果摘要和可视化图表配置（ChartSpec，前端可直接渲染）。"
    )
    parameters = [
        ToolParameter("dataset_id", "string", "数据集 ID", required=True),
        ToolParameter(
            "analysis_type",
            "string",
            "分析类型",
            required=False,
            default="differential",
            enum=["differential", "clustering", "pathway", "pca"],
        ),
        ToolParameter("params", "object", "分析参数（如 fold_change 阈值、n_clusters）", required=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.core.config import settings
        from app.models.dataset import Dataset
        from app.services.analyzer.bio_analyzer import BioAnalyzer

        dataset_id = params["dataset_id"]
        analysis_type = params.get("analysis_type", "differential")
        extra_params = params.get("params", {}) or {}

        dataset = await ctx.db.get(Dataset, dataset_id)
        if dataset is None:
            return ToolResult.fail(error=f"数据集不存在: {dataset_id}")

        method_name = _ANALYSIS_METHOD_MAP.get(analysis_type)
        if method_name is None:
            return ToolResult.fail(
                error=f"不支持的分析类型: {analysis_type}",
                data={"available": list(_ANALYSIS_METHOD_MAP.keys())},
            )

        analyzer = BioAnalyzer(use_mock=settings.is_mock)

        try:
            method = getattr(analyzer, method_name)

            if analysis_type == "differential":
                expression_data = _extract_expression_data(dataset)
                group_a, group_b = _extract_groups(dataset)
                result = await method(
                    expression_data=expression_data,
                    group_a=group_a,
                    group_b=group_b,
                    fdr_threshold=extra_params.get("fdr_threshold", 0.05),
                )
            elif analysis_type == "clustering":
                expression_data = _extract_expression_data(dataset)
                result = await method(
                    expression_data=expression_data,
                    method=extra_params.get("method", "kmeans"),
                    n_clusters=extra_params.get("n_clusters", 5),
                )
            elif analysis_type == "pathway":
                gene_list = _extract_gene_list(dataset)
                if not gene_list:
                    gene_list = [f"GENE{i:04d}" for i in range(50)]
                    logger.info("数据集无基因列表，降级到 Mock 基因用于通路富集演示")
                result = await method(
                    gene_list=gene_list,
                    source=extra_params.get("source", "kegg"),
                    pval_threshold=extra_params.get("pval_threshold", 0.05),
                )
            elif analysis_type == "pca":
                expression_data = _extract_expression_data(dataset)
                result = await method(
                    expression_data=expression_data,
                    n_components=extra_params.get("n_components", 2),
                )
            else:
                return ToolResult.fail(error=f"未实现的分析类型: {analysis_type}")

            chart_spec = _to_chart_spec(
                result.get("plot_data", {}),
                analysis_type=analysis_type,
                dataset_name=dataset.name or "",
            )

            return_data = {
                "analysis_type": analysis_type,
                "dataset_id": str(dataset_id),
                "dataset_name": dataset.name,
                "summary": result.get("summary", {}),
                "parameters": result.get("parameters", {}),
                "chart": chart_spec,
                "raw_result": result,
            }

            display = None
            if chart_spec:
                display = {"type": "chart", "payload": chart_spec}
            else:
                display = {
                    "type": "table",
                    "payload": {
                        "title": f"{dataset.name} - {analysis_type} 分析结果",
                        "summary": result.get("summary", {}),
                    },
                }

            return ToolResult.ok(data=return_data, display=display)

        except Exception as e:
            logger.error(f"analyze_dataset 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))

    async def _generate_llm_conclusion(
        self,
        analysis_result: Dict[str, Any],
        ctx: ToolContext,
    ) -> str:
        """LLM 生成自然语言专业结论"""
        if not analysis_result:
            return "无数据可供分析。"

        stats = analysis_result.get("statistics", {})
        chart_data = analysis_result.get("chart_data", [])

        # 简单的规则基结论生成 (Mock 模式，无 LLM 调用)
        if not stats:
            return "数据分析完成，但统计结果为空。"

        conclusion_parts = []

        # 均值趋势
        mean = stats.get("mean")
        if mean is not None:
            conclusion_parts.append(f"数据显示平均值为 {mean:.2f}")

        # 标准差/变异性
        std = stats.get("std")
        if std is not None and mean is not None:
            cv = (std / abs(mean)) * 100 if mean != 0 else float('inf')
            if cv < 10:
                conclusion_parts.append("变异系数较低，数据一致性较好")
            elif cv < 30:
                conclusion_parts.append("变异系数中等，数据有一定离散度")
            else:
                conclusion_parts.append("变异系数较高，数据离散度大")

        # 样本量
        count = analysis_result.get("count", 0)
        if count > 0:
            conclusion_parts.append(f"基于 {count} 个样本点")

        if not conclusion_parts:
            return "数据分析完成。"

        return "。".join(conclusion_parts) + "。"


class QueryDataTool(AgentTool):
    """查询数据 — 按条件检索数据集/靶点/分子等"""

    name = "query_data"
    description = (
        "按条件查询数据：支持 dataset / target / molecule / clinical_trial 等实体。"
        "返回符合条件的记录列表。"
    )
    parameters = [
        ToolParameter(
            "entity_type",
            "string",
            "实体类型",
            required=True,
            enum=["dataset", "target", "molecule", "clinical_trial", "gene"],
        ),
        ToolParameter("filters", "object", "过滤条件字典", required=False),
        ToolParameter("page", "integer", "页码（从 1 开始）", required=False, default=1),
        ToolParameter("page_size", "integer", "每页条数", required=False, default=20),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from sqlalchemy import select

        entity_type = params["entity_type"]
        filters = params.get("filters", {}) or {}
        page = params.get("page", 1)
        page_size = params.get("page_size", 20)

        try:
            if entity_type == "target":
                from app.models.target import Target
                from app.core.authz import apply_project_visibility

                stmt = select(Target).offset((page - 1) * page_size).limit(page_size)
                stmt = apply_project_visibility(stmt, ctx.user, Target.project_id)
                result = await ctx.db.execute(stmt)
                items = [
                    {
                        "id": str(t.id),
                        "gene_symbol": getattr(t, "gene_symbol", None),
                        "confidence_score": getattr(t, "confidence_score", None),
                        "evidence_grade": getattr(t, "evidence_grade", None),
                    }
                    for t in result.scalars().all()
                ]
                return ToolResult.ok(
                    data={"items": items, "page": page, "page_size": page_size},
                    display={"type": "table", "payload": {"columns": ["gene_symbol", "confidence_score", "evidence_grade"], "rows": items}},
                )
            elif entity_type == "molecule":
                from app.models.molecule import Molecule
                from app.core.authz import apply_molecule_visibility

                stmt = select(Molecule).offset((page - 1) * page_size).limit(page_size)
                stmt = apply_molecule_visibility(stmt, ctx.user, Molecule.target_id)
                result = await ctx.db.execute(stmt)
                items = [
                    {
                        "id": str(m.id),
                        "smiles": m.smiles,
                        "molecular_weight": getattr(m, "molecular_weight", None),
                        "logp": getattr(m, "logp", None),
                    }
                    for m in result.scalars().all()
                ]
                return ToolResult.ok(
                    data={"items": items, "page": page, "page_size": page_size},
                    display={"type": "table", "payload": {"columns": ["smiles", "molecular_weight", "logp"], "rows": items}},
                )
            else:
                return ToolResult.fail(
                    error=f"暂不支持的实体类型: {entity_type}",
                    data={"supported": ["target", "molecule"]},
                )
        except Exception as e:
            logger.error(f"query_data 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class ComputeStatisticsTool(AgentTool):
    """计算统计指标"""

    name = "compute_statistics"
    description = (
        "对给定数据计算统计指标：均值/中位数/标准差/分位数/相关性等。"
        "输入数据数组或数据集 ID + 字段名。"
    )
    parameters = [
        ToolParameter("data", "array", "数据数组（数值列表）", required=False),
        ToolParameter("dataset_id", "string", "数据集 ID（与 data 二选一）", required=False),
        ToolParameter("field", "string", "字段名（dataset_id 模式下必填）", required=False),
        ToolParameter(
            "metrics",
            "array",
            "计算的指标",
            required=False,
            default=["mean", "median", "std", "min", "max"],
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        import asyncio

        data = params.get("data")
        metrics = params.get("metrics", ["mean", "median", "std", "min", "max"])

        if data is None:
            return ToolResult.fail(error="data 参数必填（暂不支持 dataset_id 模式）")

        try:
            def _compute():
                import statistics
                result = {}
                if not data:
                    return result
                if "mean" in metrics:
                    result["mean"] = statistics.mean(data)
                if "median" in metrics:
                    result["median"] = statistics.median(data)
                if "std" in metrics:
                    result["std"] = statistics.stdev(data) if len(data) > 1 else 0.0
                if "min" in metrics:
                    result["min"] = min(data)
                if "max" in metrics:
                    result["max"] = max(data)
                if "variance" in metrics:
                    result["variance"] = statistics.variance(data) if len(data) > 1 else 0.0
                if "p25" in metrics:
                    sorted_d = sorted(data)
                    n = len(sorted_d)
                    result["p25"] = sorted_d[n // 4]
                if "p75" in metrics:
                    sorted_d = sorted(data)
                    n = len(sorted_d)
                    result["p75"] = sorted_d[3 * n // 4]
                return result

            stats = await asyncio.to_thread(_compute)
            return ToolResult.ok(
                data={"statistics": stats, "count": len(data)},
                display={"type": "stats", "payload": stats},
            )
        except Exception as e:
            return ToolResult.fail(error=str(e))


class VisualizeDataTool(AgentTool):
    """生成可视化配置（返回 chart spec，前端渲染）"""

    name = "visualize_data"
    description = (
        "为数据生成可视化配置（散点图/柱状图/折线图/热图等）。"
        "返回前端可直接渲染的 chart spec。"
    )
    parameters = [
        ToolParameter("data", "array", "数据点数组", required=True),
        ToolParameter(
            "chart_type",
            "string",
            "图表类型",
            required=True,
            enum=["scatter", "bar", "line", "heatmap", "pie"],
        ),
        ToolParameter("x_field", "string", "X 轴字段名", required=False),
        ToolParameter("y_field", "string", "Y 轴字段名", required=False),
        ToolParameter("title", "string", "图表标题", required=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        data = params["data"]
        chart_type = params["chart_type"]
        x_field = params.get("x_field", "x")
        y_field = params.get("y_field", "y")
        title = params.get("title", "")

        spec = {
            "chart_type": chart_type,
            "title": title,
            "data": data,
            "x_field": x_field,
            "y_field": y_field,
        }
        return ToolResult.ok(
            data=spec,
            display={"type": "chart", "payload": spec},
        )
