"""证据等级分类工具 (evidence) 单元测试 — 循证医学 I/II/III/IV 分级

覆盖 app/utils/evidence.py 的所有公开函数与内部辅助函数，
包含优先级路径、关键词匹配、边界条件与错误路径。
"""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.utils.evidence import (
    classify_evidence_level,
    evidence_distribution,
    _LEVEL_KEYWORDS,
    _SOURCE_DEFAULT,
    _extract_explicit_level,
    _build_search_text,
    _match_keywords,
)


# ============================================================
# classify_evidence_level — 优先级 1: payload 显式声明 evidence_level
# ============================================================
class TestClassifyExplicitEvidenceLevel:
    def test_explicit_level_I(self):
        assert classify_evidence_level("literature", {"evidence_level": "I"}) == "I"

    def test_explicit_level_II(self):
        assert classify_evidence_level("literature", {"evidence_level": "II"}) == "II"

    def test_explicit_level_III(self):
        assert classify_evidence_level("literature", {"evidence_level": "III"}) == "III"

    def test_explicit_level_IV(self):
        assert classify_evidence_level("literature", {"evidence_level": "IV"}) == "IV"

    def test_explicit_level_with_whitespace_stripped(self):
        assert classify_evidence_level("literature", {"evidence_level": "  II  "}) == "II"

    def test_explicit_level_invalid_string_falls_through(self):
        """evidence_level 不在 I/II/III/IV 中时应回退到后续逻辑"""
        # source="meta_analysis" 在 _SOURCE_DEFAULT 中，所以会返回 I
        assert classify_evidence_level("meta_analysis", {"evidence_level": "V"}) == "I"

    def test_explicit_level_invalid_string_no_source_default(self):
        """evidence_level 无效且 source 不在默认映射中，应回退到关键词匹配或默认 IV"""
        result = classify_evidence_level("unknown_source", {"evidence_level": "V"})
        assert result == "IV"

    def test_explicit_level_non_string_ignored(self):
        """非字符串 evidence_level 应被忽略"""
        # source=cohort -> II
        assert classify_evidence_level("cohort", {"evidence_level": 1}) == "II"

    def test_explicit_level_none_ignored(self):
        """None evidence_level 应被忽略"""
        assert classify_evidence_level("cohort", {"evidence_level": None}) == "II"

    def test_explicit_level_takes_priority_over_source(self):
        """显式声明优先于 source 默认"""
        # source=meta_analysis 默认为 I，但显式声明 III 应覆盖
        assert classify_evidence_level("meta_analysis", {"evidence_level": "III"}) == "III"


# ============================================================
# classify_evidence_level — 优先级 2: study_type
# ============================================================
class TestClassifyStudyType:
    def test_study_type_direct_roman_lowercase(self):
        assert classify_evidence_level("literature", {"study_type": "i"}) == "I"
        assert classify_evidence_level("literature", {"study_type": "ii"}) == "II"
        assert classify_evidence_level("literature", {"study_type": "iii"}) == "III"
        assert classify_evidence_level("literature", {"study_type": "iv"}) == "IV"

    def test_study_type_direct_roman_uppercase(self):
        assert classify_evidence_level("literature", {"study_type": "I"}) == "I"
        assert classify_evidence_level("literature", {"study_type": "IV"}) == "IV"

    def test_study_type_direct_roman_with_whitespace(self):
        assert classify_evidence_level("literature", {"study_type": "  ii  "}) == "II"

    def test_study_type_keyword_rct(self):
        assert classify_evidence_level("literature", {"study_type": "rct"}) == "I"

    def test_study_type_keyword_randomized_controlled_trial(self):
        assert classify_evidence_level(
            "literature", {"study_type": "randomized controlled trial"}
        ) == "I"

    def test_study_type_keyword_meta_analysis(self):
        assert classify_evidence_level("literature", {"study_type": "meta-analysis"}) == "I"

    def test_study_type_keyword_systematic_review(self):
        assert classify_evidence_level("literature", {"study_type": "systematic review"}) == "I"

    def test_study_type_keyword_cohort(self):
        assert classify_evidence_level("literature", {"study_type": "cohort"}) == "II"

    def test_study_type_keyword_case_control(self):
        assert classify_evidence_level("literature", {"study_type": "case-control"}) == "II"

    def test_study_type_keyword_case_report(self):
        assert classify_evidence_level("literature", {"study_type": "case report"}) == "III"

    def test_study_type_keyword_in_vitro(self):
        assert classify_evidence_level("literature", {"study_type": "in vitro"}) == "III"

    def test_study_type_keyword_expert_opinion(self):
        assert classify_evidence_level("literature", {"study_type": "expert opinion"}) == "IV"

    def test_study_type_keyword_animal_study(self):
        assert classify_evidence_level("literature", {"study_type": "animal study"}) == "IV"

    def test_study_type_keyword_review_returns_IV(self):
        """'review' 单独匹配 IV"""
        assert classify_evidence_level("literature", {"study_type": "review"}) == "IV"

    def test_study_type_non_string_ignored(self):
        """非字符串 study_type 应被忽略"""
        assert classify_evidence_level("cohort", {"study_type": 123}) == "II"

    def test_study_type_none_ignored(self):
        assert classify_evidence_level("cohort", {"study_type": None}) == "II"

    def test_study_type_keyword_in_phrase(self):
        """study_type 含关键词子串也应匹配"""
        # "prospective cohort study" 含 "cohort"
        assert classify_evidence_level(
            "literature", {"study_type": "prospective cohort study"}
        ) == "II"

    def test_study_type_takes_priority_over_source(self):
        """study_type 优先于 source 默认（因 explicit_level 优先级最高）"""
        # source=meta_analysis 默认 I，但 study_type=cohort 应覆盖为 II
        assert classify_evidence_level("meta_analysis", {"study_type": "cohort"}) == "II"


# ============================================================
# classify_evidence_level — 优先级 3: source 在 _SOURCE_DEFAULT 中
# ============================================================
class TestClassifySourceDefault:
    def test_source_clinical_trial_phase_iii(self):
        assert classify_evidence_level("clinical_trial_phase_iii") == "I"

    def test_source_clinical_trial_phase_iv(self):
        assert classify_evidence_level("clinical_trial_phase_iv") == "I"

    def test_source_meta_analysis(self):
        assert classify_evidence_level("meta_analysis") == "I"

    def test_source_systematic_review(self):
        assert classify_evidence_level("systematic_review") == "I"

    def test_source_clinical_trial_phase_ii(self):
        assert classify_evidence_level("clinical_trial_phase_ii") == "II"

    def test_source_cohort(self):
        assert classify_evidence_level("cohort") == "II"

    def test_source_case_control(self):
        assert classify_evidence_level("case_control") == "II"

    def test_source_case_report(self):
        assert classify_evidence_level("case_report") == "III"

    def test_source_case_series(self):
        assert classify_evidence_level("case_series") == "III"

    def test_source_in_vitro(self):
        assert classify_evidence_level("in_vitro") == "III"

    def test_source_expert_opinion(self):
        assert classify_evidence_level("expert_opinion") == "IV"

    def test_source_animal_study(self):
        assert classify_evidence_level("animal_study") == "IV"

    def test_source_narrative_review(self):
        assert classify_evidence_level("narrative_review") == "IV"

    def test_source_case_insensitive(self):
        """source 大小写不敏感"""
        assert classify_evidence_level("META_ANALYSIS") == "I"
        assert classify_evidence_level("Cohort") == "II"

    def test_source_with_whitespace_stripped(self):
        """source 前后空格被去除"""
        assert classify_evidence_level("  meta_analysis  ") == "I"


# ============================================================
# classify_evidence_level — 优先级 4: payload 文本关键词匹配
# ============================================================
class TestClassifyKeywordMatching:
    def test_title_with_rct_keyword(self):
        assert classify_evidence_level(
            "literature", {"title": "A RCT of new drug"}
        ) == "I"

    def test_abstract_with_meta_analysis(self):
        assert classify_evidence_level(
            "literature", {"abstract": "This meta-analysis shows..."}
        ) == "I"

    def test_summary_with_cohort(self):
        assert classify_evidence_level(
            "literature", {"summary": "A cohort study of patients"}
        ) == "II"

    def test_description_with_case_report(self):
        assert classify_evidence_level(
            "literature", {"description": "We present a case report of..."}
        ) == "III"

    def test_text_field_with_keyword(self):
        assert classify_evidence_level(
            "literature", {"text": "in vitro experiment"}
        ) == "III"

    def test_type_field_with_keyword(self):
        assert classify_evidence_level(
            "literature", {"type": "expert opinion"}
        ) == "IV"

    def test_keyword_priority_I_over_IV(self):
        """'systematic review' 应匹配 I 而非 IV 的 'review'"""
        result = classify_evidence_level(
            "literature", {"title": "A systematic review of treatments"}
        )
        assert result == "I"

    def test_keyword_priority_II_over_IV(self):
        """含 'cohort' 和 'review' 时应匹配 II"""
        result = classify_evidence_level(
            "literature", {"title": "cohort review of patients"}
        )
        assert result == "II"

    def test_keyword_only_review_returns_IV(self):
        """仅含 'review' 时匹配 IV"""
        result = classify_evidence_level(
            "literature", {"title": "a narrative review"}
        )
        # 注意: "narrative review" 在 IV 关键词中，但 "review" 也在 IV
        # 实际匹配时按 IV 关键词顺序，先匹配 "expert opinion" 等，最后 "review"
        # 但 "narrative review" 也是 IV 关键词
        assert result == "IV"

    def test_keyword_match_is_case_insensitive(self):
        """关键词匹配大小写不敏感"""
        assert classify_evidence_level(
            "literature", {"title": "A RCT OF NEW DRUG"}
        ) == "I"

    def test_falsy_payload_values_skipped(self):
        """falsy 值（空字符串/0/False）应被跳过"""
        result = classify_evidence_level(
            "literature",
            {"title": "", "abstract": None, "summary": 0, "description": False},
        )
        # 没有关键词匹配，source 不在默认，返回 IV
        assert result == "IV"

    def test_payload_none_uses_default_IV(self):
        """payload 为 None 时应正常处理"""
        assert classify_evidence_level("literature", None) == "IV"

    def test_source_keyword_in_text_match(self):
        """source 本身也会被加入搜索文本"""
        # source="rct" 在搜索文本中应匹配 I
        result = classify_evidence_level("rct", {})
        assert result == "I"


# ============================================================
# classify_evidence_level — 优先级 5: 默认 IV
# ============================================================
class TestClassifyDefault:
    def test_no_match_returns_IV(self):
        """无任何匹配时返回 IV"""
        assert classify_evidence_level("unknown_source", {"title": "no keywords here"}) == "IV"

    def test_empty_source_empty_payload_returns_IV(self):
        assert classify_evidence_level("", {}) == "IV"

    def test_empty_source_no_payload_returns_IV(self):
        assert classify_evidence_level("") == "IV"

    def test_unknown_source_no_payload_returns_IV(self):
        assert classify_evidence_level("literature") == "IV"

    def test_source_with_only_noise_returns_IV(self):
        """source 含无意义字符应返回 IV"""
        assert classify_evidence_level("   ", {}) == "IV"


# ============================================================
# evidence_distribution
# ============================================================
class TestEvidenceDistribution:
    def test_empty_list(self):
        result = evidence_distribution([])
        assert result == {"I": 0, "II": 0, "III": 0, "IV": 0, "total": 0}

    def test_all_explicit_levels(self):
        items = [
            {"evidence_level": "I"},
            {"evidence_level": "II"},
            {"evidence_level": "III"},
            {"evidence_level": "IV"},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 1, "II": 1, "III": 1, "IV": 1, "total": 4}

    def test_multiple_same_level(self):
        items = [
            {"evidence_level": "I"},
            {"evidence_level": "I"},
            {"evidence_level": "I"},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 3, "II": 0, "III": 0, "IV": 0, "total": 3}

    def test_classification_via_source(self):
        """无 evidence_level 时通过 source 分类"""
        items = [
            {"source": "meta_analysis"},
            {"source": "cohort"},
            {"source": "case_report"},
            {"source": "expert_opinion"},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 1, "II": 1, "III": 1, "IV": 1, "total": 4}

    def test_classification_via_payload(self):
        """无 evidence_level 时通过 payload 分类"""
        items = [
            {"source": "literature", "payload": {"study_type": "rct"}},
            {"source": "literature", "payload": {"study_type": "cohort"}},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 1, "II": 1, "III": 0, "IV": 0, "total": 2}

    def test_explicit_level_overrides_classification(self):
        """evidence_level 优先于 source/payload"""
        items = [
            {"source": "meta_analysis", "evidence_level": "IV", "payload": {"study_type": "rct"}},
        ]
        result = evidence_distribution(items)
        assert result["IV"] == 1
        assert result["I"] == 0
        assert result["total"] == 1

    def test_non_dict_items_skipped(self):
        """非 dict 项应被跳过"""
        items = [
            {"evidence_level": "I"},
            "not_a_dict",
            42,
            None,
            {"evidence_level": "II"},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 1, "II": 1, "III": 0, "IV": 0, "total": 2}

    def test_invalid_explicit_level_falls_back_to_classification(self):
        """evidence_level 无效时应回退到分类"""
        items = [
            # evidence_level="V" 无效，source=meta_analysis -> I
            {"source": "meta_analysis", "evidence_level": "V"},
        ]
        result = evidence_distribution(items)
        assert result["I"] == 1
        assert result["total"] == 1

    def test_payload_not_dict_uses_item_itself(self):
        """payload 不是 dict 时，应使用 item 本身作为 payload"""
        items = [
            {"source": "literature", "payload": "not_a_dict", "title": "A RCT study"},
        ]
        result = evidence_distribution(items)
        # title 含 "RCT" -> I
        assert result["I"] == 1
        assert result["total"] == 1

    def test_missing_source_uses_empty_string(self):
        """无 source 字段时使用空字符串"""
        items = [
            {"title": "A cohort study"},  # 无 source
        ]
        result = evidence_distribution(items)
        assert result["II"] == 1
        assert result["total"] == 1

    def test_mixed_items(self):
        """混合显式声明与自动分类"""
        items = [
            {"evidence_level": "I"},
            {"source": "cohort"},
            {"source": "literature", "payload": {"study_type": "case report"}},
            {"source": "unknown", "title": "no keywords"},
            "skip_me",
        ]
        result = evidence_distribution(items)
        assert result["I"] == 1
        assert result["II"] == 1
        assert result["III"] == 1
        assert result["IV"] == 1
        assert result["total"] == 4

    def test_logs_warning_for_unrecognized_level(self, caplog):
        """未识别的等级应记录警告（需通过 mock 触发）"""
        import logging
        items = [{"evidence_level": "I"}]
        with patch("app.utils.evidence.classify_evidence_level", return_value="V"):
            # evidence_level="I" 有效，不会触发分类
            # 改为无效等级触发分类路径
            items = [{"evidence_level": "X", "source": "unknown"}]
            with caplog.at_level(logging.WARNING):
                result = evidence_distribution(items)
        # classify 被 mock 返回 "V"，应触发警告
        assert any("未识别的证据等级" in r.message for r in caplog.records)
        assert result["total"] == 0

    def test_logs_info_summary(self, caplog):
        """应记录分布摘要"""
        import logging
        items = [{"evidence_level": "I"}]
        with caplog.at_level(logging.INFO):
            evidence_distribution(items)
        assert any("证据分布" in r.message for r in caplog.records)


# ============================================================
# _extract_explicit_level
# ============================================================
class TestExtractExplicitLevel:
    def test_valid_evidence_level_I(self):
        assert _extract_explicit_level({"evidence_level": "I"}) == "I"

    def test_valid_evidence_level_IV(self):
        assert _extract_explicit_level({"evidence_level": "IV"}) == "IV"

    def test_evidence_level_with_whitespace(self):
        assert _extract_explicit_level({"evidence_level": "  II  "}) == "II"

    def test_invalid_evidence_level_string(self):
        assert _extract_explicit_level({"evidence_level": "V"}) is None

    def test_invalid_evidence_level_lowercase_roman(self):
        """小写 'i' 不在 _LEVEL_KEYWORDS 的键中（键是大写）"""
        assert _extract_explicit_level({"evidence_level": "i"}) is None

    def test_evidence_level_non_string(self):
        assert _extract_explicit_level({"evidence_level": 1}) is None

    def test_evidence_level_none(self):
        assert _extract_explicit_level({"evidence_level": None}) is None

    def test_no_evidence_level_no_study_type(self):
        assert _extract_explicit_level({}) is None

    def test_study_type_direct_roman_lowercase(self):
        assert _extract_explicit_level({"study_type": "i"}) == "I"
        assert _extract_explicit_level({"study_type": "ii"}) == "II"
        assert _extract_explicit_level({"study_type": "iii"}) == "III"
        assert _extract_explicit_level({"study_type": "iv"}) == "IV"

    def test_study_type_direct_roman_uppercase(self):
        assert _extract_explicit_level({"study_type": "I"}) == "I"
        assert _extract_explicit_level({"study_type": "IV"}) == "IV"

    def test_study_type_direct_roman_with_whitespace(self):
        assert _extract_explicit_level({"study_type": "  ii  "}) == "II"

    def test_study_type_keyword(self):
        assert _extract_explicit_level({"study_type": "rct"}) == "I"
        assert _extract_explicit_level({"study_type": "cohort"}) == "II"
        assert _extract_explicit_level({"study_type": "case report"}) == "III"
        assert _extract_explicit_level({"study_type": "expert opinion"}) == "IV"

    def test_study_type_keyword_in_phrase(self):
        """study_type 含关键词子串"""
        assert _extract_explicit_level({"study_type": "a randomized trial"}) == "I"

    def test_study_type_non_string(self):
        assert _extract_explicit_level({"study_type": 123}) is None

    def test_study_type_none(self):
        assert _extract_explicit_level({"study_type": None}) is None

    def test_evidence_level_takes_priority_over_study_type(self):
        """evidence_level 优先于 study_type"""
        result = _extract_explicit_level({
            "evidence_level": "III",
            "study_type": "rct",  # 这本应返回 I
        })
        assert result == "III"

    def test_study_type_no_keyword_match(self):
        """study_type 不含任何关键词"""
        assert _extract_explicit_level({"study_type": "observational"}) is None


# ============================================================
# _build_search_text
# ============================================================
class TestBuildSearchText:
    def test_all_fields_present(self):
        payload = {
            "title": "Title",
            "abstract": "Abstract",
            "summary": "Summary",
            "description": "Description",
            "text": "Text",
            "type": "Type",
        }
        result = _build_search_text("Source", payload)
        assert "source" in result
        assert "title" in result
        assert "abstract" in result
        assert "summary" in result
        assert "description" in result
        assert "text" in result
        assert "type" in result
        # 应为小写
        assert result == result.lower()

    def test_some_fields_missing(self):
        payload = {"title": "Title"}
        result = _build_search_text("Source", payload)
        assert "source" in result
        assert "title" in result

    def test_empty_payload(self):
        result = _build_search_text("Source", {})
        assert result == "source"

    def test_empty_source(self):
        result = _build_search_text("", {"title": "Title"})
        assert result == " title"

    def test_none_source(self):
        """None source 应被转为空字符串"""
        result = _build_search_text(None, {"title": "Title"})
        assert result == " title"

    def test_falsy_values_skipped(self):
        """falsy 值应被跳过"""
        payload = {"title": "", "abstract": None, "summary": 0, "description": False, "text": "", "type": None}
        result = _build_search_text("Source", payload)
        # 只有 source
        assert result == "source"

    def test_non_string_values_converted(self):
        """非字符串值应被 str() 转换"""
        payload = {"title": 123}
        result = _build_search_text("Source", payload)
        assert "123" in result

    def test_result_is_lowercase(self):
        payload = {"title": "MixedCase TITLE"}
        result = _build_search_text("Source", payload)
        assert result == result.lower()
        assert "mixedcase" in result


# ============================================================
# _match_keywords
# ============================================================
class TestMatchKeywords:
    def test_empty_text_returns_none(self):
        assert _match_keywords("") is None

    def test_none_text_returns_none(self):
        # 函数检查 `if not text`，None 也是 falsy
        assert _match_keywords(None) is None

    def test_match_level_I_rct(self):
        assert _match_keywords("this is an rct study") == "I"

    def test_match_level_I_meta_analysis(self):
        assert _match_keywords("a meta-analysis of trials") == "I"

    def test_match_level_I_systematic_review(self):
        assert _match_keywords("systematic review of literature") == "I"

    def test_match_level_II_cohort(self):
        assert _match_keywords("a cohort study") == "II"

    def test_match_level_II_case_control(self):
        assert _match_keywords("case-control analysis") == "II"

    def test_match_level_III_case_report(self):
        assert _match_keywords("we present a case report") == "III"

    def test_match_level_III_in_vitro(self):
        assert _match_keywords("in vitro experiment") == "III"

    def test_match_level_IV_expert_opinion(self):
        assert _match_keywords("based on expert opinion") == "IV"

    def test_match_level_IV_animal_study(self):
        assert _match_keywords("an animal study in mice") == "IV"

    def test_match_level_IV_review(self):
        """'review' 单独匹配 IV"""
        assert _match_keywords("a review of topics") == "IV"

    def test_priority_I_over_IV(self):
        """'systematic review' 同时匹配 I 和 IV，应返回 I"""
        assert _match_keywords("systematic review") == "I"

    def test_priority_II_over_IV(self):
        """'cohort' (II) 和 'review' (IV) 同时存在，应返回 II"""
        assert _match_keywords("cohort review") == "II"

    def test_priority_III_over_IV(self):
        """'case report' (III) 优先于 'review' (IV)"""
        assert _match_keywords("case report and review") == "III"

    def test_no_match_returns_none(self):
        assert _match_keywords("no relevant keywords here") is None

    def test_case_insensitive(self):
        """输入应已经是小写（由 _build_search_text 处理），但函数本身不转换"""
        # 注意：函数直接做 `kw in text`，不做 tolower
        # 大写不会匹配小写关键词
        assert _match_keywords("A RCT STUDY") is None

    def test_match_keyword_at_start(self):
        assert _match_keywords("rct is here") == "I"

    def test_match_keyword_at_end(self):
        assert _match_keywords("this is an rct") == "I"

    def test_match_keyword_as_substring(self):
        """关键词作为子串即可匹配"""
        # "metaanalysisxxx" 含 "metaanalysis"
        assert _match_keywords("metaanalysisxxx") == "I"


# ============================================================
# 模块常量
# ============================================================
class TestModuleConstants:
    def test_level_keywords_has_all_four_levels(self):
        assert set(_LEVEL_KEYWORDS.keys()) == {"I", "II", "III", "IV"}

    def test_level_keywords_non_empty(self):
        for level, kws in _LEVEL_KEYWORDS.items():
            assert len(kws) > 0, f"等级 {level} 关键词列表为空"

    def test_source_default_has_entries(self):
        assert len(_SOURCE_DEFAULT) > 0

    def test_source_default_values_are_valid_levels(self):
        for src, level in _SOURCE_DEFAULT.items():
            assert level in _LEVEL_KEYWORDS, f"source {src} 映射到无效等级 {level}"

    def test_source_default_keys_are_lowercase(self):
        for src in _SOURCE_DEFAULT.keys():
            assert src == src.lower(), f"source {src} 不是小写"


# ============================================================
# 端到端 / 集成场景
# ============================================================
class TestEndToEndScenarios:
    def test_clinical_trial_evidence_chain(self):
        """临床试验证据链分级"""
        items = [
            {"source": "clinical_trial_phase_iii", "payload": {"title": "Pivotal RCT"}},
            {"source": "clinical_trial_phase_ii", "payload": {"title": "Phase II trial"}},
            {"source": "literature", "payload": {"study_type": "cohort"}},
            {"source": "clinvar", "payload": {"title": "Variant of unknown significance"}},
        ]
        result = evidence_distribution(items)
        assert result["I"] == 1
        # clinical_trial_phase_ii (source 默认 II) + cohort (study_type -> II)
        assert result["II"] == 2
        # clinvar 没有关键词，source 也不在 _SOURCE_DEFAULT，默认 IV
        assert result["IV"] == 1
        assert result["total"] == 4

    def test_literature_search_with_various_payloads(self):
        """文献检索各类研究设计"""
        items = [
            {"source": "literature", "payload": {"abstract": "Meta-analysis of 10 RCTs"}},
            {"source": "literature", "payload": {"abstract": "Prospective cohort study"}},
            {"source": "literature", "payload": {"abstract": "Case series of 5 patients"}},
            {"source": "literature", "payload": {"abstract": "Expert consensus statement"}},
        ]
        result = evidence_distribution(items)
        assert result["I"] == 1
        assert result["II"] == 1
        assert result["III"] == 1
        assert result["IV"] == 1
        assert result["total"] == 4

    def test_explicit_override_in_mixed_dataset(self):
        """显式声明覆盖自动分类的混合场景"""
        items = [
            # source 默认 II，但显式声明 IV
            {"source": "cohort", "evidence_level": "IV"},
            # 无显式声明，source 默认 I
            {"source": "meta_analysis"},
        ]
        result = evidence_distribution(items)
        assert result["I"] == 1
        assert result["IV"] == 1
        assert result["total"] == 2

    def test_docstring_examples(self):
        """验证模块文档字符串中的示例"""
        # >>> classify_evidence_level("meta_analysis") -> 'I'
        assert classify_evidence_level("meta_analysis") == "I"
        # >>> classify_evidence_level("literature", {"study_type": "cohort"}) -> 'II'
        assert classify_evidence_level("literature", {"study_type": "cohort"}) == "II"
        # >>> classify_evidence_level("literature", {"title": "A Case Report of..."}) -> 'III'
        assert classify_evidence_level("literature", {"title": "A Case Report of..."}) == "III"

    def test_docstring_distribution_example(self):
        """验证 evidence_distribution 文档字符串示例"""
        items = [
            {"source": "meta_analysis"},
            {"source": "literature", "payload": {"study_type": "cohort"}},
        ]
        result = evidence_distribution(items)
        assert result == {"I": 1, "II": 1, "III": 0, "IV": 0, "total": 2}
