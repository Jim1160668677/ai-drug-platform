"""生信数据导入导出测试"""
import pytest

from app.services.analyzer.data_io import BioDataIO


class TestBioDataIO:

    @pytest.mark.asyncio
    async def test_import_csv(self):
        content = b"gene,s1,s2,s3\nTP53,1.0,2.0,3.0\nBRCA1,4.0,5.0,6.0"
        result = await BioDataIO.import_csv(content)
        assert result["format"] == "csv"
        assert "TP53" in result["genes"]
        assert result["genes"]["TP53"] == [1.0, 2.0, 3.0]
        assert result["samples"] == ["s1", "s2", "s3"]

    @pytest.mark.asyncio
    async def test_import_csv_empty(self):
        result = await BioDataIO.import_csv(b"")
        assert result["genes"] == {}

    @pytest.mark.asyncio
    async def test_import_json(self):
        content = b'{"genes": {"G1": [1.0, 2.0]}, "samples": ["s1", "s2"]}'
        result = await BioDataIO.import_json(content)
        assert result["format"] == "json"
        assert "G1" in result["genes"]

    @pytest.mark.asyncio
    async def test_import_fasta(self):
        content = b">seq1\nATCG\n>seq2\nGCTA\nGGGG"
        result = await BioDataIO.import_fasta(content)
        assert result["format"] == "fasta"
        assert result["count"] == 2
        assert result["sequences"][0]["id"] == "seq1"
        assert result["sequences"][0]["seq"] == "ATCG"
        assert result["sequences"][1]["length"] == 8

    @pytest.mark.asyncio
    async def test_import_vcf(self):
        content = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n1\t100\trs1\tA\tT\n2\t200\trs2\tG\tC"
        result = await BioDataIO.import_vcf(content)
        assert result["format"] == "vcf"
        assert result["count"] == 2
        assert result["variants"][0]["chrom"] == "1"
        assert result["variants"][0]["pos"] == 100

    @pytest.mark.asyncio
    async def test_import_mtx(self):
        content = b"%%MatrixMarket matrix coordinate real general\n3 3 4\n1 1 1.0\n1 2 2.0\n2 3 3.0\n3 1 4.0"
        result = await BioDataIO.import_mtx(content)
        assert result["format"] == "mtx"
        assert result["shape"] == [3, 3]
        assert result["nnz"] == 4
        assert len(result["matrix"]) == 4

    @pytest.mark.asyncio
    async def test_export_csv_de(self):
        data = {"genes": [{"gene": "G1", "log2fc": 1.5, "pvalue": 0.01, "padj": 0.02,
                            "regulation": "up", "significant": True}]}
        content = await BioDataIO.export_csv(data)
        text = content.decode("utf-8")
        assert "gene" in text
        assert "G1" in text
        assert "1.5" in text

    @pytest.mark.asyncio
    async def test_export_csv_clusters(self):
        data = {"clusters": [{"gene": "G1", "cluster_id": 0, "pca_x": 1.0, "pca_y": 2.0}]}
        content = await BioDataIO.export_csv(data)
        text = content.decode("utf-8")
        assert "cluster_id" in text
        assert "G1" in text

    @pytest.mark.asyncio
    async def test_export_csv_pathways(self):
        data = {"pathways": [{"id": "hsa0010", "name": "pathway1", "pvalue": 0.01,
                               "ratio": 0.1, "genes": ["G1", "G2"]}]}
        content = await BioDataIO.export_csv(data)
        text = content.decode("utf-8")
        assert "pathway1" in text
        assert "G1;G2" in text

    @pytest.mark.asyncio
    async def test_export_json(self):
        data = {"key": "value", "number": 42}
        content = await BioDataIO.export_json(data)
        import json
        parsed = json.loads(content.decode("utf-8"))
        assert parsed["key"] == "value"
        assert parsed["number"] == 42

    @pytest.mark.asyncio
    async def test_detect_format_by_extension(self):
        assert await BioDataIO.detect_format("data.csv", b"") == "csv"
        assert await BioDataIO.detect_format("data.tsv", b"") == "tsv"
        assert await BioDataIO.detect_format("data.json", b"") == "json"
        assert await BioDataIO.detect_format("data.fasta", b"") == "fasta"
        assert await BioDataIO.detect_format("data.vcf", b"") == "vcf"
        assert await BioDataIO.detect_format("data.mtx", b"") == "mtx"

    @pytest.mark.asyncio
    async def test_detect_format_by_content(self):
        assert await BioDataIO.detect_format("unknown", b">seq1\nATCG") == "fasta"
        assert await BioDataIO.detect_format("unknown", b"##fileformat=VCF") == "vcf"
        assert await BioDataIO.detect_format("unknown", b'{"key": "value"}') == "json"
        assert await BioDataIO.detect_format("unknown", b"plain text") == "csv"

    @pytest.mark.asyncio
    async def test_export_csv_fallback(self):
        data = {"unknown_key": "value"}
        content = await BioDataIO.export_csv(data)
        text = content.decode("utf-8")
        assert "unknown_key" in text
