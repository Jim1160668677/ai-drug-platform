"""ChEMBL 服务 — 药物查询与重定位"""
from typing import Any, Dict, List

from app.core.deps import get_chembl_client


async def search_active_molecules(
    target_gene: str,
    activity_type: str = "IC50",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询靶点对应的已知活性分子"""
    client = get_chembl_client()
    return await client.get_active_molecules(target_gene, activity_type, limit)


async def get_approved_drugs(target_gene: str) -> List[Dict[str, Any]]:
    """查询已获批药物（药物重定位候选）"""
    client = get_chembl_client()
    return await client.find_approved_drugs(target_gene)


async def score_repurposing_candidates(
    candidates: List[Dict[str, Any]],
    cancer_type: str = "",
) -> List[Dict[str, Any]]:
    """对老药新用候选评分

    评分维度：
    - max_phase（已获批 4 > 临床 III 3 > II 2 > I 1）
    - 适应症匹配度（cancer_type 出现于 indication 加分）
    - 分子量/类药性
    """
    scored = []
    for c in candidates:
        score = 0.0
        max_phase = c.get("max_phase", 0) or 0
        score += max_phase * 25  # 最高 100

        if cancer_type and c.get("indication"):
            if cancer_type.lower() in (c.get("indication") or "").lower():
                score += 20

        mw = c.get("molecular_weight") or 500
        if 200 <= mw <= 600:
            score += 10

        c_copy = dict(c)
        c_copy["druglikeness_score"] = round(min(score, 100), 2)
        scored.append(c_copy)

    scored.sort(key=lambda x: x["druglikeness_score"], reverse=True)
    return scored
