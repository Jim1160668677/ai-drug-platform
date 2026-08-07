"""XeniumParser / NeoantigenParser 单元测试

覆盖：正常解析、空文件、缺列、异常格式、目录遍历、多文件合并、top_genes 输出。
目标覆盖率 ≥80%。
"""
import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

from app.services.parser.xenium import XeniumParser
from app.services.parser.neoantigen import NeoantigenParser, _safe_float


# ========== 辅助 ==========

def _ds(path, dtype="xenium", fmt="csv"):
    """构造简易 dataset 替身"""
    return SimpleNamespace(
        storage_path=path, data_type=dtype, file_format=fmt, file_size=0
    )


def _run(coro):
    """同步运行协程"""
    return asyncio.run(coro)


# ========== XeniumParser 测试 ==========

XENIUM_CSV = """Barcode,Cluster
aaaafegh-1,6
aaaboijj-1,8
aaabpcjm-1,3
aaabpphd-1,6
aaacgija-1,1
aaacgijb-1,1
"""


class TestXeniumParser:
    def test_normal_parse(self, tmp_path):
        f = tmp_path / "clusters.csv"
        f.write_text(XENIUM_CSV, encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        s = result["summary"]
        assert s["total_cells"] == 6
        assert s["n_clusters"] == 4  # clusters: 6,8,3,1
        assert s["largest_cluster"]["cluster_id"] == 6
        assert s["largest_cluster"]["n_cells"] == 2
        assert result["quality_metrics"]["parseable"] is True
        assert result["quality_metrics"]["total_cells"] == 6
        # top_genes 兼容字段
        assert len(s["top_genes"]) <= 10
        assert s["top_genes"][0]["n_cells"] == 2

    def test_file_not_exist(self):
        result = _run(XeniumParser().parse(_ds("/nonexistent/xenium.csv")))
        assert "error" in result["summary"]
        assert result["quality_metrics"] == {}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        assert "error" in result["summary"]
        assert result["quality_metrics"]["parseable"] is False

    def test_missing_columns(self, tmp_path):
        # 使用支持的别名 id / group
        f = tmp_path / "noheader.csv"
        f.write_text("id,group\ncellA,1\ncellB,2\n", encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        s = result["summary"]
        assert s["total_cells"] == 2
        assert s["n_clusters"] == 2

    def test_no_valid_columns(self, tmp_path):
        f = tmp_path / "bad.csv"
        f.write_text("foo,bar\n1,2\n", encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        assert "error" in result["summary"]
        assert "缺少 Barcode/Cluster" in " ".join(result["summary"].get("warnings", [])) or \
               "error" in result["summary"]

    def test_directory_traversal(self, tmp_path):
        d = tmp_path / "xenium_dir"
        d.mkdir()
        (d / "clusters.csv").write_text(XENIUM_CSV, encoding="utf-8")
        # 第二个文件含重复 barcode（测试去重）
        (d / "xenium_clusters2.csv").write_text(
            "Barcode,Cluster\naaaafegh-1,6\nnewcell-1,2\n", encoding="utf-8"
        )
        result = _run(XeniumParser().parse(_ds(str(d))))
        s = result["summary"]
        # aaaafegh-1 跨文件去重，新增 newcell-1 → 6+1=7
        assert s["total_cells"] == 7
        assert len(s["files_parsed"]) == 2

    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty_dir"
        d.mkdir()
        result = _run(XeniumParser().parse(_ds(str(d))))
        assert "error" in result["summary"]

    def test_non_numeric_cluster(self, tmp_path):
        f = tmp_path / "clusters.csv"
        f.write_text("Barcode,Cluster\nc1,A\nc2,B\n", encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        s = result["summary"]
        assert s["total_cells"] == 2
        assert s["n_clusters"] == 2
        # 非数字簇标签保留原值
        assert "A" in s["cluster_distribution"]

    def test_quality_metrics_fraction(self, tmp_path):
        f = tmp_path / "clusters.csv"
        f.write_text("Barcode,Cluster\na,1\nb,1\nc,2\n", encoding="utf-8")
        result = _run(XeniumParser().parse(_ds(str(f))))
        # largest cluster = 2 cells / 3 total
        assert result["quality_metrics"]["largest_cluster_fraction"] == round(2 / 3, 4)


# ========== NeoantigenParser 测试 ==========

NEOANTIGEN_TSV = (
    "ID\tIndex\tGene\tAA Change\tBest Peptide\tAllele\tIC50 MT\tIC50 WT\t"
    "RNA Expr\tDNA VAF\tTier\tEvaluation\n"
    "chr1-100-A-G\t1.TP53.ENST.missense.V600E\tTP53\tV600E\tKRFHATISF\tHLA-B*27:05\t"
    "54.9\t55.4\t0.115\t0.094\tPass\tPass\n"
    "chr2-200-T-C\t2.KRAS.ENST.missense.G12D\tKRAS\tG12D\tILNFTTLDLY\tHLA-A*01:01\t"
    "400.7\t394.7\t0.385\t0.123\tPass\tPass\n"
    "chr3-300-G-T\t3.EGFR.ENST.missense.L858R\tEGFR\tL858R\tVVGALLLLV\tHLA-A*01:01\t"
    "5000\t5100\t0.2\t0.3\tPoor\tPending\n"
    "chr4-400-C-A\t4.MYC.ENST.missense.T58A\tMYC\tT58A\t\tHLA-B*08:01\t"
    "NA\tNA\tNA\tNA\tPoor\tPending\n"
)


class TestNeoantigenParser:
    def test_normal_parse(self, tmp_path):
        f = tmp_path / "epitopes.tsv"
        f.write_text(NEOANTIGEN_TSV, encoding="utf-8")
        result = _run(NeoantigenParser().parse(_ds(str(f), dtype="neoantigen", fmt="tsv")))
        s = result["summary"]
        # 第4行无肽段但有基因，仍计入
        assert s["total_epitopes"] == 4
        assert s["hit_genes_count"] == 4
        # IC50<500 的结合肽段：54.9, 400.7 → 2 个
        assert s["binding_epitopes_count"] == 2
        # IC50<50 强结合：54.9 不 < 50 → 0 个
        assert s["strong_binder_count"] == 0
        # HLA 分布
        assert s["hla_allele_distribution"]["HLA-A*01:01"] == 2
        # Tier 分布
        assert s["tier_distribution"]["Pass"] == 2
        assert s["tier_distribution"]["Poor"] == 2
        # top_peptides 按 IC50 升序
        assert s["top_peptides"][0]["ic50_mt"] == 54.9
        assert s["top_peptides"][0]["gene"] == "TP53"
        # top_genes 兼容字段
        assert s["top_genes"][0]["symbol"] == "TP53"
        assert result["quality_metrics"]["binding_rate"] == round(2 / 4, 4)

    def test_file_not_exist(self):
        result = _run(NeoantigenParser().parse(_ds("/nonexistent/neo.tsv", dtype="neoantigen")))
        assert "error" in result["summary"]
        assert result["quality_metrics"] == {}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.tsv"
        f.write_text("", encoding="utf-8")
        result = _run(NeoantigenParser().parse(_ds(str(f), dtype="neoantigen", fmt="tsv")))
        assert "error" in result["summary"]
        assert result["quality_metrics"]["parseable"] is False

    def test_strong_binder(self, tmp_path):
        tsv = (
            "Gene\tBest Peptide\tAllele\tIC50 MT\tIC50 WT\tTier\tEvaluation\n"
            "TP53\tPEPTIDE1\tHLA-A*01:01\t10\t5000\tPass\tPass\n"
            "KRAS\tPEPTIDE2\tHLA-B*27:05\t100\t5000\tPoor\tPending\n"
        )
        f = tmp_path / "strong.tsv"
        f.write_text(tsv, encoding="utf-8")
        result = _run(NeoantigenParser().parse(_ds(str(f), dtype="neoantigen", fmt="tsv")))
        s = result["summary"]
        assert s["strong_binder_count"] == 1  # IC50=10 < 50
        # 10 < 500 且 100 < 500 → 2 个结合肽段
        assert s["binding_epitopes_count"] == 2

    def test_directory_traversal(self, tmp_path):
        d = tmp_path / "neo_dir"
        d.mkdir()
        (d / "all_epitopes.aggregated.tsv").write_text(NEOANTIGEN_TSV, encoding="utf-8")
        result = _run(NeoantigenParser().parse(_ds(str(d), dtype="neoantigen", fmt="tsv")))
        s = result["summary"]
        assert s["total_epitopes"] == 4
        assert len(s["files_parsed"]) == 1

    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty_neo"
        d.mkdir()
        result = _run(NeoantigenParser().parse(_ds(str(d), dtype="neoantigen")))
        assert "error" in result["summary"]

    def test_na_ic50_handling(self, tmp_path):
        tsv = (
            "Gene\tBest Peptide\tIC50 MT\tIC50 WT\tTier\n"
            "TP53\tPEP\tNA\tNA\tPoor\n"
            "KRAS\tPEP2\t50\t60\tPass\n"
        )
        f = tmp_path / "na.tsv"
        f.write_text(tsv, encoding="utf-8")
        result = _run(NeoantigenParser().parse(_ds(str(f), dtype="neoantigen", fmt="tsv")))
        s = result["summary"]
        # 只有 KRAS 的 IC50=50 可解析，50 < 50 不成立 → strong=0，50<500 binding=1
        assert s["binding_epitopes_count"] == 1

    def test_corrupt_file(self, tmp_path):
        f = tmp_path / "corrupt.tsv"
        f.write_text("这不是一个TSV文件\n没有制表符\n", encoding="utf-8")
        # pandas 能读但列不对，应不崩溃
        result = _run(NeoantigenParser().parse(_ds(str(f), dtype="neoantigen", fmt="tsv")))
        # 要么 parseable=False（无表位），要么有 error
        assert result["quality_metrics"]["parseable"] is False or "error" in result["summary"]


# ========== _safe_float 辅助函数测试 ==========

class TestSafeFloat:
    def test_normal(self):
        assert _safe_float("54.9") == 54.9
        assert _safe_float(100) == 100.0

    def test_na(self):
        import math
        assert math.isnan(_safe_float("NA"))
        assert math.isnan(_safe_float("nan"))
        assert math.isnan(_safe_float(None))
        assert math.isnan(_safe_float(""))
        assert math.isnan(_safe_float("none"))

    def test_invalid(self):
        import math
        assert math.isnan(_safe_float("abc"))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
