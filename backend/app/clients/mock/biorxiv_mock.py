"""Mock bioRxiv 客户端 — 预置 EGFR/TP53/KRAS 等核心基因的预印本文献

用于测试环境(USE_MOCK=true),无需真实 bioRxiv API 调用。
数据风格与 PUBMED_DATABASE 对齐,source 字段标注为 'biorxiv'。
"""
import asyncio
from typing import List

from app.clients.base import AcademicClientBase, AcademicPaper


# 预置 bioRxiv 预印本文献(按 query 关键词索引)
BIORXIV_DATABASE = {
    "EGFR": [
        AcademicPaper(
            title="EGFR mutation dynamics in non-small cell lung cancer preprint",
            authors=["Lynch T", "Bell D", "Sordella R"],
            source="biorxiv",
            abstract=(
                "EGFR mutations are found in 10-15% of NSCLC patients. "
                "This preprint characterizes exon 19 deletions and L858R mutations "
                "conferring sensitivity to EGFR TKIs."
            ),
            doi="10.1101/2024.01.00001",
            year=2024,
            url="https://www.biorxiv.org/content/10.1101/2024.01.00001v1",
            relevance_score=0.95,
        ),
        AcademicPaper(
            title="Structural basis of EGFR T790M resistance to osimertinib",
            authors=["Wu SG", "Shih JY"],
            source="biorxiv",
            abstract=(
                "Cryo-EM structures of EGFR T790M mutant reveal allosteric resistance "
                "mechanisms to third-generation TKIs."
            ),
            doi="10.1101/2024.02.00002",
            year=2024,
            url="https://www.biorxiv.org/content/10.1101/2024.02.00002v1",
            relevance_score=0.88,
        ),
    ],
    "TP53": [
        AcademicPaper(
            title="TP53 reactivation by small molecules: a preprint study",
            authors=["Bykov VJN", "Wiman KG"],
            source="biorxiv",
            abstract=(
                "Reactivation of mutant p53 by APR-246 shows tumor regression in mouse models. "
                "Mechanism involves covalent modification of cysteine residues."
            ),
            doi="10.1101/2024.03.00003",
            year=2024,
            url="https://www.biorxiv.org/content/10.1101/2024.03.00003v1",
            relevance_score=0.92,
        ),
    ],
    "KRAS": [
        AcademicPaper(
            title="KRAS G12C inhibitors: preprint of clinical candidate evaluation",
            authors=["Ostrem JM", "Shokat KM"],
            source="biorxiv",
            abstract=(
                "Covalent KRAS G12C inhibitors demonstrate selective targeting of "
                "previously undruggable KRAS mutations."
            ),
            doi="10.1101/2024.04.00004",
            year=2024,
            url="https://www.biorxiv.org/content/10.1101/2024.04.00004v1",
            relevance_score=0.90,
        ),
    ],
}


class MockBiorxivClient(AcademicClientBase):
    """Mock bioRxiv 客户端

    Usage:
        client = MockBiorxivClient()
        papers = await client.search("EGFR", limit=5)
    """

    source_name = "biorxiv"

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索预置 bioRxiv 文献

        匹配策略:精确命中关键词 -> 模糊匹配标题/摘要
        """
        # 模拟网络延迟(测试可选)
        await asyncio.sleep(0.001)

        # 1. 精确命中(EGFR/TP53/KRAS)
        if query in BIORXIV_DATABASE:
            return BIORXIV_DATABASE[query][:limit]

        # 2. 模糊匹配:query 出现在标题或摘要中
        q_lower = query.lower()
        all_papers: List[AcademicPaper] = []
        for papers in BIORXIV_DATABASE.values():
            all_papers.extend(papers)
        matched = [
            p for p in all_papers
            if q_lower in p.title.lower() or (p.abstract and q_lower in (p.abstract or "").lower())
        ]
        return matched[:limit]
