"""Mock MyVariant 客户端 — 预置 EGFR T790M/L858R/Exon19del 等 ClinVar 注释"""
import asyncio
from typing import Any, Dict, List

from app.clients.base import VariantClient


VARIANT_DATABASE: Dict[str, Dict[str, Any]] = {
    "chr7:55259515:T>A": {
        "query": "chr7:55259515:T>A",
        "gene": "EGFR",
        "hgvs_p": "p.Thr790Met",
        "hgvs_c": "c.2369C>T",
        "clinvar": {
            "clnsig": "Pathogenic",
            "clinvar_id": "VCV000033373",
            "rcv": "RCV000029669",
            "review_status": "reviewed by expert panel",
            "condition": "Drug response to tyrosine kinase inhibitor",
            "last_evaluated": "2024-01-15",
        },
        "cosmic": {
            "cosmic_id": "COSM6224",
            "cancer_type": "NSCLC",
            "tumor_site": "lung",
            "mutation_description": "EGFR T790M, resistance to first-generation TKI",
            "occurrence_count": 1823,
        },
        "dbsnp": {
            "rsid": "rs121434564",
            "merged_into": None,
        },
        "gnomad": {
            "af": 0.00002,
            "ac": 5,
            "an": 251492,
            "populations": {
                "afr": 0.0,
                "amr": 0.0,
                "eas": 0.0001,
                "eur": 0.00001,
            },
        },
        "functional_consequence": "missense_variant",
        "clinical_significance": (
            "EGFR T790M 是一代/二代 EGFR-TKI 耐药的主要机制（约 50-60% 耐药患者），"
            "对三代 TKI（Osimertinib）敏感。"
        ),
    },
    "chr7:55259513:G>A": {
        "query": "chr7:55259513:G>A",
        "gene": "EGFR",
        "hgvs_p": "p.Leu858Arg",
        "hgvs_c": "c.2573T>G",
        "clinvar": {
            "clnsig": "Pathogenic",
            "clinvar_id": "VCV000033372",
            "rcv": "RCV000029668",
            "review_status": "reviewed by expert panel",
            "condition": "Non-small cell lung cancer",
            "last_evaluated": "2024-01-15",
        },
        "cosmic": {
            "cosmic_id": "COSM6223",
            "cancer_type": "NSCLC",
            "tumor_site": "lung",
            "mutation_description": "EGFR L858R, activating mutation",
            "occurrence_count": 4271,
        },
        "dbsnp": {
            "rsid": "rs121434569",
            "merged_into": None,
        },
        "gnomad": {
            "af": 0.00003,
            "ac": 8,
            "an": 251492,
            "populations": {
                "afr": 0.0,
                "amr": 0.0,
                "eas": 0.0002,
                "eur": 0.00001,
            },
        },
        "functional_consequence": "missense_variant",
        "clinical_significance": (
            "EGFR L858R 是外显子 21 最常见的激活突变，对 EGFR-TKI 敏感。"
            "一线推荐 Osimertinib（FLAURA 试验）。"
        ),
    },
    "chr7:55242471:del": {
        "query": "chr7:55242471:del",
        "gene": "EGFR",
        "hgvs_p": "p.Glu746_Ala750del",
        "hgvs_c": "c.2235_2249del15",
        "clinvar": {
            "clnsig": "Pathogenic",
            "clinvar_id": "VCV000033371",
            "rcv": "RCV000029667",
            "review_status": "reviewed by expert panel",
            "condition": "Non-small cell lung cancer",
            "last_evaluated": "2024-01-15",
        },
        "cosmic": {
            "cosmic_id": "COSM6222",
            "cancer_type": "NSCLC",
            "tumor_site": "lung",
            "mutation_description": "EGFR exon 19 deletion, activating mutation",
            "occurrence_count": 5892,
        },
        "dbsnp": {
            "rsid": "rs121913229",
            "merged_into": None,
        },
        "gnomad": {
            "af": 0.00004,
            "ac": 10,
            "an": 251492,
            "populations": {
                "afr": 0.0,
                "amr": 0.0,
                "eas": 0.0003,
                "eur": 0.00001,
            },
        },
        "functional_consequence": "inframe_deletion",
        "clinical_significance": (
            "EGFR 外显子 19 缺失（E746-A750del）是最常见的激活突变（占 EGFR 突变 45%），"
            "对 TKI 敏感。一线推荐 Osimertinib。"
        ),
    },
    "chr12:25245350:G>A": {
        "query": "chr12:25245350:G>A",
        "gene": "KRAS",
        "hgvs_p": "p.Gly12Cys",
        "hgvs_c": "c.34G>T",
        "clinvar": {
            "clnsig": "Pathogenic",
            "clinvar_id": "VCV000039520",
            "rcv": "RCV000038791",
            "review_status": "reviewed by expert panel",
            "condition": "Non-small cell lung cancer",
            "last_evaluated": "2023-11-20",
        },
        "cosmic": {
            "cosmic_id": "COSM516535",
            "cancer_type": "NSCLC",
            "tumor_site": "lung",
            "mutation_description": "KRAS G12C, activating mutation",
            "occurrence_count": 3214,
        },
        "dbsnp": {
            "rsid": "rs121913529",
            "merged_into": None,
        },
        "gnomad": {
            "af": 0.00006,
            "ac": 15,
            "an": 251492,
            "populations": {
                "afr": 0.00001,
                "amr": 0.0,
                "eas": 0.0,
                "eur": 0.00008,
            },
        },
        "functional_consequence": "missense_variant",
        "clinical_significance": (
            "KRAS G12C 是 NSCLC 中最常见的 KRAS 突变（~14%），"
            "对 Sotorasib 和 Adagrasib（G12C 共价抑制剂）敏感。"
        ),
    },
}


class MockVariantClient(VariantClient):
    """Mock MyVariant 客户端 — 返回预置 ClinVar/COSMIC/gnomAD 注释"""

    async def query_batch(self, variants: List[str]) -> List[dict]:
        await asyncio.sleep(0.25)
        results = []
        for v in variants:
            v_stripped = v.strip()
            if v_stripped in VARIANT_DATABASE:
                results.append(dict(VARIANT_DATABASE[v_stripped]))
            else:
                results.append({
                    "query": v_stripped,
                    "gene": None,
                    "hgvs_p": None,
                    "hgvs_c": None,
                    "clinvar": None,
                    "cosmic": None,
                    "dbsnp": None,
                    "gnomad": None,
                    "functional_consequence": "unknown",
                    "clinical_significance": (
                        f"变异 {v_stripped} 在 Mock 数据库中无注释。"
                        "配置 USE_MOCK=false 并接入 MyVariant.info 真实 API 后将获得完整注释。"
                    ),
                    "note": "mock_placeholder",
                })
        return results
