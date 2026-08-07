"""核心 Analyzer 模块覆盖率增强测试

补充测试覆盖以下三个模块（提升至 >= 80%）：
- target_identifier.py (22% → 80%+)
- drug_repurposer.py (14% → 80%+)
- evidence_chain.py (57% → 80%+)

测试策略：
- 单元测试使用 Mock（不依赖网络 / DB）
- 重点覆盖未测的分支（异常路径、边界条件、CNV 维度、ClinVar 主动查询）
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK", "true")


# ============================================================
# TargetIdentifier — 补充 _compute_confidence / _assign_grade /
# _build_deep_analysis_prompt / _query_pubmed / discover 路径
# ============================================================

class TestTargetIdentifierComputeConfidenceExtra:
    """_compute_confidence 边界场景与 CNV 维度测试"""

    def _make_identifier(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        return TargetIdentifier(MagicMock())

    def test_cnv_amplification_with_high_copy_number(self):
        """CNV 扩增（拷贝数 >= 6）应得 0.15 分"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="CDK4",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "CDK4", "type": "amplification", "copy_number": 8}],
        )
        # 基础 0.04（无变异）+ 0.03（不在差异集合）+ 0.15（CNV 扩增高拷贝）+ 0.04（无 PPI 基础）+ 0.02（无药物基础）
        # = 0.28
        assert 0.25 <= score <= 0.35

    def test_cnv_amplification_with_low_copy_number(self):
        """CNV 扩增（拷贝数 < 6）应得 0.10 分"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="CDK4",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "CDK4", "type": "amplification", "copy_number": 4}],
        )
        # 基础 0.04 + 0.03 + 0.10 + 0.04 + 0.02 = 0.23
        assert 0.20 <= score <= 0.28

    def test_cnv_loss(self):
        """CNV 缺失（loss/del）应得 0.10 分"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="TP53",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "TP53", "type": "loss", "copy_number": 1}],
        )
        # 基础 0.04 + 0.03 + 0.10 + 0.04 + 0.02 = 0.23
        assert 0.20 <= score <= 0.28

    def test_cnv_with_invalid_copy_number(self):
        """CNV 拷贝数为非数字字符串时不崩溃，按 0 处理"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="MDM2",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "MDM2", "type": "amplification", "copy_number": "invalid"}],
        )
        # copy_num 转 int 失败 → 0，按低拷贝处理 0.10
        assert 0.20 <= score <= 0.28

    def test_cnv_segment_not_matching_gene(self):
        """CNV 段不匹配当前基因时不加分"""
        identifier = self._make_identifier()
        score = identifier._make_identifier_score = identifier._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "KRAS", "type": "amplification", "copy_number": 8}],
        )
        # 不匹配 → 0 CNV 分；基础分 0.04 + 0.03 + 0 + 0.04 + 0.02 = 0.13
        assert 0.10 <= score <= 0.18

    def test_cnv_with_none_cnv_segments(self):
        """cnv_segments=None 时不崩溃"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=None,
        )
        assert 0.05 <= score <= 0.20

    def test_cnv_with_alternative_type_keys(self):
        """CNV 段使用 cnv_type 键而非 type 键时也应识别"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="CDK4",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "CDK4", "cnv_type": "gain", "copy_number": 10}],
        )
        # gain 走 amplification 路径 → 0.15
        assert 0.25 <= score <= 0.35

    def test_cnv_loh_type(self):
        """CNV LOH（loss of heterozygosity）按缺失处理"""
        identifier = self._make_identifier()
        score = identifier._compute_confidence(
            gene="RB1",
            variants=[],
            neighbors=[],
            approved_drugs=[],
            diff_genes_set=set(),
            cnv_segments=[{"gene": "RB1", "type": "loh", "copy_number": 1}],
        )
        # LOH → 0.10
        assert 0.20 <= score <= 0.28

    def test_pathogenic_and_high_impact_variants_combined(self):
        """Pathogenic + HIGH impact 变异叠加加分"""
        identifier = self._make_identifier()
        variants = [
            {"clinvar": {"clnsig": "Pathogenic"}, "impact": "HIGH", "effect": "frameshift_variant"},
            {"clinvar": {"clnsig": "Likely pathogenic"}, "impact": "MODERATE", "effect": "missense_variant"},
            {"clinvar": {"clnsig": "Benign"}, "impact": "LOW", "effect": "synonymous_variant"},
        ]
        score = identifier._compute_confidence(
            gene="EGFR",
            variants=variants,
            neighbors=[{"gene": "KRAS"}, {"gene": "BRAF"}],
            approved_drugs=[{"name": "Osi", "max_phase": 4}],
            diff_genes_set={"EGFR"},
        )
        assert 0.5 <= score <= 1.0

    def test_approved_drugs_phase_4_count_weight(self):
        """max_phase=4 药物数量影响评分"""
        identifier = self._make_identifier()
        # 2 个 phase=4 药物 + 1 个 phase=2 药物
        drugs_with_phase4 = [
            {"name": "Drug1", "max_phase": 4},
            {"name": "Drug2", "max_phase": 4},
            {"name": "Drug3", "max_phase": 2},
        ]
        score = identifier._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=[],
            approved_drugs=drugs_with_phase4,
            diff_genes_set={"EGFR"},
        )
        # 0.04 + 0.15 + 0 + 0.04 + min(0.25, 0.08+0.04*2+0.02*1) = 0.04+0.15+0.04+0.18 = 0.41
        assert 0.35 <= score <= 0.50

    def test_neighbors_ppi_count_weight(self):
        """PPI 邻居数加权"""
        identifier = self._make_identifier()
        # 10 个邻居 → min(0.20, 0.04+0.016*10) = min(0.20, 0.20) = 0.20
        many_neighbors = [{"gene": f"G{i}"} for i in range(10)]
        score = identifier._make_identifier_score = identifier._compute_confidence(
            gene="EGFR",
            variants=[],
            neighbors=many_neighbors,
            approved_drugs=[],
            diff_genes_set=set(),
        )
        # 0.04 + 0.03 + 0 + 0.20 + 0.02 = 0.29
        assert 0.25 <= score <= 0.35


class TestTargetIdentifierAssignGradeExtra:
    """_assign_grade 边界场景测试"""

    def _make_identifier(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        return TargetIdentifier(MagicMock())

    def test_grade_with_many_neighbors(self):
        """5+ 邻居应得 LEVEL_II（即使无通路）"""
        from app.models.target import EvidenceGrade
        identifier = self._make_identifier()
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={},
            neighbors=[{"gene": f"G{i}"} for i in range(5)],
        )
        assert grade == EvidenceGrade.LEVEL_II

    def test_grade_with_exactly_4_neighbors_not_level_ii(self):
        """4 个邻居（<5）且无通路/摘要 → LEVEL_IV"""
        from app.models.target import EvidenceGrade
        identifier = self._make_identifier()
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={},
            neighbors=[{"gene": f"G{i}"} for i in range(4)],
        )
        # 无通路，无摘要，邻居 < 5 → LEVEL_IV
        assert grade == EvidenceGrade.LEVEL_IV

    def test_grade_with_empty_summary_string(self):
        """空字符串 summary 应得 LEVEL_IV"""
        from app.models.target import EvidenceGrade
        identifier = self._make_identifier()
        grade = identifier._assign_grade(
            approved_drugs=[],
            gene_info={"summary": ""},
            neighbors=[],
        )
        assert grade == EvidenceGrade.LEVEL_IV


class TestTargetIdentifierBuildPromptExtra:
    """_build_deep_analysis_prompt 边界场景"""

    def _make_identifier(self):
        from app.services.analyzer.target_identifier import TargetIdentifier
        return TargetIdentifier(MagicMock())

    def test_prompt_with_no_variants(self):
        """无变异时 prompt 应含 '无已知变异'"""
        identifier = self._make_identifier()
        prompt = identifier._build_deep_analysis_prompt({
            "gene_symbol": "EGFR",
            "variant_info": None,
            "pathway": {"ppi_neighbors": []},
            "approved_drugs": [],
            "evidence_grade": "I",
        })
        assert "EGFR" in prompt
        assert "无已知变异" in prompt

    def test_prompt_with_no_drugs(self):
        """无药物时 prompt 应含 '无获批药物'"""
        identifier = self._make_identifier()
        prompt = identifier._build_deep_analysis_prompt({
            "gene_symbol": "TP53",
            "variant_info": [{"query": "chr17:7577538:G>A", "hgvs_p": "p.R273H", "clinvar": {"clnsig": "Pathogenic"}}],
            "pathway": {"ppi_neighbors": [{"gene": "MDM2"}]},
            "approved_drugs": [],
            "evidence_grade": "II",
        })
        assert "无获批药物" in prompt
        assert "MDM2" in prompt

    def test_prompt_with_no_neighbors(self):
        """无 PPI 邻居时 prompt 应含 '无'"""
        identifier = self._make_identifier()
        prompt = identifier._build_deep_analysis_prompt({
            "gene_symbol": "KRAS",
            "variant_info": [],
            "pathway": {"ppi_neighbors": []},
            "approved_drugs": [{"name": "Sotorasib"}],
            "evidence_grade": "I",
        })
        assert "无" in prompt
        assert "Sotorasib" in prompt


class TestTargetIdentifierQueryPubMed:
    """_query_pubmed 方法测试（Mock httpx）"""

    @pytest.mark.asyncio
    async def test_query_pubmed_success(self):
        """PubMed 查询成功返回文献数"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"esearchresult": {"count": "1234", "idlist": ["1", "2"]}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            count = await identifier._query_pubmed("EGFR")
            assert count == 1234

    @pytest.mark.asyncio
    async def test_query_pubmed_network_failure_returns_zero(self):
        """网络失败时返回 0（不抛异常）"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            count = await identifier._query_pubmed("EGFR")
            assert count == 0

    @pytest.mark.asyncio
    async def test_query_pubmed_invalid_json_returns_zero(self):
        """无效 JSON 时返回 0"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        identifier = TargetIdentifier(MagicMock())

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("invalid json")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            count = await identifier._query_pubmed("EGFR")
            assert count == 0


class TestTargetIdentifierDiscoverExtra:
    """discover 主流程补充路径测试"""

    @pytest.mark.asyncio
    async def test_discover_with_cnv_dataset(self):
        """CNV 数据集 → 从 cnv_segments 提取靶点"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-cnv",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="cnv",
            parsed_summary={
                "cnv_segments": [
                    {"gene": "CDK4", "type": "amplification", "copy_number": 8},
                    {"gene": "MDM2", "type": "amplification", "copy_number": 10},
                    {"gene": "TP53", "type": "loss", "copy_number": 1},
                ],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "CDK4", "name": "CDK4"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            # Mock PubMed
            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=10)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="fast_screen",
                )

        assert result["count"] >= 1
        # CDK4/MDM2/TP53 都在 KNOWN_TARGET_GENES 中，应被发现
        target_genes = {t["gene_symbol"] for t in result["targets"]}
        assert "CDK4" in target_genes or "MDM2" in target_genes or "TP53" in target_genes

    @pytest.mark.asyncio
    async def test_discover_with_dict_format_variants(self):
        """variants 含 dict 格式（带 query 字段）应正确提取"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-dict",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={
                "variants": [
                    {"query": "chr7:55259515:T>A", "gene": "EGFR"},  # dict 格式
                    "chr12:25245350:G>A",  # str 格式
                ],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            # 返回注释中含 gene
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR", "clinvar": {"clnsig": "Pathogenic"}},
            ])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="fast_screen",
                )

        # dict 格式 variant 也应被提取
        target_genes = {t["gene_symbol"] for t in result["targets"]}
        assert "EGFR" in target_genes

    @pytest.mark.asyncio
    async def test_discover_with_string_top_genes(self):
        """top_genes 含 str 和 dict 混合格式应正确提取"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-mix",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="rna_seq",
            parsed_summary={
                "top_genes": [
                    {"symbol": "EGFR", "expression": 100},  # dict 格式
                    "KRAS",  # str 格式
                ],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="fast_screen",
                )

        target_genes = {t["gene_symbol"] for t in result["targets"]}
        # EGFR 和 KRAS 都在 KNOWN_TARGET_GENES 中
        assert "EGFR" in target_genes or "KRAS" in target_genes

    @pytest.mark.asyncio
    async def test_discover_with_invalid_top_genes_entry_skipped(self):
        """top_genes 含 None / 非法条目时应跳过"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-invalid",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="rna_seq",
            parsed_summary={
                "top_genes": [
                    None,  # None 应被跳过
                    {"symbol": "EGFR"},  # 有效
                    {"no_symbol": "X"},  # 无 symbol 字段，跳过
                    123,  # 非 str/dict，跳过
                ],
            },
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 3)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="fast_screen",
                )

        # 应不崩溃并返回结果
        assert "count" in result

    @pytest.mark.asyncio
    async def test_discover_gene_query_failure_continues(self):
        """基因查询失败时 fallback 到默认符号，主流程继续"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-g",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": ["chr7:55259515:T>A"]},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        # Mock variant 注释返回 EGFR gene
        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR"},
            ])
            # 基因查询抛异常 → fallback
            mock_gc.return_value.query = AsyncMock(side_effect=Exception("MyGene down"))
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                )

        # 即使基因查询失败，主流程应继续
        assert "count" in result

    @pytest.mark.asyncio
    async def test_discover_existing_target_not_re_added(self):
        """已存在的靶点应被跳过（不重复添加）"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-exist",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": [{"query": "chr7:55259515:T>A", "gene": "EGFR"}]},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]

        # existing target 已存在 → 返回非 None
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = MagicMock()  # 表示已存在
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR"},
            ])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                )

        # 主流程应继续，但 db.add 不应被调用（已存在）
        assert mock_db.add.call_count == 0

    @pytest.mark.asyncio
    async def test_discover_deep_insight_mode(self):
        """deep_insight 模式应调用 LLM 进行深度分析"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-deep",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": [{"query": "chr7:55259515:T>A", "gene": "EGFR"}]},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        # Mock LLM 客户端
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={
            "content": "EGFR 是 NSCLC 关键靶点，推荐 Osimertinib",
            "references": [{"title": "FLAURA trial"}],
        })

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc, \
             patch("app.services.analyzer.target_identifier.get_llm_client", return_value=mock_llm):
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR"},
            ])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="deep_insight",  # 关键：启用深度分析
                )

        # deep_insight 模式应在结果中含 deep_analysis 字段
        assert result["tier"] == "deep_insight"
        # LLM 应被调用
        assert mock_llm.chat.call_count >= 1
        # 至少一个靶点应有 deep_analysis
        top_target = result["targets"][0]
        if "deep_analysis" in top_target:
            assert "EGFR" in top_target["deep_analysis"]

    @pytest.mark.asyncio
    async def test_discover_deep_insight_llm_timeout_skipped(self):
        """deep_insight 模式 LLM 超时时跳过深度分析"""
        import asyncio
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-timeout",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": [{"query": "chr7:55259515:T>A", "gene": "EGFR"}]},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        # LLM 调用超时
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc, \
             patch("app.services.analyzer.target_identifier.get_llm_client", return_value=mock_llm):
            mock_vc.return_value.query_batch = AsyncMock(return_value=[
                {"query": "chr7:55259515:T>A", "gene": "EGFR"},
            ])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="deep_insight",
                )

        # 即使 LLM 超时，主流程应继续
        assert result["tier"] == "deep_insight"

    @pytest.mark.asyncio
    async def test_discover_no_candidates_falls_back_to_defaults(self):
        """无候选基因时回退到默认 EGFR/TP53/KRAS"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-empty",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": [], "top_genes": []},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 5)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            mock_vc.return_value.query_batch = AsyncMock(return_value=[])
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                    tier="fast_screen",
                )

        # 回退到默认 EGFR/TP53/KRAS
        target_genes = {t["gene_symbol"] for t in result["targets"]}
        assert any(g in target_genes for g in {"EGFR", "TP53", "KRAS"})

    @pytest.mark.asyncio
    async def test_discover_variant_client_failure_continues(self):
        """变异注释失败时不阻塞主流程"""
        from app.services.analyzer.target_identifier import TargetIdentifier

        ds = SimpleNamespace(
            id="ds-v",
            project_id="12345678-1234-1234-1234-123456789012",
            data_type="wes",
            parsed_summary={"variants": ["chr7:55259515:T>A"]},
        )
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ds]
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_result] + [existing_result] * 3)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch("app.services.analyzer.target_identifier.get_gene_client") as mock_gc, \
             patch("app.services.analyzer.target_identifier.get_variant_client") as mock_vc, \
             patch("app.services.analyzer.target_identifier.get_chembl_client") as mock_cc:
            # 变异注释抛异常
            mock_vc.return_value.query_batch = AsyncMock(side_effect=Exception("MyVariant down"))
            mock_gc.return_value.query = AsyncMock(return_value={"symbol": "EGFR", "name": "EGFR"})
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=[])

            with patch.object(TargetIdentifier, "_query_pubmed", new=AsyncMock(return_value=0)):
                identifier = TargetIdentifier(mock_db)
                result = await identifier.discover(
                    project_id="12345678-1234-1234-1234-123456789012",
                )

        # 即使变异注释失败，主流程应继续
        assert "count" in result


# ============================================================
# DrugRepurposer — 覆盖 repurpose / _compute_properties / _score_candidate
# ============================================================

class TestDrugRepurposerRepurpose:
    """DrugRepurposer.repurpose 主流程测试"""

    @pytest.mark.asyncio
    async def test_repurpose_with_mock_chembl(self):
        """Mock ChEMBL 客户端 → 返回候选药物列表"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer

        target = SimpleNamespace(gene_symbol="EGFR")
        repurposer = DrugRepurposer(db=None)

        mock_drugs = [
            {"name": "Osimertinib", "chembl_id": "CHEMBL1", "smiles": "Cc1cc2cc(Nc3ccc(F)c(Cl)c3)nc(N)c2c(n1)C",
             "max_phase": 4, "indication": "non-small cell lung cancer", "first_approval": 2015},
            {"name": "Gefitinib", "chembl_id": "CHEMBL2", "smiles": "COC1=C(OCCCN2CCOCC2)C=C2C(NC3=CC=C(F)C(Cl)=C3)=NC=NC2=C1",
             "max_phase": 4, "indication": "breast cancer"},
        ]
        with patch("app.services.analyzer.drug_repurposer.get_chembl_client") as mock_cc:
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=mock_drugs)
            result = await repurposer.repurpose(target)

        assert result["count"] == 2
        assert result["target_gene"] == "EGFR"
        assert result["source"] == "chembl"
        # Osimertinib 应得高分（phase=4 + cancer indication + 通过 Lipinski）
        names = [c["name"] for c in result["candidates"]]
        assert "Osimertinib" in names
        assert "Gefitinib" in names
        # 评分应为 float 类型
        for c in result["candidates"]:
            assert isinstance(c["druglikeness_score"], float)
            assert 0 <= c["druglikeness_score"] <= 100

    @pytest.mark.asyncio
    async def test_repurpose_chembl_failure_returns_empty(self):
        """ChEMBL 查询失败 → 返回空列表（不抛异常）"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer

        target = SimpleNamespace(gene_symbol="UNKNOWN_GENE")
        repurposer = DrugRepurposer(db=None)

        with patch("app.services.analyzer.drug_repurposer.get_chembl_client") as mock_cc:
            mock_cc.return_value.find_approved_drugs = AsyncMock(side_effect=Exception("ChEMBL down"))
            result = await repurposer.repurpose(target)

        assert result["count"] == 0
        assert result["candidates"] == []
        assert result["target_gene"] == "UNKNOWN_GENE"

    @pytest.mark.asyncio
    async def test_repurpose_with_no_smiles(self):
        """药物无 SMILES 时仍可评分（按 max_phase 等）"""
        from app.services.analyzer.drug_repurposer import DrugRepurposer

        target = SimpleNamespace(gene_symbol="EGFR")
        repurposer = DrugRepurposer(db=None)

        mock_drugs = [
            {"name": "Drug-No-Smiles", "chembl_id": "CHEMBL3", "smiles": None,
             "max_phase": 4, "indication": "cancer"},
        ]
        with patch("app.services.analyzer.drug_repurposer.get_chembl_client") as mock_cc:
            mock_cc.return_value.find_approved_drugs = AsyncMock(return_value=mock_drugs)
            result = await repurposer.repurpose(target)

        assert result["count"] == 1
        candidate = result["candidates"][0]
        # 无 SMILES → 不调用 _compute_properties，passes_rule_of_five 默认 True
        assert candidate["passes_rule_of_five"] is True
        # 评分应有 phase=4 加 40 分 + 类药性 30 + cancer 20 + (mw=0 不加) = 90
        assert candidate["druglikeness_score"] == 90.0


class TestDrugRepurposerComputeProperties:
    """DrugRepurposer._compute_properties 测试"""

    def _make_repurposer(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        return DrugRepurposer(db=None)

    def test_compute_properties_valid_smiles(self):
        """有效 SMILES → 返回完整性质"""
        repurposer = self._make_repurposer()
        # 阿司匹林 SMILES
        props = repurposer._compute_properties("CC(=O)Oc1ccccc1C(=O)O")
        # RDKit 已安装时应返回完整字典
        if "error" not in props and "note" not in props:
            assert "mw" in props
            assert "logp" in props
            assert "hbd" in props
            assert "hba" in props
            assert "passes_rule_of_five" in props
            assert "violations" in props
            assert 100 < props["mw"] < 300  # 阿司匹林 MW≈180
        else:
            # RDKit 未安装时返回 note
            assert "note" in props or "error" in props

    def test_compute_properties_invalid_smiles(self):
        """无效 SMILES → 返回 error"""
        repurposer = self._make_repurposer()
        props = repurposer._compute_properties("invalid_smiles_xyz")
        # RDKit 不可用或返回 error
        assert "error" in props or "note" in props

    def test_compute_properties_empty_smiles(self):
        """空 SMILES → 返回空字典"""
        repurposer = self._make_repurposer()
        props = repurposer._compute_properties("")
        assert props == {}

    def test_compute_properties_none_smiles(self):
        """None SMILES → 返回空字典"""
        repurposer = self._make_repurposer()
        props = repurposer._compute_properties(None)
        assert props == {}

    def test_compute_properties_rule_of_five_violations(self):
        """违反 Lipinski 五规则的分子应标记 violations"""
        repurposer = self._make_repurposer()
        # 大分子 SMILES（多肽）
        large_smiles = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
        props = repurposer._compute_properties(large_smiles)
        if "error" not in props and "note" not in props:
            # 大分子应有 violations
            assert isinstance(props.get("violations"), list)


class TestDrugRepurposerScoreCandidate:
    """DrugRepurposer._score_candidate 测试"""

    def _make_repurposer(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        return DrugRepurposer(db=None)

    def test_score_phase_4_drug(self):
        """max_phase=4 药物得 40 分"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": 4, "indication": "cancer"},
            properties={"passes_rule_of_five": True, "mw": 300},
        )
        # 40 (phase) + 30 (Lipinski) + 20 (cancer) + 10 (mw 200-600) = 100
        assert score == 100.0

    def test_score_phase_0_drug(self):
        """max_phase=0 药物得 0 分（phase 部分）"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": 0, "indication": "headache"},
            properties={"passes_rule_of_five": True, "mw": 300},
        )
        # 0 + 30 + 0 + 10 = 40
        assert score == 40.0

    def test_score_with_string_max_phase(self):
        """字符串类型 max_phase 应被转换（防 TypeError）"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": "4", "indication": "cancer"},
            properties={"passes_rule_of_five": True, "mw": 300},
        )
        assert score == 100.0  # 与 int 4 相同

    def test_score_with_invalid_max_phase(self):
        """非法 max_phase 字符串应回退到 0"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": "invalid", "indication": ""},
            properties={"passes_rule_of_five": True, "mw": 300},
        )
        # 0 + 30 + 0 + 10 = 40
        assert score == 40.0

    def test_score_with_lipinski_violations(self):
        """有 Lipinski 违规的分子减分"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": 4, "indication": "cancer"},
            properties={
                "passes_rule_of_five": False,
                "violations": ["MW>500", "LogP>5"],
                "mw": 600,  # mw=600 仍在 200-600 范围
            },
        )
        # 40 + max(0, 30-10*2) + 20 + 10 = 80
        assert score == 80.0

    def test_score_mw_out_of_range(self):
        """分子量超出 200-600 范围不加分"""
        repurposer = self._make_repurposer()
        # mw=100 < 200
        score = repurposer._score_candidate(
            drug={"max_phase": 4, "indication": "cancer"},
            properties={"passes_rule_of_five": True, "mw": 100},
        )
        # 40 + 30 + 20 + 0 = 90
        assert score == 90.0

    def test_score_with_invalid_mw_string(self):
        """非法分子量字符串应回退到 0"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": 0, "indication": "cancer", "molecular_weight": "invalid"},
            properties={"passes_rule_of_five": True},  # properties 无 mw
        )
        # 0 + 30 + 20 + 0 (mw=0 不在 200-600) = 50
        assert score == 50.0

    def test_score_indication_keywords(self):
        """indication 含 tumor/carcinoma 关键词也加分"""
        repurposer = self._make_repurposer()
        for keyword in ["tumor", "carcinoma"]:
            score = repurposer._score_candidate(
                drug={"max_phase": 0, "indication": f"some {keyword} disease"},
                properties={"passes_rule_of_five": True, "mw": 300},
            )
            # 0 + 30 + 20 + 10 = 60
            assert score == 60.0, f"关键词 {keyword} 未加分"

    def test_score_none_indication(self):
        """indication=None 不加分"""
        repurposer = self._make_repurposer()
        score = repurposer._score_candidate(
            drug={"max_phase": 0, "indication": None},
            properties={"passes_rule_of_five": True, "mw": 300},
        )
        # 0 + 30 + 0 + 10 = 40
        assert score == 40.0


# ============================================================
# EvidenceChainBuilder — 覆盖 _summarize_evidence_sources /
# _generate_summary / _enrich_variants_with_clinvar 路径
# ============================================================

class TestEvidenceChainSummarizeExtra:
    """_summarize_evidence_sources 测试"""

    def _make_builder(self):
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder
        return EvidenceChainBuilder(db=None)

    def test_summarize_with_mixed_evidence(self):
        """混合证据源统计"""
        builder = self._make_builder()
        nodes = [
            {"id": "v1", "type": "variant"},
            {"id": "v2", "type": "variant"},
            {"id": "d1", "type": "approved_drug"},
            {"id": "t1", "type": "clinical_trial"},
            {"id": "p1", "type": "pathway"},
            {"id": "g1", "type": "ppi_neighbor"},
        ]
        edges = [
            {"evidence": "ChEMBL"},
            {"evidence": "ChEMBL"},
            {"evidence": "ClinicalTrials.gov"},
            {"evidence": "KEGG"},
            {"evidence": "BioGRID"},
        ]
        result = builder._summarize_evidence_sources(nodes, edges)
        assert result["ChEMBL"] == 2
        assert result["ClinicalTrials.gov"] == 1
        assert result["KEGG"] == 1
        assert result["BioGRID"] == 1
        assert result["_node_types"]["variant"] == 2
        assert result["_node_types"]["approved_drug"] == 1

    def test_summarize_with_empty_lists(self):
        """空列表 → 空统计"""
        builder = self._make_builder()
        result = builder._summarize_evidence_sources([], [])
        assert result == {"_node_types": {}}

    def test_summarize_with_unknown_evidence(self):
        """未知证据源归到 'unknown'（key 缺失时走默认值）"""
        builder = self._make_builder()
        nodes = [{"id": "n1", "type": "unknown_type"}]
        # dict 中无 evidence key → 走默认值 "unknown"
        edges = [{}]
        result = builder._summarize_evidence_sources(nodes, edges)
        assert result["unknown"] == 1
        assert result["_node_types"]["unknown_type"] == 1

    def test_summarize_with_none_evidence_value(self):
        """evidence 值为 None 时归到 None key"""
        builder = self._make_builder()
        nodes = [{"id": "n1", "type": "variant"}]
        edges = [{"evidence": None}]  # None 是 dict 中的值
        result = builder._summarize_evidence_sources(nodes, edges)
        # .get("evidence", "unknown") 当 key 存在时返回 None（非默认值）
        assert result.get(None) == 1 or result.get("unknown") == 1


class TestEvidenceChainGenerateSummaryExtra:
    """_generate_summary 测试"""

    def _make_builder(self):
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder
        return EvidenceChainBuilder(db=None)

    def test_summary_with_pathogenic_variants(self):
        """含 Pathogenic 变异的总结应反映数量"""
        builder = self._make_builder()
        nodes = [
            {"type": "variant", "clnsig": "Pathogenic"},
            {"type": "variant", "clnsig": "Likely pathogenic"},
            {"type": "variant", "clnsig": "Benign"},  # 非 pathogenic
            {"type": "approved_drug"},
            {"type": "clinical_trial"},
            {"type": "pathway"},
            {"type": "ppi_neighbor"},
        ]
        summary = builder._generate_summary(
            gene="EGFR",
            grade="I",
            nodes=nodes,
            grade_counts={"I": 3, "II": 2, "III": 1, "IV": 1},
            evidence_sources={"ChEMBL": 1, "ClinicalTrials.gov": 1},
        )
        assert "EGFR" in summary
        assert "Pathogenic 2" in summary  # Pathogenic + Likely pathogenic
        assert "已获批药物：1" in summary
        assert "临床试验：1" in summary
        assert "通路证据：1" in summary
        assert "PPI 邻居：1" in summary

    def test_summary_with_no_evidence(self):
        """无证据时总结应反映"""
        builder = self._make_builder()
        summary = builder._generate_summary(
            gene="UNKNOWN",
            grade="IV",
            nodes=[],
            grade_counts={"I": 0, "II": 0, "III": 0, "IV": 0},
        )
        assert "UNKNOWN" in summary
        assert "共整合 0 条证据" in summary
        assert "Pathogenic 0" in summary

    def test_summary_with_evidence_sources(self):
        """含 evidence_sources 时总结应包含证据源分布"""
        builder = self._make_builder()
        nodes = [{"type": "variant", "clnsig": "Pathogenic"}]
        summary = builder._generate_summary(
            gene="TP53",
            grade="I",
            nodes=nodes,
            grade_counts={"I": 1, "II": 0, "III": 0, "IV": 0},
            evidence_sources={"NCBI ClinVar (EDirect)": 1, "_node_types": {"variant": 1}},
        )
        assert "NCBI ClinVar (EDirect)=1" in summary


class TestEvidenceChainEnrichVariantsExtra:
    """_enrich_variants_with_clinvar 路径测试"""

    @pytest.mark.asyncio
    async def test_enrich_with_no_gene_returns_original(self):
        """无 gene 时返回原始变异列表"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [{"query": "chr1:1:A>T"}]
        result = await builder._enrich_variants_with_clinvar("", original)
        assert result == original

    @pytest.mark.asyncio
    async def test_enrich_with_existing_clinvar_returns_immediately(self):
        """已有 ClinVar 注释时直接返回原列表"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [
            {"query": "clinvar:12345", "clinvar": {"clnsig": "Pathogenic"}},
        ]
        # Mock _query_clinvar_by_gene 确保不被调用
        with patch.object(builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])) as mock_clinvar:
            result = await builder._enrich_variants_with_clinvar("TP53", original)
            assert mock_clinvar.call_count == 0
        assert result == original

    @pytest.mark.asyncio
    async def test_enrich_myvariant_succeeds_skips_clinvar(self):
        """MyVariant 返回有效 ClinVar 注释时不调 ClinVar EDirect"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [{"query": "chr17:7577538:G>A", "hgvs_p": "p.R273H"}]

        mock_vc = MagicMock()
        mock_vc.query_batch = AsyncMock(return_value=[
            {"query": "chr17:7577538:G>A", "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "12345"}},
        ])

        with patch("app.services.analyzer.evidence_chain.get_variant_client", return_value=mock_vc):
            with patch.object(builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=[])) as mock_clinvar:
                result = await builder._enrich_variants_with_clinvar("TP53", original)
                # MyVariant 成功 → 不调 ClinVar EDirect
                assert mock_clinvar.call_count == 0

        # 结果应含 MyVariant 返回的注释
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_enrich_myvariant_returns_no_clinvar_triggers_edirect(self):
        """MyVariant 返回无 ClinVar 注释 → 触发 ClinVar EDirect"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [{"query": "chr12:57700000:G>A", "hgvs_p": "p.R24C"}]

        mock_vc = MagicMock()
        mock_vc.query_batch = AsyncMock(return_value=[
            {"query": "chr12:57700000:G>A", "gene": "CDK4"},  # 无 clinvar 字段
        ])

        clinvar_result = [
            {"query": "clinvar:9999", "gene": "CDK4", "hgvs_p": "p.Gln270Leu",
             "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "9999"}},
        ]

        with patch("app.services.analyzer.evidence_chain.get_variant_client", return_value=mock_vc):
            with patch.object(builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=clinvar_result)) as mock_clinvar:
                result = await builder._enrich_variants_with_clinvar("CDK4", original)
                assert mock_clinvar.call_count == 1

        # 应含 ClinVar 主动查询的结果
        clinvar_queries = [r for r in result if r.get("query", "").startswith("clinvar:")]
        assert len(clinvar_queries) >= 1

    @pytest.mark.asyncio
    async def test_enrich_get_variant_client_failure_returns_original(self):
        """get_variant_client 失败 → 返回原始列表"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [{"query": "chr1:1:A>T"}]

        with patch("app.services.analyzer.evidence_chain.get_variant_client", side_effect=Exception("init failed")):
            result = await builder._enrich_variants_with_clinvar("EGFR", original)
        # 应返回原始列表（不崩溃）
        assert result == original

    @pytest.mark.asyncio
    async def test_enrich_filters_benign_variants(self):
        """Benign 变异应被过滤掉"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [{"query": "chr1:1:A>T", "hgvs_p": "p.S1F"}]  # 无 ClinVar 注释

        mock_vc = MagicMock()
        mock_vc.query_batch = AsyncMock(return_value=[])

        clinvar_result = [
            {"query": "clinvar:1", "gene": "EGFR", "hgvs_p": "p.L858R",
             "clinvar": {"clnsig": "Pathogenic", "clinvar_id": "1"}},
            {"query": "clinvar:2", "gene": "EGFR", "hgvs_p": "p.S1F",
             "clinvar": {"clnsig": "Benign", "clinvar_id": "2"}},  # 应被过滤
            {"query": "clinvar:3", "gene": "EGFR", "hgvs_p": "p.T790M",
             "clinvar": {"clnsig": "Likely pathogenic", "clinvar_id": "3"}},
        ]

        with patch("app.services.analyzer.evidence_chain.get_variant_client", return_value=mock_vc):
            with patch.object(builder, "_query_clinvar_by_gene", new=AsyncMock(return_value=clinvar_result)):
                result = await builder._enrich_variants_with_clinvar("EGFR", original)

        # Pathogenic + Likely pathogenic 应保留，Benign 应过滤
        clinvar_results = [r for r in result if r.get("query", "").startswith("clinvar:")]
        sigs = [r["clinvar"]["clnsig"] for r in clinvar_results]
        assert "Pathogenic" in sigs
        assert "Likely pathogenic" in sigs
        assert "Benign" not in sigs

    @pytest.mark.asyncio
    async def test_enrich_deduplicates_variants(self):
        """重复变异应去重"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        original = [
            {"query": "clinvar:12345", "clinvar": {"clnsig": "Pathogenic"}},
        ]

        # 原列表已有 clinvar:12345 → 即使 ClinVar 返回相同 query 也应去重
        # 但因已有 ClinVar 注释，应直接返回原列表（不触发 EDirect）
        result = await builder._enrich_variants_with_clinvar("TP53", original)
        assert len(result) == 1


class TestEvidenceChainBuildExtra:
    """EvidenceChainBuilder.build 补充路径测试"""

    def _make_target(self, gene="EGFR", variant_info=None, approved_drugs=None,
                     pathway=None, grade="I"):
        return SimpleNamespace(
            gene_symbol=gene,
            variant_info=variant_info or [],
            approved_drugs=approved_drugs or [],
            evidence_grade=grade,
            pathway=pathway or {"pathways": [], "ppi_neighbors": []},
        )

    @pytest.mark.asyncio
    async def test_build_with_string_pathway_entries(self):
        """通路列表含字符串时应自动包装为 dict"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="EGFR",
            pathway={"pathways": ["hsa04151", "hsa04110"], "ppi_neighbors": []},
        )
        builder = EvidenceChainBuilder(db=None)
        # Mock enrichment 为空列表，跳过 ClinVar
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            result = await builder.build(target)

        # 通路节点应被创建
        pathway_nodes = [n for n in result["nodes"] if n.get("type") == "pathway"]
        assert len(pathway_nodes) == 2

    @pytest.mark.asyncio
    async def test_build_with_string_ppi_neighbors(self):
        """PPI 邻居为字符串时应自动包装为 dict"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="EGFR",
            pathway={"pathways": [], "ppi_neighbors": ["KRAS", "BRAF"]},
        )
        builder = EvidenceChainBuilder(db=None)
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            result = await builder.build(target)

        ppi_nodes = [n for n in result["nodes"] if n.get("type") == "ppi_neighbor"]
        assert len(ppi_nodes) == 2
        labels = {n["label"] for n in ppi_nodes}
        assert "KRAS" in labels
        assert "BRAF" in labels

    @pytest.mark.asyncio
    async def test_build_with_invalid_pathway_entries_skipped(self):
        """无效通路条目（无 id）应被跳过"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="EGFR",
            pathway={
                "pathways": [
                    {"id": "hsa04151", "name": "PI3K-Akt"},  # 有效
                    {"name": "no_id"},  # 无 id，跳过
                    "string_path",  # 字符串，包装为 {id: "string_path"}
                    None,  # None，跳过
                ],
                "ppi_neighbors": [],
            },
        )
        builder = EvidenceChainBuilder(db=None)
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            result = await builder.build(target)

        pathway_nodes = [n for n in result["nodes"] if n.get("type") == "pathway"]
        # 应有 2 个有效通路（hsa04151 + string_path）
        assert len(pathway_nodes) == 2

    @pytest.mark.asyncio
    async def test_build_with_invalid_ppi_neighbors_skipped(self):
        """无效 PPI 邻居（无 gene）应被跳过"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="EGFR",
            pathway={
                "pathways": [],
                "ppi_neighbors": [
                    {"gene": "KRAS"},  # 有效
                    {"interaction": "no_gene"},  # 无 gene，跳过
                    None,  # None，跳过
                ],
            },
        )
        builder = EvidenceChainBuilder(db=None)
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            result = await builder.build(target)

        ppi_nodes = [n for n in result["nodes"] if n.get("type") == "ppi_neighbor"]
        assert len(ppi_nodes) == 1
        assert ppi_nodes[0]["label"] == "KRAS"

    @pytest.mark.asyncio
    async def test_build_clinical_trials_query_failure_continues(self):
        """临床试验查询失败时不影响主流程"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(
            gene="EGFR",
            approved_drugs=[{"name": "Osi", "chembl_id": "CHEMBL1", "max_phase": 4}],
        )
        builder = EvidenceChainBuilder(db=None)
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            with patch("app.services.knowledge.gene_query.query_clinical_trials",
                       new=AsyncMock(side_effect=Exception("CT.gov down"))):
                result = await builder.build(target)

        # 主流程应继续，含药物节点
        drug_nodes = [n for n in result["nodes"] if n.get("type") == "approved_drug"]
        assert len(drug_nodes) == 1

    @pytest.mark.asyncio
    async def test_build_dict_variant_info_converted_to_list(self):
        """variant_info 为 dict 时应转为 list"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = SimpleNamespace(
            gene_symbol="TP53",
            variant_info={"query": "clinvar:12345", "clinvar": {"clnsig": "Pathogenic"}},  # dict
            approved_drugs=[],
            evidence_grade="I",
            pathway={"pathways": [], "ppi_neighbors": []},
        )
        builder = EvidenceChainBuilder(db=None)
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            result = await builder.build(target)

        # dict → list 转换后应正常处理
        assert "nodes" in result
        assert len(result["nodes"]) >= 1  # 至少含 root 节点

    @pytest.mark.asyncio
    async def test_build_phase3_trial_gets_grade_ii(self):
        """Phase 3 临床试验应得 grade=II"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(gene="EGFR")
        builder = EvidenceChainBuilder(db=None)
        mock_trials = {
            "total": 1,
            "trials": [{
                "nct_id": "NCT12345",
                "title": "Phase 3 EGFR trial",
                "phase": ["PHASE3"],
                "status": "RECRUITING",
            }],
        }
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            with patch("app.services.knowledge.gene_query.query_clinical_trials",
                       new=AsyncMock(return_value=mock_trials)):
                result = await builder.build(target)

        trial_nodes = [n for n in result["nodes"] if n.get("type") == "clinical_trial"]
        assert len(trial_nodes) == 1
        assert trial_nodes[0]["grade"] == "II"

    @pytest.mark.asyncio
    async def test_build_non_phase3_trial_gets_grade_iii(self):
        """非 Phase 3 临床试验得 grade=III"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(gene="EGFR")
        builder = EvidenceChainBuilder(db=None)
        mock_trials = {
            "total": 1,
            "trials": [{
                "nct_id": "NCT67890",
                "title": "Phase 1 EGFR trial",
                "phase": ["PHASE1"],
                "status": "RECRUITING",
            }],
        }
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            with patch("app.services.knowledge.gene_query.query_clinical_trials",
                       new=AsyncMock(return_value=mock_trials)):
                result = await builder.build(target)

        trial_nodes = [n for n in result["nodes"] if n.get("type") == "clinical_trial"]
        assert len(trial_nodes) == 1
        assert trial_nodes[0]["grade"] == "III"

    @pytest.mark.asyncio
    async def test_build_with_empty_phase_list(self):
        """空 phase 列表时 grade=III"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target = self._make_target(gene="EGFR")
        builder = EvidenceChainBuilder(db=None)
        mock_trials = {
            "total": 1,
            "trials": [{
                "nct_id": "NCT00000",
                "title": "No phase trial",
                "phase": [],  # 空列表
                "status": "UNKNOWN",
            }],
        }
        with patch.object(builder, "_enrich_variants_with_clinvar", new=AsyncMock(return_value=[])):
            with patch("app.services.knowledge.gene_query.query_clinical_trials",
                       new=AsyncMock(return_value=mock_trials)):
                result = await builder.build(target)

        trial_nodes = [n for n in result["nodes"] if n.get("type") == "clinical_trial"]
        assert len(trial_nodes) == 1
        assert trial_nodes[0]["phase"] == "N/A"
        assert trial_nodes[0]["grade"] == "III"


class TestEvidenceChainQueryClinvarExtra:
    """_query_clinvar_by_gene 异常路径测试（不依赖网络）

    重构说明（阶段 2 适配）：
    - _query_clinvar_by_gene 已重构为通过 NcbiClient.fetch_clinvar_variants() 查询
    - 不再直接调用 httpx，所有 HTTP 错误处理在 NcbiClient 内部完成
    - 测试改为 mock get_ncbi_client 工厂函数，验证 EvidenceChainBuilder 的适配层逻辑
    """

    @pytest.mark.asyncio
    async def test_query_clinvar_http_failure_returns_empty(self):
        """NcbiClient 抛异常 → 返回空列表（不抛异常）"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        mock_vc = MagicMock()

        # Mock NcbiClient 抛出异常（HTTP 失败 / 超时 / 网络错误等）
        mock_ncbi = MagicMock()
        mock_ncbi.fetch_clinvar_variants = AsyncMock(
            side_effect=Exception("HTTP 500")
        )

        with patch("app.core.deps.get_ncbi_client", return_value=mock_ncbi):
            result = await builder._query_clinvar_by_gene(mock_vc, "TP53")
            assert result == []

    @pytest.mark.asyncio
    async def test_query_clinvar_empty_idlist_returns_empty(self):
        """NcbiClient 返回空列表 → 返回空列表"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        mock_vc = MagicMock()

        # Mock NcbiClient 返回空列表（基因无 ClinVar 记录）
        mock_ncbi = MagicMock()
        mock_ncbi.fetch_clinvar_variants = AsyncMock(return_value=[])

        with patch("app.core.deps.get_ncbi_client", return_value=mock_ncbi):
            result = await builder._query_clinvar_by_gene(mock_vc, "UNKNOWN_GENE")
            assert result == []

    @pytest.mark.asyncio
    async def test_query_clinvar_parses_response_correctly(self):
        """NcbiClient 正常返回 → 转换为 evidence_chain 兼容结构"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        mock_vc = MagicMock()

        # Mock NcbiClient 返回标准化的 variant dict（NcbiClient 已处理解析）
        mock_ncbi = MagicMock()
        mock_ncbi.fetch_clinvar_variants = AsyncMock(
            return_value=[
                {
                    "uid": "12345",
                    "title": "NM_000075.4(CDK4):c.809A>T (p.Gln270Leu)",
                    "clnsig": "Pathogenic",
                    "gene": "CDK4",
                    "hgvs_p": "p.Gln270Leu",
                    "hgvs_c": "c.809A>T",
                    "variant_type": "single_nucleotide_variant",
                    "review_status": "criteria provided, multiple submitters",
                    "source": "NCBI ClinVar (E-utilities)",
                }
            ]
        )

        with patch("app.core.deps.get_ncbi_client", return_value=mock_ncbi):
            result = await builder._query_clinvar_by_gene(mock_vc, "CDK4")

        assert len(result) == 1
        variant = result[0]
        assert variant["query"] == "clinvar:12345"
        assert variant["gene"] == "CDK4"
        assert variant["hgvs_p"] == "p.Gln270Leu"
        assert variant["hgvs_c"] == "c.809A>T"
        assert variant["clinvar"]["clnsig"] == "Pathogenic"
        assert variant["clinvar"]["clinvar_id"] == "12345"
        assert variant["source"] == "NCBI ClinVar (E-utilities)"

    @pytest.mark.asyncio
    async def test_query_clinvar_handles_non_dict_clinsig(self):
        """clnsig 缺失时使用默认值 'Pathogenic'（_query_clinvar_by_gene 内部处理）"""
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        builder = EvidenceChainBuilder(db=None)
        mock_vc = MagicMock()

        # Mock NcbiClient 返回的 variant 缺失 clnsig 字段（模拟非 dict / None 情况）
        mock_ncbi = MagicMock()
        mock_ncbi.fetch_clinvar_variants = AsyncMock(
            return_value=[
                {
                    "uid": "1",
                    "title": "NM_xxx:c.1A>T (p.X1Y)",
                    # clnsig 字段缺失 → 应使用默认值 "Pathogenic"
                    "gene": "TEST",
                    "hgvs_p": "p.X1Y",
                    "hgvs_c": "c.1A>T",
                    "variant_type": "single_nucleotide_variant",
                    "review_status": "criteria provided, single submitter",
                    "source": "NCBI ClinVar (E-utilities)",
                }
            ]
        )

        with patch("app.core.deps.get_ncbi_client", return_value=mock_ncbi):
            result = await builder._query_clinvar_by_gene(mock_vc, "TEST")

        assert len(result) == 1
        # clnsig 缺失时应被填充为默认值 "Pathogenic"
        assert "Pathogenic" in result[0]["clinvar"]["clnsig"]
