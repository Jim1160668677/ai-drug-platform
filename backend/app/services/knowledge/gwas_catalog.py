"""GWAS Catalog REST API 客户端

端点：https://www.ebi.ac.uk/gwas/rest/api
搜索性状关联的 SNP 位点，过滤东亚人群验证条目。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.services.knowledge.data_cache import get_cached, set_cached
from app.services.knowledge.population_filter import filter_east_asian

logger = logging.getLogger(__name__)

GWAS_CATALOG_BASE = "https://www.ebi.ac.uk/gwas/rest/api"
DEFAULT_TIMEOUT = 30
DEFAULT_CONCURRENCY = 3  # 限流：并发 ≤ 3


class GwasCatalogClient:
    """GWAS Catalog API 客户端

    使用方法：
        client = GwasCatalogClient()
        candidates = await client.search_by_trait("allergic rhinitis")
    """

    def __init__(self, base_url: str = GWAS_CATALOG_BASE, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search_by_trait(
        self,
        db: Optional[Any],
        trait_name: str,
        *,
        east_asian_only: bool = True,
    ) -> List[Dict]:
        """按性状搜索关联 SNP 位点

        Args:
            db: 数据库会话（用于缓存）
            trait_name: 性状英文名（如 allergic rhinitis）
            east_asian_only: 仅保留东亚人群验证条目

        Returns:
            候选位点列表，每条含 rsid/chromosome/position/gene/odds_ratio/pmid 等字段
        """
        # 1. 缓存查询
        if db is not None:
            cached = await get_cached(db, "gwas_catalog", trait_name)
            if cached is not None:
                logger.info(f"GWAS Catalog 缓存命中: {trait_name}")
                return cached

        # 2. 调外部 API
        try:
            raw_results = await self._fetch_search(trait_name)
        except Exception as e:
            logger.error(f"GWAS Catalog 查询失败: {e}")
            return []

        # 3. 解析 + 人群过滤
        candidates = []
        for study in raw_results:
            try:
                parsed = self._parse_study(study)
                if parsed:
                    candidates.extend(parsed)
            except Exception as e:
                logger.warning(f"GWAS Catalog 条目解析失败: {e}")
                continue

        if east_asian_only:
            candidates = filter_east_asian(candidates, allow_pathogenic=False)

        # 4. 写入缓存
        if db is not None and candidates:
            await set_cached(db, "gwas_catalog", trait_name, candidates, ttl_days=5)

        return candidates

    async def _fetch_search(self, trait_name: str) -> List[Dict]:
        """调 GWAS Catalog search 端点"""
        url = f"{self.base_url}/search"
        params = {
            "q": f"trait:{trait_name}",
            "size": 100,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning(f"GWAS Catalog HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        return data.get("_embedded", {}).get("studies", []) or data.get("studies", []) or []

    def _parse_study(self, study: Dict) -> List[Dict]:
        """解析单条 study → 多个位点条目

        GWAS Catalog study 结构含 associations 列表，每个 association 有 snps。
        """
        results = []
        associations = study.get("associations", []) or []
        for assoc in associations:
            # risk allele
            risk_allele = assoc.get("riskAllele", {})
            rsid = risk_allele.get("name", "") if isinstance(risk_allele, dict) else ""
            if not rsid:
                continue
            # 标准化 rsid（如 "rs1234-A" → "rs1234"）
            rsid = rsid.split("-")[0].strip()

            loci = assoc.get("loci", []) or []
            chrom = ""
            position = None
            gene = ""
            for locus in loci:
                chrom = locus.get("chromosomeName", "")
                position = locus.get("position", None)
                # 基因列表
                mapped_genes = locus.get("strongestRiskAlleles", []) or []
                for allele in mapped_genes:
                    g = allele.get("mappedGenes", []) if isinstance(allele, dict) else []
                    if g:
                        gene = ", ".join(g) if isinstance(g, list) else str(g)
                        break
                break

            pval = assoc.get("pValue")
            odds_ratio = assoc.get("orPerCopyNum") or assoc.get("beta")
            pmid = (study.get("publication", {}) or {}).get("pubmedId", "")

            # 人群
            ancestry = (assoc.get("ancestryCategory", "") or
                         study.get("ancestryCategory", "") or "")
            discovery_sample = (study.get("initialSampleSize", "") or "")

            results.append({
                "rsid": rsid,
                "chromosome": chrom,
                "position_grch37": position,
                "position_grch38": None,  # GWAS Catalog 默认 GRCh37
                "gene_symbol": gene,
                "effect_allele": risk_allele.get("name", "").split("-")[-1] if isinstance(risk_allele, dict) else "",
                "effect_size": float(odds_ratio) if odds_ratio is not None else None,
                "p_value": float(pval) if pval is not None else None,
                "pmid": pmid,
                "population": ancestry,
                "discovery_sample": discovery_sample,
                "evidence_source": "gwas_catalog",
                "evidence_level": "II",
            })

        return results


__all__ = ["GwasCatalogClient", "GWAS_CATALOG_BASE"]
