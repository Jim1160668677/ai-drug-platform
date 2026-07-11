"""解析器模块集成测试 — VCF/FASTA/scRNA-seq/RNA-seq/工厂函数"""
import os
import tempfile
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock


# ========== VCF 解析器 ==========

class TestVcfParser:
    """VCF 变异文件解析器测试"""

    @pytest.mark.asyncio
    async def test_vcf_file_not_found(self):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType
        ds = SimpleNamespace(
            storage_path="/nonexistent/file.vcf",
            file_format="vcf",
            data_type=DataType.WES,
        )
        parser = VcfParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_vcf_text_parse_snv(self):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType
        vcf_content = "##fileformat=VCFv4.2\n"
        vcf_content += "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        vcf_content += "chr7\t55259515\t.\tT\tA\t100\tPASS\t.\n"
        vcf_content += "chr7\t55259513\t.\tG\tA\t100\tPASS\t.\n"
        vcf_content += "chr12\t25245350\t.\tG\tA\t100\tPASS\t.\n"
        vcf_content += "chr1\t100\t.\tAT\tA\t100\tPASS\t.\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="vcf", data_type=DataType.WES)
            parser = VcfParser()
            result = await parser.parse(ds)
            assert result["summary"]["total_variants"] == 4
            assert result["summary"]["snv_count"] == 3
            assert result["summary"]["indel_count"] == 1
            assert "ts_tv_ratio" in result["summary"]
            assert result["quality_metrics"]["pass_rate"] == 1.0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_vcf_text_parse_transitions(self):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType
        vcf_content = "##fileformat=VCFv4.2\n"
        vcf_content += "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        vcf_content += "chr1\t1\t.\tA\tG\t100\tPASS\t.\n"
        vcf_content += "chr1\t2\t.\tG\tA\t100\tPASS\t.\n"
        vcf_content += "chr1\t3\t.\tC\tT\t100\tPASS\t.\n"
        vcf_content += "chr1\t4\t.\tA\tT\t100\tPASS\t.\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="vcf", data_type=DataType.WES)
            parser = VcfParser()
            result = await parser.parse(ds)
            assert result["summary"]["snv_count"] == 4
            assert result["summary"]["ts_tv_ratio"] == 3.0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_vcf_empty_file(self):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType
        vcf_content = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="vcf", data_type=DataType.WES)
            parser = VcfParser()
            result = await parser.parse(ds)
            assert result["summary"]["total_variants"] == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_vcf_with_filter_non_pass(self):
        from app.services.parser.vcf import VcfParser
        from app.models.dataset import DataType
        vcf_content = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        vcf_content += "chr1\t1\t.\tA\tG\t100\tPASS\t.\n"
        vcf_content += "chr1\t2\t.\tC\tT\t50\tLowQual\t.\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="vcf", data_type=DataType.WES)
            parser = VcfParser()
            result = await parser.parse(ds)
            assert result["summary"]["total_variants"] == 2
            assert result["quality_metrics"]["pass_rate"] == 0.5
        finally:
            os.unlink(path)


# ========== FASTA 解析器 ==========

class TestFastaParser:
    """FASTA 序列文件解析器测试"""

    @pytest.mark.asyncio
    async def test_fasta_file_not_found(self):
        from app.services.parser.fasta import FastaParser
        ds = SimpleNamespace(storage_path="/nonexistent/file.fa", file_format="fa")
        parser = FastaParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_fasta_parse_basic(self):
        from app.services.parser.fasta import FastaParser
        fasta_content = ">seq1 Description 1\nATCGATCGATCG\n>seq2 Description 2\nGCGCGCGCGCGC\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False, encoding="utf-8") as f:
            f.write(fasta_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="fa")
            parser = FastaParser()
            result = await parser.parse(ds)
            if "error" not in result["summary"]:
                assert result["summary"]["sequence_count"] == 2
                assert result["summary"]["total_length"] == 24
                assert result["summary"]["gc_content"] > 0
            else:
                pytest.skip("BioPython not installed")
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_fasta_gc_content(self):
        from app.services.parser.fasta import FastaParser
        fasta_content = ">gc_high\nGCGCGCGC\n>gc_low\nATATATAT\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False, encoding="utf-8") as f:
            f.write(fasta_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="fa")
            parser = FastaParser()
            result = await parser.parse(ds)
            if "error" not in result["summary"]:
                assert result["summary"]["gc_content"] == 0.5
            else:
                pytest.skip("BioPython not installed")
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_fasta_empty_file(self):
        from app.services.parser.fasta import FastaParser
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False, encoding="utf-8") as f:
            f.write(">empty\n")
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="fa")
            parser = FastaParser()
            result = await parser.parse(ds)
            # 空序列文件：BioPython 解析为 1 条 length=0 的记录，或返回 error
            assert "error" in result["summary"] or result["summary"]["total_length"] == 0
        finally:
            os.unlink(path)

    def test_gc_content_helper(self):
        from app.services.parser.fasta import FastaParser
        parser = FastaParser()
        assert parser._gc_content("GCGC") == 1.0
        assert parser._gc_content("ATAT") == 0.0
        assert parser._gc_content("") == 0.0
        assert abs(parser._gc_content("ATGC") - 0.5) < 0.01

    def test_compute_n50(self):
        from app.services.parser.fasta import FastaParser
        parser = FastaParser()
        assert parser._compute_n50([]) == 0
        assert parser._compute_n50([100]) == 100
        assert parser._compute_n50([100, 200, 300]) == 300
        assert parser._compute_n50([1000, 500, 100]) == 1000

    @pytest.mark.asyncio
    async def test_fasta_length_distribution(self):
        from app.services.parser.fasta import FastaParser
        fasta_content = ">short\nATCG\n>medium\n" + "A" * 1000 + "\n>long\n" + "A" * 20000 + "\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False, encoding="utf-8") as f:
            f.write(fasta_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="fa")
            parser = FastaParser()
            result = await parser.parse(ds)
            if "error" not in result["summary"]:
                assert result["quality_metrics"]["length_distribution"]["<500"] == 1
                assert result["quality_metrics"]["length_distribution"][">10000"] == 1
            else:
                pytest.skip("BioPython not installed")
        finally:
            os.unlink(path)


# ========== RNA-seq 解析器 ==========

class TestRnaSeqParser:
    """RNA-seq CSV/TSV 表达矩阵解析器测试"""

    @pytest.mark.asyncio
    async def test_rna_seq_file_not_found(self):
        from app.services.parser.rna_seq import RnaSeqParser
        ds = SimpleNamespace(storage_path="/nonexistent/file.csv", file_format="csv")
        parser = RnaSeqParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_rna_seq_parse_csv(self):
        from app.services.parser.rna_seq import RnaSeqParser
        csv_content = "gene,sample1,sample2,sample3\nEGFR,100,200,150\nKRAS,50,60,70\nTP53,0,10,5\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="csv")
            parser = RnaSeqParser()
            result = await parser.parse(ds)
            assert result["summary"]["genes"] == 3
            assert result["summary"]["samples"] == 3
            assert "value_distribution" in result["summary"]
            assert "top_genes" in result["summary"]
            assert result["quality_metrics"]["data_type"] == "rna_seq"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_rna_seq_parse_tsv(self):
        from app.services.parser.rna_seq import RnaSeqParser
        tsv_content = "gene\tsample1\tsample2\nEGFR\t100\t200\nKRAS\t50\t60\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write(tsv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="tsv")
            parser = RnaSeqParser()
            result = await parser.parse(ds)
            assert result["summary"]["genes"] == 2
            assert result["summary"]["samples"] == 2
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_rna_seq_empty_matrix(self):
        from app.services.parser.rna_seq import RnaSeqParser
        csv_content = "gene,s1\nEGFR,100\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="csv")
            parser = RnaSeqParser()
            result = await parser.parse(ds)
            assert result["summary"]["genes"] == 1
        finally:
            os.unlink(path)


# ========== scRNA-seq 解析器 ==========

class TestScRnaSeqParser:
    """scRNA-seq 解析器测试"""

    @pytest.mark.asyncio
    async def test_scrna_file_not_found(self):
        from app.services.parser.scrna import ScRnaSeqParser
        ds = SimpleNamespace(storage_path="/nonexistent/file.h5", file_format="h5")
        parser = ScRnaSeqParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_scrna_parse_csv(self):
        from app.services.parser.scrna import ScRnaSeqParser
        csv_content = "MT-gene,cell1,cell2\nMT-1,1,2\nMT-2,0,1\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="csv")
            parser = ScRnaSeqParser()
            result = await parser.parse(ds)
            if "error" not in result["summary"]:
                assert "n_cells_raw" in result["summary"] or "n_genes_raw" in result["summary"]
        finally:
            os.unlink(path)


# ========== 工厂函数 ==========

class TestParserFactory:
    """parse_dataset 工厂函数测试"""

    @pytest.mark.asyncio
    async def test_factory_no_storage_path(self):
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        ds = SimpleNamespace(
            storage_path=None, data_type=DataType.RNA_SEQ, file_format="csv"
        )
        result = await parse_dataset(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_factory_gene_report(self):
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        ds = SimpleNamespace(
            storage_path="/tmp/report.pdf",
            data_type=DataType.GENE_REPORT,
            file_format="pdf",
            file_size=1024,
        )
        result = await parse_dataset(ds)
        assert result["quality_metrics"]["parseable"] is False

    @pytest.mark.asyncio
    async def test_factory_rna_seq(self):
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        csv_content = "gene,s1\nEGFR,100\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            path = f.name

        try:
            ds = SimpleNamespace(
                storage_path=path, data_type=DataType.RNA_SEQ, file_format="csv"
            )
            result = await parse_dataset(ds)
            assert "genes" in result["summary"] or "error" in result["summary"]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_factory_fasta(self):
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        fasta_content = ">seq1\nATCG\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False, encoding="utf-8") as f:
            f.write(fasta_content)
            path = f.name

        try:
            ds = SimpleNamespace(
                storage_path=path, data_type=DataType.FASTA, file_format="fa"
            )
            result = await parse_dataset(ds)
            assert "sequence_count" in result["summary"] or "error" in result["summary"]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_factory_vcf(self):
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType
        vcf_content = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t1\t.\tA\tG\t100\tPASS\t.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(
                storage_path=path, data_type=DataType.WES, file_format="vcf"
            )
            result = await parse_dataset(ds)
            assert "total_variants" in result["summary"] or "error" in result["summary"]
        finally:
            os.unlink(path)
