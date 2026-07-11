"""Real ChEMBL 客户端 — 调用 ebi.ac.uk/chembl API"""
from typing import Any, Dict, List

from app.clients.base import ChemblClient
from app.core.config import settings


class RealChemblClient(ChemblClient):
    """真实 ChEMBL 客户端 — 调用 https://www.ebi.ac.uk/chembl/api/data"""

    async def _find_target_chembl_id(self, gene_symbol: str) -> str:
        import httpx

        url = f"{settings.CHEMBL_BASE_URL}/target/search.json"
        params = {"q": gene_symbol, "target_type": "SINGLE PROTEIN", "limit": 5}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        targets = data.get("targets", [])
        for t in targets:
            pref = (t.get("pref_name") or "").upper()
            if gene_symbol.upper() in pref or gene_symbol.upper() == pref:
                return t.get("target_chembl_id")
        return targets[0].get("target_chembl_id") if targets else None

    async def get_active_molecules(
        self, target_gene: str, activity_type: str = "IC50", limit: int = 50
    ) -> List[Dict[str, Any]]:
        import httpx

        target_chembl_id = await self._find_target_chembl_id(target_gene)
        if not target_chembl_id:
            return []

        url = f"{settings.CHEMBL_BASE_URL}/activity.json"
        params = {
            "target_chembl_id": target_chembl_id,
            "activity_type": activity_type,
            "limit": min(limit, 100),
            "standard_units": "nM",
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        activities = data.get("activities", [])
        result = []
        for a in activities:
            molecule_chembl_id = a.get("molecule_chembl_id")
            result.append({
                "name": a.get("molecule_pref_name") or molecule_chembl_id,
                "chembl_id": molecule_chembl_id,
                "smiles": None,
                "max_phase": a.get("max_phase", 0),
                "indication": None,
                "activity": {
                    "activity_type": a.get("activity_type"),
                    "activity_value": a.get("standard_value"),
                    "activity_units": a.get("standard_units"),
                    "assay_type": a.get("assay_type"),
                    "assay_description": a.get("assay_description"),
                },
                "molecular_weight": None,
                "logp": None,
                "first_approval": None,
                "drug_indication": [],
                "target_gene": target_gene,
                "target_chembl_id": target_chembl_id,
            })
        return result

    async def find_approved_drugs(self, target_gene: str) -> List[Dict[str, Any]]:
        import httpx

        target_chembl_id = await self._find_target_chembl_id(target_gene)
        if not target_chembl_id:
            return []

        url = f"{settings.CHEMBL_BASE_URL}/drug_indication.json"
        params = {"target_chembl_id": target_chembl_id, "max_phase": 4, "limit": 50}
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        indications = data.get("drug_indications", [])
        approved = []
        for di in indications:
            approved.append({
                "name": di.get("molecule_chembl_id"),
                "chembl_id": di.get("molecule_chembl_id"),
                "smiles": None,
                "max_phase": di.get("max_phase_for_ind", 4),
                "indication": di.get("mesh_heading") or di.get("efo_term"),
                "first_approval": None,
                "molecular_weight": None,
                "drug_indication": [di.get("mesh_heading")],
                "target_gene": target_gene,
                "target_chembl_id": target_chembl_id,
            })
        return approved
