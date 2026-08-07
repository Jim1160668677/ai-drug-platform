"""RNA-seq 解析器 — 多格式表达矩阵（CSV/TSV/GCT/STAR/RSEM）"""
import os
from typing import Any, Dict

from app.services.parser.base import Parser
from app.services.parser._metadata_columns import split_metadata_columns


class RnaSeqParser(Parser):
    """RNA-seq 表达矩阵解析器

    支持格式：
    - **CSV/TSV**：标准表达矩阵（行=基因，列=样本，index_col=0=基因名）
    - **GCT**：Broad Institute 标准格式（前 2 行元数据 + Name/Description/Samples 表头）
    - **STAR ReadsPerGene.out.tab**：4 列（gene_id, unstranded, stranded_fwd, stranded_rev），
      前 4 行是 N_* 摘要；只取第 2 列 unstranded counts，跳过前 4 行
    - **RSEM *.results**：含 gene_id + 数值列（length/effective_length/expected_count/TPM/FPKM/IsoPct），
      需 split_metadata_columns 排除非样本列
    """

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {
                "summary": {"error": f"文件不存在: {path}"},
                "quality_metrics": {},
            }

        import numpy as np
        import pandas as pd

        ext = (dataset.file_format or "").lower()
        filename = os.path.basename(path).lower()

        # ---------- 按格式分发 ----------
        try:
            if ext == "gct" or filename.endswith(".gct"):
                df = self._read_gct(path)
            elif "readspergene" in filename or "reads_per_gene" in filename:
                df = self._read_star_readspergene(path)
            elif ext in ("csv", "tsv") or ext == "":
                df = self._read_csv_tsv(path)
            else:
                df = self._read_csv_tsv(path)
        except Exception as e:
            return {
                "summary": {"error": f"CSV 解析失败: {e}"},
                "quality_metrics": {},
            }

        if df is None or df.empty:
            return {
                "summary": {"error": "数据矩阵为空"},
                "quality_metrics": {},
            }

        # 排除元数据列（length/effective_length/TPM/FPKM/IsoPct 等数值型元数据）
        # 同时排除字符串列（如 gene_id、gene_name、transcript_id）
        if ext == "gct" or filename.endswith(".gct"):
            # GCT 已通过 _read_gct 正确处理，不再过滤
            numeric_df = df.select_dtypes(include=[np.number])
        else:
            # 用 split_metadata_columns 同时排除字符串元数据和数值型元数据
            numeric_df, _ = split_metadata_columns(df)

        if numeric_df.empty:
            return {
                "summary": {"error": "无数值列可分析（CSV 可能仅含元数据）"},
                "quality_metrics": {},
            }

        n_genes, n_samples = numeric_df.shape
        if n_samples == 0:
            return {
                "summary": {"error": "数据矩阵为空"},
                "quality_metrics": {},
            }

        # 质量指标（在数值矩阵上计算，避免字符串列导致 TypeError）
        missing_rate = float(numeric_df.isna().mean().mean())
        row_means = numeric_df.mean(axis=1)
        low_expression_ratio = float((row_means < 1.0).mean())
        zero_expression_ratio = float((row_means == 0).mean())

        # 表达分布
        all_values = numeric_df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        summary = {
            "genes": int(n_genes),
            "samples": int(n_samples),
            "file_format": dataset.file_format,
            "top_genes": [
                {"symbol": str(idx), "mean_expression": float(row_means.loc[idx])}
                for idx in row_means.nlargest(10).index
            ],
            "sample_columns": list(numeric_df.columns[:20]),
            "value_distribution": {
                "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                "min": float(np.min(finite_values)) if len(finite_values) > 0 else 0,
                "max": float(np.max(finite_values)) if len(finite_values) > 0 else 0,
            },
        }

        quality_metrics = {
            "missing_rate": round(missing_rate, 4),
            "low_expression_ratio": round(low_expression_ratio, 4),
            "zero_expression_ratio": round(zero_expression_ratio, 4),
            "sample_missing_rates": {
                str(c): round(float(numeric_df[c].isna().mean()), 4) for c in numeric_df.columns
            },
            "data_type": "rna_seq",
            "assumed_normalized": bool(np.max(finite_values) < 1000) if len(finite_values) > 0 else False,
        }

        return {"summary": summary, "quality_metrics": quality_metrics}

    # ---------- 格式读取器 ----------
    def _read_csv_tsv(self, path: str):
        """读取标准 CSV/TSV 表达矩阵（行=基因，列=样本）"""
        import pandas as pd

        # 自动检测分隔符
        try:
            df = pd.read_csv(path, sep=None, engine="python", index_col=0, nrows=10000)
        except Exception:
            df = pd.read_csv(path, index_col=0, nrows=10000)
        return df

    def _read_gct(self, path: str):
        """读取 Broad Institute GCT 格式

        格式：
        行1: #1.2
        行2: <数据行数>\\t<样本列数>
        行3: Name\\tDescription\\tSample1\\tSample2\\t...
        行4+: 数据行
        """
        import pandas as pd

        with open(path, "r", encoding="utf-8") as f:
            # 跳过前 2 行元数据
            f.readline()  # #1.2
            f.readline()  # rows\tcols
            # 第 3 行是表头
            header = f.readline().rstrip("\n").split("\t")
            # 剩余是数据
            df = pd.read_csv(f, sep="\t", header=None, names=header, nrows=10000)
        # 第 1 列是基因 ID（Name），第 2 列是 Description（元数据），后面是样本
        df = df.set_index(df.columns[0])
        # 丢弃 Description 列
        if "Description" in df.columns:
            df = df.drop(columns=["Description"])
        return df

    def _read_star_readspergene(self, path: str):
        """读取 STAR ReadsPerGene.out.tab 格式

        格式：4 列（tab 分隔）
        - 列1: gene_id (Ensembl)
        - 列2: unstranded counts（推荐用于后续分析）
        - 列3: stranded forward counts
        - 列4: stranded reverse counts
        前 4 行是 N_* 摘要（N_unmapped, N_multimapping, N_noFeature, N_ambiguous），应跳过
        """
        import pandas as pd

        # 跳过前 4 行摘要，只取第 1 列（gene_id）和第 2 列（unstranded counts）
        df = pd.read_csv(
            path,
            sep="\t",
            header=None,
            skiprows=4,
            usecols=[0, 1],
            names=["gene_id", "unstranded_counts"],
            index_col=0,
            nrows=10000,
        )
        # 重命名列为更具描述性的名称
        df.columns = ["unstranded_counts"]
        return df
