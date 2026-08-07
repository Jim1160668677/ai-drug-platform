"""ClinVar E-utilities API 客户端（向后兼容层）

重构说明（阶段 2）：
- 原内联 httpx 实现已废弃，改为委托 NcbiClient（app.clients.real.ncbi_real）
- 保留此类与 search_by_gene API 以兼容现有调用方
- 新代码应直接使用 get_ncbi_client().fetch_clinvar_variants()

端点：https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
搜索基因关联的临床变异，按基因查询。ClinVar 路径性变异保留所有人群。
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_TIMEOUT = 30


class ClinvarClient:
    """ClinVar API 客户端 — 委托 NcbiClient（向后兼容）

    使用方法：
        client = ClinvarClient()
        variants = await client.search_by_gene(db, "IL13")

    新代码推荐：
        from app.core.deps import get_ncbi_client
        client = get_ncbi_client()
        variants = await client.fetch_clinvar_variants("IL13")
    """

    def __init__(self, base_url: str = EUTILS_BASE, timeout: int = DEFAULT_TIMEOUT):
        # 保留参数以兼容旧调用方；NcbiClient 自管理 base_url 和 timeout
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search_by_gene(
        self,
        db: Optional[Any],
        gene: str,
        *,
        db_name: str = "clinvar",
    ) -> List[Dict]:
        """按基因搜索 ClinVar 变异

        Args:
            db: 数据库会话（用于缓存）
            gene: 基因符号
            db_name: Entrez 数据库（默认 clinvar，仅向后兼容）

        Returns:
            变异列表，每条含 rsid/clnsig/gene/condition 等
        """
        # 缓存查询（保持原有缓存行为）
        if db is not None:
            try:
                from app.services.knowledge.data_cache import get_cached
                cached = await get_cached(db, "clinvar", gene)
                if cached is not None:
                    logger.info(f"ClinVar 缓存命中: {gene}")
                    return cached
            except Exception as e:
                logger.debug(f"缓存查询失败: {e}")

        # 委托给 NcbiClient
        try:
            from app.core.deps import get_ncbi_client

            ncbi_client = get_ncbi_client()
            variants = await ncbi_client.fetch_clinvar_variants(
                gene=gene,
                retmax=50,
                db_session=db,
            )
        except Exception as e:
            logger.error(f"ClinVar 查询失败（委托 NcbiClient）: {e}")
            return []

        # 转换为旧格式（保持向后兼容）
        parsed = [self._convert_to_legacy(v, gene) for v in variants]
        parsed = [v for v in parsed if v]

        # 写入缓存（5 天 TTL，与原实现一致）
        if db is not None and parsed:
            try:
                from app.services.knowledge.data_cache import set_cached
                await set_cached(db, "clinvar", gene, parsed, ttl_days=5)
            except Exception as e:
                logger.debug(f"缓存写入失败: {e}")

        return parsed

    def _convert_to_legacy(self, variant: Dict[str, Any], default_gene: str) -> Optional[Dict]:
        """将 NcbiClient 返回结构转换为旧 ClinvarClient 格式"""
        if not isinstance(variant, dict) or not variant.get("uid"):
            return None

        clnsig = variant.get("clnsig") or ""

        return {
            "rsid": "",  # 旧字段保留（NcbiClient 未提取 rsid）
            "uid": variant.get("uid"),
            "gene_symbol": variant.get("gene", default_gene),
            "clnsig": clnsig,
            "conditions": [variant.get("title", "")] if variant.get("title") else [],
            "evidence_source": "clinvar",
            "evidence_level": "I" if "pathogenic" in clnsig.lower() else "III",
            "pmid": "",
            "population": "all",
            "discovery_sample": "",
            # 新增字段（向后兼容，老调用方忽略）
            "hgvs_p": variant.get("hgvs_p"),
            "hgvs_c": variant.get("hgvs_c"),
            "variant_type": variant.get("variant_type"),
            "review_status": variant.get("review_status"),
            "title": variant.get("title"),
        }


__all__ = ["ClinvarClient", "EUTILS_BASE"]
