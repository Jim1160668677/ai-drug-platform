"""新解析器 + EvidenceChainBuilder 增强单元测试

覆盖：
- DicomParser（医学影像元数据解析）
- MultiqcParser（质控报告解析）
- CnvParser（CNV 段表解析，输出 cnv_segments 供 TargetIdentifier 消费）
- EvidenceChainBuilder 增强（NCBI ClinVar EDirect 主动查询）

测试数据：
- 单元测试使用合成数据（不依赖网络 / 真实文件）
- 集成测试使用 Sid Sijbrandij 骨肉瘤数据集（标记 @pytest.mark.integration）
"""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 项目根
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data" / "osteosarc_all"


# ============================================================
# DicomParser 单元测试
# ============================================================

class TestDicomParserUnit:
    """DicomParser 单元测试（合成数据）"""

    @pytest.mark.asyncio
    async def test_dicom_path_not_found(self):
        from app.services.parser.dicom import DicomParser
        ds = SimpleNamespace(storage_path="/nonexistent/dicom.dcm", file_format="dcm", data_type="dicom")
        parser = DicomParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]
        assert "DICOM 路径不存在" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_dicom_no_dcm_files(self):
        """目录存在但无 .dcm 文件"""
        from app.services.parser.dicom import DicomParser
        with tempfile.TemporaryDirectory() as tmpdir:
            # 写一个非 .dcm 文件
            with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
                f.write("not a dicom")
            ds = SimpleNamespace(storage_path=tmpdir, file_format="dcm", data_type="dicom")
            parser = DicomParser()
            result = await parser.parse(ds)
            # 应返回 error：未找到 .dcm 文件
            assert "error" in result["summary"]
            assert result["quality_metrics"]["parseable"] is False

    @pytest.mark.asyncio
    @pytest.mark.skipif(not (DATA_DIR / "dicom").exists(), reason="Sid DICOM 数据未下载")
    async def test_dicom_real_sid_dataset(self):
        """集成测试：解析真实 Sid Sijbrandij DICOM 数据"""
        from app.services.parser.dicom import DicomParser
        dicom_dir = DATA_DIR / "dicom"
        ds = SimpleNamespace(storage_path=str(dicom_dir), file_format="dcm", data_type="dicom")
        parser = DicomParser()
        result = await parser.parse(ds)

        summary = result["summary"]
        quality = result["quality_metrics"]

        # Sid 数据集应至少 8 个 DCM 文件
        assert summary["dcm_file_count"] >= 8, f"DCM 文件数: {summary['dcm_file_count']}"
        assert summary["parsed_instance_count"] >= 8
        assert summary["study_count"] >= 1
        assert summary["series_count"] >= 1
        assert "CT" in summary["modality_distribution"]
        assert summary["modality"] == "CT"
        assert summary["rows"] is not None and summary["rows"] > 0
        assert quality["parse_success_rate"] >= 0.99


# ============================================================
# MultiqcParser 单元测试
# ============================================================

class TestMultiqcParserUnit:
    """MultiqcParser 单元测试（合成数据）"""

    @pytest.mark.asyncio
    async def test_multiqc_path_not_found(self):
        from app.services.parser.multiqc import MultiqcParser
        ds = SimpleNamespace(storage_path="/nonexistent/", file_format="tsv", data_type="multiqc")
        parser = MultiqcParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_multiqc_no_tsv_files(self):
        """目录存在但无 TSV 文件"""
        from app.services.parser.multiqc import MultiqcParser
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "data.csv"), "w") as f:
                f.write("a,b,c")
            ds = SimpleNamespace(storage_path=tmpdir, file_format="tsv", data_type="multiqc")
            parser = MultiqcParser()
            result = await parser.parse(ds)
            # 应返回 error：未找到 .tsv/.txt 质控文件
            assert "error" in result["summary"]
            assert result["quality_metrics"]["parseable"] is False

    @pytest.mark.asyncio
    async def test_multiqc_kv_tsv_format(self):
        """测试 KV TSV 格式（如 BG003082.metrics.tsv）"""
        from app.services.parser.multiqc import MultiqcParser
        kv_content = "Sample\tBG003082\tSARC0277\n"
        kv_content += "Mapping Rate\t0.988738\t0.951234\n"
        kv_content += "Duplicate Rate of Mapped\t0.68493\t0.5\n"
        kv_content += "Total Variants\t1000\t800\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write(kv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="tsv", data_type="multiqc")
            parser = MultiqcParser()
            result = await parser.parse(ds)
            summary = result["summary"]

            assert summary["qc_file_count"] == 1
            assert summary["sample_count"] == 2  # BG003082, SARC0277
            assert "BG003082" in summary["samples"]
            assert "SARC0277" in summary["samples"]
            # 标准化字段应被提取
            bg_sample = next(s for s in summary["sample_qc"] if s["sample_name"] == "BG003082")
            assert bg_sample["mapping_rate"] == pytest.approx(0.988738)
            assert bg_sample["duplicate_rate"] == pytest.approx(0.68493)
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_multiqc_long_tsv_format(self):
        """测试长格式 TSV（首行表头为字段名，不以 Sample\t 开头）"""
        from app.services.parser.multiqc import MultiqcParser
        # 长格式：首行是字段名（Category + 突变类型），首列是统计项
        # 注意：首行不以 "Sample\t" 开头，避免被误判为 KV 格式
        long_content = "Category\tA>C\tA>G\tA>T\n"
        long_content += "strelka.variants\t188868.0\t672647.0\t164462.0\n"
        long_content += "mutect2.filtered\t68003.0\t222081.0\t87342.0\n"

        # 文件名需含 "bcftools" 关键字以触发 _detect_tool 的工具识别
        with tempfile.NamedTemporaryFile(mode="w", suffix="_bcftools_stats.txt", delete=False, encoding="utf-8") as f:
            f.write(long_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="tsv", data_type="multiqc")
            parser = MultiqcParser()
            result = await parser.parse(ds)
            summary = result["summary"]

            assert summary["qc_file_count"] == 1
            tool_reports = summary["tool_reports"]
            assert "bcftools" in tool_reports  # 文件名含 bcftools 触发工具识别
            assert tool_reports["bcftools"]["format"] == "long_tsv"
            assert tool_reports["bcftools"]["row_count"] == 2
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not (DATA_DIR / "multiqc").exists(), reason="Sid MultiQC 数据未下载")
    async def test_multiqc_real_sid_dataset(self):
        """集成测试：解析真实 Sid MultiQC 数据集"""
        from app.services.parser.multiqc import MultiqcParser
        multiqc_dir = DATA_DIR / "multiqc"
        ds = SimpleNamespace(storage_path=str(multiqc_dir), file_format="tsv", data_type="multiqc")
        parser = MultiqcParser()
        result = await parser.parse(ds)

        summary = result["summary"]
        assert summary["qc_file_count"] >= 8
        assert len(summary["tool_reports"]) >= 3
        assert summary["sample_count"] >= 1


# ============================================================
# CnvParser 单元测试
# ============================================================

class TestCnvParserUnit:
    """CnvParser 单元测试"""

    @pytest.mark.asyncio
    async def test_cnv_path_not_found(self):
        from app.services.parser.cnv import CnvParser
        ds = SimpleNamespace(storage_path="/nonexistent/cnv.csv", file_format="csv", data_type="cnv")
        parser = CnvParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_cnv_tempus_format(self):
        """测试 Tempus annotated_cnv_v2.segments.csv 格式"""
        from app.services.parser.cnv import CnvParser
        csv_content = "chrom,start,stop,amplification,major_copy_number,minor_copy_number\n"
        csv_content += "1,1850330,6500990,loss,0,1\n"          # 缺失
        csv_content += "1,16909030,18000000,gain,3,1\n"         # 扩增
        csv_content += "12,57700000,58200000,gain,6,2\n"        # CDK4 扩增（8 拷贝）
        csv_content += "17,7550000,7700000,loss,0,1\n"          # TP53 缺失
        csv_content += "12,68800000,69300000,gain,5,3\n"        # MDM2 扩增（8 拷贝）
        csv_content += "X,100000,200000,neutral,1,1\n"         # 中性（跳过）

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="csv", data_type="cnv")
            parser = CnvParser()
            result = await parser.parse(ds)
            summary = result["summary"]

            assert summary["format_source"] == "tempus"
            assert summary["total_segments"] == 6
            assert summary["total_cnv_calls"] == 5  # neutral 跳过
            assert summary["amplification_count"] == 3
            assert summary["loss_count"] == 2

            # 验证 cnv_segments 格式（TargetIdentifier 期望）
            cnv_segs = summary["cnv_segments"]
            assert len(cnv_segs) == 5
            # CDK4 扩增段（拷贝数 = 6+2 = 8）
            cdk4_seg = next(s for s in cnv_segs if s["start"] == 57700000)
            assert cdk4_seg["type"] == "amplification"
            assert cdk4_seg["copy_number"] == 8
            assert cdk4_seg["major_copy_number"] == 6

            # 质量指标
            quality = result["quality_metrics"]
            assert quality["parseable"] is True
            assert quality["amplification_rate"] == pytest.approx(0.6)  # 3/5
            assert quality["loss_rate"] == pytest.approx(0.4)  # 2/5
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_cnv_cnvkit_format(self):
        """测试 CNVkit genemetrics TSV 格式"""
        from app.services.parser.cnv import CnvParser
        tsv_content = "gene\tchromosome\tstart\tend\tlog2\tcn\n"
        tsv_content += "CDK4\t12\t57700000\t58200000\t1.0\t8\n"     # 扩增（log2>0.5）
        tsv_content += "TP53\t17\t7550000\t7700000\t-1.0\t0\n"     # 缺失（log2<-0.5）
        tsv_content += "MDM2\t12\t68800000\t69300000\t1.5\t10\n"    # 扩增
        tsv_content += "GAPDH\t12\t6500000\t6600000\t0.1\t2\n"     # 中性（log2 在 [-0.5, 0.5]，跳过）

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write(tsv_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="tsv", data_type="cnv")
            parser = CnvParser()
            result = await parser.parse(ds)
            summary = result["summary"]

            assert summary["format_source"] == "cnvkit"
            assert summary["total_cnv_calls"] == 3  # GAPDH 中性被跳过
            assert summary["amplification_count"] == 2
            assert summary["loss_count"] == 1

            # 基因映射应包含 CDK4/TP53/MDM2
            assert "CDK4" in summary["gene_cnv"]
            assert summary["gene_cnv"]["CDK4"]["type"] == "amplification"
            assert summary["gene_cnv"]["TP53"]["type"] == "loss"
            assert summary["gene_cnv_count"] == 3
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not (DATA_DIR / "wes" / "TL-24-ALMY2X4KMV.annotated_cnv_v2.segments.csv").exists(),
        reason="Sid CNV 数据未下载",
    )
    async def test_cnv_real_sid_dataset(self):
        """集成测试：解析真实 Sid CNV 数据"""
        from app.services.parser.cnv import CnvParser
        cnv_path = DATA_DIR / "wes" / "TL-24-ALMY2X4KMV.annotated_cnv_v2.segments.csv"
        ds = SimpleNamespace(storage_path=str(cnv_path), file_format="csv", data_type="cnv")
        parser = CnvParser()
        result = await parser.parse(ds)
        summary = result["summary"]

        assert summary["format_source"] == "tempus"
        assert summary["total_segments"] == 240
        assert summary["total_cnv_calls"] > 50
        assert summary["amplification_count"] > 30
        assert summary["loss_count"] > 10


# ============================================================
# EvidenceChainBuilder 增强单元测试
# ============================================================

class TestEvidenceChainBuilderEnhancement:
    """EvidenceChainBuilder ClinVar 主动查询增强测试"""

    def _make_target(self, gene="CDK4", variant_info=None, approved_drugs=None, pathway=None, grade="I"):
        """构造最小可用 Target 对象"""
        return SimpleNamespace(
            gene_symbol=gene,
            variant_info=variant_info or [],
            approved_drugs=approved_drugs or [],
            evidence_grade=grade,
            pathway=pathway or {"pathways": [], "ppi_neighbors": []},
        )

    @pytest.mark.asyncio
    async def test_evidence_chain_with_existing_clinvar(self):
        """已有 ClinVar 注释的变异 → 直接使用，不再查询"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="TP53",
            variant_info=[{
                "query": "clinvar:12345",
                "hgvs_p": "p.R273H",
                "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "12345"},
                "cosmic": {"cosmic_id": "COSM123"},
            }],
            approved_drugs=[{"name": "Test", "chembl_id": "CHEMBL1", "max_phase": 4}],
            pathway={"pathways": ["hsa04151"], "ppi_neighbors": [{"gene": "MDM2"}]},
        )

        builder = EvidenceChainBuilder(db=None)
        # Mock _query_clinvar_by_gene 确保不被调用
        with patch.object(
            builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])
        ) as mock_clinvar:
            result = await builder.build(target)
            # 应直接使用已有 ClinVar，不调用 _query_clinvar_by_gene
            assert mock_clinvar.call_count == 0

        # 验证结果包含 Pathogenic 变异节点
        variant_nodes = [n for n in result["nodes"] if n.get("type") == "variant"]
        assert len(variant_nodes) >= 1
        assert any("pathogenic" in (n.get("clnsig") or "").lower() for n in variant_nodes)

    @pytest.mark.asyncio
    async def test_evidence_chain_clinvar_fallback(self):
        """无 ClinVar 注释 → 主动调用 _query_clinvar_by_gene"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="CDK4",
            variant_info=[{"query": "chr12:57700000:G>A", "hgvs_p": "p.R24C"}],  # 无 clinvar 字段
            approved_drugs=[],
        )

        builder = EvidenceChainBuilder(db=None)
        # Mock MyVariant 批量查询返回空（触发 ClinVar fallback）
        mock_vc = MagicMock()
        mock_vc.query_batch = AsyncMock(return_value=[])

        # Mock _query_clinvar_by_gene 返回 1 条 Pathogenic 变异
        clinvar_variants = [{
            "query": "clinvar:9999",
            "gene": "CDK4",
            "hgvs_p": "p.Gln270Leu",
            "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "9999"},
            "cosmic": None,
            "gnomad": None,
            "source": "NCBI ClinVar (EDirect)",
        }]

        with patch("app.services.analyzer.evidence_chain.get_variant_client", return_value=mock_vc):
            with patch.object(
                builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=clinvar_variants)
            ) as mock_clinvar:
                result = await builder.build(target)
                # 应触发 ClinVar fallback
                assert mock_clinvar.call_count == 1

        # 验证结果包含 1 条 Pathogenic 变异
        variant_nodes = [n for n in result["nodes"] if n.get("type") == "variant"]
        pathogenic_nodes = [n for n in variant_nodes if "pathogenic" in (n.get("clnsig") or "").lower()]
        assert len(pathogenic_nodes) >= 1
        assert any(n.get("source") == "NCBI ClinVar (EDirect)" for n in pathogenic_nodes)

    @pytest.mark.asyncio
    async def test_evidence_chain_no_variants_at_all(self):
        """无任何变异 → 触发 ClinVar 主动查询"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="MDM2",
            variant_info=[],
            approved_drugs=[],
            pathway={"pathways": [], "ppi_neighbors": []},
        )

        builder = EvidenceChainBuilder(db=None)
        clinvar_variants = [{
            "query": "clinvar:8888",
            "gene": "MDM2",
            "hgvs_p": "p.Leu205Val",
            "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "8888"},
        }]

        with patch.object(
            builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=clinvar_variants)
        ):
            result = await builder.build(target)

        # 至少有 root + 1 个变异节点
        assert len(result["nodes"]) >= 2
        variant_nodes = [n for n in result["nodes"] if n.get("type") == "variant"]
        assert len(variant_nodes) >= 1

    @pytest.mark.asyncio
    async def test_evidence_chain_grade_distribution(self):
        """证据等级分布正确（I/II/III/IV）"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="BRCA1",
            variant_info=[{
                "query": "clinvar:111",
                "hgvs_p": "p.Leu752Ter",
                "clinvar": {"clnsig": "Pathogenic"},
            }],
            approved_drugs=[{"name": "OLAPARIB", "chembl_id": "CHEMBL52437", "max_phase": 4}],
            pathway={"pathways": [{"id": "hsa04115", "name": "p53", "source": "KEGG"}],
                    "ppi_neighbors": [{"gene": "BRCA2", "interaction": "interacts_with", "evidence": "BioGRID"}]},
        )

        builder = EvidenceChainBuilder(db=None)
        with patch.object(
            builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])
        ):
            with patch(
                "app.services.knowledge.gene_query.query_clinical_trials",
                new=AsyncMock(return_value={"trials": [], "total": 0}),
            ):
                result = await builder.build(target)

        grade_counts = result["grade_distribution"]
        # 应至少有 1 个 Grade I 节点（变异 Pathogenic + max_phase=4 药物）
        assert grade_counts["I"] >= 1
        # 总节点数应 > 1（root + 至少 1 个证据节点）
        assert result["total_evidence"] >= 2

    @pytest.mark.asyncio
    async def test_evidence_chain_evidence_sources_summary(self):
        """evidence_sources 字段正确汇总"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="KRAS",
            variant_info=[{
                "query": "clinvar:222",
                "hgvs_p": "p.G12C",
                "clinvar": {"clnsig": "Pathogenic"},
            }],
            approved_drugs=[{"name": "SOTORASIB", "chembl_id": "CHEMBL4394831", "max_phase": 3}],
        )

        builder = EvidenceChainBuilder(db=None)
        with patch.object(
            builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])
        ):
            with patch(
                "app.services.knowledge.gene_query.query_clinical_trials",
                new=AsyncMock(return_value={"trials": [], "total": 0}),
            ):
                result = await builder.build(target)

        sources = result["evidence_sources"]
        # 应包含 ClinVar 和 ChEMBL
        assert "ClinVar" in sources
        assert "ChEMBL" in sources
        # _node_types 应统计节点类型分布
        assert "_node_types" in sources
        assert "variant" in sources["_node_types"]
        assert "approved_drug" in sources["_node_types"]

    @pytest.mark.asyncio
    async def test_evidence_chain_pathogenic_count_in_summary(self):
        """生成的 summary 文本含 Pathogenic 变异计数"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="TP53",
            variant_info=[{
                "query": "clinvar:333",
                "hgvs_p": "p.R175H",
                "clinvar": {"clnsig": "Pathogenic"},
            }],
            approved_drugs=[],
        )

        builder = EvidenceChainBuilder(db=None)
        with patch.object(
            builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])
        ):
            with patch(
                "app.services.knowledge.gene_query.query_clinical_trials",
                new=AsyncMock(return_value={"trials": [], "total": 0}),
            ):
                result = await builder.build(target)

        summary_text = result["summary"]
        # summary 应含 "Pathogenic" 字样和致病变异计数
        assert "Pathogenic" in summary_text
        assert "1" in summary_text  # 1 条 Pathogenic 变异


# ============================================================
# 工厂路由测试（验证 base.py 正确路由到新解析器）
# ============================================================

class TestParserFactoryRouting:
    """工厂函数 parse_dataset 路由测试"""

    @pytest.mark.asyncio
    async def test_factory_routes_dicom(self):
        """工厂函数正确路由 DICOM 类型到 DicomParser"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        ds = SimpleNamespace(
            storage_path="/nonexistent/dicom.dcm",
            file_format="dcm",
            data_type=DataType.DICOM,
        )
        result = await parse_dataset(ds)
        # 路径不存在时返回 error，但已正确路由到 DicomParser
        assert "error" in result["summary"]
        assert "DICOM" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_factory_routes_multiqc(self):
        """工厂函数正确路由 MULTIQC 类型到 MultiqcParser"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        ds = SimpleNamespace(
            storage_path="/nonexistent/multiqc/",
            file_format="tsv",
            data_type=DataType.MULTIQC,
        )
        result = await parse_dataset(ds)
        # 路径不存在时返回 error
        assert "error" in result["summary"]

    @pytest.mark.asyncio
    async def test_factory_routes_cnv(self):
        """工厂函数正确路由 CNV 类型到 CnvParser"""
        from app.services.parser.base import parse_dataset
        from app.models.dataset import DataType

        ds = SimpleNamespace(
            storage_path="/nonexistent/cnv.csv",
            file_format="csv",
            data_type=DataType.CNV,
        )
        result = await parse_dataset(ds)
        assert "error" in result["summary"]


# ============================================================
# TargetIdentifier CNV 增强单元测试
# ============================================================

class TestTargetIdentifierCNV:
    """TargetIdentifier._compute_confidence CNV 维度增强测试"""

    def test_compute_confidence_cnv_amplification(self):
        """扩增基因（CDK4 高拷贝数）应得 0.15 分"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ti = TargetIdentifier.__new__(TargetIdentifier)
        score = ti._compute_confidence(
            gene="CDK4",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"CDK4"},
            cnv_segments=[{"gene": "CDK4", "type": "amplification", "copy_number": 8}],
        )
        # CNV 扩增高拷贝数 → 0.15 + 差异表达 0.15 + 其他基础分
        # 至少应 >= 0.30
        assert score >= 0.30, f"CDK4 扩增置信度: {score}"

    def test_compute_confidence_cnv_loss(self):
        """缺失基因（TP53）应得 0.10 分"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ti = TargetIdentifier.__new__(TargetIdentifier)
        score = ti._compute_confidence(
            gene="TP53",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"TP53"},
            cnv_segments=[{"gene": "TP53", "type": "loss", "copy_number": 1}],
        )
        # CNV 缺失 → 0.10 + 差异表达 0.15
        assert score >= 0.25, f"TP53 缺失置信度: {score}"

    def test_compute_confidence_no_cnv(self):
        """无 CNV 数据时不影响置信度"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ti = TargetIdentifier.__new__(TargetIdentifier)
        score_no_cnv = ti._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"EGFR"},
            cnv_segments=None,
        )
        score_empty_cnv = ti._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"EGFR"},
            cnv_segments=[],
        )
        # 两者应相等
        assert score_no_cnv == pytest.approx(score_empty_cnv)

    def test_compute_confidence_cnv_amplification_low_copy(self):
        """低拷贝数扩增（copy_number < 6）应得 0.10 分"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ti = TargetIdentifier.__new__(TargetIdentifier)
        score_high = ti._compute_confidence(
            gene="MYC",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"MYC"},
            cnv_segments=[{"gene": "MYC", "type": "amplification", "copy_number": 8}],
        )
        score_low = ti._compute_confidence(
            gene="MYC",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"MYC"},
            cnv_segments=[{"gene": "MYC", "type": "amplification", "copy_number": 4}],
        )
        # 高拷贝数应 > 低拷贝数
        assert score_high > score_low

    def test_compute_confidence_cnv_with_variants(self):
        """CNV 扩增 + HIGH impact 变异 → 置信度更高"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ti = TargetIdentifier.__new__(TargetIdentifier)
        score_with_both = ti._compute_confidence(
            gene="MDM2",
            variants=[{"impact": "HIGH", "effect": "frameshift_variant"}],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"MDM2"},
            cnv_segments=[{"gene": "MDM2", "type": "amplification", "copy_number": 8}],
        )
        score_no_cnv = ti._compute_confidence(
            gene="MDM2",
            variants=[{"impact": "HIGH", "effect": "frameshift_variant"}],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set={"MDM2"},
            cnv_segments=None,
        )
        # 有 CNV 扩增应 > 无 CNV
        assert score_with_both > score_no_cnv
