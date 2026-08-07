"""多基因风险评分（PRS）服务

评分公式（参考 PRS-by-clumping 方法，简化版）：
  core_score = Σ(core_loci.risk_score * 0.7) / Σ(core_loci.weight)
  aux_score  = Σ(aux_loci.risk_score * 0.3)  / Σ(aux_loci.weight)
  overall    = clamp(core_score + aux_score, 0.0, 1.0)

风险等级：
  - LOW:      overall < 0.30
  - MODERATE: 0.30 ≤ overall < 0.60
  - HIGH:     0.60 ≤ overall < 0.85
  - VERY_HIGH: overall ≥ 0.85
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_genome import GenotypeMatch, PersonalGenome, RiskAssessment, RiskLevel
from app.models.snp_locus import LocusTier, SnpLocus
from app.models.trait import Trait

logger = logging.getLogger(__name__)

# PRS 权重常量
CORE_WEIGHT = 0.7
AUX_WEIGHT = 0.3

# 风险阈值
RISK_THRESHOLDS = [
    (0.85, "very_high"),
    (0.60, "high"),
    (0.30, "moderate"),
    (0.0, "low"),
]


async def score_risk(
    db: AsyncSession,
    personal_genome_id: UUID,
    trait_id: UUID,
    matches: Optional[List[GenotypeMatch]] = None,
) -> RiskAssessment:
    """计算指定性状的风险评分

    Args:
        db: 数据库会话
        personal_genome_id: 个人基因组文件 ID
        trait_id: 性状 ID
        matches: 已生成的 GenotypeMatch 列表（不传则查 DB）

    Returns:
        RiskAssessment 实例（已 flush 到 DB，未 commit）
    """
    # 1. 加载 matches（若未传）
    if matches is None:
        matches = await _load_matches_by_trait(db, personal_genome_id, trait_id)

    # 2. 按 locus_tier 分组
    core_matches, aux_matches = await _split_matches_by_tier(db, matches)

    # 3. 计算加权评分
    core_score = _calculate_tier_score(core_matches, CORE_WEIGHT)
    aux_score = _calculate_tier_score(aux_matches, AUX_WEIGHT)
    overall = max(0.0, min(1.0, core_score + aux_score))

    # 4. 确定风险等级
    risk_level = _determine_risk_level(overall)

    # 5. 写入 RiskAssessment
    matched_loci_ids = [str(m.snp_locus_id) for m in matches]

    assessment = RiskAssessment(
        personal_genome_id=personal_genome_id,
        trait_id=trait_id,
        overall_risk_score=round(overall, 4),
        risk_level=risk_level,
        core_loci_matched=len(core_matches),
        auxiliary_loci_matched=len(aux_matches),
        matched_loci_ids=matched_loci_ids,
        interpretation=None,
        llm_model=None,
    )
    db.add(assessment)
    await db.flush()

    logger.info(
        f"风险评分完成：genome={personal_genome_id} trait={trait_id} "
        f"score={overall:.4f} level={risk_level} "
        f"core={len(core_matches)} aux={len(aux_matches)}"
    )
    return assessment


async def list_assessments(
    db: AsyncSession,
    personal_genome_id: UUID,
) -> List[Dict[str, Any]]:
    """查询个人基因组文件的所有风险评估"""
    stmt = (
        select(RiskAssessment, Trait)
        .join(Trait, RiskAssessment.trait_id == Trait.id)
        .where(RiskAssessment.personal_genome_id == personal_genome_id)
        .order_by(RiskAssessment.created_at.desc())
    )
    result = await db.execute(stmt)
    items = []
    for a, t in result.all():
        items.append({
            "id": str(a.id),
            "personal_genome_id": str(a.personal_genome_id),
            "trait_id": str(a.trait_id),
            "trait_name": t.name,
            "trait_category": t.category,
            "overall_risk_score": a.overall_risk_score,
            "risk_level": a.risk_level,
            "core_loci_matched": a.core_loci_matched,
            "auxiliary_loci_matched": a.auxiliary_loci_matched,
            "matched_loci_ids": a.matched_loci_ids or [],
            "interpretation": a.interpretation,
            "llm_model": a.llm_model,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    return items


async def get_assessment(
    db: AsyncSession, assessment_id: UUID
) -> Optional[Dict[str, Any]]:
    """获取单条风险评估详情"""
    a = await db.get(RiskAssessment, assessment_id)
    if not a:
        return None
    t = await db.get(Trait, a.trait_id)
    return {
        "id": str(a.id),
        "personal_genome_id": str(a.personal_genome_id),
        "trait_id": str(a.trait_id),
        "trait_name": t.name if t else None,
        "trait_category": t.category if t else None,
        "overall_risk_score": a.overall_risk_score,
        "risk_level": a.risk_level,
        "core_loci_matched": a.core_loci_matched,
        "auxiliary_loci_matched": a.auxiliary_loci_matched,
        "matched_loci_ids": a.matched_loci_ids or [],
        "interpretation": a.interpretation,
        "llm_model": a.llm_model,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _load_matches_by_trait(
    db: AsyncSession, personal_genome_id: UUID, trait_id: UUID
) -> List[GenotypeMatch]:
    """按性状加载所有匹配记录"""
    stmt = (
        select(GenotypeMatch)
        .join(SnpLocus, GenotypeMatch.snp_locus_id == SnpLocus.id)
        .where(GenotypeMatch.personal_genome_id == personal_genome_id)
        .where(SnpLocus.trait_id == trait_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _split_matches_by_tier(
    db: AsyncSession, matches: List[GenotypeMatch]
) -> tuple:
    """按 locus_tier 分组（core / auxiliary）"""
    if not matches:
        return [], []

    locus_ids = [m.snp_locus_id for m in matches]
    stmt = select(SnpLocus).where(SnpLocus.id.in_(locus_ids))
    result = await db.execute(stmt)
    loci_by_id = {loc.id: loc for loc in result.scalars().all()}

    core = []
    aux = []
    for m in matches:
        loc = loci_by_id.get(m.snp_locus_id)
        if not loc:
            continue
        if loc.locus_tier == LocusTier.CORE:
            core.append((m, loc))
        else:
            aux.append((m, loc))
    return core, aux


def _calculate_tier_score(
    matches_with_loci: List[tuple], tier_weight: float
) -> float:
    """计算单个 tier 的加权评分

    score = Σ(risk_score * tier_weight) / Σ(weight)
    """
    if not matches_with_loci:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for m, loc in matches_with_loci:
        numerator += m.risk_score * tier_weight
        denominator += loc.weight or 0.5
    if denominator == 0:
        return 0.0
    # 归一化到 0-1（假设 risk_score 已是 OR 值，1.0 表示无风险，>1 表示风险增加）
    # 这里简化：直接用相对值，配合 0-1 clamp
    raw = numerator / denominator
    # OR 值到 0-1 概率的简单映射（logistic）
    # p = OR / (1 + OR)，但 OR 可能很大，用 log 压缩
    import math
    if raw <= 0:
        return 0.0
    return min(1.0, math.log(1 + raw) / math.log(10))  # log10 压缩到 [0, 1]


def _determine_risk_level(score: float) -> str:
    """根据评分确定风险等级"""
    for threshold, level in RISK_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


__all__ = [
    "score_risk",
    "list_assessments",
    "get_assessment",
    "CORE_WEIGHT",
    "AUX_WEIGHT",
    "RISK_THRESHOLDS",
]
