"""Real MyGene 客户端 — 调用 mygene.info API"""
from typing import Any, Dict

from app.clients.base import GeneClient
from app.core.config import settings


class RealGeneClient(GeneClient):
    """真实 MyGene 客户端 — 调用 https://mygene.info/v3"""

    async def query(self, gene_symbol: str) -> Dict[str, Any]:
        import httpx

        symbol = gene_symbol.strip()
        url = f"{settings.MYGENE_BASE_URL}/query"
        params = {
            "q": f"symbol:{symbol}",
            "fields": "symbol,name,entrezgene,ensembl.gene,uniprot.Swiss-Prot,summary,pathway,location,hgnc,type_of_gene,alias",
            "size": 1,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        hits = data.get("hits", [])
        if not hits:
            return {
                "symbol": symbol,
                "name": None,
                "entrez_id": None,
                "ensembl_id": None,
                "uniprot_id": None,
                "hgnc_id": None,
                "gene_type": None,
                "location": None,
                "summary": f"基因 {symbol} 在 MyGene.info 中未找到",
                "pathways": [],
                "synonyms": [],
                "drugbank_count": 0,
                "note": "not_found",
            }

        hit = hits[0]
        location = hit.get("location", {}) or {}
        pathways_raw = hit.get("pathway", []) or []
        if isinstance(pathways_raw, dict):
            pathways_raw = [pathways_raw]

        pathways = []
        for p in pathways_raw:
            pathways.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "source": "KEGG" if (p.get("id") or "").startswith("hsa") else "Reactome",
            })

        return {
            "symbol": hit.get("symbol", symbol),
            "name": hit.get("name"),
            "entrez_id": hit.get("entrezgene"),
            "ensembl_id": (hit.get("ensembl") or {}).get("gene"),
            "uniprot_id": (hit.get("uniprot") or {}).get("Swiss-Prot"),
            "hgnc_id": hit.get("hgnc"),
            "gene_type": hit.get("type_of_gene"),
            "location": location.get("start") and f"{location.get('chr')}:{location.get('start')}-{location.get('end')}",
            "summary": hit.get("summary"),
            "pathways": pathways,
            "synonyms": hit.get("alias", []) or [],
            "drugbank_count": 0,
            "source": "mygene.info",
        }
