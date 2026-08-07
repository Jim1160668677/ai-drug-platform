"""知识库端点 — 基因/变异/药物查询"""
import time
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_gene_client, get_variant_client, get_chembl_client
from app.db.session import get_db
from app.models.reasoning_trace import ReasoningTrace
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import success_response

router = APIRouter()


class GeneQuery(BaseModel):
    gene_symbol: str  # 如 EGFR, B7H3, FAP


class VariantQuery(BaseModel):
    variants: List[str]  # 如 ["chr7:55259515:T>A"]


class ChemblQuery(BaseModel):
    target_gene: str
    activity_type: str = "IC50"
    limit: int = 50


@router.post("/gene", response_model=StandardResponse, summary="基因查询（MyGene.info）")
async def query_gene(
    payload: GeneQuery,
    current_user: User = Depends(get_current_user),
):
    """查询基因信息 — 集成 NCBI/Ensembl/UniProt 等 30+ 数据源"""
    client = get_gene_client()
    result = await client.query(payload.gene_symbol)
    return success_response(result)


@router.post("/variant", response_model=StandardResponse, summary="变异注释（MyVariant.info）")
async def query_variants(
    payload: VariantQuery,
    current_user: User = Depends(get_current_user),
):
    """批量变异注释 — ClinVar/COSMIC/dbSNP/gnomAD 一次搞定"""
    client = get_variant_client()
    result = await client.query_batch(payload.variants)
    return success_response(result)


@router.post("/chembl/activity", response_model=StandardResponse, summary="ChEMBL 活性分子查询")
async def query_activity(
    payload: ChemblQuery,
    current_user: User = Depends(get_current_user),
):
    """查询靶点对应的已知活性分子"""
    client = get_chembl_client()
    result = await client.get_active_molecules(payload.target_gene, payload.activity_type, payload.limit)
    return success_response(result)


@router.post("/chembl/approved", response_model=StandardResponse, summary="ChEMBL 已获批药物查询")
async def query_approved_drugs(
    target_gene: str,
    current_user: User = Depends(get_current_user),
):
    """药物重定位：查找已获批药物"""
    client = get_chembl_client()
    result = await client.find_approved_drugs(target_gene)
    return success_response(result)


@router.post("/clinical-trials", response_model=StandardResponse, summary="临床试验匹配")
async def match_clinical_trials(
    gene_symbol: str,
    cancer_type: str = "",
    current_user: User = Depends(get_current_user),
):
    """ClinicalTrials.gov 试验匹配"""
    from app.services.knowledge.gene_query import query_clinical_trials
    result = await query_clinical_trials(gene_symbol, cancer_type)
    return success_response(result)


# ========== Phase B7: Co-Scientist 知识库集成 ==========


class CoscientistSearchQuery(BaseModel):
    """Co-Scientist 知识库搜索查询"""
    query: str  # 自然语言查询
    top_k: int = 5  # 返回前 K 个结果（1-50）
    scope: str = "all"  # all / hypotheses / runs


@router.post("/coscientist/search", response_model=StandardResponse, summary="搜索 Co-Scientist 知识库")
async def search_coscientist_knowledge(
    payload: CoscientistSearchQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """搜索已索引的 Co-Scientist 假设和运行

    支持按自然语言查询相似的研究假设和历史运行记录。
    搜索范围：hypotheses（仅假设）/ runs（仅运行）/ all（两者）
    """
    from app.services.knowledge.coscientist_indexer import CoScientistIndexer

    try:
        indexer = CoScientistIndexer(db)
        top_k = min(max(payload.top_k, 1), 50)

        if payload.scope == "hypotheses":
            results = await indexer.search_hypotheses(payload.query, top_k=top_k)
            data = {"hypotheses": results, "runs": [], "total": len(results)}
        elif payload.scope == "runs":
            results = await indexer.search_runs(payload.query, top_k=top_k)
            data = {"hypotheses": [], "runs": results, "total": len(results)}
        else:
            data = await indexer.search_all(payload.query, top_k=top_k)
            data["total"] = len(data["hypotheses"]) + len(data["runs"])

        return success_response(data)
    except Exception as e:
        return StandardResponse(
            success=False,
            message=f"知识库搜索失败: {str(e)}",
            data={"error": str(e)},
        )


@router.post("/coscientist/index/{run_id}", response_model=StandardResponse, summary="索引 Co-Scientist 运行")
async def index_coscientist_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动索引 Co-Scientist 运行结果到知识库

    将运行的假设和运行摘要索引到向量存储，支持后续相似度检索。
    索引操作幂等，重复索引同一运行不会产生重复文档。
    """
    from app.services.knowledge.coscientist_indexer import CoScientistIndexer

    try:
        indexer = CoScientistIndexer(db)
        result = await indexer.index_run(run_id)
        return success_response(result)
    except Exception as e:
        return StandardResponse(
            success=False,
            message=f"索引失败: {str(e)}",
            data={"run_id": str(run_id), "error": str(e)},
        )


@router.get("/coscientist/stats", response_model=StandardResponse, summary="Co-Scientist 知识库统计")
async def coscientist_knowledge_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Co-Scientist 知识库索引统计

    返回集合信息、向量存储可用性等。
    """
    from app.services.knowledge.coscientist_indexer import CoScientistIndexer

    indexer = CoScientistIndexer(db)
    stats = await indexer.get_stats()
    return success_response(stats)


class AcademicSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    sources: List[str] = Field(default=["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"])
    limit_per_source: int = Field(default=10, ge=1, le=50)
    year_from: Optional[int] = Field(default=None, ge=1900, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1900, le=2100)
    deduplicate: bool = True


class AcademicSearchResponse(BaseModel):
    query: str
    sources_queried: List[str]
    total_hits: Dict[str, int]
    papers: List[dict]
    search_time_ms: int


@router.post("/academic-search", response_model=StandardResponse, summary="学术资源聚合检索(5源并行)")
async def academic_search(payload: AcademicSearchRequest, current_user: User = Depends(get_current_user)):
    from app.services.analyzer.academic_search_client import AcademicSearchClient

    t0 = time.time()
    client = AcademicSearchClient()
    raw = await client.search_all(payload.query, payload.sources, payload.limit_per_source,
                                 payload.year_from, payload.year_to)
    papers = [p for plist in raw.values() for p in plist]
    total_hits = {src: len(plist) for src, plist in raw.items()}
    if payload.deduplicate:
        papers = client.deduplicate(papers)
    papers = AcademicSearchClient.sort_by_relevance(papers)
    elapsed = int((time.time() - t0) * 1000)
    return success_response(AcademicSearchResponse(
        query=payload.query, sources_queried=payload.sources, total_hits=total_hits,
        papers=[p.model_dump() for p in papers], search_time_ms=elapsed
    ).model_dump())


class AcademicSearchReexecuteRequest(BaseModel):
    session_id: UUID
    original_step_id: Optional[UUID] = None
    query: Optional[str] = Field(default=None, min_length=1, max_length=500)
    sources: List[str] = Field(default=["pubmed", "biorxiv", "arxiv", "semantic_scholar", "crossref"])
    add_sources: Optional[List[str]] = None
    limit_per_source: int = Field(default=10, ge=1, le=50)
    year_from: Optional[int] = Field(default=None, ge=1900, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1900, le=2100)
    deduplicate: bool = True


class AcademicSearchReexecuteResponse(BaseModel):
    step_id: str
    parent_step_id: Optional[str]
    query: str
    sources_queried: List[str]
    total_hits: Dict[str, int]
    papers: List[dict]
    search_time_ms: int


@router.post("/academic-search/reexecute", response_model=StandardResponse, summary="重执行学术检索(创建新追溯步骤)")
async def academic_search_reexecute(
    payload: AcademicSearchReexecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重执行学术检索 — 用修改后的参数重新检索,创建新的不可变追溯步骤

    原始步骤保持不变,新步骤通过 parent_step_id 链接到原始步骤,
    形成检索演进链。每个步骤的 evidence 数据独立存储。
    """
    from app.services.analyzer.academic_search_client import AcademicSearchClient

    parent_step_id = payload.original_step_id
    parent = None

    if parent_step_id:
        parent = await db.get(ReasoningTrace, parent_step_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"原始追溯步骤不存在: {parent_step_id}")

    query = payload.query
    if query is None and parent is not None:
        query = parent.input_data.get("query", "")

    sources = payload.sources
    if parent is not None:
        parent_sources = parent.input_data.get("sources", [])
        if payload.add_sources:
            sources = list(set(parent_sources + payload.add_sources))
        else:
            sources = parent_sources

    t0 = time.time()
    client = AcademicSearchClient()
    raw = await client.search_all(query, sources, payload.limit_per_source,
                                 payload.year_from, payload.year_to)
    papers = [p for plist in raw.values() for p in plist]
    total_hits = {src: len(plist) for src, plist in raw.items()}
    if payload.deduplicate:
        papers = client.deduplicate(papers)
    papers = AcademicSearchClient.sort_by_relevance(papers)
    elapsed = int((time.time() - t0) * 1000)

    new_step = ReasoningTrace(
        session_id=payload.session_id,
        parent_step_id=parent_step_id,
        step_type="tool_call",
        input_data={
            "query": query,
            "sources": sources,
            "year_from": payload.year_from,
            "year_to": payload.year_to,
            "reexecute": True,
        },
        output_data={
            "total_hits": total_hits,
            "papers": [p.model_dump() for p in papers],
        },
        status="completed",
    )
    db.add(new_step)
    await db.commit()
    await db.refresh(new_step)

    return success_response(AcademicSearchReexecuteResponse(
        step_id=str(new_step.id),
        parent_step_id=str(parent_step_id) if parent_step_id else None,
        query=query,
        sources_queried=sources,
        total_hits=total_hits,
        papers=[p.model_dump() for p in papers],
        search_time_ms=elapsed,
    ).model_dump())
