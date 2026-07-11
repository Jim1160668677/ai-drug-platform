"""知识库端点 — 基因/变异/药物查询"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_gene_client, get_variant_client, get_chembl_client
from app.db.session import get_db
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
