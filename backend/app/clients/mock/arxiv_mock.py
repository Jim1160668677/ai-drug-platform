"""Mock arXiv 客户端 — 预置计算生物学/机器学习+药物发现交叉领域预印本

arXiv 主要覆盖物理/数学/CS/定量生物学(q-bio),与 bioRxiv 互补。
"""
import asyncio
from typing import List

from app.clients.base import AcademicClientBase, AcademicPaper


ARXIV_DATABASE = {
    "EGFR": [
        AcademicPaper(
            title="Deep learning for EGFR mutation prediction from CT images",
            authors=["Wang X", "Chen Y", "Zhang L"],
            source="arxiv",
            abstract=(
                "Convolutional neural networks achieve 92% accuracy in predicting EGFR mutation "
                "status from non-invasive CT imaging in NSCLC patients."
            ),
            doi="10.48550/arxiv.2401.00001",
            year=2024,
            url="https://arxiv.org/abs/2401.00001",
            relevance_score=0.91,
        ),
        AcademicPaper(
            title="Graph neural networks for EGFR drug-target interaction prediction",
            authors=["Liu H", "Zhou T"],
            source="arxiv",
            abstract=(
                "GNN-based models outperform traditional ML methods in predicting "
                "EGFR-inhibitor binding affinities."
            ),
            doi="10.48550/arxiv.2402.00002",
            year=2024,
            url="https://arxiv.org/abs/2402.00002",
            relevance_score=0.85,
        ),
    ],
    "TP53": [
        AcademicPaper(
            title="Transformer models for TP53 mutation classification",
            authors=["Sarkar A", "Patel R"],
            source="arxiv",
            abstract=(
                "Pretrained protein language models enable zero-shot prediction of "
                "TP53 mutation pathogenicity."
            ),
            doi="10.48550/arxiv.2403.00003",
            year=2024,
            url="https://arxiv.org/abs/2403.00003",
            relevance_score=0.89,
        ),
    ],
    "KRAS": [
        AcademicPaper(
            title="Reinforcement learning for KRAS G12C drug design",
            authors=["Zhao M", "Li K"],
            source="arxiv",
            abstract=(
                "RL-based molecular generation explores novel chemical space for "
                "KRAS G12C inhibitors with improved selectivity."
            ),
            doi="10.48550/arxiv.2404.00004",
            year=2024,
            url="https://arxiv.org/abs/2404.00004",
            relevance_score=0.87,
        ),
    ],
}


class MockArxivClient(AcademicClientBase):
    """Mock arXiv 客户端

    Usage:
        client = MockArxivClient()
        papers = await client.search("EGFR", limit=5)
    """

    source_name = "arxiv"

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索预置 arXiv 文献"""
        await asyncio.sleep(0.001)

        if query in ARXIV_DATABASE:
            return ARXIV_DATABASE[query][:limit]

        q_lower = query.lower()
        all_papers: List[AcademicPaper] = []
        for papers in ARXIV_DATABASE.values():
            all_papers.extend(papers)
        matched = [
            p for p in all_papers
            if q_lower in p.title.lower() or (p.abstract and q_lower in (p.abstract or "").lower())
        ]
        return matched[:limit]
