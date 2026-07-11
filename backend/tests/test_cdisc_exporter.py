"""CdiscExporter 单元测试 — 覆盖 CDISC SDTM 导出器的全部公开方法与关键路径。

测试范围：
- export(): 报告未找到 / 成功导出 / 多种 content_json 与 llm_cost_usd 边界
- _build_ts_domain(): cancer_type / disease / 默认 NSCLC / analysis_tier 缺省
- _build_dm_domain(): created_at 存在 / 为 None
- _build_ae_domain(): 低/高置信度靶点、非字典靶点、llm_cost_usd 超支、置信度 0.3 边界
- _build_lb_domain(): 显式数据集 / 非字典 / 默认 LB 记录
- _generate_download_url(): Mock 模式 / Real 模式 / 异常降级
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ========== 辅助函数 ==========

# 哨兵：区分"未传 created_at"与"显式传 None"
_UNSET = object()


def _make_report(
    *,
    content_json=None,
    analysis_tier="quick",
    llm_cost_usd=None,
    created_at=_UNSET,
    project_id=None,
):
    """构造一个用于测试的 TargetReport-like SimpleNamespace 对象。

    使用 SimpleNamespace 规避 ORM 校验，专注导出器逻辑。
    显式传 created_at=None 时保留为 None，以测试 None 处理分支。
    """
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id or uuid4(),
        content_json=content_json,
        analysis_tier=analysis_tier,
        llm_cost_usd=llm_cost_usd,
        duration_seconds=120,
        content_md="# Report",
        cdisc_sdtm_path=None,
        created_at=(
            datetime(2024, 1, 1, tzinfo=timezone.utc) if created_at is _UNSET else created_at
        ),
    )


# ========== export() ==========

class TestCdiscExporterExport:
    """CdiscExporter.export() 测试"""

    @pytest.mark.asyncio
    async def test_export_report_not_found(self):
        """报告未找到时返回 status=not_found 降级响应"""
        from app.services.report.cdisc_exporter import CdiscExporter

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        exporter = CdiscExporter(mock_db)

        rid = uuid4()
        result = await exporter.export(rid)

        assert result["status"] == "not_found"
        assert result["download_url"] == ""
        assert result["expires_at"] == ""
        assert result["domains"] == []
        assert result["report_id"] == str(rid)

    @pytest.mark.asyncio
    async def test_export_success_basic(self):
        """完整成功路径：四域全部生成、download_url 与 expires_at 存在"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={"cancer_type": "NSCLC"})
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["status"] == "exported"
        assert result["domains"] == ["TS", "DM", "AE", "LB"]
        assert "download_url" in result
        assert "expires_at" in result
        assert result["report_id"] == str(report.id)
        assert result["study_id"].startswith("PDD-RPT-")
        assert "TS" in result["record_counts"]
        assert "DM" in result["record_counts"]
        assert "AE" in result["record_counts"]
        assert "LB" in result["record_counts"]

    @pytest.mark.asyncio
    async def test_export_study_id_derived_from_report_id(self):
        """study_id 应基于 report.id 前 8 位大写生成"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={})
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        expected_prefix = f"PDD-RPT-{str(report.id)[:8].upper()}"
        assert result["study_id"] == expected_prefix

    @pytest.mark.asyncio
    async def test_export_record_counts_with_low_confidence_targets(self):
        """低置信度靶点应计入 AE 域计数"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "GENE_A", "confidence_score": 0.1},  # 低 -> AE
                    {"gene_symbol": "GENE_B", "confidence_score": 0.9},  # 高 -> 不计
                    {"gene_symbol": "GENE_C", "confidence_score": 0.4},  # 低 -> AE
                ],
            },
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["record_counts"]["AE"] == 2
        assert result["record_counts"]["TS"] == 5

    @pytest.mark.asyncio
    async def test_export_record_counts_with_datasets(self):
        """datasets 应映射到 LB 域计数"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "datasets": [
                    {"data_type": "rna_seq", "name": "DS1", "file_format": "CSV"},
                    {"data_type": "scRNA", "name": "DS2", "file_format": "H5"},
                ],
            },
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["record_counts"]["LB"] == 2


# ========== _build_ts_domain() ==========

class TestCdiscExporterTsDomain:
    """_build_ts_domain 测试"""

    def test_ts_with_cancer_type(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={"cancer_type": "Breast"})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_ts_domain(report)

        assert len(records) == 5
        assert all(r["STUDYID"].startswith("PDD-RPT-") for r in records)
        assert all(r["DOMAIN"] == "TS" for r in records)
        # TITLE 与 INDIC 应反映 cancer_type
        title = next(r for r in records if r["TSPARMCD"] == "TITLE")
        assert "Breast" in title["TSVAL"]
        indic = next(r for r in records if r["TSPARMCD"] == "INDIC")
        assert indic["TSVAL"] == "Breast"
        # TTYPE 固定为 DRUG_DISCOVERY
        ttype = next(r for r in records if r["TSPARMCD"] == "TTYPE")
        assert ttype["TSVAL"] == "DRUG_DISCOVERY"
        # STYPE 取自 analysis_tier
        stype = next(r for r in records if r["TSPARMCD"] == "STYPE")
        assert stype["TSVAL"] == "quick"
        # TPROTCL 应为 project_id 字符串
        tprotcl = next(r for r in records if r["TSPARMCD"] == "TPROTCL")
        assert tprotcl["TSVAL"] == str(report.project_id)

    def test_ts_falls_back_to_disease_when_no_cancer_type(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={"disease": "Melanoma"})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_ts_domain(report)

        indic = next(r for r in records if r["TSPARMCD"] == "INDIC")
        assert indic["TSVAL"] == "Melanoma"

    def test_ts_defaults_to_nsclc_when_content_missing(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_ts_domain(report)

        indic = next(r for r in records if r["TSPARMCD"] == "INDIC")
        assert indic["TSVAL"] == "NSCLC"

    def test_ts_defaults_to_nsclc_when_content_json_none(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_ts_domain(report)

        assert len(records) == 5
        indic = next(r for r in records if r["TSPARMCD"] == "INDIC")
        assert indic["TSVAL"] == "NSCLC"

    def test_ts_uses_analysis_tier_when_none(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={}, analysis_tier=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_ts_domain(report)

        stype = next(r for r in records if r["TSPARMCD"] == "STYPE")
        assert stype["TSVAL"] == "quick"


# ========== _build_dm_domain() ==========

class TestCdiscExporterDmDomain:
    """_build_dm_domain 测试"""

    def test_dm_basic_with_created_at(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        report = _make_report(
            content_json={"cancer_type": "NSCLC"},
            created_at=ts,
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_dm_domain(report)

        assert len(records) == 1
        rec = records[0]
        assert rec["DOMAIN"] == "DM"
        assert rec["STUDYID"].startswith("PDD-RPT-")
        assert rec["USUBJID"].startswith("PROJ-")
        assert rec["SUBJID"] == str(report.project_id)
        assert rec["RFICDTC"] == ts.isoformat()
        assert rec["ARM"] == "NSCLC"
        assert rec["AGE"] == ""
        assert rec["SEX"] == ""
        assert rec["RACE"] == ""
        assert rec["ETHNIC"] == ""

    def test_dm_handles_none_created_at(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={}, created_at=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_dm_domain(report)

        assert records[0]["RFICDTC"] == ""

    def test_dm_defaults_arm_when_cancer_type_missing(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = exporter._build_dm_domain(report)

        assert records[0]["ARM"] == "NSCLC"


# ========== _build_ae_domain() ==========

class TestCdiscExporterAeDomain:
    """_build_ae_domain 测试"""

    @pytest.mark.asyncio
    async def test_ae_empty_when_no_targets(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records == []

    @pytest.mark.asyncio
    async def test_ae_filters_high_confidence_targets(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "HIGH", "confidence_score": 0.9},
                    {"gene_symbol": "MID", "confidence_score": 0.5},  # 边界，不计 AE
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records == []

    @pytest.mark.asyncio
    async def test_ae_includes_low_confidence_targets_with_seq(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "GENE_A", "confidence_score": 0.1},
                    {"gene_symbol": "GENE_B", "confidence_score": 0.4},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert len(records) == 2
        # AESEQ 取 enumerate 索引+1，不是按低置信度子集计数
        assert records[0]["AESEQ"] == 1
        assert records[1]["AESEQ"] == 2
        assert "GENE_A" in records[0]["AETERM"]
        assert "GENE_B" in records[1]["AETERM"]
        assert records[0]["AEDECOD"] == "LOW_CONFIDENCE_TARGET"
        # 0.1 < 0.3 -> MODERATE; 0.4 >= 0.3 -> MILD
        assert records[0]["AESEV"] == "MODERATE"
        assert records[1]["AESEV"] == "MILD"

    @pytest.mark.asyncio
    async def test_ae_confidence_0_3_boundary_is_mild(self):
        """confidence_score == 0.3 应归为 MILD（>= 0.3）"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "B", "confidence_score": 0.3},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert len(records) == 1
        assert records[0]["AESEV"] == "MILD"

    @pytest.mark.asyncio
    async def test_ae_skips_non_dict_targets(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    "not_a_dict",
                    {"gene_symbol": "LOW", "confidence_score": 0.2},
                    42,
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert len(records) == 1
        # AESEQ 取 enumerate 索引+1，第二条（i=1）记录
        assert records[0]["AESEQ"] == 2
        assert "LOW" in records[0]["AETERM"]

    @pytest.mark.asyncio
    async def test_ae_uses_unknown_gene_symbol_when_missing(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"confidence_score": 0.1},  # 无 gene_symbol
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert len(records) == 1
        assert "unknown" in records[0]["AETERM"]

    @pytest.mark.asyncio
    async def test_ae_handles_none_confidence_score(self):
        """confidence_score 为 None 时应回退为 1.0（不计 AE）"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "X", "confidence_score": None},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records == []

    @pytest.mark.asyncio
    async def test_ae_llm_cost_overflow_adds_record(self):
        """llm_cost_usd 超过 FAST_SCREEN_MAX_COST_USD 时追加 BUDGET_OVERFLOW"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={},
            llm_cost_usd=Decimal("100.0"),
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.FAST_SCREEN_MAX_COST_USD = 5.0
            records = await exporter._build_ae_domain(report)

        assert any(r["AEDECOD"] == "BUDGET_OVERFLOW" for r in records)
        budget_rec = next(r for r in records if r["AEDECOD"] == "BUDGET_OVERFLOW")
        assert budget_rec["AESEV"] == "MODERATE"
        assert budget_rec["AETERM"] == "LLM cost exceeded budget"
        # AESEQ 应为已有记录数 + 1
        assert budget_rec["AESEQ"] == 1

    @pytest.mark.asyncio
    async def test_ae_llm_cost_overflow_seq_after_targets(self):
        """BUDGET_OVERFLOW 的 AESEQ 应在低置信度靶点之后"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "LOW1", "confidence_score": 0.1},
                    {"gene_symbol": "LOW2", "confidence_score": 0.2},
                ],
            },
            llm_cost_usd=Decimal("10.0"),
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.FAST_SCREEN_MAX_COST_USD = 5.0
            records = await exporter._build_ae_domain(report)

        assert len(records) == 3
        budget_rec = next(r for r in records if r["AEDECOD"] == "BUDGET_OVERFLOW")
        assert budget_rec["AESEQ"] == 3

    @pytest.mark.asyncio
    async def test_ae_llm_cost_at_boundary_not_overflow(self):
        """llm_cost_usd == 阈值（不严格大于）时不应追加 BUDGET_OVERFLOW"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={},
            llm_cost_usd=Decimal("5.0"),
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.FAST_SCREEN_MAX_COST_USD = 5.0
            records = await exporter._build_ae_domain(report)

        assert records == []

    @pytest.mark.asyncio
    async def test_ae_skips_when_llm_cost_none(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={}, llm_cost_usd=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records == []

    @pytest.mark.asyncio
    async def test_ae_uses_created_at_iso_when_present(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        report = _make_report(
            content_json={"targets": [{"gene_symbol": "X", "confidence_score": 0.1}]},
            created_at=ts,
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records[0]["AEDTC"] == ts.isoformat()

    @pytest.mark.asyncio
    async def test_ae_handles_none_created_at(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={"targets": [{"gene_symbol": "X", "confidence_score": 0.1}]},
            created_at=None,
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_ae_domain(report)

        assert records[0]["AEDTC"] == ""


# ========== _build_lb_domain() ==========

class TestCdiscExporterLbDomain:
    """_build_lb_domain 测试"""

    @pytest.mark.asyncio
    async def test_lb_with_datasets(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "datasets": [
                    {"data_type": "rna_seq", "name": "RNA", "file_format": "CSV"},
                    {"data_type": "scRNA", "name": "Single Cell", "file_format": "H5"},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert len(records) == 2
        assert records[0]["LBSEQ"] == 1
        assert records[1]["LBSEQ"] == 2
        assert records[0]["LBTESTCD"] == "RNA_SEQ"[:8].upper()  # 截断 8 字符
        assert records[0]["LBTEST"] == "RNA"
        assert records[0]["LBORRES"] == "CSV"
        assert records[0]["LBORU"] == "FILE"
        assert records[0]["LBCAT"] == "rna_seq"
        assert records[0]["DOMAIN"] == "LB"

    @pytest.mark.asyncio
    async def test_lb_data_type_truncated_to_8_chars(self):
        """LBTESTCD 应截断为 8 字符并大写"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "datasets": [
                    {"data_type": "very_long_type_name", "name": "DS", "file_format": "CSV"},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert records[0]["LBTESTCD"] == "VERY_LON"

    @pytest.mark.asyncio
    async def test_lb_defaults_data_type_when_missing(self):
        """data_type 缺失/为 None 时 LBTESTCD 应为 UNKNOWN"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "datasets": [
                    {"name": "DS", "file_format": "CSV"},  # 无 data_type
                    {"data_type": None, "name": "DS2", "file_format": "CSV"},
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert records[0]["LBTESTCD"] == "UNKNOWN"
        assert records[1]["LBTESTCD"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_lb_skips_non_dict_datasets(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "datasets": [
                    "invalid",
                    {"data_type": "rna_seq", "name": "DS", "file_format": "CSV"},
                    42,
                ],
            },
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert len(records) == 1
        assert records[0]["LBSEQ"] == 2  # enumerate 索引+1

    @pytest.mark.asyncio
    async def test_lb_default_record_when_no_datasets(self):
        """无 datasets 时应生成默认报告 LB 记录"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert len(records) == 1
        rec = records[0]
        assert rec["LBSEQ"] == 1
        assert rec["LBTESTCD"] == "RPT"
        assert rec["LBTEST"] == "Target Report"
        assert rec["LBORRES"] == "quick"  # analysis_tier
        assert rec["LBORU"] == "TIER"
        assert rec["LBCAT"] == "REPORT"

    @pytest.mark.asyncio
    async def test_lb_default_record_when_content_json_none(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert len(records) == 1
        assert records[0]["LBTESTCD"] == "RPT"

    @pytest.mark.asyncio
    async def test_lb_default_record_when_datasets_empty_list(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={"datasets": []})
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert len(records) == 1
        assert records[0]["LBTESTCD"] == "RPT"

    @pytest.mark.asyncio
    async def test_lb_uses_created_at_iso_when_present(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        report = _make_report(
            content_json={
                "datasets": [{"data_type": "rna_seq", "name": "DS", "file_format": "CSV"}],
            },
            created_at=ts,
        )
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert records[0]["LBDTC"] == ts.isoformat()

    @pytest.mark.asyncio
    async def test_lb_handles_none_created_at(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={}, created_at=None)
        exporter = CdiscExporter.__new__(CdiscExporter)
        records = await exporter._build_lb_domain(report)

        assert records[0]["LBDTC"] == ""


# ========== _generate_download_url() ==========

class TestCdiscExporterDownloadUrl:
    """_generate_download_url 测试"""

    def test_mock_mode_returns_mock_url(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report()
        exporter = CdiscExporter.__new__(CdiscExporter)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.is_mock = True
            url, expires_at = exporter._generate_download_url(report)

        assert url.startswith("mock://cdisc/exports/")
        assert str(report.id) in url
        assert url.endswith(f"sdtm_{report.id}.csv")
        # expires_at 应为合法 ISO8601
        datetime.fromisoformat(expires_at)

    def test_real_mode_returns_minio_url(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report()
        exporter = CdiscExporter.__new__(CdiscExporter)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.is_mock = False
            mock_settings.MINIO_ENDPOINT = "minio.local:9000"
            mock_settings.MINIO_BUCKET = "pdd-bucket"
            url, expires_at = exporter._generate_download_url(report)

        assert url.startswith("https://minio.local:9000/pdd-bucket/cdisc/exports/")
        assert str(report.id) in url
        datetime.fromisoformat(expires_at)

    def test_real_mode_falls_back_to_mock_on_exception(self):
        """Real 模式下抛异常应降级为 mock URL（虽然当前实现几乎不会抛，但保留分支覆盖）"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report()
        exporter = CdiscExporter.__new__(CdiscExporter)

        # 构造一个会让 f-string 计算抛异常的对象（覆盖 except 分支）
        # 通过让 settings.MINIO_ENDPOINT 抛异常实现
        class _ThrowingSettings:
            is_mock = False

            @property
            def MINIO_ENDPOINT(self):
                raise RuntimeError("boom")

            MINIO_BUCKET = "b"

        with patch("app.services.report.cdisc_exporter.settings", _ThrowingSettings()):
            url, expires_at = exporter._generate_download_url(report)

        assert url.startswith("mock://cdisc/exports/")
        datetime.fromisoformat(expires_at)

    def test_expires_at_24_hours_in_future(self):
        """过期时间应约为当前时间 + 24 小时"""
        from app.services.report.cdisc_exporter import CdiscExporter
        from app.services.report.cdisc_exporter import _DEFAULT_LINK_TTL_HOURS

        assert _DEFAULT_LINK_TTL_HOURS == 24

        report = _make_report()
        exporter = CdiscExporter.__new__(CdiscExporter)
        before = datetime.now(timezone.utc)
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.is_mock = True
            url, expires_at = exporter._generate_download_url(report)
        after = datetime.now(timezone.utc)

        parsed = datetime.fromisoformat(expires_at)
        # 至少 23 小时后，至多 25 小时后（容忍执行延迟）
        delta = parsed - before
        assert timedelta_hours(23) <= delta <= timedelta_hours(25)


def timedelta_hours(hours):
    from datetime import timedelta

    return timedelta(hours=hours)


# ========== 集成：完整 export 路径 ==========

class TestCdiscExporterExportIntegration:
    """export() 端到端集成：覆盖四域协同"""

    @pytest.mark.asyncio
    async def test_export_with_full_content(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        report = _make_report(
            content_json={
                "cancer_type": "Breast",
                "targets": [
                    {"gene_symbol": "HIGH", "confidence_score": 0.9},
                    {"gene_symbol": "LOW1", "confidence_score": 0.1},
                    {"gene_symbol": "LOW2", "confidence_score": 0.4},
                ],
                "datasets": [
                    {"data_type": "rna_seq", "name": "DS1", "file_format": "CSV"},
                ],
            },
            analysis_tier="deep",
            llm_cost_usd=Decimal("0.5"),  # 未超阈值
            created_at=ts,
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["status"] == "exported"
        assert result["domains"] == ["TS", "DM", "AE", "LB"]
        assert result["record_counts"]["TS"] == 5
        assert result["record_counts"]["DM"] == 1
        assert result["record_counts"]["AE"] == 2  # LOW1 + LOW2
        assert result["record_counts"]["LB"] == 1  # DS1
        # study_id 应为 PDD-RPT-<前8位大写>
        assert result["study_id"] == f"PDD-RPT-{str(report.id)[:8].upper()}"
        # download_url mock 模式
        assert result["download_url"].startswith("mock://")

    @pytest.mark.asyncio
    async def test_export_with_empty_content_json(self):
        """空 content_json 不应导致异常，应使用合理默认值"""
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json={})
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["status"] == "exported"
        assert result["record_counts"]["TS"] == 5
        assert result["record_counts"]["DM"] == 1
        assert result["record_counts"]["AE"] == 0
        assert result["record_counts"]["LB"] == 1  # 默认 LB 记录
        # study_id 应非空
        assert result["study_id"] != ""

    @pytest.mark.asyncio
    async def test_export_with_none_content_json(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(content_json=None)
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        result = await exporter.export(report.id)

        assert result["status"] == "exported"
        assert result["record_counts"]["AE"] == 0
        assert result["record_counts"]["LB"] == 1

    @pytest.mark.asyncio
    async def test_export_with_budget_overflow_and_low_confidence(self):
        from app.services.report.cdisc_exporter import CdiscExporter

        report = _make_report(
            content_json={
                "targets": [
                    {"gene_symbol": "LOW1", "confidence_score": 0.1},
                ],
            },
            llm_cost_usd=Decimal("100.0"),
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=report)
        exporter = CdiscExporter(mock_db)

        # 直接用 patch 覆盖模块级 settings
        with patch("app.services.report.cdisc_exporter.settings") as mock_settings:
            mock_settings.is_mock = True
            mock_settings.FAST_SCREEN_MAX_COST_USD = 5.0
            result = await exporter.export(report.id)

        assert result["status"] == "exported"
        assert result["record_counts"]["AE"] == 2  # 1 个低置信 + 1 个 BUDGET_OVERFLOW
