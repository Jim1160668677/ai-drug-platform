"""学术检索工具组 — 1 个工具

工具列表：
- search_academic        跨学术数据库检索文献（PubMed/bioRxiv/arXiv/Semantic Scholar/CrossRef）
"""
import logging
from typing import Any, Dict

from app.core.security import UserRole
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


class SearchAcademicTool(AgentTool):
    """跨学术数据库检索 — 调用 AcademicSearchClient

    支持的数据源：
    - pubmed:            PubMed 文献检索
    - biorxiv:           bioRxiv 预印本
    - arxiv:             arXiv 预印本
    - semantic_scholar:  Semantic Scholar 学术搜索
    - crossref:          CrossRef 元数据检索
    """

    name = "search_academic"
    description = (
        "跨学术数据库检索文献。支持 PubMed、bioRxiv、arXiv、Semantic Scholar、CrossRef。"
        "返回标题/作者/摘要/DOI/发表日期/来源/相关性分数。"
    )
    parameters = [
        ToolParameter("query", "string", "检索词(如 EGFR lung cancer)", required=True),
        ToolParameter(
            "source",
            "string",
            "数据源",
            required=True,
            enum=["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"],
        ),
        ToolParameter("limit", "integer", "返回数(1-50)", required=False, default=10),
        ToolParameter("year_from", "integer", "起始年份", required=False),
        ToolParameter("year_to", "integer", "截止年份", required=False),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.academic_search_client import AcademicSearchClient

        client = AcademicSearchClient()
        query = params["query"]
        source = params["source"]
        limit = min(max(params.get("limit", 10), 1), 50)
        year_from = params.get("year_from")
        year_to = params.get("year_to")

        try:
            papers = await client.search(source, query, limit, year_from, year_to)
            return ToolResult.ok(
                data={
                    "source": source,
                    "query": query,
                    "total": len(papers),
                    "articles": [
                        {
                            "title": p.title,
                            "authors": p.authors,
                            "abstract": p.abstract,
                            "doi": p.doi,
                            "source": p.source,
                            "year": p.year,
                            "url": p.url,
                            "relevance_score": p.relevance_score,
                        }
                        for p in papers
                    ],
                },
                display={
                    "type": "literature_list",
                    "payload": {
                        "articles": [
                            {
                                "title": p.title,
                                "authors": p.authors,
                                "doi": p.doi,
                                "source": p.source,
                            }
                            for p in papers[:limit]
                        ]
                    },
                },
            )
        except Exception as e:
            logger.error(f"search_academic failed: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
