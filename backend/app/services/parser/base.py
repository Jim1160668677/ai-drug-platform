"""解析器基类与工厂 — 根据 data_type 路由到具体 parser"""
from abc import ABC, abstractmethod
from typing import Any, Dict

from app.models.dataset import DataType


class Parser(ABC):
    """解析器抽象基类 — 所有具体 parser 必须实现 parse()"""

    def __init__(self, db=None):
        self.db = db

    @abstractmethod
    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        """解析数据集，返回 {summary, quality_metrics}"""
        ...


async def parse_dataset(dataset, db=None) -> Dict[str, Any]:
    """工厂函数 — 根据 dataset.data_type 路由到对应 parser

    Returns:
        {
            "summary": {...},
            "quality_metrics": {...}
        }
    """
    data_type = dataset.data_type
    storage_path = dataset.storage_path

    if not storage_path:
        return {
            "summary": {"error": "数据集未关联文件路径"},
            "quality_metrics": {},
        }

    parser: Parser
    if data_type == DataType.RNA_SEQ:
        from app.services.parser.rna_seq import RnaSeqParser
        parser = RnaSeqParser()
    elif data_type == DataType.SCRNA_SEQ:
        from app.services.parser.scrna import ScRnaSeqParser
        parser = ScRnaSeqParser()
    elif data_type in (DataType.WES, DataType.WGS, DataType.VCF):
        from app.services.parser.vcf import VcfParser
        parser = VcfParser()
    elif data_type == DataType.FASTA:
        from app.services.parser.fasta import FastaParser
        parser = FastaParser()
    elif data_type == DataType.PROTEOMICS:
        from app.services.parser.proteomics import ProteomicsParser
        parser = ProteomicsParser()
    elif data_type == DataType.METABOLOMICS:
        from app.services.parser.metabolomics import MetabolomicsParser
        parser = MetabolomicsParser()
    elif data_type == DataType.GENE_REPORT:
        # 基因检测报告 — 仅返回元数据摘要
        import os
        return {
            "summary": {
                "filename": os.path.basename(storage_path) if storage_path else None,
                "file_format": dataset.file_format,
                "file_size": dataset.file_size,
                "note": "基因检测报告（PDF/图像），需 LLM 提取结构化信息",
            },
            "quality_metrics": {
                "parseable": False,
                "reason": "Gene report requires LLM extraction (use /chat endpoint)",
            },
        }
    else:
        # 通用回退处理 — 对 CLINICAL_IMAGING / CLINICAL_LAB / IHC 等类型，
        # 尝试作为 CSV/TSV 解析，提取 top_genes 兼容字段供下游分析
        import os
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"使用通用回退解析器处理数据类型: {data_type}")
        try:
            import pandas as pd
            import numpy as np
            df = pd.read_csv(storage_path, sep=None, engine="python", index_col=0, nrows=10000)
            n_rows, n_cols = df.shape
            if n_rows == 0 or n_cols == 0:
                return {
                    "summary": {
                        "data_type": str(data_type),
                        "filename": os.path.basename(storage_path),
                        "file_format": dataset.file_format,
                        "note": f"数据类型 {data_type} 使用通用回退解析器，数据矩阵为空",
                    },
                    "quality_metrics": {"parseable": True, "data_type": str(data_type)},
                }
            row_means = df.mean(axis=1)
            top_genes = [
                {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
                for idx in row_means.nlargest(10).index
            ]
            all_values = df.values.flatten()
            finite_values = all_values[np.isfinite(all_values)] if all_values.dtype.kind in "fi" else np.array([])
            return {
                "summary": {
                    "data_type": str(data_type),
                    "filename": os.path.basename(storage_path),
                    "file_format": dataset.file_format,
                    "rows": int(n_rows),
                    "samples": int(n_cols),
                    "top_genes": top_genes,
                    "sample_columns": list(df.columns[:20]),
                    "value_distribution": {
                        "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                        "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                        "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                    },
                    "note": f"数据类型 {data_type} 使用通用回退解析器",
                },
                "quality_metrics": {
                    "missing_rate": round(float(df.isna().mean().mean()), 4),
                    "parseable": True,
                    "data_type": str(data_type),
                },
            }
        except Exception as e:
            return {
                "summary": {
                    "data_type": str(data_type),
                    "filename": os.path.basename(storage_path),
                    "file_format": dataset.file_format,
                    "error": f"通用回退解析失败: {e}",
                    "note": f"数据类型 {data_type} 无法自动解析，可使用高级分析或 LLM 提取信息",
                },
                "quality_metrics": {
                    "parseable": False,
                    "data_type": str(data_type),
                    "error": str(e),
                },
            }

    return await parser.parse(dataset, db)
