"""Xenium 空间转录组解析器 — 解析 Xenium 聚类结果

输入文件格式（Sid Sijbrandij 骨肉瘤数据集 xenium/clusters.csv）：
    Barcode,Cluster
    aaaafegh-1,6
    aaaboijj-1,8

输出：
- summary: 细胞总数、聚类数、各簇细胞数分布、最大簇
- quality_metrics: 解析成功率、细胞数、聚类数
- top_genes: 兼容字段（按簇 ID 聚合，作为"特征簇"占位；真正的基因表达需 per-gene CSV）

支持单文件 CSV 解析；若 storage_path 指向目录，遍历该目录下所有 clusters CSV 合并。
"""
import csv
import os
from collections import Counter
from typing import Any, Dict, List

from app.services.parser.base import Parser


class XeniumParser(Parser):
    """Xenium 空间转录组聚类结果解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"Xenium 文件不存在: {path}"}, "quality_metrics": {}}

        # 收集待解析文件（支持目录遍历）
        files_to_parse: List[str] = []
        if os.path.isdir(path):
            for fname in sorted(os.listdir(path)):
                if fname.lower().endswith(".csv") and ("cluster" in fname.lower() or "xenium" in fname.lower()):
                    files_to_parse.append(os.path.join(path, fname))
            if not files_to_parse:
                # 目录下无 cluster CSV，退而解析所有 CSV
                for fname in sorted(os.listdir(path)):
                    if fname.lower().endswith(".csv"):
                        files_to_parse.append(os.path.join(path, fname))
        else:
            files_to_parse = [path]

        if not files_to_parse:
            return {"summary": {"error": f"目录下无可解析的 CSV: {path}"}, "quality_metrics": {}}

        total_cells = 0
        cluster_counter: Counter = Counter()
        barcodes_seen: set = set()
        files_parsed: List[str] = []
        errors: List[str] = []

        for fpath in files_to_parse:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace", newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames is None:
                        errors.append(f"{os.path.basename(fpath)}: 空文件")
                        continue
                    # 识别 Barcode / Cluster 列（兼容大小写与别名）
                    fields_lower = {fn.lower(): fn for fn in reader.fieldnames}
                    bc_col = (
                        fields_lower.get("barcode")
                        or fields_lower.get("cell_id")
                        or fields_lower.get("id")
                    )
                    cl_col = (
                        fields_lower.get("cluster")
                        or fields_lower.get("cluster_id")
                        or fields_lower.get("group")
                    )
                    if not bc_col or not cl_col:
                        errors.append(
                            f"{os.path.basename(fpath)}: 缺少 Barcode/Cluster 列，实际列={reader.fieldnames}"
                        )
                        continue
                    n_in_file = 0
                    for row in reader:
                        bc = (row.get(bc_col) or "").strip()
                        cl_raw = (row.get(cl_col) or "").strip()
                        if not bc or not cl_raw:
                            continue
                        # 去重 barcode（跨文件合并时避免重复计数）
                        if bc in barcodes_seen:
                            continue
                        barcodes_seen.add(bc)
                        try:
                            cluster_id = int(cl_raw)
                        except ValueError:
                            cluster_id = cl_raw  # 非数字簇标签保留原值
                        cluster_counter[cluster_id] += 1
                        total_cells += 1
                        n_in_file += 1
                    files_parsed.append(f"{os.path.basename(fpath)}({n_in_file} cells)")
            except Exception as e:
                errors.append(f"{os.path.basename(fpath)}: {type(e).__name__}: {e}")

        if total_cells == 0:
            return {
                "summary": {
                    "data_type": "xenium",
                    "error": "未解析到任何细胞，请检查文件格式",
                    "files_checked": [os.path.basename(f) for f in files_to_parse],
                    "errors": errors,
                },
                "quality_metrics": {"parseable": False, "data_type": "xenium"},
            }

        n_clusters = len(cluster_counter)
        # 各簇细胞数分布，按簇 ID 排序
        cluster_distribution = {
            str(k): cluster_counter[k] for k in sorted(cluster_counter.keys(), key=lambda x: (isinstance(x, str), x))
        }
        max_cluster = max(cluster_counter.items(), key=lambda x: x[1])

        # top_genes 兼容字段：Xenium clusters.csv 仅含细胞→簇映射，无基因表达
        # 以"各簇代表"形式占位，标注数据来源限制
        top_genes = [
            {"symbol": f"Cluster_{k}", "mean_abundance": float(v), "n_cells": v}
            for k, v in sorted(cluster_counter.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        summary = {
            "data_type": "xenium",
            "file_format": os.path.splitext(files_to_parse[0])[1].lstrip("."),
            "files_parsed": files_parsed,
            "total_cells": total_cells,
            "n_clusters": n_clusters,
            "cluster_distribution": cluster_distribution,
            "largest_cluster": {"cluster_id": max_cluster[0], "n_cells": max_cluster[1]},
            "top_genes": top_genes,
            "note": (
                f"Xenium 空间转录组：{total_cells} 个细胞分布到 {n_clusters} 个簇。"
                f"clusters.csv 仅含细胞→簇映射，基因级表达需 per-gene counts 矩阵。"
            ),
        }
        if errors:
            summary["warnings"] = errors

        quality_metrics = {
            "parseable": True,
            "data_type": "xenium",
            "total_cells": total_cells,
            "n_clusters": n_clusters,
            "largest_cluster_fraction": round(max_cluster[1] / total_cells, 4),
            "n_files_parsed": len(files_parsed),
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
