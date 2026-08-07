"""Mock CrossRef 客户端 — 预置已发表论文(含 DOI 元数据)

CrossRef 覆盖正式发表的期刊文章,与 bioRxiv/arXiv(预印本)互补。
"""
import asyncio
from typing import List

from app.clients.base import AcademicClientBase, AcademicPaper


CROSSREF_DATABASE = {
    "EGFR": [
        AcademicPaper(
            title="Activating mutations in the epidermal growth factor receptor underlying responsiveness of non-small-cell lung cancer to gefitinib",
            authors=["Lynch TJ", "Bell DW", "Sordella R"],
            source="crossref",
            abstract=(
                "EGFR mutations are associated with gefitinib sensitivity in NSCLC. "
                "Patients with these mutations have distinct clinical characteristics."
            ),
            doi="10.1056/NEJMoa040938",
            year=2004,
            url="http://dx.doi.org/10.1056/NEJMoa040938",
            relevance_score=0.97,
        ),
        AcademicPaper(
            title="EGFR T790M mutation as a mechanism of acquired resistance to gefitinib",
            authors=["Kobayashi S", "Boggon TJ", "Dayaram T"],
            source="crossref",
            abstract=(
                "Secondary EGFR T790M mutation confers resistance to gefitinib/erlotinib "
                "in approximately 50% of NSCLC cases."
            ),
            doi="10.1056/NEJMoa040938",
            year=2005,
            url="http://dx.doi.org/10.1056/NEJMoa040938",
            relevance_score=0.93,
        ),
    ],
    "TP53": [
        AcademicPaper(
            title="Wild-type p53 reactivation by small molecules: clinical implications",
            authors=["Bykov VJN", "Eriksson SE", "Bianchi J", "Wiman KG"],
            source="crossref",
            abstract=(
                "APR-246 (eprenetapopt) reactivates mutant p53 and shows clinical activity "
                "in combination with azacitidine in TP53-mutant MDS."
            ),
            doi="10.1038/s41568-018-0040-5",
            year=2018,
            url="http://dx.doi.org/10.1038/s41568-018-0040-5",
            relevance_score=0.92,
        ),
    ],
    "KRAS": [
        AcademicPaper(
            title="Targeting KRAS G12C: from undruggable to druggable",
            authors=["Papke B", "Der CJ"],
            source="crossref",
            abstract=(
                "Covalent inhibitors of KRAS G12C represent a breakthrough in targeting "
                "previously undruggable RAS mutants."
            ),
            doi="10.1038/nrc.2017.79",
            year=2017,
            url="http://dx.doi.org/10.1038/nrc.2017.79",
            relevance_score=0.94,
        ),
    ],
}


class MockCrossrefClient(AcademicClientBase):
    """Mock CrossRef 客户端

    Usage:
        client = MockCrossrefClient()
        papers = await client.search("EGFR", limit=5)
    """

    source_name = "crossref"

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索预置 CrossRef 文献"""
        await asyncio.sleep(0.001)

        if query in CROSSREF_DATABASE:
            return CROSSREF_DATABASE[query][:limit]

        q_lower = query.lower()
        all_papers: List[AcademicPaper] = []
        for papers in CROSSREF_DATABASE.values():
            all_papers.extend(papers)
        matched = [
            p for p in all_papers
            if q_lower in p.title.lower() or (p.abstract and q_lower in (p.abstract or "").lower())
        ]
        return matched[:limit]
