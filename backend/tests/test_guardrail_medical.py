"""AI 医学红线规则单元测试 — v3.0 文档 11.3 节

覆盖 5 条医学红线规则：
1. 诊断请求拦截（blocked=True）
2. 用药建议拦截（blocked=True）
3. 预后预测标注（passed=True + annotations）
4. 矛盾结论警告（passed=True + annotations）
5. 证据不足标注（passed=True + annotations）

每条规则覆盖正例（触发）、反例（不触发）、边界条件。
"""
import pytest

from app.services.llm.guardrail import (
    Guardrail,
    GuardrailResult,
    MedicalRedlineChecker,
)


# ============================================================
# MedicalRedlineChecker 独立测试
# ============================================================
class TestMedicalRedlineCheckerInit:
    def test_default_enabled_from_settings(self):
        checker = MedicalRedlineChecker()
        assert checker.enabled is True

    def test_explicit_disable(self):
        checker = MedicalRedlineChecker(enabled=False)
        assert checker.enabled is False


# ============================================================
# 规则 1：诊断请求拦截
# ============================================================
class TestDiagnosisRequestRule:
    def setup_method(self):
        self.checker = MedicalRedlineChecker(enabled=True)

    @pytest.mark.parametrize(
        "text",
        [
            "诊断我是否患肺癌",
            "诊断病人有没有肿瘤",
            "帮我看病理报告",
            "帮我判断检查报告",
            "我是不是得了癌症",
            "告诉我是不是肿瘤",
            "帮我确诊",
            "请诊断这个病情",
            "diagnose me",
            "do i have cancer",
            "diagnose the patient",
        ],
    )
    def test_diagnosis_requests_blocked(self, text):
        result = self.checker.check_input(text)
        assert result.blocked is True
        assert result.passed is False
        assert any("诊断请求拦截" in r for r in result.reasons)

    @pytest.mark.parametrize(
        "text",
        [
            "EGFR 基因突变与肺癌的关系是什么",
            "靶向治疗的机制有哪些",
            "请介绍一下免疫治疗",
            "什么是 CDK4/6 抑制剂",
            "PD-L1 表达水平如何检测",
        ],
    )
    def test_non_diagnosis_requests_pass(self, text):
        result = self.checker.check_input(text)
        assert result.passed is True
        assert result.blocked is False

    def test_empty_input_passes(self):
        result = self.checker.check_input("")
        assert result.passed is True
        assert result.blocked is False

    def test_disabled_checker_passes_everything(self):
        checker = MedicalRedlineChecker(enabled=False)
        result = checker.check_input("诊断我是否患癌")
        assert result.passed is True
        assert result.blocked is False


# ============================================================
# 规则 2：用药建议拦截
# ============================================================
class TestMedicationRequestRule:
    def setup_method(self):
        self.checker = MedicalRedlineChecker(enabled=True)

    @pytest.mark.parametrize(
        "text",
        [
            "推荐我吃什么药",
            "建议我用哪种药",
            "告诉我服什么药比较好",
            "我应该吃什么",
            "帮我开药",
            "请给我配处方",
            "推荐具体的用药方案",
            "用什么药最好",
            "what medication should i take",
            "recommend me drugs",
        ],
    )
    def test_medication_requests_blocked(self, text):
        result = self.checker.check_input(text)
        assert result.blocked is True
        assert result.passed is False
        assert any("用药建议拦截" in r for r in result.reasons)

    @pytest.mark.parametrize(
        "text",
        [
            "EGFR 抑制剂的作用机制是什么",
            "奥希替尼的副作用有哪些",
            "介绍一下克唑替尼",
            "靶向药物的耐药机制",
            "化疗药物如何选择适应症",
        ],
    )
    def test_non_medication_requests_pass(self, text):
        result = self.checker.check_input(text)
        assert result.passed is True
        assert result.blocked is False


# ============================================================
# 规则 3：预后预测标注
# ============================================================
class TestPrognosisAnnotationRule:
    def setup_method(self):
        self.checker = MedicalRedlineChecker(enabled=True)

    @pytest.mark.parametrize(
        "text",
        [
            "预计生存期 12 个月",
            "患者还能存活 24 个月",
            "中位生存期 18 个月",
            "5 年生存率 30%",
            "预计寿命 5 年",
            "expected survival of 12 months",
        ],
    )
    def test_prognosis_annotated_not_blocked(self, text):
        result = self.checker.check_output(text)
        assert result.passed is True
        assert result.blocked is False
        assert len(result.annotations) > 0
        assert any("预后免责声明" in a for a in result.annotations)

    @pytest.mark.parametrize(
        "text",
        [
            "EGFR 突变患者对靶向治疗反应较好",
            "该靶点的表达水平在肿瘤组织中升高",
            "免疫治疗通过激活 T 细胞发挥作用",
        ],
    )
    def test_non_prognosis_no_annotation(self, text):
        result = self.checker.check_output(text)
        assert result.passed is True
        assert len(result.annotations) == 0

    def test_prognosis_only_one_annotation(self):
        """多个预后预测模式只标注一次"""
        text = "预计生存期 12 个月，5 年生存率 30%"
        result = self.checker.check_output(text)
        prognosis_annotations = [a for a in result.annotations if "预后免责声明" in a]
        assert len(prognosis_annotations) == 1


# ============================================================
# 规则 4：矛盾结论警告
# ============================================================
class TestContradictionWarningRule:
    def setup_method(self):
        self.checker = MedicalRedlineChecker(enabled=True)

    @pytest.mark.parametrize(
        "text",
        [
            "化疗没有任何效果",
            "所有癌症都可以治愈",
            "靶向治疗完全替代化疗",
            "早期癌症一定治愈",
            "这个基因对所有癌症有效",
        ],
    )
    def test_contradiction_warned_not_blocked(self, text):
        result = self.checker.check_output(text)
        assert result.passed is True
        assert result.blocked is False
        assert any("医学共识警告" in a for a in result.annotations)

    @pytest.mark.parametrize(
        "text",
        [
            "化疗在晚期患者中有效率约 30%",
            "靶向治疗可作为化疗的补充方案",
            "早期癌症五年生存率较高",
        ],
    )
    def test_non_contradiction_no_warning(self, text):
        result = self.checker.check_output(text)
        assert result.passed is True
        # 不应有矛盾结论警告
        contradiction_annotations = [a for a in result.annotations if "医学共识警告" in a]
        assert len(contradiction_annotations) == 0


# ============================================================
# 规则 5：证据不足标注
# ============================================================
class TestLowEvidenceAnnotationRule:
    def setup_method(self):
        self.checker = MedicalRedlineChecker(enabled=True)

    @pytest.mark.parametrize("grade", ["C", "D", "c", "d"])
    def test_low_evidence_grade_annotated(self, grade):
        text = "该靶点可能有效"
        result = self.checker.check_output(text, evidence_grade=grade)
        assert result.passed is True
        assert any("证据有限" in a for a in result.annotations)

    @pytest.mark.parametrize("grade", ["A", "B", "a", "b"])
    def test_high_evidence_grade_not_annotated(self, grade):
        text = "该靶点可能有效"
        result = self.checker.check_output(text, evidence_grade=grade)
        evidence_annotations = [a for a in result.annotations if "证据有限" in a]
        assert len(evidence_annotations) == 0

    def test_none_evidence_grade_not_annotated(self):
        text = "该靶点可能有效"
        result = self.checker.check_output(text, evidence_grade=None)
        evidence_annotations = [a for a in result.annotations if "证据有限" in a]
        assert len(evidence_annotations) == 0

    def test_empty_text_no_annotation(self):
        result = self.checker.check_output("", evidence_grade="D")
        assert result.passed is True
        assert len(result.annotations) == 0


# ============================================================
# Guardrail 集成测试
# ============================================================
class TestGuardrailMedicalIntegration:
    def setup_method(self):
        self.guardrail = Guardrail(enabled=True, medical_redlines_enabled=True)

    def test_check_input_blocks_diagnosis(self):
        result = self.guardrail.check_input("诊断我是否患肺癌")
        assert result.blocked is True
        assert any("诊断请求拦截" in r for r in result.reasons)

    def test_check_input_blocks_medication(self):
        result = self.guardrail.check_input("推荐我吃什么药")
        assert result.blocked is True
        assert any("用药建议拦截" in r for r in result.reasons)

    def test_check_input_allows_normal_query(self):
        result = self.guardrail.check_input("EGFR 基因功能是什么")
        assert result.passed is True
        assert result.blocked is False

    def test_check_output_annotates_prognosis(self):
        result = self.guardrail.check_output("预计生存期 12 个月")
        assert result.passed is True
        assert any("预后免责声明" in a for a in result.annotations)

    def test_check_output_with_low_evidence(self):
        result = self.guardrail.check_output("该靶点有效", evidence_grade="D")
        assert result.passed is True
        assert any("证据有限" in a for a in result.annotations)

    def test_check_output_without_evidence_grade(self):
        """不传 evidence_grade 时不应触发证据不足标注"""
        result = self.guardrail.check_output("该靶点有效")
        evidence_annotations = [a for a in result.annotations if "证据有限" in a]
        assert len(evidence_annotations) == 0

    def test_medical_redlines_can_be_disabled(self):
        guardrail = Guardrail(enabled=True, medical_redlines_enabled=False)
        result = guardrail.check_input("诊断我是否患癌")
        assert result.passed is True
        assert result.blocked is False

    def test_multiple_annotations_combined(self):
        """预后预测 + 低证据等级 → 两条标注同时出现"""
        text = "预计生存期 12 个月"
        result = self.guardrail.check_output(text, evidence_grade="D")
        assert result.passed is True
        assert len(result.annotations) >= 2
        assert any("预后免责声明" in a for a in result.annotations)
        assert any("证据有限" in a for a in result.annotations)
