"""管道管理器 — Nextflow 管道元数据管理"""
from typing import Dict, List


# 可用管道定义
PIPELINES = {
    "scrna_pipeline": {
        "name": "scrna_pipeline",
        "description": "单细胞测序数据处理（Scanpy）",
        "phase": "P0",
        "script": "nextflow/scrna_pipeline.nf",
        "input_type": "scrna_seq",
        "output_files": ["annotated.h5ad", "markers.csv", "qc_report.html"],
        "params_template": {
            "input": "data/scrna.h5",
            "output": "results/scrna/",
            "min_genes": 200,
            "min_cells": 3,
            "n_pcs": 50,
            "resolution": 0.8,
        },
    },
    "rna_seq_pipeline": {
        "name": "rna_seq_pipeline",
        "description": "RNA-seq 定量与差异表达分析",
        "phase": "P0",
        "script": "nextflow/rna_seq_pipeline.nf",
        "input_type": "rna_seq",
        "output_files": ["deseq2_results.csv", "normalized_counts.csv"],
        "params_template": {
            "input": "data/counts.csv",
            "samples": "data/samples.csv",
            "output": "results/rna_seq/",
            "fdr_threshold": 0.05,
            "log2fc_threshold": 1.0,
        },
    },
    "variant_annotation": {
        "name": "variant_annotation",
        "description": "WES/WGS 变异注释（VEP/SnpEff）",
        "phase": "P2",
        "script": "nextflow/variant_annotation.nf",
        "input_type": "wes",
        "output_files": ["annotated.vcf", "summary.json"],
        "params_template": {
            "vcf": "data/variants.vcf",
            "reference": "GRCh38",
            "output": "results/variants/",
            "annotation_tool": "vep",
        },
    },
}


class PipelineManager:
    """管道管理器 — 列出和配置可用管道"""

    def list_pipelines(self) -> List[Dict]:
        """返回可用管道列表"""
        return [
            {
                "name": p["name"],
                "description": p["description"],
                "phase": p["phase"],
                "input_type": p["input_type"],
                "output_files": p["output_files"],
            }
            for p in PIPELINES.values()
        ]

    def get_pipeline_config(self, name: str) -> Dict:
        """获取管道配置

        Args:
            name: 管道名称
        Returns:
            管道完整配置（含参数模板）
        """
        if name not in PIPELINES:
            return {"error": f"管道 '{name}' 不存在", "available": list(PIPELINES.keys())}
        return PIPELINES[name]
