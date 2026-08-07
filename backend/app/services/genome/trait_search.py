"""性状 SNP 位点检索服务

设计来源：参照 Trae 论坛「个人基因组定制解密」方案，
用户选择性状后系统从本地知识库 + 外部数据源（GWAS Catalog / ClinVar / OMIM）
交叉验证位点，东亚人群过滤后写入待审核。

流程：
1. 从本地 SnpLocus 表查询指定性状的 approved 位点
2. 若 use_external=True，并行调外部源补充候选位点
3. 经 filter_east_asian 过滤后写入 SnpLocus 表（is_approved=False）
4. 返回 {trait, loci, external_sources_queried, new_loci_added}
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snp_locus import (
    EvidenceLevel,
    EvidenceSource,
    LocusTier,
    Population,
    SnpLocus,
)
from app.models.trait import Trait
from app.services.knowledge.clinvar_client import ClinvarClient
from app.services.knowledge.gwas_catalog import GwasCatalogClient
from app.services.knowledge.omim_client import OmimClient
from app.services.knowledge.population_filter import filter_east_asian

logger = logging.getLogger(__name__)


async def list_traits(
    db: AsyncSession,
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """性状列表（分页）

    Args:
        db: 数据库会话
        category: 可选性状分类过滤
        page: 页码（从 1 开始）
        page_size: 每页条数

    Returns:
        {items, total, page, page_size}
    """
    skip = (page - 1) * page_size
    stmt = select(Trait).order_by(Trait.category, Trait.name)
    if category:
        stmt = stmt.where(Trait.category == category)
    stmt = stmt.offset(skip).limit(page_size)

    result = await db.execute(stmt)
    items = result.scalars().all()

    count_stmt = select(func.count()).select_from(Trait)
    if category:
        count_stmt = count_stmt.where(Trait.category == category)
    total = (await db.execute(count_stmt)).scalar() or 0

    return {
        "items": [_trait_to_dict(t) for t in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_trait_loci(
    db: AsyncSession,
    trait_id: UUID,
    *,
    approved_only: bool = True,
) -> List[Dict[str, Any]]:
    """获取性状关联的所有位点"""
    stmt = select(SnpLocus).where(SnpLocus.trait_id == trait_id)
    if approved_only:
        stmt = stmt.where(SnpLocus.is_approved == True)  # noqa: E712
    # CORE 位点优先（core < auxiliary 字母序相反，故用 CASE 强制 core 在前）
    stmt = stmt.order_by(
        case((SnpLocus.locus_tier == LocusTier.CORE, 0), else_=1),
        SnpLocus.rsid,
    )
    result = await db.execute(stmt)
    return [_locus_to_dict(loc) for loc in result.scalars().all()]


async def search_loci(
    db: AsyncSession,
    trait_id: UUID,
    user,
    user_llm_config_id: Optional[UUID] = None,
    use_external: bool = True,
) -> Dict[str, Any]:
    """AI 检索位点 — 本地 + 外部数据源交叉验证

    Args:
        db: 数据库会话
        trait_id: 性状 ID
        user: 当前用户
        user_llm_config_id: 用户级 LLM 配置 ID（不传则用系统激活）
        use_external: 是否调外部 API（GWAS Catalog / ClinVar / OMIM）

    Returns:
        {trait, loci, external_sources_queried, new_loci_added, llm_model}
    """
    # 1. 加载性状
    trait = await db.get(Trait, trait_id)
    if not trait:
        raise ValueError(f"性状不存在: {trait_id}")

    # 2. 本地 approved 位点
    local_loci = await _query_local_loci(db, trait_id, approved_only=True)

    # 3. 外部数据源（可选）
    external_queried: List[str] = []
    external_candidates: List[Dict] = []
    if use_external:
        external_queried, external_candidates = await _fetch_external_sources(
            db, trait.name, trait.category
        )

    # 4. 去重 + 写入新位点（is_approved=False）
    new_loci_added = 0
    if external_candidates:
        new_loci_added = await _save_external_loci(db, trait_id, external_candidates, local_loci)

    # 5. 重新查全部位点（approved + 新增）
    all_loci = await _query_local_loci(db, trait_id, approved_only=False)

    return {
        "trait": _trait_to_dict(trait),
        "loci": all_loci,
        "external_sources_queried": external_queried,
        "new_loci_added": new_loci_added,
        "total_loci": len(all_loci),
    }


async def _query_local_loci(
    db: AsyncSession, trait_id: UUID, approved_only: bool
) -> List[Dict[str, Any]]:
    """查本地 SnpLocus 表"""
    stmt = select(SnpLocus).where(SnpLocus.trait_id == trait_id)
    if approved_only:
        stmt = stmt.where(SnpLocus.is_approved == True)  # noqa: E712
    # CORE 位点优先
    stmt = stmt.order_by(
        case((SnpLocus.locus_tier == LocusTier.CORE, 0), else_=1),
        SnpLocus.rsid,
    )
    result = await db.execute(stmt)
    return [_locus_to_dict(loc) for loc in result.scalars().all()]


async def _fetch_external_sources(
    db: AsyncSession, trait_name: str, trait_category: str
) -> tuple:
    """并行调 GWAS Catalog / ClinVar / OMIM

    Returns:
        (queried_sources, candidates)
    """
    queried: List[str] = []
    candidates: List[Dict] = []

    # GWAS Catalog — 按性状查
    try:
        gwas = GwasCatalogClient()
        gwas_results = await asyncio.to_thread(
            lambda: asyncio.run(gwas.search_by_trait(db, trait_name))
        )
        if gwas_results:
            queried.append("gwas_catalog")
            candidates.extend(gwas_results)
    except Exception as e:
        logger.warning(f"GWAS Catalog 查询失败: {e}")

    # ClinVar — 按基因查（trait_category 推断候选基因简化处理：用性状名）
    try:
        clinvar = ClinvarClient()
        clinvar_results = await asyncio.to_thread(
            lambda: asyncio.run(clinvar.search_by_gene(db, trait_name))
        )
        if clinvar_results:
            queried.append("clinvar")
            candidates.extend(clinvar_results)
    except Exception as e:
        logger.warning(f"ClinVar 查询失败: {e}")

    # OMIM — 按关键词查
    try:
        omim = OmimClient()
        if omim.is_configured():
            omim_results = await asyncio.to_thread(
                lambda: asyncio.run(omim.search_by_keyword(db, trait_name))
            )
            if omim_results:
                queried.append("omim")
                # OMIM 返回的是基因-疾病关联，不直接产出位点，仅作交叉验证
                for entry in omim_results:
                    for gene in entry.get("gene_symbols", []):
                        candidates.append({
                            "rsid": None,
                            "gene_symbol": gene,
                            "evidence_source": "omim",
                            "evidence_level": entry.get("evidence_level", "II"),
                            "pmid": "",
                            "population": "all",
                            "discovery_sample": "",
                        })
    except Exception as e:
        logger.warning(f"OMIM 查询失败: {e}")

    # 东亚人群过滤（保留 ClinVar pathogenic）
    candidates = filter_east_asian(candidates, allow_pathogenic=True)
    return queried, candidates


async def _save_external_loci(
    db: AsyncSession,
    trait_id: UUID,
    candidates: List[Dict],
    existing_loci: List[Dict],
) -> int:
    """去重后写入新位点（is_approved=False 待审核）

    去重键：rsid（若 rsid 为 None 则跳过）
    """
    existing_rsids = {loc["rsid"] for loc in existing_loci if loc.get("rsid")}
    added = 0

    for cand in candidates:
        rsid = cand.get("rsid")
        if not rsid or rsid in existing_rsids:
            continue

        # 构造 SnpLocus
        locus = SnpLocus(
            rsid=rsid,
            chromosome=cand.get("chromosome", "") or "",
            position_grch37=cand.get("position_grch37"),
            position_grch38=cand.get("position_grch38"),
            ref_allele=None,
            alt_allele=None,
            gene_symbol=cand.get("gene_symbol"),
            trait_id=trait_id,
            effect_allele=cand.get("effect_allele"),
            risk_genotype=None,
            effect_size=cand.get("effect_size"),
            weight=0.5,
            locus_tier=LocusTier.AUXILIARY,
            population=cand.get("population", Population.UNKNOWN) or Population.UNKNOWN,
            evidence_source=cand.get("evidence_source", EvidenceSource.LLM),
            evidence_level=cand.get("evidence_level", EvidenceLevel.LEVEL_IV),
            pmid=cand.get("pmid"),
            is_approved=False,
        )
        db.add(locus)
        existing_rsids.add(rsid)
        added += 1

    if added:
        await db.flush()
    return added


def _trait_to_dict(t: Trait) -> Dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "category": t.category,
        "description": t.description,
        "icon": t.icon,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _locus_to_dict(loc: SnpLocus) -> Dict[str, Any]:
    return {
        "id": str(loc.id),
        "rsid": loc.rsid,
        "chromosome": loc.chromosome,
        "position_grch37": loc.position_grch37,
        "position_grch38": loc.position_grch38,
        "ref_allele": loc.ref_allele,
        "alt_allele": loc.alt_allele,
        "gene_symbol": loc.gene_symbol,
        "trait_id": str(loc.trait_id),
        "effect_allele": loc.effect_allele,
        "risk_genotype": loc.risk_genotype,
        "effect_size": loc.effect_size,
        "weight": loc.weight,
        "locus_tier": loc.locus_tier,
        "population": loc.population,
        "evidence_source": loc.evidence_source,
        "evidence_level": loc.evidence_level,
        "pmid": loc.pmid,
        "is_approved": loc.is_approved,
        "created_at": loc.created_at.isoformat() if loc.created_at else None,
    }


__all__ = ["list_traits", "get_trait_loci", "search_loci"]
