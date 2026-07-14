"""药物相互作用（DDI）检查器单元测试

覆盖：
- 规则表精确匹配（正例 + 反例）
- 靶点重合度算法
- 风险等级汇总
- 边界条件（空输入、单药物、无匹配）
"""
import pytest

from app.services.analyzer.ddi_checker import (
    DDIChecker,
    RISK_NONE,
    RISK_MINOR,
    RISK_MODERATE,
    RISK_MAJOR,
    RISK_CONTRAINDICATED,
    get_ddi_checker,
)


# ============================================================
# 基础构造
# ============================================================
class TestDDICheckerInit:
    def test_singleton(self):
        c1 = get_ddi_checker()
        c2 = get_ddi_checker()
        assert c1 is c2

    def test_new_instance(self):
        c = DDIChecker()
        assert c is not get_ddi_checker()

    def test_rules_populated(self):
        c = DDIChecker()
        assert len(c._rules) >= 50


# ============================================================
# 边界条件
# ============================================================
class TestEdgeCases:
    def setup_method(self):
        self.checker = DDIChecker()

    def test_empty_drug_list(self):
        result = self.checker.check([])
        assert result["risk_level"] == RISK_NONE
        assert result["interactions"] == []
        assert result["drug_count"] == 0

    def test_single_drug(self):
        result = self.checker.check(["warfarin"])
        assert result["risk_level"] == RISK_NONE
        assert result["interactions"] == []
        assert result["drug_count"] == 1

    def test_two_drugs_no_interaction(self):
        result = self.checker.check(["acetaminophen", "ibuprofen"])
        assert result["risk_level"] == RISK_NONE
        assert len(result["interactions"]) == 0

    def test_drugs_with_whitespace(self):
        """带空格的药物名应被规范化"""
        result = self.checker.check([" warfarin ", " aspirin "])
        assert result["risk_level"] == RISK_MAJOR
        assert result["drug_count"] == 2

    def test_drugs_with_empty_strings(self):
        """空字符串应被过滤"""
        result = self.checker.check(["warfarin", "", "  ", "aspirin"])
        assert result["risk_level"] == RISK_MAJOR
        assert result["drug_count"] == 2

    def test_case_insensitive(self):
        """药物名应大小写不敏感"""
        result = self.checker.check(["WARFARIN", "ASPIRIN"])
        assert result["risk_level"] == RISK_MAJOR


# ============================================================
# 规则表匹配
# ============================================================
class TestRuleTableMatching:
    def setup_method(self):
        self.checker = DDIChecker()

    def test_warfarin_aspirin_major(self):
        result = self.checker.check(["warfarin", "aspirin"])
        assert result["risk_level"] == RISK_MAJOR
        assert len(result["interactions"]) == 1
        i = result["interactions"][0]
        assert i["severity"] == RISK_MAJOR
        assert "出血" in i["clinical_effect"]
        assert i["source"] == "rule_table"

    def test_simvastatin_itraconazole_contraindicated(self):
        result = self.checker.check(["simvastatin", "itraconazole"])
        assert result["risk_level"] == RISK_CONTRAINDICATED
        assert len(result["interactions"]) == 1
        assert "横纹肌溶解" in result["interactions"][0]["clinical_effect"]

    def test_bidirectional_matching(self):
        """规则表应双向匹配（drug_a/drug_b 顺序无关）"""
        r1 = self.checker.check(["warfarin", "aspirin"])
        r2 = self.checker.check(["aspirin", "warfarin"])
        assert r1["risk_level"] == r2["risk_level"]
        assert len(r1["interactions"]) == len(r2["interactions"])

    def test_methotrexate_trimethoprim_contraindicated(self):
        result = self.checker.check(["methotrexate", "trimethoprim"])
        assert result["risk_level"] == RISK_CONTRAINDICATED

    def test_fluoxetine_tramadol_serotonin_syndrome(self):
        result = self.checker.check(["fluoxetine", "tramadol"])
        assert result["risk_level"] == RISK_MAJOR
        assert any("5-羟色胺" in i["clinical_effect"] for i in result["interactions"])

    def test_multiple_interactions(self):
        """三药组合 → 多对相互作用"""
        result = self.checker.check(["warfarin", "aspirin", "amiodarone"])
        # warfarin-aspirin (major) + warfarin-amiodarone (major)
        assert len(result["interactions"]) >= 2
        assert result["risk_level"] == RISK_MAJOR

    def test_qt_prolongation_combination(self):
        result = self.checker.check(["amiodarone", "haloperidol"])
        assert result["risk_level"] == RISK_MAJOR
        assert any("QT" in i["mechanism"] for i in result["interactions"])


# ============================================================
# 风险等级汇总
# ============================================================
class TestRiskLevelAggregation:
    def setup_method(self):
        self.checker = DDIChecker()

    def test_max_risk_selected(self):
        """多相互作用时取最高风险等级"""
        # warfarin + aspirin (major) + simvastatin + itraconazole (contraindicated)
        result = self.checker.check(["warfarin", "aspirin", "simvastatin", "itraconazole"])
        assert result["risk_level"] == RISK_CONTRAINDICATED

    def test_summary_contains_count(self):
        result = self.checker.check(["warfarin", "aspirin"])
        assert "1 项相互作用" in result["summary"]

    def test_summary_mentions_severe_count(self):
        result = self.checker.check(["warfarin", "aspirin", "simvastatin", "itraconazole"])
        assert "严重或禁忌" in result["summary"]


# ============================================================
# 靶点重合度
# ============================================================
class TestTargetOverlap:
    def setup_method(self):
        self.checker = DDIChecker()

    def test_drugs_with_overlapping_targets(self):
        """两药物共享靶点 → 检测到相互作用"""
        # fluoxetine 和 sertraline 都作用于 SLC6A4 + CYP2D6
        result = self.checker.check(["fluoxetine", "sertraline"])
        # 靶点完全重合，overlap_ratio = 1.0 >= 0.5
        target_overlap_interactions = [
            i for i in result["interactions"] if i["source"] == "target_overlap"
        ]
        assert len(target_overlap_interactions) >= 1
        assert target_overlap_interactions[0]["overlap_ratio"] >= 0.5

    def test_drugs_without_known_targets(self):
        """未知靶点的药物不触发靶点重合"""
        result = self.checker.check(["unknown_drug_a", "unknown_drug_b"])
        target_overlap = [
            i for i in result["interactions"] if i["source"] == "target_overlap"
        ]
        assert len(target_overlap) == 0

    def test_target_list_integration(self):
        """额外靶点列表与药物靶点重合"""
        # warfarin 的靶点包含 VKORC1, CYP2C9
        result = self.checker.check(
            ["warfarin", "metformin"],
            target_list=["VKORC1", "CYP2C9"],
        )
        # 应检测到 warfarin 与靶点列表的重合
        target_list_interactions = [
            i for i in result["interactions"] if i["source"] == "target_list"
        ]
        assert len(target_list_interactions) >= 1


# ============================================================
# 规则表完整性
# ============================================================
class TestRulesIntegrity:
    def test_all_rules_have_required_fields(self):
        c = DDIChecker()
        required = {"drug_a", "drug_b", "severity", "mechanism", "clinical_effect"}
        for rule in c._rules:
            assert required.issubset(rule.keys()), f"规则缺少字段: {rule}"

    def test_all_severities_valid(self):
        c = DDIChecker()
        valid = {RISK_MINOR, RISK_MODERATE, RISK_MAJOR, RISK_CONTRAINDICATED}
        for rule in c._rules:
            assert rule["severity"] in valid, f"无效风险等级: {rule['severity']}"

    def test_at_least_50_rules(self):
        """规则表应包含至少 50 条规则"""
        c = DDIChecker()
        assert len(c._rules) >= 50

    def test_no_duplicate_rules(self):
        """不应有重复规则（双向不视为重复）"""
        c = DDIChecker()
        pairs = set()
        for rule in c._rules:
            pair = frozenset({rule["drug_a"], rule["drug_b"]})
            assert pair not in pairs, f"重复规则: {rule['drug_a']} + {rule['drug_b']}"
            pairs.add(pair)
