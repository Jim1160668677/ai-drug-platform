"""SDTM 校验器单元测试

覆盖 8 条 FDA 核心校验规则（CG0001-CG0008）：
- 正例触发（数据有问题 → 检出错误/警告）
- 反例通过（合规数据 → passed=True）
- 边界条件（空数据、单域、多域）
"""
import pytest

from app.services.cdisc.sdtm_validator import SDTMValidator


# ============================================================
# 测试数据工厂
# ============================================================
def make_sdtm(
    domains: dict = None,
    study_id: str = "PDD-TEST0001",
) -> dict:
    """构造 SDTM 数据结构"""
    if domains is None:
        domains = {
            "DM": [{
                "STUDYID": study_id,
                "DOMAIN": "DM",
                "USUBJID": "SUBJ-001",
                "RFICDTC": "2026-01-01",
                "ARM": "NSCLC",
                "AGE": "",
                "SEX": "",
            }],
            "VS": [{
                "STUDYID": study_id,
                "DOMAIN": "VS",
                "USUBJID": "SUBJ-001",
                "VSTEST": "rna_seq",
                "VSORRES": "csv",
                "VSTPT": "Dataset1",
                "VISITNUM": 1,
                "VISIT": "SCREENING",
            }],
        }
    return {
        "domains": domains,
        "metadata": {
            "study_id": study_id,
            "version": "SDTMIG 3.3",
            "export_time": "2026-01-01T00:00:00Z",
            "record_counts": {k: len(v) for k, v in domains.items()},
        },
    }


@pytest.fixture
def validator():
    return SDTMValidator()


# ============================================================
# CG0001: USUBJID 必须唯一
# ============================================================
class TestCG0001USUBJIDUnique:
    def test_duplicate_usubjid_detected(self, validator):
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "DUP-001"},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "DUP-001"},
            ],
        })
        result = validator.validate(data)
        assert not result["passed"]
        cg0001_errors = [e for e in result["errors"] if e["rule_id"] == "CG0001"]
        assert len(cg0001_errors) >= 1
        assert "DUP-001" in cg0001_errors[0]["message"]

    def test_unique_usubjid_passes(self, validator):
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "SUBJ-001"},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "SUBJ-002"},
            ],
        })
        result = validator.validate(data)
        cg0001_errors = [e for e in result["errors"] if e["rule_id"] == "CG0001"]
        assert len(cg0001_errors) == 0

    def test_empty_usubjid_skipped(self, validator):
        """空 USUBJID 不触发重复检查"""
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": ""},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": ""},
            ],
        })
        result = validator.validate(data)
        cg0001_errors = [e for e in result["errors"] if e["rule_id"] == "CG0001"]
        assert len(cg0001_errors) == 0


# ============================================================
# CG0002: DOMAIN 必填
# ============================================================
class TestCG0002DomainRequired:
    def test_missing_domain_detected(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "", "USUBJID": "S1"}],
        })
        result = validator.validate(data)
        cg0002_errors = [e for e in result["errors"] if e["rule_id"] == "CG0002"]
        assert len(cg0002_errors) >= 1

    def test_mismatched_domain_detected(self, validator):
        """DOMAIN 值与域名不匹配"""
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "VS", "USUBJID": "S1"}],
        })
        result = validator.validate(data)
        cg0002_errors = [e for e in result["errors"] if e["rule_id"] == "CG0002"]
        assert len(cg0002_errors) >= 1
        assert "VS" in cg0002_errors[0]["message"]

    def test_correct_domain_passes(self, validator):
        data = make_sdtm()
        result = validator.validate(data)
        cg0002_errors = [e for e in result["errors"] if e["rule_id"] == "CG0002"]
        assert len(cg0002_errors) == 0


# ============================================================
# CG0003: STUDYID 跨域一致
# ============================================================
class TestCG0003StudyIDConsistent:
    def test_inconsistent_studyid_detected(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1"}],
            "VS": [{"STUDYID": "S2", "DOMAIN": "VS", "USUBJID": "S1", "VSTEST": "test"}],
        }, study_id="S1")
        result = validator.validate(data)
        cg0003_errors = [e for e in result["errors"] if e["rule_id"] == "CG0003"]
        assert len(cg0003_errors) >= 1

    def test_missing_studyid_detected(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "", "DOMAIN": "DM", "USUBJID": "S1"}],
        }, study_id="S1")
        result = validator.validate(data)
        cg0003_errors = [e for e in result["errors"] if e["rule_id"] == "CG0003"]
        assert len(cg0003_errors) >= 1

    def test_consistent_studyid_passes(self, validator):
        data = make_sdtm()
        result = validator.validate(data)
        cg0003_errors = [e for e in result["errors"] if e["rule_id"] == "CG0003"]
        assert len(cg0003_errors) == 0


# ============================================================
# CG0004: USUBJID 跨域引用完整
# ============================================================
class TestCG0004USUBJIDCrossRef:
    def test_orphan_usubjid_detected(self, validator):
        """VS 域的 USUBJID 不在 DM 中"""
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "SUBJ-001"}],
            "VS": [{"STUDYID": "S1", "DOMAIN": "VS", "USUBJID": "SUBJ-999", "VSTEST": "test"}],
        })
        result = validator.validate(data)
        cg0004_errors = [e for e in result["errors"] if e["rule_id"] == "CG0004"]
        assert len(cg0004_errors) >= 1
        assert "SUBJ-999" in cg0004_errors[0]["message"]

    def test_valid_cross_ref_passes(self, validator):
        data = make_sdtm()
        result = validator.validate(data)
        cg0004_errors = [e for e in result["errors"] if e["rule_id"] == "CG0004"]
        assert len(cg0004_errors) == 0

    def test_no_dm_domain_skips_check(self, validator):
        """无 DM 域时跳过跨域引用检查"""
        data = make_sdtm({
            "VS": [{"STUDYID": "S1", "DOMAIN": "VS", "USUBJID": "SUBJ-001", "VSTEST": "test"}],
        })
        result = validator.validate(data)
        cg0004_errors = [e for e in result["errors"] if e["rule_id"] == "CG0004"]
        assert len(cg0004_errors) == 0


# ============================================================
# CG0005: --SEQ 必须连续
# ============================================================
class TestCG0005SeqContinuous:
    def test_non_sequential_seq_warned(self, validator):
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "DMSEQ": 1},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S2", "DMSEQ": 5},
            ],
        })
        result = validator.validate(data)
        cg0005_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0005"]
        assert len(cg0005_warnings) >= 1

    def test_sequential_seq_passes(self, validator):
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "DMSEQ": 1},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S2", "DMSEQ": 2},
            ],
        })
        result = validator.validate(data)
        cg0005_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0005"]
        assert len(cg0005_warnings) == 0

    def test_invalid_seq_type_warned(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "DMSEQ": "abc"}],
        })
        result = validator.validate(data)
        cg0005_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0005"]
        assert len(cg0005_warnings) >= 1


# ============================================================
# CG0006: 必填变量非空
# ============================================================
class TestCG0006RequiredVarsNonEmpty:
    def test_empty_required_var_warned(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": ""}],
        })
        result = validator.validate(data)
        cg0006_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0006"]
        assert len(cg0006_warnings) >= 1
        assert any("USUBJID" in w["message"] for w in cg0006_warnings)

    def test_all_required_vars_filled_passes(self, validator):
        data = make_sdtm()
        result = validator.validate(data)
        cg0006_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0006"]
        assert len(cg0006_warnings) == 0

    def test_vs_domain_vstest_required(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1"}],
            "VS": [{"STUDYID": "S1", "DOMAIN": "VS", "USUBJID": "S1", "VSTEST": ""}],
        })
        result = validator.validate(data)
        cg0006_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0006"]
        assert any("VSTEST" in w["message"] for w in cg0006_warnings)


# ============================================================
# CG0007: 变量名 ≤ 8 字符
# ============================================================
class TestCG0007VarNameLength:
    def test_long_var_name_detected(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "VERYLONGVARNAME": "x"}],
        })
        result = validator.validate(data)
        cg0007_errors = [e for e in result["errors"] if e["rule_id"] == "CG0007"]
        assert len(cg0007_errors) >= 1
        assert "VERYLONGVARNAME" in cg0007_errors[0]["message"]

    def test_short_var_names_pass(self, validator):
        data = make_sdtm()
        result = validator.validate(data)
        cg0007_errors = [e for e in result["errors"] if e["rule_id"] == "CG0007"]
        assert len(cg0007_errors) == 0

    def test_exactly_8_chars_passes(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "EIGHTCHR": "x"}],
        })
        result = validator.validate(data)
        cg0007_errors = [e for e in result["errors"] if e["rule_id"] == "CG0007"]
        assert len(cg0007_errors) == 0


# ============================================================
# CG0008: 日期格式 ISO 8601
# ============================================================
class TestCG0008DateFormat:
    def test_invalid_date_format_warned(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "RFICDTC": "01/15/2026"}],
        })
        result = validator.validate(data)
        cg0008_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0008"]
        assert len(cg0008_warnings) >= 1

    def test_valid_iso8601_passes(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "RFICDTC": "2026-01-15"}],
        })
        result = validator.validate(data)
        cg0008_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0008"]
        assert len(cg0008_warnings) == 0

    def test_partial_date_passes(self, validator):
        """ISO 8601 支持部分日期（仅年份）"""
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "RFICDTC": "2026"}],
        })
        result = validator.validate(data)
        cg0008_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0008"]
        assert len(cg0008_warnings) == 0

    def test_empty_date_skipped(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "S1", "RFICDTC": ""}],
        })
        result = validator.validate(data)
        cg0008_warnings = [w for w in result["warnings"] if w["rule_id"] == "CG0008"]
        assert len(cg0008_warnings) == 0


# ============================================================
# 边界条件
# ============================================================
class TestEdgeCases:
    def test_empty_domains(self, validator):
        result = validator.validate({"domains": {}, "metadata": {"study_id": "S1"}})
        assert result["passed"] is True
        assert len(result["errors"]) == 0

    def test_empty_records_list(self, validator):
        data = make_sdtm({"DM": [], "VS": []})
        result = validator.validate(data)
        assert result["passed"] is True

    def test_single_domain(self, validator):
        data = make_sdtm({
            "DM": [{"STUDYID": "PDD-TEST0001", "DOMAIN": "DM", "USUBJID": "S1"}],
        })
        result = validator.validate(data)
        assert result["passed"] is True

    def test_rules_checked_count(self, validator):
        result = validator.validate(make_sdtm())
        assert result["rules_checked"] == 8

    def test_summary_string_generated(self, validator):
        result = validator.validate(make_sdtm())
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_total_issues_counted(self, validator):
        data = make_sdtm({
            "DM": [
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "DUP"},
                {"STUDYID": "S1", "DOMAIN": "DM", "USUBJID": "DUP"},
            ],
        })
        result = validator.validate(data)
        assert result["total_issues"] == len(result["errors"]) + len(result["warnings"])
