"""变异注释服务 — 通过 VariantClient 注释变异"""
from typing import Any, Dict, List

from app.core.deps import get_variant_client


async def annotate_variant(variant: str) -> Dict[str, Any]:
    """注释单个变异"""
    client = get_variant_client()
    results = await client.query_batch([variant])
    return results[0] if results else {"query": variant, "error": "无注释结果"}


async def batch_annotate(variants: List[str]) -> List[Dict[str, Any]]:
    """批量变异注释"""
    client = get_variant_client()
    return await client.query_batch(variants)


async def filter_pathogenic(variants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从变异列表中筛选致病性变异"""
    pathogenic_keywords = ["pathogenic", "likely_pathogenic"]
    result = []
    for v in variants:
        clinvar = v.get("clinvar") or {}
        clnsig = (clinvar.get("clnsig") or "").lower()
        if any(k in clnsig for k in pathogenic_keywords):
            result.append(v)
    return result


async def get_drug_resistance_variants(variants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """识别耐药相关变异（基于 ClinVar condition 字段）"""
    result = []
    drug_keywords = ["drug response", "resistance", "drug resistance"]
    for v in variants:
        clinvar = v.get("clinvar") or {}
        condition = (clinvar.get("condition") or "").lower()
        if any(k in condition for k in drug_keywords):
            result.append(v)
    return result
