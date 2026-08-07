"""data_analysis 工具组测试 — 4 个工具

测试策略：mock 委托对象（BioAnalyzer 等）+ mock ctx.db，
避免真实数据库与外部依赖。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.data_analysis import (
    AnalyzeDatasetTool,
    ComputeStatisticsTool,
    QueryDataTool,
    VisualizeDataTool,
)


def _make_ctx(db=None, user=None):
    """构造 ToolContext，db 与 user 可 mock"""
    return ToolContext(
        db=db or MagicMock(),
        user=user or MagicMock(),
        task_id="task-test",
        session_id="session-test",
    )


# ========== AnalyzeDatasetTool ==========


@pytest.mark.asyncio
async def test_analyze_dataset_success():
    """成功：BioAnalyzer.differential_expression 返回 plot_data"""
    mock_dataset = MagicMock(id="ds-1")
    mock_db = MagicMock()
    mock_db.get = AsyncMock(return_value=mock_dataset)

    with patch(
        "app.services.analyzer.bio_analyzer.BioAnalyzer"
    ) as MockAnalyzer:
        instance = MockAnalyzer.return_value
        # 方法名必须与 _ANALYSIS_METHOD_MAP["differential"] = "differential_expression" 一致
        # plot_data 必须含 volcano_plot.points 才能生成 chart（否则降级为 table）
        instance.differential_expression = AsyncMock(
            return_value={
                "summary": "ok",
                "plot_data": {
                    "volcano_plot": {
                        "points": [
                            {"x": 1.5, "y": 3.2, "significant": True, "gene": "EGFR"},
                            {"x": -0.8, "y": 1.1, "significant": False, "gene": "KRAS"},
                        ]
                    }
                },
            }
        )
        tool = AnalyzeDatasetTool()
        ctx = _make_ctx(mock_db)
        result = await tool.execute({"dataset_id": "ds-1"}, ctx)

    assert result.success is True
    assert result.data["summary"] == "ok"
    assert result.display["type"] == "chart"


@pytest.mark.asyncio
async def test_analyze_dataset_not_found():
    """数据集不存在"""
    mock_db = MagicMock()
    mock_db.get = AsyncMock(return_value=None)

    tool = AnalyzeDatasetTool()
    ctx = _make_ctx(mock_db)
    result = await tool.execute({"dataset_id": "nonexistent"}, ctx)

    assert result.success is False
    assert "数据集不存在" in result.error


@pytest.mark.asyncio
async def test_analyze_dataset_unsupported_type():
    """不支持的分析类型"""
    mock_dataset = MagicMock(id="ds-1")
    mock_db = MagicMock()
    mock_db.get = AsyncMock(return_value=mock_dataset)

    with patch(
        "app.services.analyzer.bio_analyzer.BioAnalyzer"
    ) as MockAnalyzer:
        # analyzer.analyze_unknown 方法不存在 → getattr 返回 None
        instance = MockAnalyzer.return_value
        instance.analyze_unknown = None
        tool = AnalyzeDatasetTool()
        ctx = _make_ctx(mock_db)
        result = await tool.execute(
            {"dataset_id": "ds-1", "analysis_type": "unknown"}, ctx
        )

    assert result.success is False
    assert "不支持的分析类型" in result.error
    assert "differential" in result.data["available"]


@pytest.mark.asyncio
async def test_analyze_dataset_bio_analyzer_raises():
    """BioAnalyzer 抛异常 → ToolResult.fail"""
    mock_dataset = MagicMock(id="ds-1")
    mock_db = MagicMock()
    mock_db.get = AsyncMock(return_value=mock_dataset)

    with patch(
        "app.services.analyzer.bio_analyzer.BioAnalyzer"
    ) as MockAnalyzer:
        instance = MockAnalyzer.return_value
        # 方法名必须与 _ANALYSIS_METHOD_MAP["differential"] = "differential_expression" 一致
        instance.differential_expression = AsyncMock(
            side_effect=RuntimeError("analysis failed")
        )
        tool = AnalyzeDatasetTool()
        ctx = _make_ctx(mock_db)
        result = await tool.execute({"dataset_id": "ds-1"}, ctx)

    assert result.success is False
    assert "analysis failed" in result.error


# ========== QueryDataTool ==========


@pytest.mark.asyncio
async def test_query_data_unsupported_entity():
    """不支持的实体类型"""
    tool = QueryDataTool()
    ctx = _make_ctx()
    result = await tool.execute({"entity_type": "unknown"}, ctx)
    assert result.success is False
    assert "暂不支持" in result.error


@pytest.mark.asyncio
async def test_query_data_target_entity():
    """target 实体查询：mock apply_project_visibility + db.execute"""
    mock_target = MagicMock()
    mock_target.id = "t-1"
    mock_target.gene_symbol = "EGFR"
    mock_target.confidence_score = 0.9
    mock_target.evidence_grade = "A"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_target]
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch(
        "app.core.authz.apply_project_visibility", return_value=MagicMock()
    ):
        tool = QueryDataTool()
        ctx = _make_ctx(mock_db)
        result = await tool.execute({"entity_type": "target"}, ctx)

    assert result.success is True
    assert result.data["items"][0]["gene_symbol"] == "EGFR"
    assert result.display["type"] == "table"


@pytest.mark.asyncio
async def test_query_data_molecule_entity():
    """molecule 实体查询"""
    mock_mol = MagicMock()
    mock_mol.id = "m-1"
    mock_mol.smiles = "CCO"
    mock_mol.molecular_weight = 46.07
    mock_mol.logp = -0.3

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_mol]
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch(
        "app.core.authz.apply_molecule_visibility", return_value=MagicMock()
    ):
        tool = QueryDataTool()
        ctx = _make_ctx(mock_db)
        result = await tool.execute({"entity_type": "molecule"}, ctx)

    assert result.success is True
    assert result.data["items"][0]["smiles"] == "CCO"


# ========== ComputeStatisticsTool ==========


@pytest.mark.asyncio
async def test_compute_statistics_with_data():
    tool = ComputeStatisticsTool()
    ctx = _make_ctx()
    result = await tool.execute({"data": [1, 2, 3, 4, 5]}, ctx)
    assert result.success is True
    assert result.data["statistics"]["mean"] == 3.0
    assert result.data["count"] == 5
    assert result.display["type"] == "stats"


@pytest.mark.asyncio
async def test_compute_statistics_empty_data():
    tool = ComputeStatisticsTool()
    ctx = _make_ctx()
    result = await tool.execute({"data": []}, ctx)
    assert result.success is True
    assert result.data["statistics"] == {}
    assert result.data["count"] == 0


@pytest.mark.asyncio
async def test_compute_statistics_single_value_std_zero():
    """单值数据 std=0.0（避免除零）"""
    tool = ComputeStatisticsTool()
    ctx = _make_ctx()
    result = await tool.execute({"data": [5]}, ctx)
    assert result.success is True
    assert result.data["statistics"]["std"] == 0.0


@pytest.mark.asyncio
async def test_compute_statistics_missing_data_param():
    """data=None 时返回 fail"""
    tool = ComputeStatisticsTool()
    ctx = _make_ctx()
    result = await tool.execute({}, ctx)
    assert result.success is False
    assert "data 参数必填" in result.error


# ========== VisualizeDataTool ==========


@pytest.mark.asyncio
async def test_visualize_data_returns_spec():
    tool = VisualizeDataTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"data": [{"x": 1, "y": 2}], "chart_type": "scatter", "title": "测试"},
        ctx,
    )
    assert result.success is True
    assert result.data["chart_type"] == "scatter"
    assert result.data["title"] == "测试"
    assert result.display["type"] == "chart"


@pytest.mark.asyncio
async def test_visualize_data_default_fields():
    """不传 x_field/y_field → 默认 "x"/"y" """
    tool = VisualizeDataTool()
    ctx = _make_ctx()
    result = await tool.execute({"data": [1, 2], "chart_type": "bar"}, ctx)
    assert result.success is True
    assert result.data["x_field"] == "x"
    assert result.data["y_field"] == "y"
