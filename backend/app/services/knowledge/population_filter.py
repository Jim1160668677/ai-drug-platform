"""东亚人群特异性筛选器

设计来源：参照 Trae 论坛方案，仅收录 GWAS Catalog、ClinVar、OMIM
有大样本汉族队列验证的位点，剔除仅欧美人群弱关联变异。

ClinVar 路径性变异例外：不受人群限制（致病性变异跨人群通用）。
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


# 东亚人群相关标签集合（含中英文变体）
EAST_ASIAN_KEYWORDS = {
    "east_asian", "east asian", "east-asian",
    "han_chinese", "han chinese", "han",
    "chinese", "china", "chinese_han",
    "asian", "japanese", "korean",
    "东亚", "汉族", "中国", "亚洲",
}


def _normalize(text: str) -> str:
    if not text:
        return ""
    return text.strip().lower()


def is_east_asian(population: str = "", discovery_sample: str = "", ancestry: str = "") -> bool:
    """判断位点的人群标签是否为东亚

    Args:
        population: 人群标签（如 east_asian / european）
        discovery_sample: 发现样本描述
        ancestry: 血统标签

    Returns:
        True 表示属于东亚人群
    """
    text = " ".join(_normalize(t) for t in [population, discovery_sample, ancestry])
    if not text:
        # 无人群标签 — 默认不放行（除非显式标注东亚）
        return False
    return any(kw in text for kw in EAST_ASIAN_KEYWORDS)


def filter_east_asian(
    candidates: List[dict],
    *,
    allow_pathogenic: bool = True,
) -> List[dict]:
    """筛选东亚人群验证位点

    Args:
        candidates: 候选位点列表（每条需含 population/discovery_sample/ancestry/evidence_type 字段）
        allow_pathogenic: ClinVar 路径性变异是否保留所有人群

    Returns:
        过滤后的位点列表
    """
    filtered: List[dict] = []
    skipped = 0
    for cand in candidates:
        # ClinVar 路径性变异例外
        if allow_pathogenic:
            clnsig = _normalize(cand.get("clnsig", "") or cand.get("clinical_significance", ""))
            if clnsig and any(s in clnsig for s in ["pathogenic", "likely_pathogenic", "致病", "可能致病"]):
                filtered.append(cand)
                continue

        population = cand.get("population", "") or ""
        discovery_sample = cand.get("discovery_sample", "") or cand.get("study_sample", "") or ""
        ancestry = cand.get("ancestry", "") or cand.get("ancestry_label", "") or ""

        if is_east_asian(population, discovery_sample, ancestry):
            filtered.append(cand)
        else:
            skipped += 1
    logger.info(f"东亚人群筛选：{len(filtered)}/{len(candidates)} 通过，{skipped} 剔除")
    return filtered


__all__ = ["is_east_asian", "filter_east_asian", "EAST_ASIAN_KEYWORDS"]
