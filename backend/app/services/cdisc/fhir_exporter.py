"""HL7 FHIR R4 标准化导出器

设计来源：v3.0 文档第 10 章技术栈选型 + 第 3 章子系统 A 数据整合平台

映射关系（系统模型 → FHIR R4 资源）：
- Project → Patient（患者假名作为标识符）
- Dataset → Observation（数据集质量指标作为观察结果）
- Target → Condition（靶点/基因突变作为疾病状态）
- Treatment → MedicationStatement（治疗方案作为用药记录）
- Bundle — transaction 类型，打包所有资源

FHIR R4 规范参考：https://hl7.org/fhir/R4/
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset
from app.models.project import Project
from app.models.target import Target
from app.models.treatment import Treatment

logger = logging.getLogger(__name__)

# FHIR R4 固定字段
FHIR_VERSION = "4.0"
FHIR_RESOURCE_TYPE = "resource"
BUNDLE_TYPE = "transaction"


class FHIRExporter:
    """HL7 FHIR R4 导出器

    将系统中的项目数据导出为 FHIR R4 标准化资源，便于与 HIS/EMR 系统互操作。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_bundle(self, project_id: str) -> Dict[str, Any]:
        """导出完整 FHIR Bundle

        Args:
            project_id: 项目 ID
        Returns:
            FHIR Bundle（transaction 类型），包含 Patient/Observation/Condition/MedicationStatement
        """
        # 加载项目
        project = await self.db.get(Project, UUID(project_id))
        if not project:
            return {"error": "项目不存在", "resourceType": "OperationOutcome"}

        # 加载关联数据
        datasets = await self._load_datasets(project_id)
        targets = await self._load_targets(project_id)
        treatments = await self._load_treatments(project_id)

        # 构建资源
        entries: List[Dict[str, Any]] = []

        # 1. Patient 资源
        patient = self.export_patient(project)
        entries.append(self._make_entry(patient))

        # 2. Observation 资源（数据集）
        for ds in datasets:
            obs = self.export_observation(ds, project)
            entries.append(self._make_entry(obs))

        # 3. Condition 资源（靶点/基因突变）
        for tg in targets:
            cond = self.export_condition(tg, project)
            entries.append(self._make_entry(cond))

        # 4. MedicationStatement 资源（治疗方案）
        for tr in treatments:
            med = self.export_medication_statement(tr, project)
            entries.append(self._make_entry(med))

        bundle = {
            "resourceType": "Bundle",
            "id": f"bundle-{project_id}",
            "type": BUNDLE_TYPE,
            "meta": {
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
                "profile": ["http://hl7.org/fhir/4.0/StructureDefinition/Bundle"],
            },
            "total": len(entries),
            "entry": entries,
        }

        logger.info("FHIR Bundle 导出完成: project=%s, resources=%d", project_id, len(entries))
        return bundle

    def export_patient(self, project: Project) -> Dict[str, Any]:
        """导出 Patient 资源

        映射：patient_pseudonym → identifier, cancer_type → condition（在 Condition 中表达）
        """
        patient_id = str(project.id)
        return {
            "resourceType": "Patient",
            "id": patient_id,
            "identifier": [
                {
                    "system": "urn:oid:2.16.840.1.113883.19.5",
                    "value": project.patient_pseudonym or patient_id,
                    "use": "official",
                }
            ],
            "active": project.status == "active",
            "name": [
                {
                    "use": "anonymous",
                    "text": project.patient_pseudonym or f"Patient-{patient_id[:8]}",
                }
            ],
            "text": {
                "status": "generated",
                "div": f'<div xmlns="http://www.w3.org/1999/xhtml">患者假名: {project.patient_pseudonym or "匿名"}</div>',
            },
            "meta": {
                "lastUpdated": project.updated_at.isoformat() if project.updated_at else None,
                "tag": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
                         "code": "PSEUDED", "display": "pseudonymized"}],
            },
            "extension": [
                {
                    "url": "http://example.org/fhir/StructureDefinition/cancerType",
                    "valueString": project.cancer_type or "unknown",
                },
                {
                    "url": "http://example.org/fhir/StructureDefinition/stage",
                    "valueString": project.stage or "unknown",
                },
            ],
        }

    def export_observation(self, dataset: Dataset, project: Project) -> Dict[str, Any]:
        """导出 Observation 资源

        映射：Dataset.data_type → code, quality_metrics → valueQuantity
        使用 LOINC 编码体系
        """
        # 数据类型 → LOINC 编码映射（简化版）
        loinc_map = {
            "rna_seq": {"code": "81247-9", "display": "Gene expression panel"},
            "scrna_seq": {"code": "81247-9", "display": "Single cell gene expression panel"},
            "wes": {"code": "21636-6", "display": "Variant analysis panel"},
            "wgs": {"code": "21636-6", "display": "Whole genome sequencing panel"},
            "vcf": {"code": "21636-6", "display": "Genetic variant analysis"},
            "fasta": {"code": "69548-6", "display": "Genetic sequence"},
        }
        loinc = loinc_map.get(dataset.data_type, {"code": "unknown", "display": dataset.data_type})

        # 质量指标转为 observation value
        components = []
        quality_metrics = dataset.quality_metrics or {}
        for key, value in quality_metrics.items():
            if isinstance(value, (int, float)):
                components.append({
                    "code": {"text": key},
                    "valueQuantity": {"value": float(value), "unit": "metric"},
                })

        obs = {
            "resourceType": "Observation",
            "id": f"obs-{dataset.id}",
            "status": self._map_parse_status_to_observation_status(dataset.parse_status),
            "category": [
                {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }],
                }
            ],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": loinc["code"],
                    "display": loinc["display"],
                }],
                "text": dataset.name,
            },
            "subject": {"reference": f"Patient/{project.id}"},
            "effectiveDateTime": dataset.created_at.isoformat() if dataset.created_at else None,
            "meta": {
                "lastUpdated": dataset.created_at.isoformat() if dataset.created_at else None,
            },
        }

        if components:
            obs["component"] = components

        if dataset.parsed_summary:
            obs["note"] = [{"text": str(dataset.parsed_summary)[:500]}]

        return obs

    def export_condition(self, target: Target, project: Project) -> Dict[str, Any]:
        """导出 Condition 资源

        映射：Target.gene_symbol → code (SNOMED CT 基因突变), evidence_grade → verificationStatus
        """
        # 证据等级 → verificationStatus 映射
        grade_map = {
            "A": "confirmed",
            "B": "confirmed",
            "C": "provisional",
            "D": "differential",
        }
        verification = grade_map.get(
            getattr(target, "evidence_grade", ""),
            "unconfirmed",
        )

        return {
            "resourceType": "Condition",
            "id": f"cond-{target.id}",
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active",
                }],
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": verification,
                    "display": verification.capitalize(),
                }],
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "problem-list-item",
                    "display": "Problem List Item",
                }],
            }],
            "code": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "106223005",
                    "display": f"Gene mutation: {target.gene_symbol}",
                }],
                "text": f"靶点: {target.gene_symbol}" + (f" ({target.gene_name})" if target.gene_name else ""),
            },
            "subject": {"reference": f"Patient/{project.id}"},
            "onsetDateTime": target.created_at.isoformat() if target.created_at else None,
            "note": [{
                "text": f"证据等级: {target.evidence_grade}, 置信度: {target.confidence_score or 'N/A'}, 来源: {target.source or 'N/A'}",
            }],
            "meta": {
                "lastUpdated": target.created_at.isoformat() if target.created_at else None,
            },
        }

    def export_medication_statement(self, treatment: Treatment, project: Project) -> Dict[str, Any]:
        """导出 MedicationStatement 资源

        映射：Treatment.name → medicationCodeableConcept, status → status
        """
        # 治疗状态 → FHIR MedicationStatement.status 映射
        status_map = {
            "proposed": "intended",
            "testing": "active",
            "effective": "completed",
            "ineffective": "stopped",
            "deprecated": "unknown",
        }
        med_status = status_map.get(treatment.status, "unknown")

        # 治疗类型 → 药物编码
        therapy_type_map = {
            "targeted": "靶向治疗",
            "immuno": "免疫治疗",
            "chemo": "化疗",
            "radio": "放疗",
            "combination": "联合治疗",
            "vaccine": "mRNA 肿瘤疫苗",
        }
        therapy_display = therapy_type_map.get(treatment.therapy_type, treatment.therapy_type)

        med = {
            "resourceType": "MedicationStatement",
            "id": f"med-{treatment.id}",
            "status": med_status,
            "medicationCodeableConcept": {
                "coding": [{
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "display": treatment.name,
                }],
                "text": f"{treatment.name} ({therapy_display})",
            },
            "subject": {"reference": f"Patient/{project.id}"},
            "effectiveDateTime": treatment.created_at.isoformat() if treatment.created_at else None,
            "dateAsserted": treatment.created_at.isoformat() if treatment.created_at else None,
            "informationSource": {"reference": f"Patient/{project.id}"},
            "note": [],
            "meta": {
                "lastUpdated": treatment.created_at.isoformat() if treatment.created_at else None,
            },
        }

        # 添加疗效和风险评分
        notes = []
        if treatment.efficacy_score is not None:
            notes.append(f"疗效评分: {treatment.efficacy_score:.2f}")
        if treatment.risk_score is not None:
            notes.append(f"风险评分: {treatment.risk_score:.2f}")
        if treatment.confidence is not None:
            notes.append(f"置信度: {treatment.confidence:.2f}")
        if notes:
            med["note"] = [{"text": " | ".join(notes)}]

        return med

    # ========== 辅助方法 ==========

    async def _load_datasets(self, project_id: str) -> List[Dataset]:
        result = await self.db.execute(
            select(Dataset).where(Dataset.project_id == UUID(project_id))
        )
        return list(result.scalars().all())

    async def _load_targets(self, project_id: str) -> List[Target]:
        result = await self.db.execute(
            select(Target).where(Target.project_id == UUID(project_id))
        )
        return list(result.scalars().all())

    async def _load_treatments(self, project_id: str) -> List[Treatment]:
        result = await self.db.execute(
            select(Treatment).where(Treatment.project_id == UUID(project_id))
        )
        return list(result.scalars().all())

    def _map_parse_status_to_observation_status(self, parse_status: str) -> str:
        """映射数据集解析状态到 FHIR Observation.status"""
        mapping = {
            "pending": "preliminary",
            "parsing": "preliminary",
            "completed": "final",
            "failed": "entered-in-error",
        }
        return mapping.get(parse_status, "unknown")

    def _make_entry(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """构建 Bundle entry"""
        resource_id = resource.get("id", "")
        resource_type = resource.get("resourceType", "")
        return {
            "fullUrl": f"urn:uuid:{resource_id}" if resource_id else "",
            "resource": resource,
            "request": {
                "method": "POST",
                "url": resource_type,
            },
        }
