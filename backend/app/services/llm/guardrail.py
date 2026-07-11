"""LLM 安全护栏 — 输入/输出安全检查

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/LLM服务层.md

拦截类别：
1. 剂量超限（GUARDRAIL_MAX_DOSE_MG）
2. 绝对化表述（"100%有效"、"包治百病"等）
3. PII（个人身份信息）
4. 角色扮演越狱（"假装你是…"、"忽略之前指令"等）
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


def _compile_patterns(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


class Guardrail:
    """LLM 安全护栏

    配置驱动：通过 settings.GUARDRAIL_* 控制行为。
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        max_dose_mg: Optional[float] = None,
        block_patterns: Optional[str] = None,
    ):
        self.enabled = enabled if enabled is not None else settings.GUARDRAIL_ENABLED
        self.max_dose_mg = max_dose_mg or settings.GUARDRAIL_MAX_DOSE_MG
        custom_patterns = block_patterns or settings.GUARDRAIL_BLOCK_PATTERNS
        custom_list = [p.strip() for p in custom_patterns.split(",") if p.strip()]
        self._absolute_patterns = _compile_patterns(_ABSOLUTE_PATTERNS + custom_list)
        self._pii_patterns = {k: re.compile(v) for k, v in _PII_PATTERNS.items()}
        self._jailbreak_patterns = _compile_patterns(_JAILBREAK_PATTERNS)

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

    def check_output(self, text: str) -> GuardrailResult:
        """检查 LLM 输出

        Args:
            text: LLM 输出文本
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

        return GuardrailResult(passed=True)


# 模块级单例
_guardrail: Optional[Guardrail] = None


def get_guardrail() -> Guardrail:
    """获取 Guardrail 单例"""
    global _guardrail
    if _guardrail is None:
        _guardrail = Guardrail()
    return _guardrail
