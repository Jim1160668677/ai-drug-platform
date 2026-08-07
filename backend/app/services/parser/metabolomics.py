"""代谢组学解析器 — CSV/TSV 代谢物丰度矩阵

修复历史 bug：
- 误将 pubchem_cid / mz / rt 等元数据列当作样本列，导致样本数错误和无意义排序
- 修复后按丰度排序得到 Glutamine/Succinate/Glucose/Pyruvate/Lactate 等符合
  肿瘤 Warburg 效应的核心代谢物
"""
import os
from typing import Any, Dict

from app.services.parser._metadata_columns import split_metadata_columns
from app.services.parser.base import Parser


class MetabolomicsParser(Parser):
    """代谢组学 CSV/TSV 丰度矩阵解析器"""

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

        # 分离元数据列（pubchem_cid/mz/rt/compound_name 等）与样本数据列
        # 历史 bug：未过滤元数据列导致 pubchem_cid 被当作样本，样本数错误，排序无意义
        data_df, metadata_df = split_metadata_columns(df)
        n_metabolites, n_samples = data_df.shape
        if n_samples == 0 or n_metabolites == 0:
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        missing_rate = float(data_df.isna().mean().mean())
        row_means = data_df.mean(axis=1)
        low_abundance_ratio = float((row_means < 1.0).mean())

        all_values = data_df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        # 按丰度降序排列，得到 Glucose / Lactate / Pyruvate 等核心代谢物
        top_metabolites = [
            {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
            for idx in row_means.nlargest(10).index
        ]

        summary = {
            "metabolites": int(n_metabolites),
            "samples": int(n_samples),
            "file_format": dataset.file_format,
            "top_metabolites": top_metabolites,
            "top_genes": top_metabolites,  # 兼容性：复用同一份数据供下游分析
            "sample_columns": list(data_df.columns[:20]),
            "metadata_columns": list(metadata_df.columns) if not metadata_df.empty else [],
            "value_distribution": {
                "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                "min": float(np.min(finite_values)) if len(finite_values) > 0 else 0,
                "max": float(np.max(finite_values)) if len(finite_values) > 0 else 0,
            },
            "data_type": "metabolomics",
        }

        quality_metrics = {
            "missing_rate": missing_rate,
            "low_abundance_ratio": low_abundance_ratio,
            "sample_missing_rates": {
                str(col): float(data_df[col].isna().mean())
                for col in data_df.columns
            },
            "data_type": "metabolomics",
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
