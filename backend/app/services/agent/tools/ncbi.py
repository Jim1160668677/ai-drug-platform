"""NCBI 检索工具组 — 1 个工具

工具列表：
- search_ncbi              NCBI 数据库检索（PubMed/ClinVar/Gene/Protein）
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


class SearchNcbiTool(AgentTool):
    """NCBI 数据库检索 — 调用 NcbiClient

    支持的数据库：
    - pubmed:       文献检索
    - clinvar:      致病变异查询
    - gene:         基因信息查询
    - protein:      FASTA 蛋白序列
    - nucleotide:   FASTA 核酸序列
    """

    name = "search_ncbi"
    description = (
        "检索 NCBI 数据库获取权威生物医学数据。"
        "支持 PubMed 文献、ClinVar 致病变异、Gene 基因信息、Protein/Nucleotide FASTA 序列。"
        "返回结构化结果，含 PMID/HGVS/基因 symbol/序列等。"
    )
    parameters = [
        ToolParameter(
            "db",
            "string",
            "NCBI 数据库",
            required=True,
            enum=["pubmed", "clinvar", "gene", "protein", "nucleotide"],
        ),
        ToolParameter("query", "string", "检索词或基因符号", required=True),
        ToolParameter(
            "retmax",
            "integer",
            "最大返回数（1-50）",
            required=False,
            default=5,
        ),
        ToolParameter(
            "rettype",
            "string",
            "返回类型（仅 protein/nucleotide：fasta/abstract）",
            required=False,
            default="abstract",
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.core.deps import get_ncbi_client

        db = params["db"]
        query = params["query"]
        retmax = min(max(params.get("retmax", 5), 1), 50)
        rettype = params.get("rettype", "abstract")

        try:
            client = get_ncbi_client()

            # 根据 db 分发到对应的高层封装方法
            if db == "pubmed":
                from app.services.analyzer.academic_search_client import AcademicSearchClient

                papers = await AcademicSearchClient().search("pubmed", query=query, limit=retmax)
                results = [
                    {
                        "title": p.title,
                        "authors": p.authors,
                        "abstract": p.abstract,
                        "doi": p.doi,
                        "source": p.source,
                        "year": p.year,
                        "url": p.url,
                    }
                    for p in papers
                ]
                return ToolResult.ok(
                    data={
                        "db": db,
                        "query": query,
                        "total": len(results),
                        "articles": results,
                    },
                    display={
                        "type": "literature_list",
                        "payload": {"articles": results[:retmax]},
                    },
                )

            elif db == "clinvar":
                # query 视为基因符号
                variants = await client.fetch_clinvar_variants(
                    gene=query,
                    retmax=retmax,
                    db_session=ctx.db,
                )
                return ToolResult.ok(
                    data={
                        "db": db,
                        "gene": query,
                        "total": len(variants),
                        "variants": variants,
                    },
                    display={
                        "type": "variant_list",
                        "payload": {"variants": variants[:retmax]},
                    },
                )

            elif db == "gene":
                gene_info = await client.fetch_gene_info(
                    gene_symbol=query,
                    db_session=ctx.db,
                )
                return ToolResult.ok(
                    data={
                        "db": db,
                        "gene_symbol": query,
                        "gene_info": gene_info,
                    },
                    display={
                        "type": "gene_info",
                        "payload": gene_info,
                    },
                )

            elif db in ("protein", "nucleotide"):
                # query 视为 accession 列表（逗号分隔）
                ids = [s.strip() for s in query.split(",") if s.strip()]
                if not ids:
                    return ToolResult.fail(error="protein/nucleotide 查询需提供 accession ID 列表")
                fasta = await client.fetch_sequences(
                    ids=ids,
                    db=db,
                    db_session=ctx.db,
                )
                return ToolResult.ok(
                    data={
                        "db": db,
                        "ids": ids,
                        "fasta": fasta,
                        "length": len(fasta),
                    },
                    display={
                        "type": "sequence",
                        "payload": {"fasta": fasta[:2000]},
                    },
                )

            else:
                return ToolResult.fail(error=f"不支持的数据库: {db}")

        except Exception as e:
            logger.error(f"search_ncbi 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
