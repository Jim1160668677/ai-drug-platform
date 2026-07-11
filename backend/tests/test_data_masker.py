"""数据脱敏器 (DataMasker) 单元测试 — HIPAA Safe Harbor 18 项标识符

覆盖 app/services/privacy/data_masker.py 的所有公开方法与各 _mask_* 私有处理器，
包含成功路径、错误路径与边界条件。
"""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.services.privacy.data_masker import (
    DataMasker,
    IDENTIFIER_TYPES,
)


# ============================================================
# 构造函数
# ============================================================
class TestDataMaskerInit:
    def test_default_salt_when_none_passed(self):
        """未传 salt 时使用 settings.MASK_SALT 或默认值"""
        m = DataMasker()
        # 默认盐值应为 "pdd_salt_v1" 或 settings 中配置
        assert m._salt in ("pdd_salt_v1", getattr(__import__("app.core.config", fromlist=["settings"]).settings, "MASK_SALT", ""))

    def test_custom_salt(self):
        """传入自定义 salt"""
        m = DataMasker(salt="my_salt")
        assert m._salt == "my_salt"

    def test_empty_string_salt_falls_back_to_default(self):
        """空字符串 salt 应回退到默认"""
        m = DataMasker(salt="")
        assert m._salt == "pdd_salt_v1"

    def test_default_rules_populated(self):
        """_default_rules 应包含常见字段映射"""
        m = DataMasker()
        rules = m._rules
        assert rules["name"] == "name"
        assert rules["patient_name"] == "name"
        assert rules["phone"] == "telephone"
        assert rules["email"] == "email"
        assert rules["ssn"] == "ssn"
        assert rules["mrn"] == "mrn"
        assert rules["account"] == "account"
        assert rules["ip"] == "ip"
        assert rules["age"] == "age_over_89"
        assert rules["dob"] == "dates"

    def test_init_logs_in_mock_mode(self, caplog):
        """Mock 模式下应记录日志"""
        import logging
        with caplog.at_level(logging.INFO):
            DataMasker()
        # USE_MOCK 在 conftest 中被设为 true
        assert any("Mock" in r.message for r in caplog.records)


# ============================================================
# mask_records
# ============================================================
class TestMaskRecords:
    def test_empty_records_returns_empty_list(self):
        m = DataMasker()
        assert m.mask_records([]) == []

    def test_non_dict_record_passed_through(self):
        """非 dict 记录原样追加"""
        m = DataMasker()
        result = m.mask_records(["hello", 42, None])
        assert result == ["hello", 42, None]

    def test_dict_record_with_no_identifier_fields(self):
        """字段不在规则中应原样保留"""
        m = DataMasker()
        result = m.mask_records([{"gene": "EGFR", "fold_change": 2.5}])
        assert result[0]["gene"] == "EGFR"
        assert result[0]["fold_change"] == 2.5

    def test_dict_record_with_identifier_fields_masked(self):
        """识别符字段应被脱敏"""
        m = DataMasker()
        result = m.mask_records([{"name": "John Doe", "email": "john@example.com"}])
        assert result[0]["name"].startswith("h_")
        assert "@" in result[0]["email"]
        assert result[0]["email"].startswith("j***@example.com")

    def test_does_not_mutate_original(self):
        """脱敏不应修改原始记录"""
        m = DataMasker()
        original = [{"name": "Alice"}]
        m.mask_records(original)
        assert original[0]["name"] == "Alice"

    def test_custom_rules_override_defaults(self):
        """自定义规则应覆盖默认规则"""
        m = DataMasker()
        # 默认 name -> name (哈希)，覆盖为 photo
        result = m.mask_records(
            [{"name": "Bob"}],
            rules={"name": "photo"},
        )
        assert result[0]["name"] == "[REDACTED_PHOTO]"

    def test_custom_rules_add_new_field(self):
        """自定义规则可添加新字段映射"""
        m = DataMasker()
        result = m.mask_records(
            [{"custom_field": "123456789"}],
            rules={"custom_field": "ssn"},
        )
        # ssn 脱敏：取数字，保留后 4 位 -> ***-**-6789
        assert result[0]["custom_field"] == "***-**-6789"

    def test_field_with_invalid_rule_type_returns_none_inferred(self):
        """规则映射到非法类型时，_infer_field_type 返回 None，字段原样保留"""
        m = DataMasker()
        result = m.mask_records(
            [{"foo": "bar"}],
            rules={"foo": "not_a_real_type"},
        )
        assert result[0]["foo"] == "bar"

    def test_mask_failure_sets_mask_failed_placeholder(self):
        """mask_field 抛异常时应替换为 [MASK_FAILED]"""
        m = DataMasker()
        with patch.object(m, "mask_field", side_effect=RuntimeError("boom")):
            result = m.mask_records([{"name": "John"}])
        assert result[0]["name"] == "[MASK_FAILED]"

    def test_mixed_records(self):
        """混合 dict / 非 dict 记录"""
        m = DataMasker()
        result = m.mask_records([
            {"name": "Alice"},
            "not_a_dict",
            {"email": "bob@test.com"},
            None,
        ])
        assert len(result) == 4
        assert result[0]["name"].startswith("h_")
        assert result[1] == "not_a_dict"
        assert "@" in result[2]["email"]
        assert result[3] is None

    def test_logs_completion_count(self, caplog):
        """应记录脱敏完成条数"""
        import logging
        m = DataMasker()
        with caplog.at_level(logging.INFO):
            m.mask_records([{"name": "A"}, {"name": "B"}])
        assert any("2" in r.message and "记录" in r.message for r in caplog.records)


# ============================================================
# mask_field
# ============================================================
class TestMaskField:
    def test_none_value_returns_none(self):
        m = DataMasker()
        assert m.mask_field(None, "name") is None

    def test_unknown_field_type_raises_value_error(self):
        m = DataMasker()
        with pytest.raises(ValueError, match="未知标识符类型"):
            m.mask_field("foo", "not_a_type")

    def test_known_type_without_handler_uses_hash_default(self):
        """有 IDENTIFIER_TYPES 中类型但无 _mask_X 方法时，走 _hash 默认"""
        m = DataMasker()
        # 构造一个在 IDENTIFIER_TYPES 中但没有对应 _mask_X 方法的类型
        # 实际上所有 18 种都有处理器，所以这里通过 mock 验证默认路径
        with patch.object(m, "_hash", return_value="h_mocked") as mock_hash:
            # 临时移除 _mask_name 方法以触发默认路径
            original = DataMasker._mask_name
            del DataMasker._mask_name
            try:
                result = m.mask_field("John", "name")
                assert result == "h_mocked"
                mock_hash.assert_called_once_with("John")
            finally:
                DataMasker._mask_name = original

    def test_known_type_with_handler_calls_handler(self):
        m = DataMasker()
        result = m.mask_field("photo_data", "photo")
        assert result == "[REDACTED_PHOTO]"


# ============================================================
# assess_k_anonymity
# ============================================================
class TestAssessKAnonymity:
    def test_empty_records(self):
        m = DataMasker()
        result = m.assess_k_anonymity([], ["zip"])
        assert result == {"k": 0, "groups": 0, "violation_groups": 0, "distribution": {}}

    def test_single_record_violation(self):
        """单条记录：k=1, violation_groups=1"""
        m = DataMasker()
        result = m.assess_k_anonymity([{"zip": "12345"}], ["zip"])
        assert result["k"] == 1
        assert result["groups"] == 1
        assert result["violation_groups"] == 1
        assert result["distribution"] == {1: 1}

    def test_two_records_same_group_no_violation(self):
        m = DataMasker()
        records = [{"zip": "12345"}, {"zip": "12345"}]
        result = m.assess_k_anonymity(records, ["zip"])
        assert result["k"] == 2
        assert result["groups"] == 1
        assert result["violation_groups"] == 0
        # distribution: group_size -> 等价组数量；1 个组大小为 2
        assert result["distribution"] == {2: 1}

    def test_multiple_groups_with_violations(self):
        m = DataMasker()
        records = [
            {"zip": "10001", "age": 30},
            {"zip": "10001", "age": 30},
            {"zip": "10002", "age": 40},  # 单独一组 -> 违规
            {"zip": "10003", "age": 50},
            {"zip": "10003", "age": 50},
        ]
        result = m.assess_k_anonymity(records, ["zip", "age"])
        assert result["k"] == 1
        assert result["groups"] == 3
        assert result["violation_groups"] == 1
        assert result["distribution"] == {2: 2, 1: 1}

    def test_multiple_quasi_identifiers(self):
        m = DataMasker()
        records = [
            {"zip": "10001", "gender": "M"},
            {"zip": "10001", "gender": "F"},
            {"zip": "10001", "gender": "M"},
            {"zip": "10001", "gender": "F"},
        ]
        result = m.assess_k_anonymity(records, ["zip", "gender"])
        assert result["k"] == 2
        assert result["groups"] == 2
        assert result["violation_groups"] == 0

    def test_missing_quasi_identifier_field_uses_none(self):
        """记录缺失准标识符字段时，键中含 None"""
        m = DataMasker()
        records = [{"zip": "10001"}, {"zip": "10001"}]
        result = m.assess_k_anonymity(records, ["zip", "gender"])
        assert result["k"] == 2
        assert result["groups"] == 1

    def test_logs_summary(self, caplog):
        import logging
        m = DataMasker()
        with caplog.at_level(logging.INFO):
            m.assess_k_anonymity([{"zip": "10001"}], ["zip"])
        assert any("k-匿名评估" in r.message for r in caplog.records)


# ============================================================
# _infer_field_type
# ============================================================
class TestInferFieldType:
    def test_known_field(self):
        m = DataMasker()
        assert m._infer_field_type("name", m._rules) == "name"
        assert m._infer_field_type("email", m._rules) == "email"

    def test_case_insensitive(self):
        m = DataMasker()
        assert m._infer_field_type("NAME", m._rules) == "name"
        assert m._infer_field_type("Email", m._rules) == "email"

    def test_unknown_field_returns_none(self):
        m = DataMasker()
        assert m._infer_field_type("nonexistent", m._rules) is None

    def test_rule_with_invalid_type_returns_none(self):
        m = DataMasker()
        rules = {"foo": "invalid_type"}
        assert m._infer_field_type("foo", rules) is None


# ============================================================
# _hash
# ============================================================
class TestHash:
    def test_hash_format(self):
        m = DataMasker(salt="salt")
        h = m._hash("value")
        assert h.startswith("h_")
        assert len(h) == 2 + 16  # "h_" + 16 hex chars

    def test_hash_deterministic(self):
        m = DataMasker(salt="salt")
        assert m._hash("value") == m._hash("value")

    def test_hash_uses_salt(self):
        """不同盐值应产生不同哈希"""
        m1 = DataMasker(salt="salt1")
        m2 = DataMasker(salt="salt2")
        assert m1._hash("value") != m2._hash("value")

    def test_hash_different_inputs_different_output(self):
        m = DataMasker(salt="salt")
        assert m._hash("a") != m._hash("b")


# ============================================================
# _mask (通用掩码)
# ============================================================
class TestMaskGeneric:
    def test_normal_string(self):
        m = DataMasker()
        # 默认 keep_head=1, keep_tail=1
        # "abcdef" -> "a****f"
        assert m._mask("abcdef") == "a****f"

    def test_short_string_all_asterisks(self):
        """长度 <= keep_head + keep_tail 时全部掩码"""
        m = DataMasker()
        # 长度 2, keep_head=1, keep_tail=1 -> 2 <= 2 -> 全 *
        assert m._mask("ab") == "**"

    def test_empty_string(self):
        m = DataMasker()
        assert m._mask("") == ""

    def test_keep_tail_zero(self):
        m = DataMasker()
        # "abcdef", keep_head=3, keep_tail=0 -> "abc***"
        assert m._mask("abcdef", keep_head=3, keep_tail=0) == "abc***"

    def test_custom_keep_head_tail(self):
        m = DataMasker()
        # "1234567890", keep_head=2, keep_tail=4 -> "12****7890"
        assert m._mask("1234567890", keep_head=2, keep_tail=4) == "12****7890"

    def test_non_string_input_converted(self):
        m = DataMasker()
        # int 12345 -> "12345", keep_head=1, keep_tail=1 -> "1***5"
        assert m._mask(12345) == "1***5"


# ============================================================
# 各 _mask_* 处理器
# ============================================================
class TestMaskName:
    def test_hashes_value(self):
        m = DataMasker(salt="s")
        assert m._mask_name("John") == m._hash("John")

    def test_non_string_converted(self):
        m = DataMasker(salt="s")
        assert m._mask_name(123) == m._hash("123")


class TestMaskTelephone:
    def test_normal_phone(self):
        m = DataMasker()
        assert m._mask_telephone("1234567890") == "***-***-7890"

    def test_phone_with_formatting(self):
        m = DataMasker()
        assert m._mask_telephone("(123) 456-7890") == "***-***-7890"

    def test_short_phone_less_than_4_digits(self):
        m = DataMasker()
        assert m._mask_telephone("12") == "**"

    def test_empty_phone(self):
        m = DataMasker()
        assert m._mask_telephone("") == ""

    def test_phone_with_no_digits(self):
        m = DataMasker()
        assert m._mask_telephone("abc") == ""


class TestMaskFax:
    def test_delegates_to_telephone(self):
        m = DataMasker()
        assert m._mask_fax("1234567890") == "***-***-7890"


class TestMaskEmail:
    def test_normal_email(self):
        m = DataMasker()
        result = m._mask_email("john@example.com")
        assert result == "j***@example.com"

    def test_email_no_at_sign_hashes(self):
        m = DataMasker(salt="s")
        result = m._mask_email("notanemail")
        assert result == m._hash("notanemail")

    def test_email_empty_local_part(self):
        m = DataMasker()
        result = m._mask_email("@example.com")
        assert result == "@example.com"

    def test_email_single_char_local(self):
        m = DataMasker()
        result = m._mask_email("a@example.com")
        # local[0]='a', "*" * max(0, 1) = "*"
        assert result == "a*@example.com"

    def test_email_long_local(self):
        m = DataMasker()
        result = m._mask_email("johnny@example.com")
        # local="johnny", masked_local = "j" + "*" * 5 = "j*****"
        assert result == "j*****@example.com"


class TestMaskSSN:
    def test_normal_ssn(self):
        m = DataMasker()
        assert m._mask_ssn("123-45-6789") == "***-**-6789"

    def test_ssn_no_dashes(self):
        m = DataMasker()
        assert m._mask_ssn("123456789") == "***-**-6789"

    def test_short_ssn(self):
        m = DataMasker()
        assert m._mask_ssn("123") == "***"

    def test_empty_ssn(self):
        m = DataMasker()
        assert m._mask_ssn("") == ""


class TestMaskMRN:
    def test_hashes_value(self):
        m = DataMasker(salt="s")
        assert m._mask_mrn("MRN123") == m._hash("MRN123")


class TestMaskAccount:
    def test_normal_account(self):
        m = DataMasker()
        # "1234567890", keep_head=2, keep_tail=4 -> "12****7890"
        assert m._mask_account("1234567890") == "12****7890"

    def test_short_account(self):
        m = DataMasker()
        # 长度 3, keep_head=2, keep_tail=4 -> 3 <= 6 -> "***"
        assert m._mask_account("123") == "***"


class TestMaskCertificate:
    def test_normal_certificate(self):
        m = DataMasker()
        # "ABC1234567" len=10, keep_head=2, keep_tail=2 -> middle = 10-2-2 = 6 个 *
        # -> "AB******67"
        assert m._mask_certificate("ABC1234567") == "AB******67"

    def test_short_certificate(self):
        m = DataMasker()
        # 长度 3, keep_head=2, keep_tail=2 -> 3 <= 4 -> "***"
        assert m._mask_certificate("ABC") == "***"


class TestMaskVehicle:
    def test_normal_plate(self):
        m = DataMasker()
        # "ABC1234", keep_head=1, keep_tail=2 -> "A****34"
        assert m._mask_vehicle("ABC1234") == "A****34"

    def test_short_plate(self):
        m = DataMasker()
        # 长度 2, keep_head=1, keep_tail=2 -> 2 <= 3 -> "**"
        assert m._mask_vehicle("AB") == "**"


class TestMaskDevice:
    def test_hashes_value(self):
        m = DataMasker(salt="s")
        assert m._mask_device("dev-001") == m._hash("dev-001")


class TestMaskURL:
    def test_url_with_scheme(self):
        m = DataMasker()
        result = m._mask_url("https://www.example.com/path/to/page")
        # scheme="https", host="www.example.com", path="path/to/page"
        # masked_host = _mask("www.example.com", keep_head=3, keep_tail=0)
        #   len=15 > 3, head="www", middle="*"*12 -> "www************"
        assert result.startswith("https://www")
        assert "*" in result
        assert result.endswith("/path/to/page")

    def test_url_with_short_host(self):
        m = DataMasker()
        result = m._mask_url("http://ab/page")
        # host="ab", len=2 <= 3+0 -> "**"
        assert result == "http://**/page"

    def test_url_without_scheme(self):
        m = DataMasker()
        result = m._mask_url("www.example.com")
        # 走 _mask(s, keep_head=4, keep_tail=0)
        # "www.example.com" len=15, head="www.", middle="*" * 11
        assert result.startswith("www.")
        assert "*" in result

    def test_url_without_scheme_short(self):
        m = DataMasker()
        result = m._mask_url("abc")
        # len=3 <= 4 -> "***"
        assert result == "***"


class TestMaskIP:
    def test_ipv4_normal(self):
        m = DataMasker()
        assert m._mask_ip("192.168.1.100") == "192.168.*.*"

    def test_ipv4_with_short_segments(self):
        m = DataMasker()
        assert m._mask_ip("10.0.0.1") == "10.0.*.*"

    def test_non_ipv4_hashes(self):
        m = DataMasker(salt="s")
        result = m._mask_ip("not.an.ip.address")
        # 4 段也会匹配 ipv4 路径！ "not","an","ip","address" -> "not.an.*.*"
        # 实际上 "not.an.ip.address" split(".") 得到 4 段，所以走 ipv4 路径
        assert result == "not.an.*.*"

    def test_truly_non_ipv4_hashes(self):
        m = DataMasker(salt="s")
        result = m._mask_ip("fe80::1")
        # split(".") -> ["fe80::1"]，长度 1，不等于 4，走 _hash
        assert result == m._hash("fe80::1")

    def test_ipv6_hashes(self):
        m = DataMasker(salt="s")
        result = m._mask_ip("2001:db8::1")
        assert result == m._hash("2001:db8::1")


class TestMaskBiometric:
    def test_hashes_value(self):
        m = DataMasker(salt="s")
        assert m._mask_biometric("fp_12345") == m._hash("fp_12345")


class TestMaskPhoto:
    def test_returns_redacted_placeholder(self):
        m = DataMasker()
        assert m._mask_photo("any_binary_data") == "[REDACTED_PHOTO]"

    def test_returns_redacted_for_none_input(self):
        # 注意：mask_field 在 value is None 时直接返回 None，
        # 但直接调用 _mask_photo(None) 会执行 str(None)="None"
        m = DataMasker()
        assert m._mask_photo(None) == "[REDACTED_PHOTO]"


class TestMaskProfession:
    def test_doctor_mapped(self):
        m = DataMasker()
        assert m._mask_profession("doctor") == "healthcare_worker"

    def test_nurse_mapped(self):
        m = DataMasker()
        assert m._mask_profession("nurse") == "healthcare_worker"

    def test_physician_mapped(self):
        m = DataMasker()
        assert m._mask_profession("physician") == "healthcare_worker"

    def test_teacher_mapped(self):
        m = DataMasker()
        assert m._mask_profession("teacher") == "education"

    def test_engineer_mapped(self):
        m = DataMasker()
        assert m._mask_profession("engineer") == "technical"

    def test_lawyer_mapped(self):
        m = DataMasker()
        assert m._mask_profession("lawyer") == "legal"

    def test_farmer_mapped(self):
        m = DataMasker()
        assert m._mask_profession("farmer") == "agriculture"

    def test_unknown_profession_returns_other(self):
        m = DataMasker()
        assert m._mask_profession("astronaut") == "other"

    def test_case_insensitive_and_trimmed(self):
        m = DataMasker()
        assert m._mask_profession("  Doctor  ") == "healthcare_worker"
        assert m._mask_profession("DOCTOR") == "healthcare_worker"

    def test_non_string_input(self):
        m = DataMasker()
        # str(123)="123" -> lower="123" -> 不在 map -> "other"
        assert m._mask_profession(123) == "other"


class TestMaskGeographic:
    def test_single_word(self):
        m = DataMasker()
        result = m._mask_geographic("Boston")
        assert result == "Bo***"

    def test_multi_word_takes_last(self):
        m = DataMasker()
        result = m._mask_geographic("Boston MA")
        assert result == "MA"

    def test_multi_word_longer(self):
        m = DataMasker()
        result = m._mask_geographic("New York City NY")
        assert result == "NY"

    def test_empty_string(self):
        m = DataMasker()
        # "" 不含空格，走 s[:2] + "***" -> "" + "***" = "***"
        assert m._mask_geographic("") == "***"

    def test_non_string_input(self):
        m = DataMasker()
        # str(12345)="12345" -> 不含空格 -> "12***"
        assert m._mask_geographic(12345) == "12***"


class TestMaskDates:
    def test_iso_date_extracts_year(self):
        m = DataMasker()
        assert m._mask_dates("2023-05-15") == "2023"

    def test_date_with_text(self):
        m = DataMasker()
        assert m._mask_dates("Admitted on 1999-12-31") == "1999"

    def test_year_1900s(self):
        m = DataMasker()
        assert m._mask_dates("1985-06-15") == "1985"

    def test_no_year_hashes(self):
        m = DataMasker(salt="s")
        result = m._mask_dates("no year here")
        assert result == m._hash("no year here")

    def test_empty_string_hashes(self):
        m = DataMasker(salt="s")
        assert m._mask_dates("") == m._hash("")

    def test_year_outside_pattern_hashes(self):
        r"""1800 年或 2100 年不匹配 (19|20)\d{2}"""
        m = DataMasker(salt="s")
        result = m._mask_dates("1800-01-01")
        assert result == m._hash("1800-01-01")


class TestMaskAgeOver89:
    def test_age_above_89(self):
        m = DataMasker()
        assert m._mask_age_over_89(95) == "90+"

    def test_age_exactly_89(self):
        m = DataMasker()
        assert m._mask_age_over_89(89) == "89"

    def test_age_below_89(self):
        m = DataMasker()
        assert m._mask_age_over_89(45) == "45"

    def test_age_string_numeric(self):
        m = DataMasker()
        assert m._mask_age_over_89("75") == "75"

    def test_age_string_above_89(self):
        m = DataMasker()
        assert m._mask_age_over_89("100") == "90+"

    def test_age_invalid_string(self):
        m = DataMasker()
        assert m._mask_age_over_89("not_a_number") == "[AGE_MASKED]"

    def test_age_none(self):
        m = DataMasker()
        assert m._mask_age_over_89(None) == "[AGE_MASKED]"

    def test_age_zero(self):
        m = DataMasker()
        assert m._mask_age_over_89(0) == "0"

    def test_age_negative(self):
        m = DataMasker()
        assert m._mask_age_over_89(-5) == "-5"


# ============================================================
# 端到端集成场景
# ============================================================
class TestEndToEndScenarios:
    def test_full_record_all_field_types(self):
        """验证包含多种标识符的完整记录脱敏"""
        m = DataMasker(salt="test_salt")
        record = {
            "name": "John Doe",
            "phone": "123-456-7890",
            "email": "john@example.com",
            "ssn": "123-45-6789",
            "mrn": "MRN001",
            "ip": "192.168.1.1",
            "url": "https://example.com/path",
            "photo": "binary",
            "age": 92,
            "address": "Boston MA",
            "dob": "1990-05-15",
        }
        result = m.mask_records([record])
        r = result[0]
        assert r["name"].startswith("h_")
        assert r["phone"] == "***-***-7890"
        assert r["email"] == "j***@example.com"
        assert r["ssn"] == "***-**-6789"
        assert r["mrn"].startswith("h_")
        assert r["ip"] == "192.168.*.*"
        assert r["url"].startswith("https://")
        assert r["photo"] == "[REDACTED_PHOTO]"
        assert r["age"] == "90+"
        assert r["address"] == "MA"
        assert r["dob"] == "1990"

    def test_field_name_case_variations(self):
        """字段名大小写不影响推断"""
        m = DataMasker()
        result = m.mask_records([{"NAME": "Alice", "Email": "a@b.com"}])
        assert result[0]["NAME"].startswith("h_")
        assert "@" in result[0]["Email"]


# ============================================================
# IDENTIFIER_TYPES 常量
# ============================================================
class TestIdentifierTypes:
    def test_contains_all_18_types(self):
        assert len(IDENTIFIER_TYPES) == 18

    def test_includes_key_types(self):
        for t in ("name", "geographic", "dates", "telephone", "fax",
                  "email", "ssn", "mrn", "account", "certificate",
                  "vehicle", "device", "url", "ip", "biometric",
                  "photo", "profession", "age_over_89"):
            assert t in IDENTIFIER_TYPES
