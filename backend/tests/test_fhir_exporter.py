"""HL7 FHIR R4 导出器单元测试

覆盖：
- Patient 资源导出（字段完整性 + 假名脱敏）
- Observation 资源导出（LOINC 编码 + 质量指标）
- Condition 资源导出（SNOMED CT + 证据等级映射）
- MedicationStatement 资源导出（状态映射 + 疗效评分）
- Bundle 结构完整性
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.cdisc.fhir_exporter import FHIRExporter


# ============================================================
# 测试数据工厂
# ============================================================
def make_project(**kwargs):
    p = MagicMock()
    p.id = kwargs.get("id", uuid4())
    p.name = kwargs.get("name", "Test Project")
    p.patient_pseudonym = kwargs.get("patient_pseudonym", "PATIENT-001")
    p.cancer_type = kwargs.get("cancer_type", "NSCLC")
    p.stage = kwargs.get("stage", "IIIB")
    p.status = kwargs.get("status", "active")
    p.description = kwargs.get("description", "Test description")
    p.updated_at = kwargs.get("updated_at", None)
    return p


def make_dataset(**kwargs):
    d = MagicMock()
    d.id = kwargs.get("id", uuid4())
    d.name = kwargs.get("name", "RNA-seq Dataset")
    d.data_type = kwargs.get("data_type", "rna_seq")
    d.parse_status = kwargs.get("parse_status", "completed")
    d.quality_metrics = kwargs.get("quality_metrics", {"coverage": 30.5, "read_count": 50000000})
    d.parsed_summary = kwargs.get("parsed_summary", {"total_genes": 20000})
    d.created_at = kwargs.get("created_at", None)
    return d


def make_target(**kwargs):
    t = MagicMock()
    t.id = kwargs.get("id", uuid4())
    t.gene_symbol = kwargs.get("gene_symbol", "EGFR")
    t.gene_name = kwargs.get("gene_name", "Epidermal Growth Factor Receptor")
    t.evidence_grade = kwargs.get("evidence_grade", "A")
    t.confidence_score = kwargs.get("confidence_score", 0.95)
    t.source = kwargs.get("source", "COSMIC")
    t.created_at = kwargs.get("created_at", None)
    return t


def make_treatment(**kwargs):
    tr = MagicMock()
    tr.id = kwargs.get("id", uuid4())
    tr.name = kwargs.get("name", "Osimertinib 80mg")
    tr.therapy_type = kwargs.get("therapy_type", "targeted")
    tr.status = kwargs.get("status", "effective")
    tr.efficacy_score = kwargs.get("efficacy_score", 0.85)
    tr.risk_score = kwargs.get("risk_score", 0.15)
    tr.confidence = kwargs.get("confidence", 0.90)
    tr.created_at = kwargs.get("created_at", None)
    return tr


# ============================================================
# Patient 资源导出
# ============================================================
class TestExportPatient:
    def test_resource_type_is_patient(self):
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project()
        result = exporter.export_patient(patient)
        assert result["resourceType"] == "Patient"

    def test_identifier_contains_pseudonym(self):
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project(patient_pseudonym="PSEUDO-123")
        result = exporter.export_patient(patient)
        assert any(i["value"] == "PSEUDO-123" for i in result["identifier"])

    def test_active_status_mapped(self):
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project(status="active")
        result = exporter.export_patient(patient)
        assert result["active"] is True

    def test_inactive_status_mapped(self):
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project(status="archived")
        result = exporter.export_patient(patient)
        assert result["active"] is False

    def test_cancer_type_extension(self):
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project(cancer_type="NSCLC")
        result = exporter.export_patient(patient)
        ext = [e for e in result["extension"] if "cancerType" in e["url"]]
        assert len(ext) == 1
        assert ext[0]["valueString"] == "NSCLC"

    def test_pseudonymization_tag(self):
        """Patient 资源应标记为已脱敏"""
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project()
        result = exporter.export_patient(patient)
        tags = result.get("meta", {}).get("tag", [])
        assert any(t.get("code") == "PSEUDED" for t in tags)

    def test_name_is_anonymous(self):
        """姓名使用 anonymous 用途标记"""
        exporter = FHIRExporter(db=MagicMock())
        patient = make_project(patient_pseudonym="ANON-001")
        result = exporter.export_patient(patient)
        assert result["name"][0]["use"] == "anonymous"
        assert result["name"][0]["text"] == "ANON-001"


# ============================================================
# Observation 资源导出
# ============================================================
class TestExportObservation:
    def test_resource_type_is_observation(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset()
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert result["resourceType"] == "Observation"

    def test_rna_seq_loinc_mapping(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset(data_type="rna_seq")
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        coding = result["code"]["coding"][0]
        assert coding["system"] == "http://loinc.org"
        assert coding["code"] == "81247-9"

    def test_completed_status_maps_to_final(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset(parse_status="completed")
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert result["status"] == "final"

    def test_failed_status_maps_to_entered_in_error(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset(parse_status="failed")
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert result["status"] == "entered-in-error"

    def test_quality_metrics_as_components(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset(quality_metrics={"coverage": 30.5, "read_count": 50000000})
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert "component" in result
        assert len(result["component"]) == 2

    def test_subject_reference_to_patient(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset()
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert result["subject"]["reference"] == f"Patient/{proj.id}"

    def test_category_is_laboratory(self):
        exporter = FHIRExporter(db=MagicMock())
        ds = make_dataset()
        proj = make_project()
        result = exporter.export_observation(ds, proj)
        assert result["category"][0]["coding"][0]["code"] == "laboratory"


# ============================================================
# Condition 资源导出
# ============================================================
class TestExportCondition:
    def test_resource_type_is_condition(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target()
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        assert result["resourceType"] == "Condition"

    def test_gene_symbol_in_code(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target(gene_symbol="EGFR")
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        assert "EGFR" in result["code"]["text"]
        assert "EGFR" in result["code"]["coding"][0]["display"]

    def test_grade_a_maps_to_confirmed(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target(evidence_grade="A")
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        assert result["verificationStatus"]["coding"][0]["code"] == "confirmed"

    def test_grade_d_maps_to_differential(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target(evidence_grade="D")
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        assert result["verificationStatus"]["coding"][0]["code"] == "differential"

    def test_clinical_status_is_active(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target()
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        assert result["clinicalStatus"]["coding"][0]["code"] == "active"

    def test_note_contains_evidence_info(self):
        exporter = FHIRExporter(db=MagicMock())
        tg = make_target(evidence_grade="A", confidence_score=0.95, source="COSMIC")
        proj = make_project()
        result = exporter.export_condition(tg, proj)
        note_text = result["note"][0]["text"]
        assert "A" in note_text
        assert "0.95" in note_text
        assert "COSMIC" in note_text


# ============================================================
# MedicationStatement 资源导出
# ============================================================
class TestExportMedicationStatement:
    def test_resource_type_is_medication_statement(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment()
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        assert result["resourceType"] == "MedicationStatement"

    def test_effective_status_maps_to_completed(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment(status="effective")
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        assert result["status"] == "completed"

    def test_testing_status_maps_to_active(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment(status="testing")
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        assert result["status"] == "active"

    def test_medication_name_in_codeable_concept(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment(name="Osimertinib 80mg", therapy_type="targeted")
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        assert "Osimertinib" in result["medicationCodeableConcept"]["text"]
        assert "靶向治疗" in result["medicationCodeableConcept"]["text"]

    def test_scores_in_note(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment(efficacy_score=0.85, risk_score=0.15, confidence=0.90)
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        note_text = result["note"][0]["text"]
        assert "0.85" in note_text
        assert "0.15" in note_text
        assert "0.90" in note_text

    def test_subject_reference_to_patient(self):
        exporter = FHIRExporter(db=MagicMock())
        tr = make_treatment()
        proj = make_project()
        result = exporter.export_medication_statement(tr, proj)
        assert result["subject"]["reference"] == f"Patient/{proj.id}"


# ============================================================
# Bundle 导出
# ============================================================
class TestExportBundle:
    @pytest.mark.asyncio
    async def test_bundle_structure(self):
        """Bundle 应包含 resourceType=Bundle, type=transaction, entry 列表"""
        mock_db = AsyncMock()
        exporter = FHIRExporter(db=mock_db)

        proj = make_project(id=uuid4())

        with patch.object(exporter, '_load_datasets', return_value=[]), \
             patch.object(exporter, '_load_targets', return_value=[]), \
             patch.object(exporter, '_load_treatments', return_value=[]), \
             patch.object(mock_db, 'get', return_value=proj):
            bundle = await exporter.export_bundle(str(proj.id))

        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "transaction"
        assert "entry" in bundle
        assert bundle["total"] >= 1  # 至少有 Patient

    @pytest.mark.asyncio
    async def test_bundle_contains_patient(self):
        mock_db = AsyncMock()
        exporter = FHIRExporter(db=mock_db)
        proj = make_project(id=uuid4())

        with patch.object(exporter, '_load_datasets', return_value=[]), \
             patch.object(exporter, '_load_targets', return_value=[]), \
             patch.object(exporter, '_load_treatments', return_value=[]), \
             patch.object(mock_db, 'get', return_value=proj):
            bundle = await exporter.export_bundle(str(proj.id))

        patient_entries = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"]
        assert len(patient_entries) == 1

    @pytest.mark.asyncio
    async def test_bundle_contains_all_resource_types(self):
        """Bundle 应包含 Patient + Observation + Condition + MedicationStatement"""
        mock_db = AsyncMock()
        exporter = FHIRExporter(db=mock_db)
        proj = make_project(id=uuid4())
        ds = make_dataset()
        tg = make_target()
        tr = make_treatment()

        with patch.object(exporter, '_load_datasets', return_value=[ds]), \
             patch.object(exporter, '_load_targets', return_value=[tg]), \
             patch.object(exporter, '_load_treatments', return_value=[tr]), \
             patch.object(mock_db, 'get', return_value=proj):
            bundle = await exporter.export_bundle(str(proj.id))

        types = {e["resource"]["resourceType"] for e in bundle["entry"]}
        assert "Patient" in types
        assert "Observation" in types
        assert "Condition" in types
        assert "MedicationStatement" in types

    @pytest.mark.asyncio
    async def test_bundle_project_not_found(self):
        mock_db = AsyncMock()
        exporter = FHIRExporter(db=mock_db)
        with patch.object(mock_db, 'get', return_value=None):
            result = await exporter.export_bundle(str(uuid4()))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_entry_has_request_method(self):
        """每个 entry 应包含 request.method=POST"""
        mock_db = AsyncMock()
        exporter = FHIRExporter(db=mock_db)
        proj = make_project(id=uuid4())

        with patch.object(exporter, '_load_datasets', return_value=[]), \
             patch.object(exporter, '_load_targets', return_value=[]), \
             patch.object(exporter, '_load_treatments', return_value=[]), \
             patch.object(mock_db, 'get', return_value=proj):
            bundle = await exporter.export_bundle(str(proj.id))

        for entry in bundle["entry"]:
            assert entry["request"]["method"] == "POST"
            assert "url" in entry["request"]
