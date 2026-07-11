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
    elif data_type in (DataType.WES, DataType.WGS):
        from app.services.parser.vcf import VcfParser
        parser = VcfParser()
    elif data_type == DataType.FASTA:
        from app.services.parser.fasta import FastaParser
        parser = FastaParser()
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
        return {
            "summary": {"error": f"暂不支持的数据类型: {data_type}"},
            "quality_metrics": {},
        }

    return await parser.parse(dataset, db)
