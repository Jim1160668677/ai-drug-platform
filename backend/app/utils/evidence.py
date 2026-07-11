"""证据等级分类工具 — 循证医学 I/II/III/IV 分级

设计来源：repowiki/zh/content/分析模块/证据链构建.md
           app/models/report.py — EvidenceItem.evidence_level

证据分级（与 EvidenceItem.evidence_level 一致）：
- I   ：RCT / Meta-analysis / Systematic review
- II  ：Cohort / Case-control
- III ：Case report / Case series / In vitro
- IV  ：Expert opinion / Animal study
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 各等级关键词（小写匹配）
_LEVEL_KEYWORDS: Dict[str, List[str]] = {
    "I": [
        "rct", "randomized controlled trial", "randomised controlled trial",
        "randomized trial", "randomised trial",
        "meta-analysis", "meta analysis", "metaanalysis",
        "systematic review", "systematic literature review",
        "pooled analysis",
    ],
    "II": [
        "cohort", "case-control", "case control",
        "nested case-control",
        "longitudinal", "prospective", "retrospective cohort",
    ],
    "III": [
        "case report", "case series",
        "in vitro", "in-vitro",
        "ex vivo", "ex-vivo",
        "cross-sectional",
        "mechanistic study",
    ],
    "IV": [
        "expert opinion", "expert consensus",
        "animal study", "in vivo", "in-vivo",
        "mechanism reasoning", "mechanistic reasoning",
        "review", "narrative review",
    ],
}


# 默认来源 -> 等级映射（用于 source 已表征类型的快速路径）
_SOURCE_DEFAULT: Dict[str, str] = {
    "clinical_trial_phase_iii": "I",
    "clinical_trial_phase_iv": "I",
    "meta_analysis": "I",
    "systematic_review": "I",
    "clinical_trial_phase_ii": "II",
    "cohort": "II",
    "case_control": "II",
    "case_report": "III",
    "case_series": "III",
    "in_vitro": "III",
    "expert_opinion": "IV",
    "animal_study": "IV",
    "narrative_review": "IV",
}


def classify_evidence_level(
    source: str,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """根据来源和负载文本分类证据等级

    优先级：
    1. payload["study_type"] / payload["evidence_level"] 显式声明
    2. source 在 _SOURCE_DEFAULT 中的默认等级
    3. 在 payload 文本字段中按关键词匹配（title / abstract / summary / description）
    4. 默认 IV 级

    Args:
        source: 证据来源标识（如 "clinical_trial_phase_iii" / "literature" / "clinvar"）
        payload: 证据详情（dict），可包含 study_type, evidence_level,
                 title, abstract, summary, description 等字段
    Returns:
        "I" / "II" / "III" / "IV"
    Examples:
        >>> classify_evidence_level("meta_analysis")
        'I'
        >>> classify_evidence_level("literature", {"study_type": "cohort"})
        'II'
        >>> classify_evidence_level("literature", {"title": "A Case Report of..."})
        'III'
    """
    payload = payload or {}

    # 1. payload 中显式声明
    explicit_level = _extract_explicit_level(payload)
    if explicit_level:
        logger.debug("证据等级由显式声明决定: %s", explicit_level)
        return explicit_level

    # 2. source 默认
    src_lower = (source or "").lower().strip()
    if src_lower in _SOURCE_DEFAULT:
        level = _SOURCE_DEFAULT[src_lower]
        logger.debug("证据等级由 source=%s 决定: %s", src_lower, level)
        return level

    # 3. 关键词匹配
    text = _build_search_text(source, payload)
    level = _match_keywords(text)
    if level:
        logger.debug("证据等级由关键词匹配决定: %s (source=%s)", level, src_lower)
        return level

    # 4. 默认 IV
    logger.debug("证据等级未识别，默认 IV (source=%s)", src_lower)
    return "IV"


def evidence_distribution(
    evidence_items: List[Dict[str, Any]],
) -> Dict[str, int]:
    """统计证据项的等级分布

    Args:
        evidence_items: 证据项列表，每项为 dict，应包含 source 和/或 payload，
                        或已包含 evidence_level 字段
    Returns:
        {"I": n, "II": n, "III": n, "IV": n, "total": n}
    Examples:
        >>> evidence_distribution([
        ...     {"source": "meta_analysis"},
        ...     {"source": "literature", "payload": {"study_type": "cohort"}},
        ... ])
        {'I': 1, 'II': 1, 'III': 0, 'IV': 0, 'total': 2}
    """
    distribution: Dict[str, int] = {"I": 0, "II": 0, "III": 0, "IV": 0}
    total = 0
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        # 优先用已声明的 evidence_level
        level = item.get("evidence_level")
        if level not in distribution:
            level = classify_evidence_level(
                item.get("source", ""),
                item.get("payload") if isinstance(item.get("payload"), dict) else item,
            )
        if level in distribution:
            distribution[level] += 1
            total += 1
        else:
            logger.warning("未识别的证据等级: %s", level)

    distribution["total"] = total
    logger.info("证据分布: %s", distribution)
    return distribution


# ---------- 内部辅助 ----------
def _extract_explicit_level(payload: Dict[str, Any]) -> Optional[str]:
    """从 payload 提取显式声明的等级"""
    # evidence_level 直接声明
    level = payload.get("evidence_level")
    if isinstance(level, str) and level.strip() in _LEVEL_KEYWORDS:
        return level.strip()

    # study_type 映射
    study_type = payload.get("study_type")
    if isinstance(study_type, str):
        st_lower = study_type.lower().strip()
        # 直接是等级名
        if st_lower in {"i", "ii", "iii", "iv"}:
            return st_lower.upper()
        # 在关键词中查找
        for lvl, kws in _LEVEL_KEYWORDS.items():
            for kw in kws:
                if kw in st_lower:
                    return lvl
    return None


def _build_search_text(source: str, payload: Dict[str, Any]) -> str:
    """拼接用于关键词匹配的文本"""
    parts: List[str] = [str(source or "")]
    for key in ("title", "abstract", "summary", "description", "text", "type"):
        val = payload.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def _match_keywords(text: str) -> Optional[str]:
    """在文本中按等级优先级匹配关键词

    匹配顺序：I > II > III > IV（避免被 IV 的 "review" 误判）
    """
    if not text:
        return None
    for level in ("I", "II", "III", "IV"):
        for kw in _LEVEL_KEYWORDS[level]:
            if kw in text:
                return level
    return None


__all__ = ["classify_evidence_level", "evidence_distribution"]
