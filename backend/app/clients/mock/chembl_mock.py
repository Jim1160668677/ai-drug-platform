"""Mock ChEMBL 客户端 — 预置 EGFR 靶点对应分子（Osimertinib/Gefitinib/Erlotinib/Afatinib）"""
import asyncio
from typing import Any, Dict, List

from app.clients.base import ChemblClient


MOLECULE_DATABASE: Dict[str, List[Dict[str, Any]]] = {
    "EGFR": [
        {
            "name": "Osimertinib",
            "chembl_id": "CHEMBL3353080",
            "smiles": "COC1=CC(N(CCN(C)C)C2=CC=C(NC(=O)C=C)C(NC3=CC4=CC=CC=C4N3)=C2)=CC=C1NC(=O)C=C",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer with EGFR T790M mutation",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 12.0,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "EGFR (T790M/L858R) inhibitory activity",
            },
            "molecular_weight": 499.62,
            "logp": 3.95,
            "first_approval": 2017,
            "drug_indication": ["Non-small cell lung cancer", "EGFR T790M mutation NSCLC"],
        },
        {
            "name": "Gefitinib",
            "chembl_id": "CHEMBL937",
            "smiles": "COC1=C(OCCCN2CCOCC2)C=CC(NC3=CC=C(F)C(Cl)=C3NC4=CC=NC=C4)=C1",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer with EGFR activating mutation",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 34.0,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "EGFR wild-type inhibitory activity",
            },
            "molecular_weight": 446.91,
            "logp": 4.15,
            "first_approval": 2003,
            "drug_indication": ["Non-small cell lung cancer"],
        },
        {
            "name": "Erlotinib",
            "chembl_id": "CHEMBL85",
            "smiles": "COCCOC1=C(OCCOC)C=CC(NC2=CC=CC(NC(=O)C=C)=C2)=C1C#C",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer, pancreatic cancer",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 2.0,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "EGFR kinase inhibitory activity",
            },
            "molecular_weight": 393.44,
            "logp": 2.75,
            "first_approval": 2004,
            "drug_indication": ["Non-small cell lung cancer", "Pancreatic cancer"],
        },
        {
            "name": "Afatinib",
            "chembl_id": "CHEMBL1173655",
            "smiles": "CN(C)C/C=C/C(=O)NC1=CC(Cl)=CC(N/C=C/C(=O)NCC2=CC=C(F)C(F)=C2)=C1OC3=CC=NC=C3",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer with EGFR exon 19 deletion or L858R",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 0.5,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "EGFR WT and T790M inhibitory activity",
            },
            "molecular_weight": 485.94,
            "logp": 4.32,
            "first_approval": 2013,
            "drug_indication": ["Non-small cell lung cancer", "Squamous cell carcinoma of head and neck"],
        },
    ],
    "KRAS": [
        {
            "name": "Sotorasib",
            "chembl_id": "CHEMBL4297660",
            "smiles": "CC1=NC2=CC=C(C=C2N1)C3=CC=CN=C3N4CCNCC4",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer with KRAS G12C mutation",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 89.0,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "KRAS G12C covalent inhibition",
            },
            "molecular_weight": 439.53,
            "logp": 2.85,
            "first_approval": 2021,
            "drug_indication": ["Non-small cell lung cancer", "KRAS G12C mutation solid tumor"],
        },
        {
            "name": "Adagrasib",
            "chembl_id": "CHEMBL4298058",
            "smiles": "C[C@@H]1CN(C(=O)/C=C/C2=CC=C(N3CCN(C)CC3)C=C2)C[C@@H]1C#N",
            "max_phase": 4,
            "indication": "Non-small cell lung cancer with KRAS G12C mutation",
            "activity": {
                "activity_type": "IC50",
                "activity_value": 12.0,
                "activity_units": "nM",
                "assay_type": "B",
                "assay_description": "KRAS G12C covalent inhibition",
            },
            "molecular_weight": 604.7,
            "logp": 3.45,
            "first_approval": 2022,
            "drug_indication": ["Non-small cell lung cancer", "KRAS G12C mutation solid tumor"],
        },
    ],
}


class MockChemblClient(ChemblClient):
    """Mock ChEMBL 客户端 — 返回预置分子活性与已获批药物数据"""

    async def get_active_molecules(
        self, target_gene: str, activity_type: str = "IC50", limit: int = 50
    ) -> List[dict]:
        await asyncio.sleep(0.3)
        gene_upper = target_gene.strip().upper()
        molecules = MOLECULE_DATABASE.get(gene_upper, [])

        result = []
        for m in molecules[:limit]:
            molecule = dict(m)
            if activity_type and molecule.get("activity", {}).get("activity_type") != activity_type:
                continue
            molecule["target_gene"] = gene_upper
            result.append(molecule)
        return result

    async def find_approved_drugs(self, target_gene: str) -> List[dict]:
        await asyncio.sleep(0.25)
        gene_upper = target_gene.strip().upper()
        molecules = MOLECULE_DATABASE.get(gene_upper, [])

        approved = []
        for m in molecules:
            if m.get("max_phase", 0) >= 4:
                drug = {
                    "name": m["name"],
                    "chembl_id": m["chembl_id"],
                    "smiles": m["smiles"],
                    "max_phase": m["max_phase"],
                    "indication": m["indication"],
                    "first_approval": m.get("first_approval"),
                    "molecular_weight": m.get("molecular_weight"),
                    "drug_indication": m.get("drug_indication", []),
                    "target_gene": gene_upper,
                }
                approved.append(drug)
        return approved
