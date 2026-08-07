"""新抗原表位解析器 — 解析新抗原预测结果（HLA/肽段/IC50）

输入文件格式（Sid Sijbrandij 骨肉瘤数据集 neoantigen/*.tsv，制表符分隔）：
列含 ID / Index / Gene / AA Change / Best Peptide / Allele / IC50 MT / IC50 WT /
     RNA Expr / DNA VAF / Tier / Ref Match / Evaluation

支持两种文件：
1. all_epitopes.aggregated.tsv — 聚合表位（每行一个突变的最优肽段）
2. all_epitopes.tsv — 逐肽段表位（更大，每个突变多肽段）

支持两种格式：
- Vaxrank/自定义格式（列含 Gene/Peptide/Allele/IC50 MT/Tier/Evaluation）
- pVACseq 格式（99 列，列含 Gene Name/MT Epitope Seq/HLA Allele/Best MT IC50 Score/HGVSp 等）

输出：
- summary: 表位数、命中基因数、HLA 等位型分布、Tier 分布、Top 高亲和力肽段
- quality_metrics: 解析成功率、结合肽段数（IC50<500nM）、高亲和力比例
- top_genes: 突变基因列表（按表位数排序，供下游靶点发现兼容）
"""
import os
from collections import Counter
from typing import Any, Dict, List

from app.services.parser.base import Parser


# IC50 阈值（nM）— 新抗原结合亲和力分级
IC50_STRONG = 50      # <50nM 强结合
IC50_WEAK = 500       # <500nM 弱结合（仍为候选）


# 列名别名表（小写匹配）— 兼容 Vaxrank / pVACseq / 自定义格式
# 顺序：从最常见到次常见，第一个匹配的列名胜出
_COLUMN_ALIASES = {
    "gene": ["gene", "gene name", "gene_name", "gene symbol", "symbol"],
    "peptide": ["best peptide", "peptide", "mt epitope seq", "mt_epitope_seq",
                "epitope", "mutant peptide", "mt peptide"],
    "allele": ["allele", "hla", "hla allele", "hla_allele"],
    "ic50_mt": ["ic50 mt", "ic50_mt", "best mt ic50 score", "best_mt_ic50_score",
                "mt ic50", "mt_ic50"],
    "ic50_wt": ["ic50 wt", "ic50_wt", "corresponding wt ic50 score",
                "corresponding_wt_ic50_score", "wt ic50", "wt_ic50"],
    "aa_change": ["aa change", "aa_change", "hgvsp", "hgvs_p", "protein change",
                  "protein_change", "mutation"],
    "tier": ["tier", "tier class", "tier_class"],
    "evaluation": ["evaluation", "eval", "result", "status"],
    "rna_expr": ["rna expr", "rna_expr", "gene expression", "gene_expression",
                 "transcript expression", "transcript_expression", "tpm", "rpkm"],
    "dna_vaf": ["dna vaf", "dna_vaf", "tumor dna vaf", "tumor_dna_vaf", "vaf"],
    "percentile": ["best mt percentile", "best_mt_percentile", "mt percentile",
                   "mt_percentile", "percentile rank", "percentile_rank"],
}


def _safe_float(val) -> float:
    """安全转 float，NA/None/空 → nan"""
    if val is None:
        return float("nan")
    s = str(val).strip()
    if not s or s.lower() in ("na", "nan", "none", "null"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _resolve_column(cols_lower: Dict[str, str], field: str) -> str:
    """从已小写的列名映射中按别名表查找实际列名"""
    for alias in _COLUMN_ALIASES.get(field, []):
        if alias in cols_lower:
            return cols_lower[alias]
    return ""


def _infer_tier(ic50_mt: float) -> str:
    """根据 IC50 MT 推断 Tier（pVACseq 无 Tier 列时使用）

    Tier 1: IC50 < 50nM（强结合）
    Tier 2: 50 ≤ IC50 < 500nM（弱结合）
    Tier 3: 500 ≤ IC50 < 5000nM（候选）
    Tier 4: IC50 ≥ 5000nM（不结合）
    """
    if ic50_mt != ic50_mt:  # nan
        return "NoTier"
    if ic50_mt < IC50_STRONG:
        return "Tier 1"
    if ic50_mt < IC50_WEAK:
        return "Tier 2"
    if ic50_mt < 5000:
        return "Tier 3"
    return "Tier 4"


class NeoantigenParser(Parser):
    """新抗原表位预测结果解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"新抗原文件不存在: {path}"}, "quality_metrics": {}}

        # 支持目录（遍历 .tsv）或单文件
        files_to_parse: List[str] = []
        if os.path.isdir(path):
            for fname in sorted(os.listdir(path)):
                if fname.lower().endswith(".tsv") and "epitope" in fname.lower():
                    files_to_parse.append(os.path.join(path, fname))
        else:
            files_to_parse = [path]

        if not files_to_parse:
            return {"summary": {"error": f"未找到新抗原 TSV 文件: {path}"}, "quality_metrics": {}}

        import pandas as pd

        all_epitopes: List[Dict[str, Any]] = []
        files_parsed: List[str] = []
        errors: List[str] = []

        for fpath in files_to_parse:
            try:
                df = pd.read_csv(fpath, sep="\t", dtype=str, keep_default_na=False, na_values=["NA"])
                # 列名归一化（小写匹配）
                cols_lower = {c.lower(): c for c in df.columns}
                gene_col = _resolve_column(cols_lower, "gene")
                peptide_col = _resolve_column(cols_lower, "peptide")
                allele_col = _resolve_column(cols_lower, "allele")
                ic50_mt_col = _resolve_column(cols_lower, "ic50_mt")
                ic50_wt_col = _resolve_column(cols_lower, "ic50_wt")
                aa_change_col = _resolve_column(cols_lower, "aa_change")
                tier_col = _resolve_column(cols_lower, "tier")
                eval_col = _resolve_column(cols_lower, "evaluation")
                rna_expr_col = _resolve_column(cols_lower, "rna_expr")
                dna_vaf_col = _resolve_column(cols_lower, "dna_vaf")
                percentile_col = _resolve_column(cols_lower, "percentile")
                n_rows = len(df)
                for _, row in df.iterrows():
                    gene = str(row.get(gene_col, "")).strip() if gene_col else ""
                    peptide = str(row.get(peptide_col, "")).strip() if peptide_col else ""
                    allele = str(row.get(allele_col, "")).strip() if allele_col else ""
                    ic50_mt = _safe_float(row.get(ic50_mt_col) if ic50_mt_col else None)
                    ic50_wt = _safe_float(row.get(ic50_wt_col) if ic50_wt_col else None)
                    aa_change = str(row.get(aa_change_col, "")).strip() if aa_change_col else ""
                    tier = str(row.get(tier_col, "")).strip() if tier_col else ""
                    evaluation = str(row.get(eval_col, "")).strip() if eval_col else ""
                    rna_expr = _safe_float(row.get(rna_expr_col) if rna_expr_col else None)
                    dna_vaf = _safe_float(row.get(dna_vaf_col) if dna_vaf_col else None)
                    percentile = _safe_float(row.get(percentile_col) if percentile_col else None)

                    # 跳过无肽段或无基因的空行
                    if not peptide and not gene:
                        continue

                    # pVACseq 无 Tier 列时根据 IC50 推断
                    if not tier:
                        tier = _infer_tier(ic50_mt)

                    all_epitopes.append({
                        "gene": gene,
                        "peptide": peptide,
                        "allele": allele,
                        "ic50_mt": ic50_mt if ic50_mt == ic50_mt else None,  # nan → None
                        "ic50_wt": ic50_wt if ic50_wt == ic50_wt else None,
                        "aa_change": aa_change,
                        "tier": tier,
                        "evaluation": evaluation,
                        "rna_expr": rna_expr if rna_expr == rna_expr else None,
                        "dna_vaf": dna_vaf if dna_vaf == dna_vaf else None,
                        "percentile": percentile if percentile == percentile else None,
                    })
                files_parsed.append(f"{os.path.basename(fpath)}({n_rows} rows)")
            except Exception as e:
                errors.append(f"{os.path.basename(fpath)}: {type(e).__name__}: {e}")

        if not all_epitopes:
            return {
                "summary": {
                    "data_type": "neoantigen",
                    "error": "未解析到任何表位，请检查文件格式",
                    "files_checked": [os.path.basename(f) for f in files_to_parse],
                    "errors": errors,
                },
                "quality_metrics": {"parseable": False, "data_type": "neoantigen"},
            }

        total_epitopes = len(all_epitopes)

        # 命中基因
        gene_counter: Counter = Counter()
        for e in all_epitopes:
            g = e["gene"]
            if g and g.lower() not in ("nan", "none", ""):
                gene_counter[g] += 1
        hit_genes = dict(gene_counter.most_common())

        # HLA 等位型分布
        allele_counter: Counter = Counter()
        for e in all_epitopes:
            a = e["allele"]
            if a and a.lower() not in ("nan", "none", ""):
                allele_counter[a] += 1
        hla_distribution = dict(allele_counter.most_common())

        # Tier 分布
        tier_counter: Counter = Counter()
        for e in all_epitopes:
            t = e["tier"]
            if t:
                tier_counter[t] += 1
        tier_distribution = dict(tier_counter.most_common())

        # 结合亲和力分级（基于 IC50 MT）
        binding_epitopes = [e for e in all_epitopes if e["ic50_mt"] is not None and e["ic50_mt"] < IC50_WEAK]
        strong_binders = [e for e in all_epitopes if e["ic50_mt"] is not None and e["ic50_mt"] < IC50_STRONG]
        # 评估通过（Pass/Accept）的表位
        passing = [e for e in all_epitopes if e["evaluation"].lower() in ("pass", "accept", "accepted")]

        # Top 高亲和力肽段（IC50 MT 升序，取前 20）
        ranked = sorted(
            [e for e in all_epitopes if e["ic50_mt"] is not None],
            key=lambda x: x["ic50_mt"],
        )[:20]
        top_peptides = [
            {
                "gene": e["gene"],
                "peptide": e["peptide"],
                "allele": e["allele"],
                "ic50_mt": e["ic50_mt"],
                "aa_change": e["aa_change"],
                "tier": e["tier"],
            }
            for e in ranked
        ]

        # top_genes 兼容字段（突变基因，供下游靶点发现）
        top_genes = [
            {"symbol": g, "mean_abundance": float(c), "n_epitopes": c}
            for g, c in gene_counter.most_common(20)
        ]

        summary = {
            "data_type": "neoantigen",
            "file_format": os.path.splitext(files_to_parse[0])[1].lstrip("."),
            "files_parsed": files_parsed,
            "total_epitopes": total_epitopes,
            "hit_genes_count": len(hit_genes),
            "hit_genes": hit_genes,
            "hla_allele_distribution": hla_distribution,
            "tier_distribution": tier_distribution,
            "binding_epitopes_count": len(binding_epitopes),
            "strong_binder_count": len(strong_binders),
            "passing_evaluation_count": len(passing),
            "top_peptides": top_peptides,
            "top_genes": top_genes,
            "note": (
                f"解析 {total_epitopes} 个新抗原表位，命中 {len(hit_genes)} 个突变基因，"
                f"{len(binding_epitopes)} 个结合肽段（IC50<{IC50_WEAK}nM），"
                f"{len(strong_binders)} 个强结合（IC50<{IC50_STRONG}nM）。"
            ),
        }
        if errors:
            summary["warnings"] = errors

        quality_metrics = {
            "parseable": True,
            "data_type": "neoantigen",
            "total_epitopes": total_epitopes,
            "binding_rate": round(len(binding_epitopes) / max(1, total_epitopes), 4),
            "strong_binder_rate": round(len(strong_binders) / max(1, total_epitopes), 4),
            "n_files_parsed": len(files_parsed),
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
