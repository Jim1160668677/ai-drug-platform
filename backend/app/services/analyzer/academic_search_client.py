"""统一学术检索客户端 — 封装 5 个 AcademicClientBase 实现

提供单源查询 + 并行聚合查询,DOI 去重,相关性排序。
数据源: PubMed / bioRxiv / arXiv / Semantic Scholar / CrossRef
"""
import asyncio
import logging
from typing import Dict, List, Optional

from app.clients.base import AcademicPaper

logger = logging.getLogger(__name__)


class AcademicSearchClient:
    """统一学术检索客户端

    封装 5 个学术数据源客户端,提供:
    - 单源查询(search)
    - 并行聚合查询(search_all)
    - DOI 去重(deduplicate)
    - 相关性排序(sort_by_relevance)

    Usage:
        client = AcademicSearchClient()
        papers = await client.search("pubmed", "EGFR lung cancer", limit=10)
        results = await client.search_all("EGFR", ["pubmed", "arxiv"])
    """

    VALID_SOURCES = ["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"]

    _SOURCE_CLIENT_MAP = {
        "biorxiv": "app.clients.real.biorxiv_real.RealBiorxivClient",
        "arxiv": "app.clients.real.arxiv_real.RealArxivClient",
        "semantic_scholar": "app.clients.real.semantic_scholar_real.RealSemanticScholarClient",
        "crossref": "app.clients.real.crossref_real.RealCrossrefClient",
    }

    async def _get_pubmed(self):
        """懒加载 PubMed 客户端(通过依赖注入)"""
        from app.core.deps import get_ncbi_client
        return get_ncbi_client()

    async def _get_client(self, source: str):
        """根据 source 获取对应的学术客户端实例

        Args:
            source: 数据源名称
        Returns:
            对应客户端实例
        """
        if source == "pubmed":
            return await self._get_pubmed()
        module_path, class_name = self._SOURCE_CLIENT_MAP[source].rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        client_class = getattr(module, class_name)
        return client_class()

    async def search(
        self,
        source: str,
        query: str,
        limit: int = 10,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> List[AcademicPaper]:
        """单源学术检索

        Args:
            source: 数据源名称(pubmed/biorxiv/arxiv/semantic_scholar/crossref)
            query: 检索词
            limit: 最大返回数(默认 10)
            year_from: 起始年份(可选,仅部分数据源支持)
            year_to: 结束年份(可选,仅部分数据源支持)
        Returns:
            AcademicPaper 列表,超时或异常返回空列表
        Raises:
            ValueError: 无效的 source
        """
        if source not in self.VALID_SOURCES:
            raise ValueError(f"无效数据源: {source}，有效值: {self.VALID_SOURCES}")

        try:
            if source == "pubmed":
                client = await self._get_pubmed()
                raw_results = await asyncio.wait_for(
                    client.search_pubmed(query=query, retmax=limit),
                    timeout=10,
                )
                return [self._pubmed_to_paper(r) for r in raw_results]
            else:
                client = await self._get_client(source)
                return await asyncio.wait_for(
                    client.search(
                        query=query,
                        limit=limit,
                        year_from=year_from,
                        year_to=year_to,
                    ),
                    timeout=10,
                )
        except asyncio.TimeoutError:
            logger.warning(f"学术检索超时: source={source}, query={query[:60]}")
            return []
        except Exception as e:
            logger.warning(f"学术检索异常: source={source}, error={e}")
            return []

    async def search_all(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        limit_per_source: int = 10,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> Dict[str, List[AcademicPaper]]:
        """并行聚合检索 — 多数据源同时查询

        Args:
            query: 检索词
            sources: 数据源列表(默认全部 5 个)
            limit_per_source: 每个数据源最大返回数(默认 10)
            year_from: 起始年份(可选)
            year_to: 结束年份(可选)
        Returns:
            {source: [AcademicPaper, ...]} 字典
        """
        if sources is None:
            sources = self.VALID_SOURCES

        tasks = [
            self.search(source, query, limit_per_source, year_from, year_to)
            for source in sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, List[AcademicPaper]] = {}
        for source, result in zip(sources, results):
            if isinstance(result, Exception):
                logger.warning(f"数据源检索失败降级: source={source}, error={result}")
                output[source] = []
            else:
                output[source] = result
        return output

    @staticmethod
    def deduplicate(papers: List[AcademicPaper]) -> List[AcademicPaper]:
        """DOI 去重 — 保留 relevance_score 最高的版本

        Args:
            papers: AcademicPaper 列表
        Returns:
            去重后的列表(保持原始相对顺序)
        """
        seen: Dict[str, AcademicPaper] = {}
        order: List[str] = []
        for paper in papers:
            doi = paper.doi
            if not doi:
                continue
            key = doi.lower()
            if key in seen:
                existing = seen[key]
                if (
                    paper.relevance_score is not None
                    and (
                        existing.relevance_score is None
                        or paper.relevance_score > existing.relevance_score
                    )
                ):
                    seen[key] = paper
            else:
                seen[key] = paper
                order.append(key)

        doi_papers = [seen[k] for k in order]
        no_doi_papers = [p for p in papers if not p.doi]
        return doi_papers + no_doi_papers

    @staticmethod
    def sort_by_relevance(papers: List[AcademicPaper]) -> List[AcademicPaper]:
        """按相关性排序 — relevance_score 降序(None 置后),year 降序

        Args:
            papers: AcademicPaper 列表
        Returns:
            排序后的列表
        """
        return sorted(
            papers,
            key=lambda p: (
                -(p.relevance_score if p.relevance_score is not None else -1),
                -(p.year if p.year is not None else 0),
            ),
        )

    @staticmethod
    def _pubmed_to_paper(record: Dict) -> AcademicPaper:
        """将 PubMed 返回的字典转换为 AcademicPaper

        Args:
            record: PubMed esummary 返回的单条记录
        Returns:
            AcademicPaper 实例
        """
        authors = record.get("authors", []) or []
        if authors and isinstance(authors[0], dict):
            authors = [a.get("name", "") for a in authors]

        pubdate = record.get("pubdate", "") or ""
        year = None
        if pubdate and len(pubdate) >= 4:
            try:
                year = int(pubdate[:4])
            except (ValueError, TypeError):
                pass

        uid = record.get("uid", "")
        return AcademicPaper(
            title=record.get("title", ""),
            authors=authors,
            source="pubmed",
            abstract=record.get("abstract"),
            doi=record.get("doi"),
            year=year,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}" if uid else None,
            relevance_score=None,
        )
