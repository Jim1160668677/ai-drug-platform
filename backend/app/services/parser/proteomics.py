"""蛋白质组学解析器 — CSV/TSV 蛋白表达矩阵"""
import os
from typing import Any, Dict

from app.services.parser._metadata_columns import split_metadata_columns
from app.services.parser.base import Parser


class ProteomicsParser(Parser):
    """蛋白质组学 CSV/TSV 表达矩阵解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"文件不存在: {path}"}, "quality_metrics": {}}

        import pandas as pd
        import numpy as np

        try:
            df = pd.read_csv(path, sep=None, engine="python", index_col=0, nrows=10000)
        except Exception:
            try:
                df = pd.read_csv(path, index_col=0, nrows=10000)
            except Exception as e2:
                return {"summary": {"error": f"CSV 解析失败: {e2}"}, "quality_metrics": {}}

        n_proteins, n_total_cols = df.shape
        if n_total_cols == 0 or n_proteins == 0:
            # 空矩阵（仅表头/无表头）早返回 — 与 MetabolomicsParser 保持一致
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        # 拆分数据列与元数据列
        # - 字符串元数据（protein_name、group、pathway）→ select_dtypes 排除
        # - 数值型元数据（uniprot_id、mz、rt）→ 列名黑名单排除
        # 不排除会导致 n_samples 虚高、max/mean 被污染（与 MetabolomicsParser 同源问题）
        numeric_df, metadata_cols = split_metadata_columns(df)
        if numeric_df.empty:
            return {
                "summary": {"error": "无数值列可分析（CSV 可能仅含元数据）"},
                "quality_metrics": {},
            }

        # 聚合重复索引 — 相互作用/复用数据可能多次出现同一蛋白
        # 不聚合会导致 row_means.loc[idx] 返回 Series 而非标量
        if numeric_df.index.has_duplicates:
            numeric_df = numeric_df.groupby(level=0).mean()

        n_numeric_samples = numeric_df.shape[1]
        if n_numeric_samples == 0:
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        missing_rate = float(numeric_df.isna().mean().mean())
        row_means = numeric_df.mean(axis=1)
        low_abundance_ratio = float((row_means < 1.0).mean())

        all_values = numeric_df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        top_proteins = [
            {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
            for idx in row_means.nlargest(10).index
        ]

        summary = {
            "proteins": int(n_proteins),
            "samples": int(n_numeric_samples),
            "total_columns": int(n_total_cols),
            "file_format": dataset.file_format,
            "top_proteins": top_proteins,
            "top_genes": top_proteins,  # 兼容性：复用同一份数据供下游分析
            "sample_columns": list(numeric_df.columns[:20]),
            "metadata_columns": metadata_cols,
            "value_distribution": {
                "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                "min": float(np.min(finite_values)) if len(finite_values) > 0 else 0,
                "max": float(np.max(finite_values)) if len(finite_values) > 0 else 0,
            },
            "data_type": "proteomics",
        }

        quality_metrics = {
            "missing_rate": round(missing_rate, 4),
            "low_abundance_ratio": round(low_abundance_ratio, 4),
            "sample_missing_rates": {
                str(c): round(float(numeric_df[c].isna().mean()), 4)
                for c in numeric_df.columns
            },
            "parseable": True,
            "data_type": "proteomics",
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
