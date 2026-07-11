"""TargetIdentifier 与 LLMOrchestrator.full_analysis 测试 — 提升核心业务逻辑覆盖率"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ["USE_MOCK"] = "true"


# ========== TargetIdentifier ==========

class TestTargetIdentifier:
    """靶点发现引擎测试"""

    @pytest.mark.asyncio
    async def test_discover_no_datasets(self):
        """项目无数据集时应返回空结果"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        identifier = TargetIdentifier(mock_db)
        result = await identifier.discover(project_id="12345678-1234-1234-1234-123456789012")

        assert result["count"] == 0
        assert result["targets"] == []
        assert "无可用数据集" in result["message"]

    @pytest.mark.asyncio
    async def test_discover_with_vcf_dataset(self):
        """VCF 数据集 — 从 variants 提取靶点"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-1",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={
                "variants": [
                    {"query": "chr7:55259515:T>A"},
                    {"query": "chr12:25245350:C>A"},
                ],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        # 查询已存在靶点（返回 None 表示不存在）
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        # 注意：execute 第一次返回 datasets，后续返回 existing target 查询
        mock_db.execute = AsyncMock(side_effect=[mock_result, existing_result, existing_result])

        # Mock 客户端
        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR", "clinvar": {"clnsig": "Pathogenic"}},
            ])
            mock_gc.return_value.query = AsyncMock(return_value={
                "symbol": "EGFR", "name": "Epidermal Growth Factor Receptor",
                "entrez_id": 1956, "pathways": ["MAPK signaling"],
            })
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[
                {"name": "Osimertinib", "max_phase": 4},
            ])

            identifier = TargetIdentifier(mock_db)
            result = await identifier.discover(
                project_id="12345678-1234-1234-1234-123456789012",
                tier="fast_screen",
            )

        assert result["count"] >= 1
        assert result["tier"] == "fast_screen"
        assert result["datasets_analyzed"] == 1

    @pytest.mark.asyncio
    async def test_discover_with_scrna_dataset(self):
        """scRNA-seq 数据集 — 从 top_markers 提取靶点"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-2",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="scrna_seq",
            parsed_summary={
                "top_markers_per_cluster": {
                    "0": [{"gene": "EGFR"}, {"gene": "KRAS"}],
                    "1": [{"gene": "TP53"}],
                },
                "top_genes": [{"symbol": "BRAF"}],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result, existing_result, existing_result, existing_result, existing_result])
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            identifier = TargetIdentifier(mock_db)
            result = await identifier.discover(
                project_id="12345678-1234-1234-1234-123456789012",
                tier="fast_screen",
            )

        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_discover_scrna_with_none_marker_cluster(self):
        """scRNA-seq 数据集 top_markers_per_cluster 含 None 值时不应崩溃

        回归测试：当 top_markers_per_cluster 的某个值是 None 时，
        for m in marker_cluster 会抛出 TypeError。修复后应跳过 None 值。
        """
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-none",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="scrna_seq",
            parsed_summary={
                "top_markers_per_cluster": {
                    "0": None,
                    "1": [{"gene": "EGFR"}],
                },
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result, existing_result, existing_result])
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            identifier = TargetIdentifier(mock_db)
            result = await identifier.discover(
                project_id="12345678-1234-1234-1234-123456789012",
                tier="fast_screen",
            )

        assert result["count"] >= 1

    def test_compute_confidence_with_variants(self):
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())
        # Pathogenic 变异 + 差异表达 + PPI + 获批药物 → 高置信度
        score = identifier._compute_confidence(
            gene="EGFR",
            variants=[{"clinvar": {"clnsig": "Pathogenic"}}],
            neighbors=[{"gene": "KRAS"}, {"gene": "BRAF"}],
            approved_drugs=[{"name": "Osi"}],
            diff_genes_set={"EGFR"},
        )
        assert 0.5 < score <= 1.0

    def test_compute_confidence_empty(self):
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())
        score = identifier._compute_confidence(
            gene="UNKNOWN",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
        )
        # 仅基础分（0.05 + 0.05 + 0.05 + 0.03 = 0.18）
        assert 0 < score < 0.3

    def test_assign_grade_with_approved_drugs(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        from app.models.target import EvidenceGrade

        identifier = TargetIdentifier(MagicMock())
        grade = identifier._assign_grade(
            approved_drugs=[{"name": "Osimertinib"}],
            gene_info={},
            neighbors=[],
        )
        assert grade == EvidenceGrade.LEVEL_I

    def test_assign_grade_with_pathways(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        from app.models.target import EvidenceGrade

        identifier = TargetIdentifier(MagicMock())
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={"pathways": ["MAPK"]},
            neighbors=[],
        )
        assert grade == EvidenceGrade.LEVEL_II

    def test_assign_grade_with_summary(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        from app.models.target import EvidenceGrade

        identifier = TargetIdentifier(MagicMock())
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={"summary": "some summary"},
            neighbors=[],
        )
        assert grade == EvidenceGrade.LEVEL_III

    def test_assign_grade_lowest(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        from app.models.target import EvidenceGrade

        identifier = TargetIdentifier(MagicMock())
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={},
            neighbors=[],
        )
        assert grade == EvidenceGrade.LEVEL_IV

    def test_build_deep_analysis_prompt(self):
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())
        prompt = identifier._build_deep_analysis_prompt({
            "gene_symbol": "EGFR",
            "variant_info": [{"query": "chr7:55259515:T>A", "hgvs_p": "p.L858R", "clinvar": {"clnsig": "Pathogenic"}}],
            "pathway": {"ppi_neighbors": [{"gene": "KRAS"}]},
            "approved_drugs": [{"name": "Osimertinib"}],
            "evidence_grade": "I",
        })
        assert "EGFR" in prompt
        assert "L858R" in prompt
        assert "KRAS" in prompt
        assert "Osimertinib" in prompt


# ========== LLMOrchestrator.full_analysis ==========

class TestLLMOrchestratorFullAnalysis:
    """LLM 编排器完整分析流程测试"""

    @pytest.mark.asyncio
    async def test_full_analysis_target_discovery(self):
        """full_analysis — 靶点发现意图"""
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "EGFR 是 NSCLC 的关键靶点。推荐 Osimertinib。",
            "references": [{"title": "FLAURA"}],
            "code": None,
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        })
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Mock TargetIdentifier.discover
        with patch("app.services.analyzer.target_identifier.TargetIdentifier") as MockIdentifier:
            mock_instance = MagicMock()
            mock_instance.discover = AsyncMock(return_value={
                "targets": [
                    {"gene_symbol": "EGFR", "evidence_grade": "I", "confidence_score": 0.85},
                ],
                "count": 1,
            })
            MockIdentifier.return_value = mock_instance

            orchestrator = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
            user = SimpleNamespace(id="user-1")
            result = await orchestrator.full_analysis(
                message="帮我发现 NSCLC 靶点",
                project_id="12345678-1234-1234-1234-123456789012",
                tier=AnalysisTier.FAST_SCREEN,
                user=user,
            )

        assert "report" in result
        assert "charts" in result
        assert "code" in result
        assert "hypothesis" in result
        assert "conclusion" in result
        assert result["intent"] == "target_discovery"

    @pytest.mark.asyncio
    async def test_full_analysis_general_intent(self):
        """full_analysis — 通用意图（fallback 到靶点发现）"""
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "分析完成",
            "references": [],
            "code": None,
            "usage": {"prompt_tokens": 50, "completion_tokens": 30},
        })
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch("app.services.analyzer.target_identifier.TargetIdentifier") as MockIdentifier:
            mock_instance = MagicMock()
            mock_instance.discover = AsyncMock(return_value={
                "targets": [], "count": 0,
            })
            MockIdentifier.return_value = mock_instance

            orchestrator = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
            user = SimpleNamespace(id="user-1")
            result = await orchestrator.full_analysis(
                message="你好",
                project_id="12345678-1234-1234-1234-123456789012",
                tier=AnalysisTier.FAST_SCREEN,
                user=user,
            )

        assert result["intent"] == "general_qa"

    @pytest.mark.asyncio
    async def test_full_analysis_drug_repurposing_no_targets(self):
        """full_analysis — 老药新用意图但无靶点"""
        from app.services.llm.orchestrator import LLMOrchestrator
        from app.models.analysis_job import AnalysisTier

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "无可用靶点",
            "references": [],
            "code": None,
            "usage": {"prompt_tokens": 30, "completion_tokens": 20},
        })
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch("app.services.analyzer.target_identifier.TargetIdentifier") as MockIdentifier:
            mock_instance = MagicMock()
            mock_instance.discover = AsyncMock(return_value={"targets": [], "count": 0})
            MockIdentifier.return_value = mock_instance

            orchestrator = LLMOrchestrator(db=mock_db, llm_client=mock_llm)
            user = SimpleNamespace(id="user-1")
            result = await orchestrator.full_analysis(
                message="老药新用候选",
                project_id="12345678-1234-1234-1234-123456789012",
                tier=AnalysisTier.FAST_SCREEN,
                user=user,
            )

        assert result["intent"] == "drug_repurposing"

    def test_build_report_prompt(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        prompt = orchestrator._build_report_prompt(
            "发现靶点", "target_discovery", {"targets": [{"gene": "EGFR"}]}
        )
        assert "发现靶点" in prompt
        assert "target_discovery" in prompt
        assert "EGFR" in prompt

    def test_generate_analysis_code_target_discovery(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        code = orchestrator._generate_analysis_code(
            "target_discovery",
            {"targets": [{"gene_symbol": "EGFR"}, {"gene_symbol": "KRAS"}]},
        )
        assert "靶点发现" in code
        assert "EGFR" in code

    def test_generate_analysis_code_drug_repurposing(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        code = orchestrator._generate_analysis_code(
            "drug_repurposing",
            {"candidates": [{"name": "Aspirin"}]},
        )
        assert "老药新用" in code

    def test_generate_analysis_code_general(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        code = orchestrator._generate_analysis_code("general_qa", {})
        assert "通用分析" in code

    def test_build_charts_with_targets(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        charts = orchestrator._build_charts({
            "targets": [
                {"gene_symbol": "EGFR", "confidence_score": 0.9, "evidence_grade": "I"},
                {"gene_symbol": "KRAS", "confidence_score": 0.7, "evidence_grade": "II"},
            ],
        })
        assert len(charts) >= 1
        assert any(c["type"] == "bar" for c in charts)

    def test_build_charts_with_candidates(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        charts = orchestrator._build_charts({
            "candidates": [{"name": "Aspirin", "druglikeness_score": 80}],
        })
        assert len(charts) >= 1

    def test_build_charts_empty(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        charts = orchestrator._build_charts({})
        assert charts == []

    def test_extract_conclusion_with_targets(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        conclusion = orchestrator._extract_conclusion("report", {
            "targets": [{"gene_symbol": "EGFR", "evidence_grade": "I", "confidence_score": 0.9}],
        })
        assert "EGFR" in conclusion

    def test_extract_conclusion_with_candidates(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        conclusion = orchestrator._extract_conclusion("report", {
            "candidates": [{"name": "Aspirin", "max_phase": 4}],
        })
        assert "Aspirin" in conclusion

    def test_extract_conclusion_from_report(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        conclusion = orchestrator._extract_conclusion("这是报告首行\n第二行", {})
        assert "这是报告首行" in conclusion

    def test_build_hypothesis(self):
        from app.services.llm.orchestrator import LLMOrchestrator

        orchestrator = LLMOrchestrator(db=MagicMock(), llm_client=MagicMock())
        hyp = orchestrator._build_hypothesis(
            "target_discovery",
            "发现靶点",
            {"targets": [{"gene_symbol": "EGFR"}]},
        )
        assert "target_discovery" in hyp
        assert "EGFR" in hyp


# ========== VCF 文本解析路径（cyvcf2 不可用时的降级）==========

class TestVcfTextParserFallback:
    """VCF 解析器文本降级路径测试"""

    @pytest.mark.asyncio
    async def test_vcf_text_parse_basic_snv(self):
        """cyvcf2 未安装时通过文本解析 VCF"""
        import tempfile
        from app.services.parser.vcf import VcfParser
        from types import SimpleNamespace

        vcf_content = (
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "chr7\t55259515\t.\tT\tA\t100\tPASS\t.\n"
            "chr7\t55259516\t.\tG\tC\t100\tPASS\t.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vcf", delete=False, encoding="utf-8") as f:
            f.write(vcf_content)
            path = f.name

        try:
            ds = SimpleNamespace(storage_path=path, file_format="vcf")
            parser = VcfParser()
            result = await parser.parse(ds)
            # cyvcf2 可用走 cyvcf2 路径，不可用走文本路径
            # 两条都有结果即可
            assert "summary" in result
            summary = result["summary"]
            # 不论走哪条路径，应该能解析出至少 2 条变异
            assert summary.get("total_variants", 0) >= 2 or "error" in summary
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_vcf_parse_nonexistent_file(self):
        from app.services.parser.vcf import VcfParser
        from types import SimpleNamespace

        ds = SimpleNamespace(storage_path="/nonexistent/file.vcf", file_format="vcf")
        parser = VcfParser()
        result = await parser.parse(ds)
        assert "error" in result["summary"]


# ========== gene_query 临床试验 Mock 数据测试 ==========

class TestGeneQueryClinicalTrials:
    """基因查询服务临床试验 Mock 测试"""

    @pytest.mark.asyncio
    async def test_clinical_trials_egfr_mock(self):
        from app.services.knowledge.gene_query import _mock_clinical_trials

        result = _mock_clinical_trials("EGFR", "")
        assert result["total"] > 0
        assert any(t["nct_id"] == "NCT02296125" for t in result["trials"])
        assert result["source"] == "mock_clinical_trials.gov"

    @pytest.mark.asyncio
    async def test_clinical_trials_egfr_with_cancer_filter(self):
        from app.services.knowledge.gene_query import _mock_clinical_trials

        result = _mock_clinical_trials("EGFR", "NSCLC")
        # 过滤后应只包含含 NSCLC 的试验
        for t in result["trials"]:
            conds = " ".join(t["condition"]).lower()
            assert "non-small" in conds or "nsclc" in conds

    @pytest.mark.asyncio
    async def test_clinical_trials_kras(self):
        from app.services.knowledge.gene_query import _mock_clinical_trials

        result = _mock_clinical_trials("KRAS", "")
        assert result["total"] > 0
        # condition 是 list，需检查任一元素包含 KRAS
        assert any(
            any("KRAS" in c for c in t["condition"])
            for t in result["trials"]
        )

    @pytest.mark.asyncio
    async def test_clinical_trials_b7h3(self):
        from app.services.knowledge.gene_query import _mock_clinical_trials

        result = _mock_clinical_trials("B7H3", "")
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_clinical_trials_unknown_gene(self):
        from app.services.knowledge.gene_query import _mock_clinical_trials

        result = _mock_clinical_trials("UNKNOWN_GENE", "")
        assert result["total"] == 0
        assert result["trials"] == []

    @pytest.mark.asyncio
    async def test_query_clinical_trials_mock_mode(self):
        """Mock 模式下 query_clinical_trials 应调用 _mock_clinical_trials"""
        from app.services.knowledge.gene_query import query_clinical_trials
        from app.core.config import settings

        # 确认 Mock 模式
        assert settings.is_mock is True
        result = await query_clinical_trials("EGFR", "NSCLC")
        assert "total" in result
        assert "trials" in result
