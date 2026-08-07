"""个人基因组解读模块 — 服务包

子模块：
- coordinate: 坐标转换与基因型匹配
- trait_search: 性状位点检索（本地 + 外部数据源）
- genotype_matcher: 基因型匹配
- risk_scorer: 多基因风险评分（PRS）
- recommendation_engine: 生活建议生成
- kb_expander: LLM 解读与知识库扩充
"""
from app.services.genome import (
    genotype_matcher,
    kb_expander,
    recommendation_engine,
    risk_scorer,
    trait_search,
)

__all__ = [
    "genotype_matcher",
    "kb_expander",
    "recommendation_engine",
    "risk_scorer",
    "trait_search",
]
