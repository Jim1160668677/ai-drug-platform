"""MultiQC 质控报告解析器 — 聚合 RNA-seq/WES/QC 工具的统计指标

支持 Sid Sijbrandij 骨肉瘤数据集中 bcftools_stats / genemetrics / metrics.tsv 等
MultiQC 导出的 TSV/TXT 报告。统一提取：
- 样本/工具/指标矩阵（value 列数值化）
- 关键 QC 指标（mapping_rate / duplicate_rate / ti_tv_ratio 等）
- 各样本的简明 QC 卡片

输入：单文件 .tsv/.txt 或目录（storage_path 指向目录时遍历）
输出：
- summary: 样本列表 / 指标矩阵 / 工具分布
- quality_metrics: 各样本 QC 通过率
"""
import os
import re
from typing import Any, Dict, List

from app.services.parser.base import Parser


# 关键 QC 指标 → 标准化字段名（用于跨样本对比）
_QC_METRIC_ALIASES = {
    "mapping rate": "mapping_rate",
    "mapping_rate": "mapping_rate",
    "unique rate of mapped": "unique_rate",
    "duplicate rate of mapped": "duplicate_rate",
    "duplicate rate of mapped, excluding globins": "duplicate_rate_excluding_globins",
    "base mismatch": "base_mismatch_rate",
    "end 1 mapping rate": "end1_mapping_rate",
    "end 2 mapping rate": "end2_mapping_rate",
    "end 1 mismatch rate": "end1_mismatch_rate",
    "end 2 mismatch rate": "end2_mismatch_rate",
    "expression profiling efficiency": "expression_profiling_efficiency",
    "high quality rate": "high_quality_rate",
    "exonic rate": "exonic_rate",
    "intronic rate": "intronic_rate",
    "intergenic rate": "intergenic_rate",
    "intragenic rate": "intragenic_rate",
    "ambiguous alignment rate": "ambiguous_alignment_rate",
    "high quality exonic rate": "hq_exonic_rate",
    "high quality intronic rate": "hq_intronic_rate",
    "high quality intergenic rate": "hq_intergenic_rate",
    "ti/tv ratio": "ti_tv_ratio",
    "titv": "ti_tv_ratio",
    "total variants": "total_variants",
    "snvs": "snv_count",
    "indels": "indel_count",
    "mean coverage": "mean_coverage",
    "median coverage": "median_coverage",
    "% bases above 20x": "pct_bases_above_20x",
    "% bases above 30x": "pct_bases_above_30x",
}


def _try_float(value):
    """安全转 float；失败返回 None"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # 处理科学计数法 / 百分比 / 逗号分隔
        s = str(value).strip().rstrip("%").replace(",", "")
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_tsv(path: str) -> List[Dict[str, Any]]:
    """解析 TSV（首行为表头），返回 dict 列表"""
    import csv

    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = []
        for r in reader:
            # 数值化数值字段，保留字符串字段
            converted = {}
            for k, v in r.items():
                if v is None or v == "":
                    continue
                fv = _try_float(v)
                converted[k] = fv if fv is not None else v
            rows.append(converted)
        return rows


def _parse_kv_tsv(path: str) -> Dict[str, Dict[str, Any]]:
    """解析 key-value TSV（如 BG003082.metrics.tsv 格式）

    格式：
        Sample  BG003082
        Mapping Rate    0.988738
        ...
    返回：{sample_name: {metric_name: value, ...}}
    """
    sample_cols: List[str] = []
    sample_metrics: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            parts = line.split("\t")
            if not parts:
                continue
            key = parts[0]
            # 第一行：Sample <sample_name1> <sample_name2> ...
            if key.lower() == "sample":
                sample_cols = parts[1:]
                for sname in sample_cols:
                    sample_metrics[sname] = {}
                continue
            # 数据行：<metric> <v1> <v2> ...
            if not sample_cols:
                continue
            for i, sname in enumerate(sample_cols):
                val = parts[i + 1] if i + 1 < len(parts) else None
                fv = _try_float(val)
                sample_metrics[sname][key] = fv if fv is not None else val
    return sample_metrics


class MultiqcParser(Parser):
    """MultiQC 质控报告解析器

    识别两种常见 MultiQC TSV 子格式：
    1. 长格式 TSV（首行表头为字段名）：bcftools-stats-subtypes / genemetrics / indel-lengths
    2. 宽格式 KV TSV（首列 Sample，余列样本名）：BG003082.metrics.tsv

    自动按文件名前缀识别工具来源（bcftools / cnvkit / picard / rnaseqc 等）。
    """

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"路径不存在: {path}"}, "quality_metrics": {}}

        # 收集文件
        qc_files: List[str] = []
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    if f.lower().endswith((".tsv", ".txt")):
                        qc_files.append(os.path.join(root, f))
        elif os.path.isfile(path):
            qc_files.append(path)

        if not qc_files:
            return {
                "summary": {"data_type": "multiqc", "error": "未找到 .tsv/.txt 质控文件"},
                "quality_metrics": {"parseable": False},
            }

        tool_reports: Dict[str, Dict[str, Any]] = {}  # tool_name -> {metrics, samples, raw_rows}
        sample_qc: Dict[str, Dict[str, Any]] = {}  # sample_name -> {metric_field: value}

        for qc_path in qc_files:
            fname = os.path.basename(qc_path)
            tool_name = self._detect_tool(fname)

            try:
                with open(qc_path, "r", encoding="utf-8", errors="replace") as f:
                    first_line = f.readline().rstrip("\r\n")
                is_kv = first_line.lower().startswith("sample\t") or first_line.lower().startswith("sample,")

                if is_kv:
                    sample_metrics = _parse_kv_tsv(qc_path)
                    samples = list(sample_metrics.keys())
                    # 标准化字段名 + 合并到全局 sample_qc
                    for sname, metrics in sample_metrics.items():
                        if sname not in sample_qc:
                            sample_qc[sname] = {"sample_name": sname}
                        for raw_key, value in metrics.items():
                            std_key = _QC_METRIC_ALIASES.get(raw_key.lower().strip())
                            if std_key:
                                sample_qc[sname][std_key] = value
                            else:
                                # 其他字段保留原 key（snake_case 化以避免冲突）
                                snake = re.sub(r"\W+", "_", raw_key.strip().lower())
                                sample_qc[sname][snake] = value

                    tool_reports[tool_name] = {
                        "file": fname,
                        "format": "kv_tsv",
                        "samples": samples,
                        "metric_count": len(next(iter(sample_metrics.values()))) if sample_metrics else 0,
                    }
                else:
                    rows = _parse_tsv(qc_path)
                    # 简化：仅保留前 20 行
                    samples_field = "Sample" if rows and "Sample" in rows[0] else None
                    samples = sorted({str(r.get(samples_field)) for r in rows if r.get(samples_field)}) if samples_field else []
                    tool_reports[tool_name] = {
                        "file": fname,
                        "format": "long_tsv",
                        "row_count": len(rows),
                        "samples": samples[:20],
                        "fields": list(rows[0].keys())[:20] if rows else [],
                        "preview": rows[:5],
                    }
            except Exception as e:
                tool_reports[tool_name] = {"file": fname, "error": str(e)[:100]}

        # 计算关键 QC 通过率
        total_samples = len(sample_qc)
        qc_passed = 0
        if total_samples > 0:
            for sname, metrics in sample_qc.items():
                # 通过标准：mapping_rate >= 0.8 或 duplicate_rate <= 0.5
                if metrics.get("mapping_rate") is not None and metrics["mapping_rate"] >= 0.8:
                    qc_passed += 1
                elif metrics.get("duplicate_rate") is not None and metrics["duplicate_rate"] <= 0.5:
                    qc_passed += 1
            qc_pass_rate = round(qc_passed / total_samples, 4)
        else:
            qc_pass_rate = None

        summary = {
            "data_type": "multiqc",
            "file_format": "tsv",
            "qc_file_count": len(qc_files),
            "tool_reports": tool_reports,
            "samples": list(sample_qc.keys()),
            "sample_count": total_samples,
            "sample_qc": list(sample_qc.values())[:20],
            "qc_pass_rate": qc_pass_rate,
            "note": (
                f"解析 {len(qc_files)} 个 MultiQC 文件，"
                f"覆盖 {len(tool_reports)} 个工具 / {total_samples} 个样本"
            ),
        }

        quality_metrics = {
            "parseable": True,
            "data_type": "multiqc",
            "qc_pass_rate": qc_pass_rate,
            "sample_count": total_samples,
            "tool_count": len(tool_reports),
            "key_metrics_extracted": sum(
                1 for s in sample_qc.values()
                if any(k in s for k in ("mapping_rate", "duplicate_rate", "ti_tv_ratio"))
            ),
        }

        return {"summary": summary, "quality_metrics": quality_metrics}

    def _detect_tool(self, fname: str) -> str:
        """根据文件名识别工具来源"""
        lower = fname.lower()
        if "bcftools" in lower or "variant" in lower:
            return "bcftools"
        if "genemetrics" in lower:
            return "cnvkit_genemetrics"
        if "indel" in lower and "length" in lower:
            return "bcftools_indel_lengths"
        if "depth" in lower:
            return "variant_depths"
        if "metrics" in lower:
            return "rnaseqc_metrics"
        if "multiqc" in lower:
            return "multiqc_general"
        return "unknown"
