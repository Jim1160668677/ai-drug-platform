"""CNV 段解析器 — 解析 CNVkit genemetrics / Tempus annotated_cnv segments

输出 cnv_segments 字段供 TargetIdentifier._compute_confidence 直接消费：
[{"gene": "CDK4", "type": "amplification", "copy_number": 8, "chrom": "12", ...}]

支持两种常见格式：
1. Tempus annotated_cnv_v2.segments.csv — 列: chrom,start,stop,amplification,major_copy_number,minor_copy_number
2. CNVkit genemetrics.tsv — 列: gene,chromosome,start,end,log2,cn,...
"""
import os
from typing import Any, Dict, List

from app.services.parser.base import Parser


class CnvParser(Parser):
    """CNV 段解析器 — 提取基因级拷贝数变异并标准化为 cnv_segments"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"CNV 文件不存在: {path}"}, "quality_metrics": {}}

        import pandas as pd

        try:
            # 自动识别分隔符（CSV 或 TSV）
            if path.lower().endswith(".csv"):
                df = pd.read_csv(path)
            elif path.lower().endswith(".tsv"):
                df = pd.read_csv(path, sep="\t")
            else:
                # 探测：看第一行是否含逗号
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    first_line = f.readline()
                sep = "," if "," in first_line and "\t" not in first_line else "\t"
                df = pd.read_csv(path, sep=sep)
        except Exception as e:
            return {"summary": {"error": f"CNV 解析失败: {e}"}, "quality_metrics": {}}

        columns_lower = {c.lower(): c for c in df.columns}
        n_total = len(df)

        # 识别格式
        is_tempus = "amplification" in columns_lower and "major_copy_number" in columns_lower
        is_cnvkit = "gene" in columns_lower and "log2" in columns_lower

        cnv_segments: List[Dict[str, Any]] = []

        if is_tempus:
            # Tempus annotated_cnv_v2.segments.csv
            for _, row in df.iterrows():
                amp_type = str(row.get("amplification", "")).lower()
                # gain / loss / neutral
                if amp_type not in ("gain", "loss", "neutral", "amp", "del", "loh"):
                    continue
                if amp_type == "neutral":
                    continue
                major_cn = int(row.get("major_copy_number") or 0)
                minor_cn = int(row.get("minor_copy_number") or 0)
                total_cn = major_cn + minor_cn
                # 标准化类型字段（与 TargetIdentifier._compute_confidence 兼容）
                std_type = "amplification" if amp_type in ("gain", "amp") else (
                    "loss" if amp_type in ("loss", "del") else "loh"
                )
                cnv_segments.append({
                    "gene": None,  # Tempus segments 通常不含基因名（基因在另一个文件）
                    "chrom": str(row.get("chrom")),
                    "start": int(row.get("start") or 0),
                    "end": int(row.get("stop") or row.get("end") or 0),
                    "type": std_type,
                    "cnv_type": std_type,
                    "copy_number": total_cn,
                    "major_copy_number": major_cn,
                    "minor_copy_number": minor_cn,
                    "source": "tempus_annotated_cnv",
                })

        elif is_cnvkit:
            # CNVkit genemetrics.tsv — 含 gene 列
            for _, row in df.iterrows():
                gene = str(row.get("gene") or "").strip()
                if not gene or gene == "nan":
                    continue
                log2_val = float(row.get("log2") or 0)
                # log2 > 0.5 → 扩增，< -0.5 → 缺失（CNVkit 经验阈值）
                if log2_val > 0.5:
                    std_type = "amplification"
                    # 估算 copy_number：log2(CN/2) → CN = 2 * 2^log2
                    estimated_cn = int(round(2 * (2 ** log2_val)))
                elif log2_val < -0.5:
                    std_type = "loss"
                    estimated_cn = max(0, int(round(2 * (2 ** log2_val))))
                else:
                    continue  # 中性段跳过
                cnv_segments.append({
                    "gene": gene,
                    "chrom": str(row.get("chromosome") or row.get("chrom") or ""),
                    "start": int(row.get("start") or 0),
                    "end": int(row.get("end") or 0),
                    "type": std_type,
                    "cnv_type": std_type,
                    "copy_number": estimated_cn,
                    "log2": log2_val,
                    "source": "cnvkit_genemetrics",
                })

        # 统计
        amplification_count = sum(1 for s in cnv_segments if s["type"] == "amplification")
        loss_count = sum(1 for s in cnv_segments if s["type"] == "loss")
        loh_count = sum(1 for s in cnv_segments if s["type"] == "loh")

        # 按染色体统计
        chrom_dist: Dict[str, int] = {}
        for s in cnv_segments:
            chrom_dist[s["chrom"]] = chrom_dist.get(s["chrom"], 0) + 1

        # 提取已识别基因（仅 cnvkit 格式有 gene 字段）
        gene_cnv_map: Dict[str, Dict[str, Any]] = {}
        for s in cnv_segments:
            if s.get("gene"):
                gene_cnv_map[s["gene"]] = {
                    "type": s["type"],
                    "copy_number": s["copy_number"],
                    "log2": s.get("log2"),
                    "chrom": s["chrom"],
                    "start": s["start"],
                    "end": s["end"],
                }

        summary = {
            "data_type": "cnv",
            "file_format": os.path.splitext(path)[1].lstrip("."),
            "format_source": "tempus" if is_tempus else ("cnvkit" if is_cnvkit else "unknown"),
            "total_segments": n_total,
            "cnv_segments": cnv_segments[:200],  # 限制 200 条避免超大 summary
            "total_cnv_calls": len(cnv_segments),
            "amplification_count": amplification_count,
            "loss_count": loss_count,
            "loh_count": loh_count,
            "chromosome_distribution": chrom_dist,
            "gene_cnv": gene_cnv_map,  # 基因 → CNV 信息（仅 cnvkit 格式）
            "gene_cnv_count": len(gene_cnv_map),
            "note": (
                f"解析 {n_total} 个 CNV 段，识别 "
                f"{amplification_count} 扩增 / {loss_count} 缺失 / {loh_count} LOH"
            ),
        }

        quality_metrics = {
            "parseable": True,
            "data_type": "cnv",
            "total_cnv_calls": len(cnv_segments),
            "amplification_rate": round(amplification_count / max(1, len(cnv_segments)), 4),
            "loss_rate": round(loss_count / max(1, len(cnv_segments)), 4),
            "has_gene_annotations": len(gene_cnv_map) > 0,
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
