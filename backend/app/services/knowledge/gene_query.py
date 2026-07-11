"""基因查询服务 — 基因信息 + 临床试验匹配"""
from typing import Any, Dict, List

from app.core.config import settings
from app.core.deps import get_gene_client


async def query_gene_info(gene_symbol: str) -> Dict[str, Any]:
    """查询基因详细信息（通过 GeneClient）"""
    client = get_gene_client()
    return await client.query(gene_symbol)


async def query_clinical_trials(gene_symbol: str, cancer_type: str = "") -> Dict[str, Any]:
    """匹配 ClinicalTrials.gov 临床试验

    Args:
        gene_symbol: 靶点基因符号（如 EGFR）
        cancer_type: 癌症类型（如 NSCLC、lung）

    Returns:
        {"total": int, "trials": [{nct_id, title, phase, status, condition, intervention}]}
    """
    if settings.is_mock:
        return _mock_clinical_trials(gene_symbol, cancer_type)

    return await _real_clinical_trials(gene_symbol, cancer_type)


async def _real_clinical_trials(gene_symbol: str, cancer_type: str) -> Dict[str, Any]:
    """真实 ClinicalTrials.gov API v2"""
    import httpx

    base = settings.CLINICALTRIALS_BASE_URL
    url = f"{base}/studies"
    params = {
        "query.intr": gene_symbol,
        "query.cond": cancer_type or "cancer",
        "pageSize": 25,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    trials = []
    for study in data.get("studies", []):
        proto = study.get("protocolSection", {}) or {}
        ident = proto.get("identificationModule", {}) or {}
        design = proto.get("designModule", {}) or {}
        status_mod = proto.get("statusModule", {}) or {}
        cond_mod = proto.get("conditionsModule", {}) or {}
        int_mod = proto.get("armsInterventionsModule", {}) or {}

        interventions = []
        for i in (int_mod.get("interventions") or []):
            interventions.append({
                "type": i.get("type"),
                "name": i.get("name"),
            })

        trials.append({
            "nct_id": ident.get("nctId"),
            "title": ident.get("briefTitle"),
            "phase": design.get("phases"),
            "status": status_mod.get("overallStatus"),
            "condition": cond_mod.get("conditions", []),
            "intervention": interventions,
        })

    return {
        "total": data.get("totalCount", len(trials)),
        "trials": trials,
        "source": "ClinicalTrials.gov",
    }


def _mock_clinical_trials(gene_symbol: str, cancer_type: str) -> Dict[str, Any]:
    """Mock 临床试验数据 — EGFR NSCLC 经典试验"""
    symbol_upper = gene_symbol.strip().upper()
    mock_db = {
        "EGFR": [
            {
                "nct_id": "NCT02296125",
                "title": "FLAURA: Osimertinib vs Standard EGFR-TKI in NSCLC",
                "phase": ["PHASE3"],
                "status": "COMPLETED",
                "condition": ["Non-small Cell Lung Cancer", "EGFR Mutation"],
                "intervention": [{"type": "DRUG", "name": "Osimertinib"}],
            },
            {
                "nct_id": "NCT02151981",
                "title": "AURA3: Osimertinib vs Platinum in T790M+ NSCLC",
                "phase": ["PHASE3"],
                "status": "COMPLETED",
                "condition": ["Non-small Cell Lung Cancer", "EGFR T790M"],
                "intervention": [{"type": "DRUG", "name": "Osimertinib"}],
            },
            {
                "nct_id": "NCT03710666",
                "title": "ADAURA: Osimertinib as Adjuvant Therapy in EGFR+ NSCLC",
                "phase": ["PHASE3"],
                "status": "ACTIVE_NOT_RECRUITING",
                "condition": ["Non-small Cell Lung Cancer", "EGFR Mutation", "Adjuvant"],
                "intervention": [{"type": "DRUG", "name": "Osimertinib"}],
            },
            {
                "nct_id": "NCT02411459",
                "title": "RELAY: Erlotinib + Ramucirumab in EGFR+ NSCLC",
                "phase": ["PHASE3"],
                "status": "COMPLETED",
                "condition": ["Non-small Cell Lung Cancer", "EGFR Mutation"],
                "intervention": [
                    {"type": "DRUG", "name": "Erlotinib"},
                    {"type": "DRUG", "name": "Ramucirumab"},
                ],
            },
        ],
        "B7H3": [
            {
                "nct_id": "NCT04666988",
                "title": "B7-H3-targeted CAR-T for Solid Tumors",
                "phase": ["PHASE1", "PHASE2"],
                "status": "RECRUITING",
                "condition": ["Solid Tumor", "B7-H3 Positive"],
                "intervention": [{"type": "CELLULAR_THERAPY", "name": "B7-H3 CAR-T"}],
            },
            {
                "nct_id": "NCT05293996",
                "title": "B7-H3 ADC in Pediatric Solid Tumors",
                "phase": ["PHASE1"],
                "status": "RECRUITING",
                "condition": ["Pediatric Solid Tumor", "Neuroblastoma"],
                "intervention": [{"type": "DRUG", "name": "B7-H3 Antibody-Drug Conjugate"}],
            },
        ],
        "KRAS": [
            {
                "nct_id": "NCT03600883",
                "title": "CodeBreaK100: Sotorasib in KRAS G12C NSCLC",
                "phase": ["PHASE1", "PHASE2"],
                "status": "COMPLETED",
                "condition": ["Non-small Cell Lung Cancer", "KRAS G12C"],
                "intervention": [{"type": "DRUG", "name": "Sotorasib"}],
            },
            {
                "nct_id": "NCT04933652",
                "title": "KRYSTAL-1: Adagrasib in KRAS G12C Solid Tumors",
                "phase": ["PHASE1", "PHASE2"],
                "status": "ACTIVE_NOT_RECRUITING",
                "condition": ["Non-small Cell Lung Cancer", "Colorectal Cancer", "KRAS G12C"],
                "intervention": [{"type": "DRUG", "name": "Adagrasib"}],
            },
        ],
    }

    trials = mock_db.get(symbol_upper, [])
    if cancer_type:
        cancer_lower = cancer_type.lower()
        filtered = []
        for t in trials:
            conds = " ".join(t["condition"]).lower()
            if cancer_lower in conds:
                filtered.append(t)
        trials = filtered

    return {
        "total": len(trials),
        "trials": trials,
        "source": "mock_clinical_trials.gov",
        "query": {"gene_symbol": symbol_upper, "cancer_type": cancer_type},
    }


async def batch_query_genes(gene_symbols: List[str]) -> List[Dict[str, Any]]:
    """批量查询基因信息"""
    client = get_gene_client()
    results = []
    for sym in gene_symbols:
        try:
            info = await client.query(sym)
            results.append(info)
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
    return results
