"""优化器与服务模块集成测试 — TreatmentPlanner/DynamicAdjuster/EfficacyMonitor/FederatedLearner/DrugRepurposer/EvidenceChain/PrivacyLayer/GeneQuery/VariantQuery/Nextflow"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ========== TreatmentPlanner ==========

class TestTreatmentPlanner:
    """治疗方案规划器测试"""

    @pytest.mark.asyncio
    async def test_optimize_rule_based_with_targets(self):
        from app.services.optimizer.treatment_planner import TreatmentPlanner
        from app.models.target import EvidenceGrade

        mock_db = MagicMock()
        targets_result = MagicMock()
        targets_result.scalars.return_value.all.return_value = [
            SimpleNamespace(
                id=uuid4(),
                gene_symbol="EGFR",
                evidence_grade=EvidenceGrade.LEVEL_I,
                confidence_score=0.9,
                approved_drugs=[{"name": "Osimertinib"}],
                variant_info=[],
                pathway={},
            )
        ]
        treatments_result = MagicMock()
        treatments_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[targets_result, treatments_result])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        planner = TreatmentPlanner(mock_db)
        result = await planner.optimize(uuid4())
        assert "combinations" in result
        assert "optimal" in result
        assert result["method"] in ("rule_based", "rl_framework")
        assert len(result["combinations"]) >= 1

    @pytest.mark.asyncio
    async def test_optimize_empty_targets(self):
        from app.services.optimizer.treatment_planner import TreatmentPlanner

        mock_db = MagicMock()
        targets_result = MagicMock()
        targets_result.scalars.return_value.all.return_value = []
        treatments_result = MagicMock()
        treatments_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[targets_result, treatments_result])

        planner = TreatmentPlanner(mock_db)
        result = await planner.optimize(uuid4())
        assert result["optimal"] is None
        assert len(result["combinations"]) == 0

    def test_estimate_efficacy_level_i(self):
        from app.services.optimizer.treatment_planner import TreatmentPlanner, GRADE_SCORE
        from app.models.target import EvidenceGrade

        planner = TreatmentPlanner.__new__(TreatmentPlanner)
        target = SimpleNamespace(
            evidence_grade=EvidenceGrade.LEVEL_I, confidence_score=0.9
        )
        eff = planner._estimate_efficacy(target, combine_with_immuno=False)
        assert 0 < eff <= 1.0
        eff_immuno = planner._estimate_efficacy(target, combine_with_immuno=True)
        assert eff_immuno > eff

    def test_estimate_risk(self):
        from app.services.optimizer.treatment_planner import TreatmentPlanner
        from app.models.target import EvidenceGrade

        planner = TreatmentPlanner.__new__(TreatmentPlanner)
        target_i = SimpleNamespace(evidence_grade=EvidenceGrade.LEVEL_I)
        target_iii = SimpleNamespace(evidence_grade=EvidenceGrade.LEVEL_III)
        risk_single = planner._estimate_risk(target_i, combination=False)
        risk_combo = planner._estimate_risk(target_i, combination=True)
        risk_grade3 = planner._estimate_risk(target_iii, combination=True)
        assert risk_combo > risk_single
        assert risk_grade3 > risk_combo


# ========== DynamicAdjuster ==========

class TestDynamicAdjuster:
    """动态调整器测试"""

    @pytest.mark.asyncio
    async def test_adjust_low_efficacy(self):
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            uuid4(),
            {"current_efficacy": 0.2, "trend": "declining", "adverse_events": []},
        )
        assert result["urgency"] == "high"
        assert len(result["adjustments"]) > 0

    @pytest.mark.asyncio
    async def test_adjust_many_adverse_events(self):
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            uuid4(),
            {"current_efficacy": 0.6, "trend": "stable", "adverse_events": ["a", "b", "c"]},
        )
        assert result["urgency"] in ("high", "critical")
        assert any("剂量" in a for a in result["adjustments"])

    @pytest.mark.asyncio
    async def test_adjust_good_efficacy(self):
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            uuid4(),
            {"current_efficacy": 0.85, "trend": "improving", "adverse_events": []},
        )
        assert result["urgency"] == "low"
        assert any("维持" in a for a in result["adjustments"])

    @pytest.mark.asyncio
    async def test_adjust_stable_moderate(self):
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            uuid4(),
            {"current_efficacy": 0.6, "trend": "stable", "adverse_events": []},
        )
        assert result["urgency"] == "low"

    @pytest.mark.asyncio
    async def test_adjust_declining_moderate(self):
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            uuid4(),
            {"current_efficacy": 0.45, "trend": "declining", "adverse_events": []},
        )
        assert result["urgency"] == "medium"


# ========== EfficacyMonitor ==========

class TestEfficacyMonitor:
    """疗效监测器测试"""

    @pytest.mark.asyncio
    async def test_check_treatment_not_found(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        monitor = EfficacyMonitor(mock_db)
        result = await monitor.check(uuid4())
        assert "error" in result

    @pytest.mark.asyncio
    async def test_check_with_experiments(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        from app.models.experiment import ExperimentStatus

        treatment = SimpleNamespace(name="Test Treatment")
        exp_result = MagicMock()
        exp_result.scalars.return_value.all.return_value = [
            SimpleNamespace(
                name="exp1", result={"efficacy": 0.8, "adverse_events": ["nausea"]},
                success=True, status=ExperimentStatus.COMPLETED,
            ),
            SimpleNamespace(
                name="exp2", result={"efficacy": 0.85, "adverse_events": []},
                success=True, status=ExperimentStatus.COMPLETED,
            ),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=exp_result)
        monitor = EfficacyMonitor(mock_db)
        result = await monitor.check(uuid4())
        assert result["current_efficacy"] > 0
        assert result["trend"] in ("improving", "stable", "declining", "insufficient_data")
        assert "recommendation" in result

    def test_analyze_trend_improving(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.5, 0.7]) == "improving"
        assert monitor._analyze_trend([0.7, 0.5]) == "declining"
        assert monitor._analyze_trend([0.5, 0.52]) == "stable"
        assert monitor._analyze_trend([0.5]) == "insufficient_data"
        assert monitor._analyze_trend([]) == "insufficient_data"

    def test_recommend(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "更换" in monitor._recommend(0.2, "declining", [])
        assert "联合" in monitor._recommend(0.45, "declining", [])
        assert "降低" in monitor._recommend(0.6, "stable", ["a", "b", "c"])
        assert "维持" in monitor._recommend(0.8, "improving", [])
        assert "继续" in monitor._recommend(0.6, "improving", [])
        assert "稳定" in monitor._recommend(0.6, "stable", [])


# ========== FederatedLearner ==========

class TestFederatedLearner:
    """联邦学习器测试"""

    @pytest.mark.asyncio
    async def test_update_weights_framework_only(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        job = await learner.create_job(project_id="p1")
        result = await learner.submit_weights(job["job_id"], "client_1", {"layer1": [0.1, 0.2]})
        assert result["job_id"] == job["job_id"]
        assert "status" in result

    @pytest.mark.asyncio
    async def test_aggregate_empty_models(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        result = learner._aggregate([], 0)
        assert result["aggregated_weights"] == {}
        assert result["num_clients"] == 0

    @pytest.mark.asyncio
    async def test_aggregate_fedavg(self):
        from app.services.optimizer.federated_learning import FederatedLearner
        learner = FederatedLearner()
        models = [
            {"weights": {"l1": 1.0, "l2": 2.0}, "num_samples": 10},
            {"weights": {"l1": 3.0, "l2": 4.0}, "num_samples": 30},
        ]
        result = learner._aggregate(models, 0)
        # (1*10 + 3*30) / 40 = 2.5
        assert abs(result["aggregated_weights"]["l1"] - 2.5) < 0.01


# ========== DrugRepurposer ==========

class TestDrugRepurposer:
    """老药新用引擎测试"""

    @pytest.mark.asyncio
    async def test_repurpose_with_mock_client(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        from app.clients.mock.chembl_mock import MockChemblClient

        with patch("app.services.analyzer.drug_repurposer.get_chembl_client", return_value=MockChemblClient()):
            repurposer = DrugRepurposer(db=None)
            target = SimpleNamespace(gene_symbol="EGFR")
            result = await repurposer.repurpose(target)
            assert result["count"] > 0
            assert "candidates" in result
            assert result["target_gene"] == "EGFR"

    def test_compute_properties_empty(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer.__new__(DrugRepurposer)
        assert repurposer._compute_properties("") == {}

    def test_compute_properties_invalid(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer.__new__(DrugRepurposer)
        result = repurposer._compute_properties("invalid_smiles_xyz")
        assert "error" in result or "note" in result

    def test_score_candidate_approved_cancer(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer.__new__(DrugRepurposer)
        drug = {"max_phase": 4, "indication": "Non-small cell lung cancer"}
        props = {"passes_rule_of_five": True, "mw": 450}
        score = repurposer._score_candidate(drug, props)
        assert score >= 70  # 40 (approved) + 30 (ro5) + 20 (cancer) + 10 (mw)

    def test_score_candidate_no_indication(self):
        from app.services.analyzer.drug_repurposer import DrugRepurposer
        repurposer = DrugRepurposer.__new__(DrugRepurposer)
        drug = {"max_phase": 2, "indication": ""}
        props = {"passes_rule_of_five": False, "violations": ["MW>500", "LogP>5"], "mw": 550}
        score = repurposer._score_candidate(drug, props)
        assert score < 60


# ========== EvidenceChainBuilder ==========

class TestEvidenceChainBuilder:
    """证据链构建器测试"""

    @pytest.mark.asyncio
    async def test_build_with_variants_and_drugs(self):
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder
        from app.models.target import EvidenceGrade

        builder = EvidenceChainBuilder(db=None)
        target = SimpleNamespace(
            gene_symbol="EGFR",
            evidence_grade=EvidenceGrade.LEVEL_I,
            variant_info=[
                {
                    "query": "chr7:55259515:T>A",
                    "hgvs_p": "p.Thr790Met",
                    "clinvar": {"clnsig": "Pathogenic"},
                    "cosmic": {"cosmic_id": "COSM6240"},
                }
            ],
            approved_drugs=[
                {"name": "Osimertinib", "chembl_id": "CHEMBL2114657", "indication": "NSCLC"}
            ],
            pathway={
                "pathways": [
                    {"id": "hsa04012", "name": "ERBB signaling", "source": "KEGG"},
                    "hsa04370",
                ],
                "ppi_neighbors": [
                    "KRAS",
                    {"gene": "PIK3CA", "interaction": "phosphorylates", "evidence": "BioGRID"},
                ],
            },
        )
        result = await builder.build(target)
        assert result["root"] == "EGFR"
        assert len(result["nodes"]) > 0
        assert len(result["edges"]) > 0
        assert "grade_distribution" in result
        assert "summary" in result
        assert "EGFR" in result["summary"]

    @pytest.mark.asyncio
    async def test_build_empty_target(self):
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder
        from app.models.target import EvidenceGrade

        builder = EvidenceChainBuilder(db=None)
        target = SimpleNamespace(
            gene_symbol="NEWGENE",
            evidence_grade=EvidenceGrade.LEVEL_IV,
            variant_info=[],
            approved_drugs=[],
            pathway={},
        )
        result = await builder.build(target)
        assert result["root"] == "NEWGENE"
        assert len(result["nodes"]) == 1  # 仅根节点
        assert result["grade_distribution"]["IV"] == 1

    def test_generate_summary(self):
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder
        builder = EvidenceChainBuilder.__new__(EvidenceChainBuilder)
        nodes = [
            {"type": "variant"},
            {"type": "variant"},
            {"type": "approved_drug"},
            {"type": "clinical_trial"},
            {"type": "pathway"},
            {"type": "ppi_neighbor"},
        ]
        summary = builder._generate_summary("EGFR", "I", nodes, {"I": 2, "II": 1, "III": 2, "IV": 1})
        assert "EGFR" in summary
        assert "2" in summary  # 2 variants


# ========== PrivacyLayer ==========

class TestPrivacyLayer:
    """隐私保护层测试"""

    @pytest.mark.asyncio
    async def test_encrypt_data_simple_anonymize(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        layer = PrivacyLayer()
        result = await layer.encrypt_data({
            "name": "John",
            "email": "john@example.com",
            "gene": "EGFR",
            "nested": {"patient_id": "P001", "data": "ok"},
        })
        assert result["encrypted"] is False
        assert "[REDACTED_name]" in str(result["data"])
        assert "[REDACTED_email]" in str(result["data"])
        assert result["data"]["gene"] == "EGFR"
        assert "[REDACTED_patient_id]" in str(result["data"]["nested"])

    @pytest.mark.asyncio
    async def test_federated_query_framework_only(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        layer = PrivacyLayer()
        result = await layer.federated_query({"targets": ["EGFR"], "centers": ["A", "B"]})
        assert result["status"] in ("framework_only", "framework_ready")

    def test_simple_anonymize_non_dict(self):
        from app.services.knowledge.privacy_layer import PrivacyLayer
        layer = PrivacyLayer()
        assert layer._simple_anonymize("string") == "string"
        assert layer._simple_anonymize([1, 2]) == [1, 2]


# ========== GeneQuery 服务 ==========

class TestGeneQueryService:
    """基因查询服务测试"""

    @pytest.mark.asyncio
    async def test_query_gene_info_mock(self):
        from app.services.knowledge.gene_query import query_gene_info
        result = await query_gene_info("EGFR")
        assert result["symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_query_clinical_trials_egfr(self):
        from app.services.knowledge.gene_query import query_clinical_trials
        result = await query_clinical_trials("EGFR")
        assert result["total"] >= 3
        assert any("Osimertinib" in str(t.get("intervention", [])) for t in result["trials"])

    @pytest.mark.asyncio
    async def test_query_clinical_trials_kras(self):
        from app.services.knowledge.gene_query import query_clinical_trials
        result = await query_clinical_trials("KRAS")
        assert result["total"] >= 2
        assert any("Sotorasib" in str(t.get("intervention", [])) for t in result["trials"])

    @pytest.mark.asyncio
    async def test_query_clinical_trials_unknown(self):
        from app.services.knowledge.gene_query import query_clinical_trials
        result = await query_clinical_trials("UNKNOWN")
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_query_clinical_trials_with_cancer_filter(self):
        from app.services.knowledge.gene_query import query_clinical_trials
        result = await query_clinical_trials("EGFR", cancer_type="lung")
        assert all("lung" in " ".join(t.get("condition", [])).lower() for t in result["trials"])

    @pytest.mark.asyncio
    async def test_batch_query_genes(self):
        from app.services.knowledge.gene_query import batch_query_genes
        results = await batch_query_genes(["EGFR", "KRAS", "TP53"])
        assert len(results) == 3
        assert all("symbol" in r for r in results)


# ========== VariantQuery 服务 ==========

class TestVariantQueryService:
    """变异注释服务测试"""

    @pytest.mark.asyncio
    async def test_annotate_variant(self):
        from app.services.knowledge.variant_query import annotate_variant
        result = await annotate_variant("chr7:55259515:T>A")
        assert result["gene"] == "EGFR"

    @pytest.mark.asyncio
    async def test_batch_annotate(self):
        from app.services.knowledge.variant_query import batch_annotate
        results = await batch_annotate(["chr7:55259515:T>A", "chr12:25245350:G>A"])
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_pathogenic(self):
        from app.services.knowledge.variant_query import filter_pathogenic
        variants = [
            {"clinvar": {"clnsig": "Pathogenic"}},
            {"clinvar": {"clnsig": "Benign"}},
            {"clinvar": {"clnsig": "Likely pathogenic"}},
            {"clinvar": {}},
        ]
        result = await filter_pathogenic(variants)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_drug_resistance_variants(self):
        from app.services.knowledge.variant_query import get_drug_resistance_variants
        variants = [
            {"clinvar": {"condition": "drug response"}},
            {"clinvar": {"condition": "cancer"}},
            {"clinvar": {"condition": "EGFR drug resistance"}},
        ]
        result = await get_drug_resistance_variants(variants)
        assert len(result) == 2


# ========== NextflowRunner ==========

class TestNextflowRunner:
    """Nextflow 工作流执行器测试"""

    @pytest.mark.asyncio
    async def test_run_mock_mode(self):
        from app.services.workflow.nextflow_runner import NextflowRunner
        from app.models.workflow_run import WorkflowRun, WorkflowStatus

        mock_db = MagicMock()
        runner = NextflowRunner(mock_db)
        wf_run = SimpleNamespace(
            pipeline_name="scrna_pipeline",
            params={"input": "/data/input.h5"},
            run_id=None,
            status=None,
            output_path=None,
            duration_sec=None,
            trace_url=None,
            error=None,
        )
        result = await runner.run(wf_run)
        assert result["status"] == WorkflowStatus.COMPLETED
        assert result["mock"] is True
        assert "output_path" in result

    @pytest.mark.asyncio
    async def test_run_mock_rna_seq_pipeline(self):
        from app.services.workflow.nextflow_runner import NextflowRunner

        mock_db = MagicMock()
        runner = NextflowRunner(mock_db)
        wf_run = SimpleNamespace(
            pipeline_name="rna_seq_pipeline",
            params={},
            run_id=None, status=None, output_path=None, duration_sec=None, trace_url=None, error=None,
        )
        result = await runner.run(wf_run)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_check_status_mock(self):
        from app.services.workflow.nextflow_runner import NextflowRunner

        mock_db = MagicMock()
        runner = NextflowRunner(mock_db)
        result = await runner.check_status("nf-test123")
        assert result["status"] == "completed"
        assert result["progress"] == 100
