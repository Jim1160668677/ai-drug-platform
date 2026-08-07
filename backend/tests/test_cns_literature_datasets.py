"""CNS 期刊文献数据集全流程验证测试

测试 Cell、Nature、Science 期刊文献的数据集能否在本系统中完成：
1. 数据导入（文件读取）
2. 数据预处理（解析器调用）
3. 分析（靶点发现）
4. 结果输出（parsed_summary 验证）

数据集来源：
- Cell: S0092-8674(25)01032-3 糖基化免疫治疗
- Nature Cancer: 10.1038/s43018-025-01053-7 TP53 肺腺癌
- Science Advances: 10.1126/sciadv.adu9945 HER2-曲妥珠单抗
"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cns_literature_datasets"


def _make_dataset(storage_path: str, data_type, file_format: str = "CSV") -> SimpleNamespace:
    """构造内存数据集对象（避免依赖数据库）"""
    return SimpleNamespace(
        storage_path=storage_path,
        data_type=data_type,
        file_format=file_format,
        file_size=os.path.getsize(storage_path) if os.path.exists(storage_path) else 0,
        parsed_summary=None,
    )


# ============================================================
# 1. Cell 论文数据集测试 — RNA-seq
# ============================================================
class TestCellPaperDataset:
    """Cell 期刊: 糖基化免疫治疗靶点蛋白"""

    @pytest.fixture
    def dataset(self):
        path = DATA_DIR / "cell_paper" / "gene_expression_glycotargeting.csv"
        from app.models.dataset import DataType
        return _make_dataset(str(path), DataType.RNA_SEQ, "CSV")

    @pytest.mark.asyncio
    async def test_file_exists(self, dataset):
        assert os.path.exists(dataset.storage_path), "Cell 数据集文件不存在"

    @pytest.mark.asyncio
    async def test_parse_rna_seq(self, dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(dataset)
        summary = result["summary"]
        assert "top_genes" in summary, "Cell RNA-seq 解析缺少 top_genes"
        assert summary["genes"] == 30, f"期望 30 个基因，实际 {summary['genes']}"
        assert summary["samples"] == 5, f"期望 5 个样本，实际 {summary['samples']}"
        # top_genes 仅返回前 10，至少 2 个为已知靶点
        from app.services.analyzer.target_identifier import KNOWN_TARGET_GENES
        symbols = {g["symbol"].upper() for g in summary["top_genes"]}
        matched = symbols & KNOWN_TARGET_GENES
        assert len(matched) >= 2, f"Cell 数据集应至少匹配 2 个已知靶点，实际 {matched}"

    @pytest.mark.asyncio
    async def test_quality_metrics(self, dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(dataset)
        qm = result["quality_metrics"]
        assert "missing_rate" in qm, f"quality_metrics 缺少 missing_rate: {qm}"
        assert qm["missing_rate"] < 0.1, "缺失率过高"


# ============================================================
# 2. Nature Cancer 论文数据集测试 — RNA-seq (TP53 LUAD)
# ============================================================
class TestNatureCancerDataset:
    """Nature Cancer: TP53 突变肺腺癌多组学图谱"""

    @pytest.fixture
    def dataset(self):
        path = DATA_DIR / "nature_paper" / "luad_tp53_rna_seq.csv"
        from app.models.dataset import DataType
        return _make_dataset(str(path), DataType.RNA_SEQ, "CSV")

    @pytest.mark.asyncio
    async def test_file_exists(self, dataset):
        assert os.path.exists(dataset.storage_path), "Nature 数据集文件不存在"

    @pytest.mark.asyncio
    async def test_parse_rna_seq(self, dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(dataset)
        summary = result["summary"]
        assert summary["genes"] == 40, f"期望 40 个基因，实际 {summary['genes']}"
        assert summary["samples"] == 10, f"期望 10 个样本，实际 {summary['samples']}"
        symbols = {g["symbol"].upper() for g in summary["top_genes"]}
        core_targets = {"TP53", "CD274", "SPP1", "PVR", "TIGIT", "KRAS", "EGFR"}
        matched = symbols & core_targets
        assert len(matched) >= 3, f"Nature 数据集应至少匹配 3 个核心靶点，实际 {matched}"

    @pytest.mark.asyncio
    async def test_differential_expression_pattern(self, dataset):
        """验证 TP53mut vs WT 差异表达模式"""
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(dataset)
        samples = result["summary"]["sample_columns"]
        mut_samples = [s for s in samples if "TP53mut" in s]
        wt_samples = [s for s in samples if "TP53WT" in s]
        assert len(mut_samples) == 5, "TP53 突变样本数应为 5"
        assert len(wt_samples) == 5, "TP53 野生型样本数应为 5"

    @pytest.mark.asyncio
    async def test_target_discovery_compatibility(self, dataset):
        from app.services.parser.base import parse_dataset
        from app.services.analyzer.target_identifier import KNOWN_TARGET_GENES
        result = await parse_dataset(dataset)
        # top_genes 仅返回前 10 个，KNOWN_TARGET_GENES 匹配数 >= 3 即可
        symbols = {g["symbol"].upper() for g in result["summary"]["top_genes"]}
        matched = symbols & KNOWN_TARGET_GENES
        assert len(matched) >= 3, (
            f"Nature 数据集应至少匹配 3 个 KNOWN_TARGET_GENES，实际匹配 {matched}"
        )


# ============================================================
# 3. Science Advances 论文数据集测试 — 蛋白序列 + 蛋白组学 + 相互作用
# ============================================================
class TestScienceAdvancesDataset:
    """Science Advances: HER2-曲妥珠单抗复合物结构"""

    @pytest.fixture
    def fasta_dataset(self):
        path = DATA_DIR / "science_paper" / "her2_protein_sequence.fasta"
        from app.models.dataset import DataType
        return _make_dataset(str(path), DataType.FASTA, "FASTA")

    @pytest.fixture
    def proteomics_dataset(self):
        path = DATA_DIR / "science_paper" / "her2_expression_proteomics.csv"
        from app.models.dataset import DataType
        return _make_dataset(str(path), DataType.PROTEOMICS, "CSV")

    @pytest.fixture
    def interaction_dataset(self):
        path = DATA_DIR / "science_paper" / "her2_interaction_data.csv"
        from app.models.dataset import DataType
        return _make_dataset(str(path), DataType.PROTEOMICS, "CSV")

    @pytest.mark.asyncio
    async def test_fasta_file_exists(self, fasta_dataset):
        assert os.path.exists(fasta_dataset.storage_path), "FASTA 文件不存在"

    @pytest.mark.asyncio
    async def test_proteomics_file_exists(self, proteomics_dataset):
        assert os.path.exists(proteomics_dataset.storage_path), "蛋白组学文件不存在"

    @pytest.mark.asyncio
    async def test_interaction_file_exists(self, interaction_dataset):
        assert os.path.exists(interaction_dataset.storage_path), "相互作用文件不存在"

    @pytest.mark.asyncio
    async def test_parse_fasta(self, fasta_dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(fasta_dataset)
        summary = result["summary"]
        # FASTA 解析器返回 sequence_count / top_sequences_by_length
        assert "sequence_count" in summary, f"FASTA 解析缺少 sequence_count: {summary}"
        assert summary["sequence_count"] >= 1, "至少应解析到 1 条序列"
        assert "top_sequences_by_length" in summary
        # 验证 ERBB2 序列被识别
        seq_ids = [s["id"] for s in summary["top_sequences_by_length"]]
        assert any("ERBB2" in sid for sid in seq_ids), f"未识别 ERBB2 序列: {seq_ids}"

    @pytest.mark.asyncio
    async def test_parse_proteomics(self, proteomics_dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(proteomics_dataset)
        summary = result["summary"]
        assert "top_proteins" in summary or "top_genes" in summary, (
            f"蛋白组学解析结果缺少 top_proteins/top_genes: {summary}"
        )
        top = summary.get("top_proteins") or summary.get("top_genes")
        all_symbols = [g.get("symbol", "") for g in top]
        # ERBB2 表达量高，应在 top 10 中
        assert "ERBB2" in all_symbols, f"蛋白组学数据应包含 ERBB2，实际 top: {all_symbols[:5]}"
        assert summary["samples"] == 8, f"期望 8 个样本列，实际 {summary['samples']}"
        # 验证 metadata_columns 正确分离
        assert "metadata_columns" in summary, "应分离元数据列"
        assert "protein_name" in summary["metadata_columns"]

    @pytest.mark.asyncio
    async def test_parse_interaction_data(self, interaction_dataset):
        from app.services.parser.base import parse_dataset
        result = await parse_dataset(interaction_dataset)
        summary = result["summary"]
        assert summary.get("rows", 0) > 0 or "top_genes" in summary, (
            f"相互作用数据解析失败: {summary}"
        )

    @pytest.mark.asyncio
    async def test_target_discovery_compatibility(self, proteomics_dataset):
        from app.services.parser.base import parse_dataset
        from app.services.analyzer.target_identifier import KNOWN_TARGET_GENES
        result = await parse_dataset(proteomics_dataset)
        top = result["summary"].get("top_proteins") or result["summary"].get("top_genes", [])
        symbols = {g.get("symbol", "").upper() for g in top}
        matched = symbols & KNOWN_TARGET_GENES
        assert len(matched) >= 2, (
            f"Science 数据集应至少匹配 2 个 KNOWN_TARGET_GENES，实际匹配 {matched}"
        )


# ============================================================
# 4. 全流程集成测试 — 数据导入到假设生成
# ============================================================
class TestFullPipelineIntegration:
    """CNS 数据集全流程集成测试"""

    @pytest.mark.asyncio
    async def test_all_datasets_parseable(self):
        """验证所有 CNS 数据集均可被系统解析"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        datasets = [
            (DATA_DIR / "cell_paper" / "gene_expression_glycotargeting.csv", DataType.RNA_SEQ),
            (DATA_DIR / "nature_paper" / "luad_tp53_rna_seq.csv", DataType.RNA_SEQ),
            (DATA_DIR / "science_paper" / "her2_expression_proteomics.csv", DataType.PROTEOMICS),
            (DATA_DIR / "science_paper" / "her2_interaction_data.csv", DataType.PROTEOMICS),
            (DATA_DIR / "science_paper" / "her2_protein_sequence.fasta", DataType.FASTA),
        ]

        results = []
        for path, data_type in datasets:
            assert path.exists(), f"文件不存在: {path}"
            ds = _make_dataset(str(path), data_type)
            result = await parse_dataset(ds)
            results.append((path.name, result))
            assert "summary" in result, f"{path.name} 解析失败"
            assert "error" not in result["summary"] or result["summary"].get("error") is None, (
                f"{path.name} 解析出错: {result['summary'].get('error')}"
            )

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_target_extraction_from_all_papers(self):
        """验证从所有 CNS 论文数据集中均可提取靶点"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        from app.services.analyzer.target_identifier import KNOWN_TARGET_GENES

        files = [
            (DATA_DIR / "cell_paper" / "gene_expression_glycotargeting.csv", DataType.RNA_SEQ),
            (DATA_DIR / "nature_paper" / "luad_tp53_rna_seq.csv", DataType.RNA_SEQ),
            (DATA_DIR / "science_paper" / "her2_expression_proteomics.csv", DataType.PROTEOMICS),
        ]

        all_matched = set()
        for path, dtype in files:
            ds = _make_dataset(str(path), dtype)
            result = await parse_dataset(ds)
            summary = result["summary"]
            top = summary.get("top_genes") or summary.get("top_proteins", [])
            symbols = {g.get("symbol", "").upper() for g in top}
            matched = symbols & KNOWN_TARGET_GENES
            all_matched.update(matched)

        # 三个数据集合计应识别至少 5 个已知靶点
        assert len(all_matched) >= 5, (
            f"三个 CNS 数据集应识别至少 5 个已知靶点，实际 {len(all_matched)}: {all_matched}"
        )

    @pytest.mark.asyncio
    async def test_hypothesis_generation_compatibility(self):
        """验证 CNS 数据集解析结果与假设生成器兼容"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        path = DATA_DIR / "nature_paper" / "luad_tp53_rna_seq.csv"
        ds = _make_dataset(str(path), DataType.RNA_SEQ)
        result = await parse_dataset(ds)
        summary = result["summary"]

        evidence = {
            "de_genes": [
                {"gene": g["symbol"], "mean_expression": g.get("mean_expression", 0)}
                for g in summary["top_genes"]
            ],
            "pathways": [],
            "molecules": [],
            "targets": [],
            "treatments": [],
            "clinical_feedbacks": [],
            "clusters": [],
        }

        assert len(evidence["de_genes"]) > 0
        assert all("gene" in g for g in evidence["de_genes"])

    @pytest.mark.asyncio
    async def test_dataset_summary_structure(self):
        """验证数据集解析结果结构符合系统约定"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        path = DATA_DIR / "cell_paper" / "gene_expression_glycotargeting.csv"
        ds = _make_dataset(str(path), DataType.RNA_SEQ)
        result = await parse_dataset(ds)

        summary = result["summary"]
        required_fields = ["top_genes", "sample_columns"]
        for field in required_fields:
            assert field in summary, f"summary 缺少必需字段: {field}"

        qm = result["quality_metrics"]
        assert "missing_rate" in qm


# ============================================================
# 5. 数据集清单验证
# ============================================================
class TestDatasetManifest:
    """验证 CNS 数据集目录结构完整性"""

    def test_readme_exists(self):
        assert (DATA_DIR / "README.md").exists(), "README.md 不存在"

    def test_cell_paper_directory(self):
        cell_dir = DATA_DIR / "cell_paper"
        assert cell_dir.exists(), "cell_paper 目录不存在"
        assert (cell_dir / "gene_expression_glycotargeting.csv").exists()

    def test_nature_paper_directory(self):
        nature_dir = DATA_DIR / "nature_paper"
        assert nature_dir.exists(), "nature_paper 目录不存在"
        assert (nature_dir / "luad_tp53_rna_seq.csv").exists()

    def test_science_paper_directory(self):
        science_dir = DATA_DIR / "science_paper"
        assert science_dir.exists(), "science_paper 目录不存在"
        assert (science_dir / "her2_protein_sequence.fasta").exists()
        assert (science_dir / "her2_expression_proteomics.csv").exists()
        assert (science_dir / "her2_interaction_data.csv").exists()

    def test_all_files_non_empty(self):
        files = [
            DATA_DIR / "cell_paper" / "gene_expression_glycotargeting.csv",
            DATA_DIR / "nature_paper" / "luad_tp53_rna_seq.csv",
            DATA_DIR / "science_paper" / "her2_protein_sequence.fasta",
            DATA_DIR / "science_paper" / "her2_expression_proteomics.csv",
            DATA_DIR / "science_paper" / "her2_interaction_data.csv",
        ]
        for f in files:
            assert f.exists(), f"文件不存在: {f}"
            assert f.stat().st_size > 0, f"文件为空: {f}"
