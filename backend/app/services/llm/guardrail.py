"""LLM 安全护栏 — 输入/输出安全检查

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/LLM服务层.md

拦截类别：
1. 剂量超限（GUARDRAIL_MAX_DOSE_MG）
2. 绝对化表述（"100%有效"、"包治百病"等）
3. PII（个人身份信息）
4. 角色扮演越狱（"假装你是…"、"忽略之前指令"等）
5. 医学红线（v3.0 文档 11.3 节）：诊断请求/用药建议/预后预测/矛盾结论/证据不足
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    """护栏检查结果"""
    passed: bool
    blocked: bool = False
    reasons: List[str] = field(default_factory=list)
    sanitized_text: Optional[str] = None
    annotations: List[str] = field(default_factory=list)  # 非拦截性标注（免责声明等）


# 绝对化表述模式
_ABSOLUTE_PATTERNS = [
    r"100\s*%\s*(有效|治愈|安全)",
    r"绝对\s*(治愈|有效|安全|无毒)",
    r"包治百病",
    r"根治\s*(所有|任何)",
    r"无任何\s*(副作用|风险)",
    r"万灵药",
    r"神药",
]

# PII 模式（简化）
_PII_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\b1[3-9]\d{9}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "id_card": r"\b\d{15}|\d{18}\b",
}

# 角色扮演越狱模式
_JAILBREAK_PATTERNS = [
    r"假装你是",
    r"忽略(之前|上面|所有)(的)?指令",
    r"无视(之前|上面|所有)(的)?(指令|规则|限制)",
    r"你(现在)?(是|扮演)",
    r"进入\s*(DAN|开发者|无限制)\s*模式",
    r"do anything now",
    r"ignore (previous|above) instructions",
]

# ========== 医学红线模式（v3.0 文档 11.3 节） ==========

# 1. 诊断请求模式 — 用户要求系统进行医学诊断
_DIAGNOSIS_REQUEST_PATTERNS = [
    r"诊断(我|病人|患者|这个).*(是否|有没有|是不是).*(癌|肿瘤|病|症)",
    r"帮我(看|判断|分析).*(病理|检查报告|CT|MRI|影像)",
    r"我(是不是|是否)得了.*(癌|肿瘤|病|症)",
    r"(判断|告诉我).*(是不是|是否).*(癌症|肿瘤|恶性)",
    r"(帮我|请).*(确诊|诊断)",
    r"diagnose\s+(me|this|the patient)",
    r"do\s+i\s+have\s+(cancer|tumor|disease)",
]

# 2. 用药建议请求模式 — 用户要求系统推荐具体用药
_MEDICATION_REQUEST_PATTERNS = [
    r"(推荐|建议|告诉)\s*我\s*(吃|用|服|打).*(什么药|哪种药|啥药)",
    r"我\s*应该\s*(吃|用|服).*(什么|哪种|啥)",
    r"(帮我|请|给我).*(开|配|买).*(药|处方)",
    r"(推荐|建议).*(具体|什么).*(用药|药物|治疗方案)",
    r"用什么药(最好|最合适|比较好)",
    r"what\s+(medication|drug|medicine)\s+should\s+i\s+take",
    r"recommend\s+(me\s+)?(medication|drugs|pills)",
]

# 3. 预后预测模式 — 输出含生存期/寿命等预后判断
_PROGNOSIS_PATTERNS = [
    r"预计(生存|寿命|存活).*(\d+)\s*(个?月|年|天|周)",
    r"(还能|可以)\s*(活|生存|存活).*(\d+)\s*(个?月|年|天|周)",
    r"(生存|存活|寿命)期.*(\d+)\s*(个?月|年|天)",
    r"(预后).*(\d+)\s*(个?月|年|天)",
    r"中位(生存|存活).*(\d+)",
    r"5\s*年(生存|存活)率.*(\d+)\s*%",
    r"expected\s+survival\s+(?:of\s+)?(\d+)",
]

# 4. 矛盾结论模式 — 输出与已知医学共识矛盾
_CONTRADICTION_PATTERNS = [
    r"(化疗|放疗|手术).*(没有|无|不产生)(任何)?(效果|作用|疗效)",
    r"(所有|全部)(癌症|肿瘤).*(可以|能够|都能)(治愈|根治)",
    r"(靶向|免疫)治疗.*(完全|100%)(替代|取代)(化疗|放疗)",
    r"(早期|晚期)(癌症|肿瘤).*(一定|必然|100%)(治愈|死亡)",
    r"(这个|该)(基因|靶点).*(所有|任何)(癌症|肿瘤).*(有效|治愈)",
]

# 低证据等级集合（用于规则 5）
_LOW_EVIDENCE_GRADES = {"C", "D", "c", "d"}

# 免责声明模板
_PROGNOSIS_DISCLAIMER = (
    "【预后免责声明】以下预后预测基于统计学数据，个体差异较大，"
    "请结合临床医生综合评估，不作为唯一决策依据。"
)
_CONTRADICTION_WARNING = (
    "【医学共识警告】以下结论与现有医学共识存在差异，请谨慎参考并咨询专业医生。"
)
_LOW_EVIDENCE_ANNOTATION = (
    "【证据有限】以下结论基于较低证据等级（C/D 级），请结合更高质量证据综合判断。"
)


def _compile_patterns(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


class MedicalRedlineChecker:
    """医学红线检查器 — v3.0 文档 11.3 节定义的 5 条医学特定红线

    规则分类：
    - 拦截类（blocked=True）：诊断请求、用药建议
    - 标注类（passed=True + annotations）：预后预测、矛盾结论、证据不足
    """

    def __init__(self, enabled: Optional[bool] = None):
        self.enabled = enabled if enabled is not None else settings.GUARDRAIL_MEDICAL_REDLINES_ENABLED
        self._diagnosis_patterns = _compile_patterns(_DIAGNOSIS_REQUEST_PATTERNS)
        self._medication_patterns = _compile_patterns(_MEDICATION_REQUEST_PATTERNS)
        self._prognosis_patterns = _compile_patterns(_PROGNOSIS_PATTERNS)
        self._contradiction_patterns = _compile_patterns(_CONTRADICTION_PATTERNS)

    def check_input(self, text: str) -> GuardrailResult:
        """检查用户输入 — 拦截诊断请求和用药建议"""
        if not self.enabled or not text:
            return GuardrailResult(passed=True)

        # 规则 1：诊断请求拦截
        for pattern in self._diagnosis_patterns:
            if pattern.search(text):
                return GuardrailResult(
                    passed=False,
                    blocked=True,
                    reasons=[
                        f"医学红线-诊断请求拦截: 系统不提供医学诊断服务，请咨询专业医生进行诊断。"
                    ],
                )

        # 规则 2：用药建议拦截
        for pattern in self._medication_patterns:
            if pattern.search(text):
                return GuardrailResult(
                    passed=False,
                    blocked=True,
                    reasons=[
                        f"医学红线-用药建议拦截: 系统不提供具体用药建议，请咨询执业医师获取处方。"
                    ],
                )

        return GuardrailResult(passed=True)

    def check_output(
        self,
        text: str,
        evidence_grade: Optional[str] = None,
    ) -> GuardrailResult:
        """检查 LLM 输出 — 标注预后预测、矛盾结论、证据不足

        Args:
            text: LLM 输出文本
            evidence_grade: 证据等级（A/B/C/D），用于规则 5
        Returns:
            GuardrailResult（标注类不拦截，annotations 含免责声明）
        """
        if not self.enabled or not text:
            return GuardrailResult(passed=True)

        reasons: List[str] = []
        annotations: List[str] = []

        # 规则 3：预后预测标注（不拦截，添加免责声明）
        for pattern in self._prognosis_patterns:
            if pattern.search(text):
                annotations.append(_PROGNOSIS_DISCLAIMER)
                reasons.append("医学红线-预后预测标注: 已添加免责声明")
                break  # 只标注一次

        # 规则 4：矛盾结论警告（不拦截，添加警告标注）
        for pattern in self._contradiction_patterns:
            if pattern.search(text):
                annotations.append(_CONTRADICTION_WARNING)
                reasons.append("医学红线-矛盾结论警告: 与医学共识存在差异")
                break

        # 规则 5：证据不足标注（不拦截，添加证据等级标注）
        if evidence_grade and evidence_grade in _LOW_EVIDENCE_GRADES:
            annotations.append(_LOW_EVIDENCE_ANNOTATION)
            reasons.append(f"医学红线-证据不足标注: 证据等级 {evidence_grade}")

        return GuardrailResult(
            passed=True,
            blocked=False,
            reasons=reasons,
            annotations=annotations,
        )


class Guardrail:
    """LLM 安全护栏

    配置驱动：通过 settings.GUARDRAIL_* 控制行为。
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        max_dose_mg: Optional[float] = None,
        block_patterns: Optional[str] = None,
        medical_redlines_enabled: Optional[bool] = None,
    ):
        self.enabled = enabled if enabled is not None else settings.GUARDRAIL_ENABLED
        self.max_dose_mg = max_dose_mg or settings.GUARDRAIL_MAX_DOSE_MG
        custom_patterns = block_patterns or settings.GUARDRAIL_BLOCK_PATTERNS
        custom_list = [p.strip() for p in custom_patterns.split(",") if p.strip()]
        self._absolute_patterns = _compile_patterns(_ABSOLUTE_PATTERNS + custom_list)
        self._pii_patterns = {k: re.compile(v) for k, v in _PII_PATTERNS.items()}
        self._jailbreak_patterns = _compile_patterns(_JAILBREAK_PATTERNS)
        self._medical_checker = MedicalRedlineChecker(enabled=medical_redlines_enabled)

    def check_input(self, text: str) -> GuardrailResult:
        """检查用户输入

        Args:
            text: 用户输入文本
        Returns:
            GuardrailResult（passed=True 表示通过，blocked=True 表示拦截）
        """
        if not self.enabled or not text:
            return GuardrailResult(passed=True)

        reasons: List[str] = []

        # 1. 角色扮演越狱检测
        for pattern in self._jailbreak_patterns:
            if pattern.search(text):
                reasons.append(f"检测到角色扮演越狱模式: {pattern.pattern}")
                return GuardrailResult(passed=False, blocked=True, reasons=reasons)

        # 1.5 医学红线检查（诊断请求/用药建议拦截）
        medical_result = self._medical_checker.check_input(text)
        if medical_result.blocked:
            return medical_result

        # 2. 剂量超限检测（简单正则：数字 + mg/mg/kg）
        dose_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:mg|毫克)", text, re.IGNORECASE)
        for dose_str in dose_matches:
            try:
                dose = float(dose_str)
                if dose > self.max_dose_mg:
                    reasons.append(f"剂量超限: {dose}mg > {self.max_dose_mg}mg")
                    return GuardrailResult(passed=False, blocked=True, reasons=reasons)
            except ValueError:
                continue

        # 3. PII 检测（警告但不拦截，做脱敏）
        sanitized = text
        pii_found = []
        for pii_type, pattern in self._pii_patterns.items():
            if pattern.search(text):
                pii_found.append(pii_type)
                sanitized = pattern.sub(f"[REDACTED_{pii_type.upper()}]", sanitized)

        if pii_found:
            reasons.append(f"检测到 PII: {', '.join(pii_found)}（已脱敏）")
            return GuardrailResult(
                passed=True,
                blocked=False,
                reasons=reasons,
                sanitized_text=sanitized,
            )

        return GuardrailResult(passed=True)

    def check_output(
        self,
        text: str,
        evidence_grade: Optional[str] = None,
    ) -> GuardrailResult:
        """检查 LLM 输出

        Args:
            text: LLM 输出文本
            evidence_grade: 证据等级（A/B/C/D），用于医学红线规则 5
        Returns:
            GuardrailResult（passed=True 表示通过，blocked=True 表示拦截）
        """
        if not self.enabled or not text:
            return GuardrailResult(passed=True)

        reasons: List[str] = []

        # 1. 绝对化表述检测
        for pattern in self._absolute_patterns:
            if pattern.search(text):
                reasons.append(f"检测到绝对化表述: {pattern.pattern}")
                return GuardrailResult(passed=False, blocked=True, reasons=reasons)

        # 2. PII 泄露检测（拦截）
        for pii_type, pattern in self._pii_patterns.items():
            if pattern.search(text):
                reasons.append(f"输出中泄露 PII: {pii_type}")
                return GuardrailResult(passed=False, blocked=True, reasons=reasons)

        # 3. 医学红线标注（预后预测/矛盾结论/证据不足 — 不拦截，添加标注）
        medical_result = self._medical_checker.check_output(text, evidence_grade)
        if medical_result.annotations:
            return GuardrailResult(
                passed=True,
                blocked=False,
                reasons=reasons + medical_result.reasons,
                annotations=medical_result.annotations,
            )

        return GuardrailResult(passed=True)


# 模块级单例
_guardrail: Optional[Guardrail] = None


def get_guardrail() -> Guardrail:
    """获取 Guardrail 单例"""
    global _guardrail
    if _guardrail is None:
        _guardrail = Guardrail()
    return _guardrail
