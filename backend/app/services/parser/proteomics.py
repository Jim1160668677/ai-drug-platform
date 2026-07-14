"""蛋白质组学解析器 — CSV/TSV 蛋白表达矩阵"""
import os
from typing import Any, Dict

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

        n_proteins, n_samples = df.shape
        if n_samples == 0 or n_proteins == 0:
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        missing_rate = float(df.isna().mean().mean())
        row_means = df.mean(axis=1)
        low_abundance_ratio = float((row_means < 1.0).mean())

        all_values = df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        top_proteins = [
            {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
            for idx in row_means.nlargest(10).index
        ]

        summary = {
            "proteins": int(n_proteins),
            "samples": int(n_samples),
            "file_format": dataset.file_format,
            "top_proteins": top_proteins,
            "top_genes": top_proteins,  # 兼容性：复用同一份数据供下游分析
            "sample_columns": list(df.columns[:20]),
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
                str(c): round(float(df[c].isna().mean()), 4) for c in df.columns
            },
            "data_type": "proteomics",
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
