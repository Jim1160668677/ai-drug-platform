"""Mock Semantic Scholar 客户端 — 预置高被引文献(含 citation count)

Semantic Scholar 提供影响力指标(influentialCitationCount/citationCount),
本 Mock 模拟该字段为 relevance_score(归一化到 0-1)。
"""
import asyncio
from typing import List

from app.clients.base import AcademicClientBase, AcademicPaper


SEMANTIC_SCHOLAR_DATABASE = {
    "EGFR": [
        AcademicPaper(
            title="Comprehensive molecular profiling of lung adenocarcinoma with EGFR mutations",
            authors=["Cancer Genome Atlas Research Network"],
            source="semantic_scholar",
            abstract=(
                "TCGA project reveals comprehensive genomic landscape of lung adenocarcinoma, "
                "identifying EGFR mutations in 14% of cases with therapeutic implications."
            ),
            doi="10.1038/nature13385",
            year=2014,
            url="https://www.semanticscholar.org/paper/egfr-tcga",
            relevance_score=0.98,
        ),
        AcademicPaper(
            title="Osimertinib in untreated EGFR-mutated advanced non-small-cell lung cancer",
            authors=["Soria JC", "Ohe Y", "Vansteenkiste J"],
            source="semantic_scholar",
            abstract=(
                "FLAURA trial: osimertinib significantly prolonged progression-free survival "
                "(18.9 vs 10.2 months) compared to first-generation EGFR TKIs."
            ),
            doi="10.1056/NEJMoa1713137",
            year=2018,
            url="https://www.semanticscholar.org/paper/flaura",
            relevance_score=0.96,
        ),
    ],
    "TP53": [
        AcademicPaper(
            title="TP53 mutations in human cancers: origins, consequences, and clinical use",
            authors=["Olivier M", "Hollstein M", "Hainaut P"],
            source="semantic_scholar",
            abstract=(
                "Comprehensive review of TP53 mutation patterns across 80,000 tumors in IARC TP53 database."
            ),
            doi="10.1101/cshperspect.a001008",
            year=2010,
            url="https://www.semanticscholar.org/paper/tp53-review",
            relevance_score=0.94,
        ),
    ],
    "KRAS": [
        AcademicPaper(
            title="Clinical activity of sotorasib in KRAS p.G12C-mutated non-small-cell lung cancer",
            authors=["Skoulidis F", "Li BT", "Dy GK"],
            source="semantic_scholar",
            abstract=(
                "CodeBreaK100 trial: sotorasib shows 37.1% objective response rate in KRAS G12C NSCLC."
            ),
            doi="10.1056/NEJMoa2103695",
            year=2021,
            url="https://www.semanticscholar.org/paper/sotorasib",
            relevance_score=0.95,
        ),
    ],
}


class MockSemanticScholarClient(AcademicClientBase):
    """Mock Semantic Scholar 客户端

    Usage:
        client = MockSemanticScholarClient()
        papers = await client.search("EGFR", limit=5)
    """

    source_name = "semantic_scholar"

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索预置 Semantic Scholar 文献"""
        await asyncio.sleep(0.001)

        if query in SEMANTIC_SCHOLAR_DATABASE:
            return SEMANTIC_SCHOLAR_DATABASE[query][:limit]

        q_lower = query.lower()
        all_papers: List[AcademicPaper] = []
        for papers in SEMANTIC_SCHOLAR_DATABASE.values():
            all_papers.extend(papers)
        matched = [
            p for p in all_papers
            if q_lower in p.title.lower() or (p.abstract and q_lower in (p.abstract or "").lower())
        ]
        return matched[:limit]
