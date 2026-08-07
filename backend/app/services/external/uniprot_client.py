"""UniProt 蛋白序列查询客户端

通过 UniProt REST API（https://rest.uniprot.org）按基因符号查询
canonical 蛋白氨基酸序列，用于蛋白结构预测时自动填充序列。

主要接口：
- fetch_canonical_sequence(gene_symbol, organism=9606) -> {uniprot_id, sequence, ...}

UniProt API 文档: https://www.uniprot.org/help/api
"""
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

UNIPROT_REST_URL = "https://rest.uniprot.org/uniprotkb/search"
ORGANISM_HUMAN = 9606


async def fetch_canonical_sequence(
    gene_symbol: str,
    organism: int = ORGANISM_HUMAN,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """根据基因符号从 UniProt 查询 canonical 蛋白序列

    Args:
        gene_symbol: 基因符号，如 EGFR、B7H3、KRAS
        organism: 物种 NCBI Taxonomy ID，默认 9606（人）
        timeout: 超时秒数
    Returns:
        {
            "uniprot_id": "P00533",
            "gene_symbol": "EGFR",
            "protein_name": "Epidermal growth factor receptor",
            "sequence": "MRPSGTAGAALLALLAALCPASRALEEK...",
            "sequence_length": 1210,
            "organism": 9606,
            "source": "uniprot",
        }
        失败时返回 {"source": "error", "error": "..."}
    """
    if not gene_symbol:
        return {"source": "error", "error": "基因符号不能为空"}

    gene_symbol = gene_symbol.strip().upper()
    # UniProt 查询语法：gene_exact:"EGFR" AND organism_id:9606
    query = f'gene_exact:"{gene_symbol}" AND organism_id:{organism}'

    params = {
        "query": query,
        "fields": "accession,id,gene_names,protein_name,sequence,length",
        "format": "json",
        "size": 1,  # 只取第一个结果（canonical）
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(UNIPROT_REST_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.warning(f"UniProt 查询失败 gene={gene_symbol}: {e}")
        return {"source": "error", "error": f"UniProt 网络查询失败: {e}"}
    except Exception as e:
        logger.warning(f"UniProt 解析失败 gene={gene_symbol}: {e}")
        return {"source": "error", "error": f"UniProt 解析失败: {e}"}

    results = data.get("results") or []
    if not results:
        # 退化为宽松匹配（gene_names 而非 gene_exact）
        try:
            params["query"] = f'gene:"{gene_symbol}" AND organism_id:{organism}'
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(UNIPROT_REST_URL, params=params)
                response.raise_for_status()
                data = response.json()
            results = data.get("results") or []
        except Exception as e:
            logger.warning(f"UniProt 宽松查询失败 gene={gene_symbol}: {e}")

    if not results:
        return {
            "source": "error",
            "error": f"未在 UniProt 找到基因 {gene_symbol}（organism={organism}）的蛋白序列",
        }

    entry = results[0]
    uniprot_id = entry.get("primaryAccession", "")
    # 蛋白序列在 sequence.value 字段
    sequence_obj = entry.get("sequence") or {}
    sequence = sequence_obj.get("value", "") or ""
    length = sequence_obj.get("length", len(sequence))

    # 蛋白全名
    protein_name = ""
    desc = entry.get("proteinDescription") or {}
    if desc.get("recommendedName"):
        protein_name = desc["recommendedName"].get("fullName", {}).get("value", "")
    elif desc.get("submissionNames"):
        protein_name = desc["submissionNames"][0].get("fullName", {}).get("value", "")

    return {
        "uniprot_id": uniprot_id,
        "gene_symbol": gene_symbol,
        "protein_name": protein_name,
        "sequence": sequence,
        "sequence_length": length,
        "organism": organism,
        "source": "uniprot",
    }
