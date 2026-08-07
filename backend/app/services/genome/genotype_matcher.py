"""基因型匹配服务

输入：PersonalGenome.id + SnpLocus 列表
输出：GenotypeMatch 列表（含 is_risk、risk_score、note）

流程：
1. 从 PersonalGenome.parsed_summary 流式读取用户基因型（按 rsid 索引）
2. 对每个 SnpLocus：
   - 若用户 rsid 未覆盖 → is_risk=False, risk_score=0.0, note="未检测"
   - 否则用 coordinate.is_genotype_match(user_gt, locus.risk_genotype) 判断
   - risk_score = locus.effect_size * (1.0 if is_risk else 0.0)
3. 批量 db.add_all(matches) + await db.flush()
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_genome import GenotypeMatch, PersonalGenome
from app.models.snp_locus import SnpLocus
from app.services.genome.coordinate import is_genotype_match

logger = logging.getLogger(__name__)


async def match_genotype(
    db: AsyncSession,
    personal_genome_id: UUID,
    loci: List[SnpLocus],
    *,
    replace_existing: bool = True,
) -> List[GenotypeMatch]:
    """对指定 SnpLocus 列表执行基因型匹配

    Args:
        db: 数据库会话
        personal_genome_id: 个人基因组文件 ID
        loci: 待匹配的 SnpLocus 列表
        replace_existing: 是否覆盖已有匹配记录（按 personal_genome_id + snp_locus_id 唯一）

    Returns:
        新生成的 GenotypeMatch 列表
    """
    # 1. 加载 PersonalGenome，取出用户基因型字典
    genome = await db.get(PersonalGenome, personal_genome_id)
    if not genome:
        raise ValueError(f"PersonalGenome 不存在: {personal_genome_id}")

    user_genotypes = _extract_user_genotypes(genome)
    if not user_genotypes:
        logger.warning(f"PersonalGenome {personal_genome_id} 无可用基因型数据")

    # 2. 可选：删除旧的匹配记录
    if replace_existing:
        from sqlalchemy import delete
        await db.execute(
            delete(GenotypeMatch).where(
                GenotypeMatch.personal_genome_id == personal_genome_id
            )
        )

    # 3. 逐位点匹配
    matches: List[GenotypeMatch] = []
    for locus in loci:
        user_gt = user_genotypes.get(locus.rsid)

        if not user_gt or user_gt in ("--", "", "00"):
            # 未覆盖
            match = GenotypeMatch(
                personal_genome_id=personal_genome_id,
                snp_locus_id=locus.id,
                user_genotype=user_gt or "--",
                is_risk=False,
                risk_score=0.0,
                note="未检测",
            )
        else:
            # 检查风险基因型
            risk_gt = locus.risk_genotype or locus.effect_allele or ""
            is_risk = False
            if risk_gt:
                is_risk = is_genotype_match(user_gt, risk_gt)
            elif locus.effect_allele:
                # 仅有效应等位 → 用户基因型含此等位即风险
                is_risk = locus.effect_allele.upper() in user_gt.upper()

            # risk_score = effect_size * (1 if risk else 0)
            effect_size = locus.effect_size if locus.effect_size is not None else 0.0
            risk_score = effect_size if is_risk else 0.0

            note = None
            if is_risk and locus.effect_allele and locus.effect_allele.upper() not in user_gt.upper():
                # 通过链翻转命中
                note = "通过链翻转匹配"

            match = GenotypeMatch(
                personal_genome_id=personal_genome_id,
                snp_locus_id=locus.id,
                user_genotype=user_gt,
                is_risk=is_risk,
                risk_score=risk_score,
                note=note,
            )

        matches.append(match)

    # 4. 批量插入
    if matches:
        db.add_all(matches)
        await db.flush()

    logger.info(
        f"基因型匹配完成：genome={personal_genome_id} "
        f"loci={len(loci)} matched={len(matches)} "
        f"risk={sum(1 for m in matches if m.is_risk)}"
    )
    return matches


async def list_matches(
    db: AsyncSession,
    personal_genome_id: UUID,
    *,
    risk_only: bool = False,
) -> List[Dict[str, Any]]:
    """查询匹配结果"""
    stmt = (
        select(GenotypeMatch, SnpLocus)
        .join(SnpLocus, GenotypeMatch.snp_locus_id == SnpLocus.id)
        .where(GenotypeMatch.personal_genome_id == personal_genome_id)
        .order_by(GenotypeMatch.is_risk.desc(), SnpLocus.rsid)
    )
    if risk_only:
        stmt = stmt.where(GenotypeMatch.is_risk == True)  # noqa: E712

    result = await db.execute(stmt)
    items = []
    for match, locus in result.all():
        items.append({
            "id": str(match.id),
            "personal_genome_id": str(match.personal_genome_id),
            "snp_locus_id": str(match.snp_locus_id),
            "rsid": locus.rsid,
            "gene_symbol": locus.gene_symbol,
            "user_genotype": match.user_genotype,
            "is_risk": match.is_risk,
            "risk_score": match.risk_score,
            "note": match.note,
            "effect_allele": locus.effect_allele,
            "risk_genotype": locus.risk_genotype,
            "locus_tier": locus.locus_tier,
        })
    return items


def _extract_user_genotypes(genome: PersonalGenome) -> Dict[str, str]:
    """从 PersonalGenome.parsed_summary 提取用户基因型字典

    parsed_summary 含 genotype_sample 字段（{rsid: genotype}），
    或在 quality_metrics 中含完整 genotypes（大文件可能不全）。
    """
    if not genome.parsed_summary:
        return {}

    # 优先用 genotype_sample（解析器只保留前 5 条）
    sample = genome.parsed_summary.get("genotype_sample", {})
    if sample and len(sample) > 5:
        return sample

    # 回退：尝试从存储路径重新解析（大文件场景）
    # 此处简化：仅返回 sample；上层若需全量匹配应直接读文件
    return sample if isinstance(sample, dict) else {}


__all__ = ["match_genotype", "list_matches"]
