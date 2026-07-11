"""Real MyVariant 客户端 — 调用 myvariant.info API"""
from typing import Any, Dict, List

from app.clients.base import VariantClient
from app.core.config import settings


class RealVariantClient(VariantClient):
    """真实 MyVariant 客户端 — 调用 https://myvariant.info/v1"""

    async def query_batch(self, variants: List[str]) -> List[Dict[str, Any]]:
        import httpx

        if not variants:
            return []

        url = f"{settings.MYVARIANT_BASE_URL}/variant"
        ids = ",".join(v.strip() for v in variants)
        params = {
            "ids": ids,
            "fields": "clinvar,cosmic,dbsnp,gnomad_genome,gene,hgvs.p,hgvs.c,ann",
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        if not isinstance(data, list):
            data = [data]

        for v in data:
            query = v.get("query") or v.get("_id", "")
            clinvar = v.get("clinvar") or {}
            cosmic = v.get("cosmic") or {}
            dbsnp = v.get("dbsnp") or {}
            gnomad = v.get("gnomad_genome") or {}
            ann = v.get("ann") or {}

            results.append({
                "query": query,
                "gene": v.get("gene") or ann.get("gene"),
                "hgvs_p": (v.get("hgvs") or {}).get("p") or ann.get("hgvs_p"),
                "hgvs_c": (v.get("hgvs") or {}).get("c") or ann.get("hgvs_c"),
                "clinvar": {
                    "clnsig": clinvar.get("clnsig") or clinvar.get("clinical_significance"),
                    "clinvar_id": clinvar.get("clinvar_id") or clinvar.get("rcv"),
                    "rcv": clinvar.get("rcv"),
                    "review_status": clinvar.get("review_status"),
                    "condition": clinvar.get("clndn"),
                    "last_evaluated": clinvar.get("last_evaluated"),
                } if clinvar else None,
                "cosmic": {
                    "cosmic_id": cosmic.get("cosmic_id"),
                    "cancer_type": cosmic.get("primary_site"),
                    "tumor_site": cosmic.get("tumor_site"),
                    "mutation_description": cosmic.get("mutation_description"),
                    "occurrence_count": cosmic.get("occurrence_count"),
                } if cosmic else None,
                "dbsnp": {
                    "rsid": dbsnp.get("rsid") or dbsnp.get("rs"),
                    "merged_into": dbsnp.get("merged_into"),
                } if dbsnp else None,
                "gnomad": {
                    "af": gnomad.get("af") or gnomad.get("afes"),
                    "ac": gnomad.get("ac"),
                    "an": gnomad.get("an"),
                    "populations": {
                        "afr": gnomad.get("afes_afr"),
                        "amr": gnomad.get("afes_amr"),
                        "eas": gnomad.get("afes_eas"),
                        "eur": gnomad.get("afes_nfe"),
                    },
                } if gnomad else None,
                "functional_consequence": ann.get("consequence") or v.get("cadd", {}).get("consequence"),
                "clinical_significance": (clinvar or {}).get("clnsig"),
                "source": "myvariant.info",
            })

        return results
