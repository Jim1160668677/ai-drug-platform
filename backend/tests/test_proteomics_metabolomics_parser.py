"""D1/D2/D3 — 非基因数据解析器测试

验证：
- ProteomicsParser 解析蛋白质表达矩阵 CSV，返回 top_proteins 和 top_genes
- MetabolomicsParser 解析代谢物丰度矩阵 CSV，返回 top_metabolites 和 top_genes
- parse_dataset() 工厂函数正确路由 PROTEOMICS / METABOLOMICS 数据类型
- 文件不存在 / 空矩阵等边界条件
"""
import os
import sys
import tempfile
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.models.dataset import DataType  # noqa: E402
from app.services.parser.base import parse_dataset  # noqa: E402
from app.services.parser.proteomics import ProteomicsParser  # noqa: E402
from app.services.parser.metabolomics import MetabolomicsParser  # noqa: E402


def _write_temp_csv(content: str) -> str:
    """写入临时 CSV 文件并返回路径"""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="test_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _make_dataset(data_type: DataType, path: str) -> SimpleNamespace:
    """构造内存 Dataset 对象"""
    return SimpleNamespace(
        data_type=data_type,
        storage_path=path,
        file_format="CSV",
        file_size=1024,
    )


PROTEOMICS_CSV = """protein,sample1,sample2,sample3
TP53,10.5,12.3,9.8
EGFR,8.1,7.5,8.9
BRCA1,5.2,6.0,4.8
MYC,15.2,14.8,16.0
KRAS,7.3,7.8,7.0
"""

METABOLOMICS_CSV = """metabolite,sample1,sample2,sample3
Glucose,100.5,98.3,102.1
Lactate,45.2,50.0,42.8
Pyruvate,12.1,13.5,11.0
Citrate,8.5,9.0,8.0
Succinate,5.2,5.8,4.9
"""


class TestProteomicsParser:
    """D1: ProteomicsParser"""

    @pytest.mark.asyncio
    async def test_proteomics_parser_parses_csv(self):
        """解析蛋白质表达矩阵 CSV"""
        path = _write_temp_csv(PROTEOMICS_CSV)
        try:
            dataset = _make_dataset(DataType.PROTEOMICS, path)
            parser = ProteomicsParser()
            result = await parser.parse(dataset)
        finally:
            os.unlink(path)

        assert "summary" in result
        assert "quality_metrics" in result
        summary = result["summary"]
        assert summary["proteins"] == 5
        assert summary["samples"] == 3
        assert summary["data_type"] == "proteomics"

        # 同时包含语义化字段和兼容性字段
        assert "top_proteins" in summary
        assert "top_genes" in summary
        assert len(summary["top_proteins"]) == 5
        assert summary["top_proteins"] == summary["top_genes"]

        # top_proteins 按 mean_abundance 降序排列，MYC 应排第一
        top = summary["top_proteins"]
        assert top[0]["symbol"] == "MYC"
        assert top[0]["mean_abundance"] > top[1]["mean_abundance"]

        assert "value_distribution" in summary
        assert "mean" in summary["value_distribution"]

    @pytest.mark.asyncio
    async def test_proteomics_parser_handles_missing_file(self):
        """文件不存在时返回 error"""
        dataset = _make_dataset(DataType.PROTEOMICS, "/nonexistent/path.csv")
        parser = ProteomicsParser()
        result = await parser.parse(dataset)
        assert "error" in result["summary"]
        assert "文件不存在" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_proteomics_parser_handles_empty_matrix(self):
        """空矩阵（仅有表头）时返回 error"""
        path = _write_temp_csv("protein,sample1\n")
        try:
            dataset = _make_dataset(DataType.PROTEOMICS, path)
            parser = ProteomicsParser()
            result = await parser.parse(dataset)
        finally:
            os.unlink(path)
        assert "error" in result["summary"]
        assert "数据矩阵为空" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_proteomics_parser_quality_metrics(self):
        """质量指标包含 missing_rate / low_abundance_ratio"""
        path = _write_temp_csv(PROTEOMICS_CSV)
        try:
            dataset = _make_dataset(DataType.PROTEOMICS, path)
            parser = ProteomicsParser()
            result = await parser.parse(dataset)
        finally:
            os.unlink(path)

        qm = result["quality_metrics"]
        assert "missing_rate" in qm
        assert "low_abundance_ratio" in qm
        assert "sample_missing_rates" in qm
        assert qm["data_type"] == "proteomics"


class TestMetabolomicsParser:
    """D2: MetabolomicsParser"""

    @pytest.mark.asyncio
    async def test_metabolomics_parser_parses_csv(self):
        """解析代谢物丰度矩阵 CSV"""
        path = _write_temp_csv(METABOLOMICS_CSV)
        try:
            dataset = _make_dataset(DataType.METABOLOMICS, path)
            parser = MetabolomicsParser()
            result = await parser.parse(dataset)
        finally:
            os.unlink(path)

        assert "summary" in result
        assert "quality_metrics" in result
        summary = result["summary"]
        assert summary["metabolites"] == 5
        assert summary["samples"] == 3
        assert summary["data_type"] == "metabolomics"

        # 同时包含语义化字段和兼容性字段
        assert "top_metabolites" in summary
        assert "top_genes" in summary
        assert len(summary["top_metabolites"]) == 5
        assert summary["top_metabolites"] == summary["top_genes"]

        # Glucose 丰度最高，应排第一
        top = summary["top_metabolites"]
        assert top[0]["symbol"] == "Glucose"
        assert top[0]["mean_abundance"] > top[1]["mean_abundance"]

    @pytest.mark.asyncio
    async def test_metabolomics_parser_handles_missing_file(self):
        """文件不存在时返回 error"""
        dataset = _make_dataset(DataType.METABOLOMICS, "/nonexistent/path.csv")
        parser = MetabolomicsParser()
        result = await parser.parse(dataset)
        assert "error" in result["summary"]
        assert "文件不存在" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_metabolomics_parser_handles_empty_matrix(self):
        """空矩阵时返回 error"""
        path = _write_temp_csv("metabolite,sample1\n")
        try:
            dataset = _make_dataset(DataType.METABOLOMICS, path)
            parser = MetabolomicsParser()
            result = await parser.parse(dataset)
        finally:
            os.unlink(path)
        assert "error" in result["summary"]
        assert "数据矩阵为空" in result["summary"]["error"]


class TestParseDatasetRouting:
    """D3: parse_dataset() 工厂函数路由"""

    @pytest.mark.asyncio
    async def test_parse_dataset_routes_proteomics(self):
        """工厂函数正确路由 PROTEOMICS 数据类型"""
        path = _write_temp_csv(PROTEOMICS_CSV)
        try:
            dataset = _make_dataset(DataType.PROTEOMICS, path)
            result = await parse_dataset(dataset)
        finally:
            os.unlink(path)

        assert "summary" in result
        assert result["summary"]["data_type"] == "proteomics"
        assert "top_proteins" in result["summary"]

    @pytest.mark.asyncio
    async def test_parse_dataset_routes_metabolomics(self):
        """工厂函数正确路由 METABOLOMICS 数据类型"""
        path = _write_temp_csv(METABOLOMICS_CSV)
        try:
            dataset = _make_dataset(DataType.METABOLOMICS, path)
            result = await parse_dataset(dataset)
        finally:
            os.unlink(path)

        assert "summary" in result
        assert result["summary"]["data_type"] == "metabolomics"
        assert "top_metabolites" in result["summary"]

    @pytest.mark.asyncio
    async def test_parse_dataset_handles_missing_storage_path(self):
        """无 storage_path 时返回 error"""
        dataset = SimpleNamespace(
            data_type=DataType.PROTEOMICS,
            storage_path=None,
            file_format="CSV",
            file_size=0,
        )
        result = await parse_dataset(dataset)
        assert "error" in result["summary"]
        assert "数据集未关联文件路径" in result["summary"]["error"]
