"""CDISC SDTM/ADaM 导出器 — FDA 认可的临床试验数据标准"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset
from app.models.experiment import Experiment, ExperimentStatus
from app.models.target import Target
from app.models.treatment import Treatment
from app.models.project import Project

logger = logging.getLogger(__name__)


class SDTMExporter:
    """CDISC SDTM 导出器 — 将项目数据转为 SDTM 域格式"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export(self, project_id: UUID) -> Dict[str, Any]:
        """导出 SDTM 格式数据

        构建 SDTM 域：DM（人口学）、VS（生命体征/数据集）、RS（疾病响应/靶点）、
        EX（暴露/治疗）、SV（访问/实验迭代）
        """
        project = await self.db.get(Project, project_id)
        study_id = f"PDD-{str(project_id)[:8].upper()}"

        # 查询各类数据
        targets = (await self.db.execute(
            select(Target).where(Target.project_id == project_id)
        )).scalars().all()
        datasets = (await self.db.execute(
            select(Dataset).where(Dataset.project_id == project_id)
        )).scalars().all()
        experiments = (await self.db.execute(
            select(Experiment).where(Experiment.project_id == project_id)
        )).scalars().all()
        treatments = (await self.db.execute(
            select(Treatment).where(Treatment.project_id == project_id)
        )).scalars().all()

        usubjid = str(project_id)

        # DM 域 — Demographics
        dm_records = [{
            "STUDYID": study_id,
            "DOMAIN": "DM",
            "USUBJID": usubjid,
            "RFICDTC": project.created_at.isoformat() if project.created_at else "",
            "ARM": project.cancer_type or "NSCLC",
            "AGE": "",
            "SEX": "",
        }]

        # VS 域 — Vital Signs（数据集元数据）
        vs_records = []
        for ds in datasets:
            vs_records.append({
                "STUDYID": study_id,
                "DOMAIN": "VS",
                "USUBJID": usubjid,
                "VSTEST": ds.data_type,
                "VSORRES": ds.file_format or "",
                "VSTPT": ds.name,
                "VISITNUM": 1,
                "VISIT": "SCREENING",
            })

        # RS 域 — Disease Response（靶点发现结果）
        rs_records = []
        for t in targets:
            rs_records.append({
                "STUDYID": study_id,
                "DOMAIN": "RS",
                "USUBJID": usubjid,
                "RSTEST": t.gene_symbol,
                "RSORRES": t.evidence_grade or "IV",
                "RSSTRESC": str(t.confidence_score or 0),
                "VNAM": t.source or "AI_ANALYSIS",
            })

        # EX 域 — Exposure（治疗方案）
        ex_records = []
        for tr in treatments:
            ex_records.append({
                "STUDYID": study_id,
                "DOMAIN": "EX",
                "USUBJID": usubjid,
                "EXTRT": tr.name,
                "EXCAT": tr.therapy_type,
                "EXDOSE": str((tr.config or {}).get("dose", "")),
                "EXDOSU": (tr.config or {}).get("unit", ""),
                "EXSTDTC": tr.created_at.isoformat() if tr.created_at else "",
            })

        # SV 域 — Subject Visits（实验迭代）
        sv_records = []
        visit_num = 1
        for exp in experiments:
            sv_records.append({
                "STUDYID": study_id,
                "DOMAIN": "SV",
                "USUBJID": usubjid,
                "VISITNUM": visit_num,
                "VISIT": f"ITERATION_{exp.iteration or 1}",
                "SVSTDTC": exp.created_at.isoformat() if exp.created_at else "",
                "SVENDTC": exp.created_at.isoformat() if exp.created_at else "",
            })
            visit_num += 1

        return {
            "domains": {
                "DM": dm_records,
                "VS": vs_records,
                "RS": rs_records,
                "EX": ex_records,
                "SV": sv_records,
            },
            "metadata": {
                "study_id": study_id,
                "version": "SDTMIG 3.3",
                "export_time": datetime.now(timezone.utc).isoformat(),
                "record_counts": {
                    "DM": len(dm_records),
                    "VS": len(vs_records),
                    "RS": len(rs_records),
                    "EX": len(ex_records),
                    "SV": len(sv_records),
                },
            },
        }

    def to_csv(self, sdtm_data: Dict[str, Any]) -> str:
        """将 SDTM 数据转为 CSV 字符串（多域拼接）

        每个域一个 section，以 --- DOMAIN Domain --- 分隔
        """
        output = io.StringIO()
        domains = sdtm_data.get("domains", {})
        metadata = sdtm_data.get("metadata", {})

        # 写入元数据头
        output.write("# CDISC SDTM Export\n")
        output.write(f"# Study: {metadata.get('study_id', '')}\n")
        output.write(f"# Version: {metadata.get('version', '')}\n")
        output.write(f"# Export Time: {metadata.get('export_time', '')}\n")
        output.write(f"# Record Counts: {metadata.get('record_counts', {})}\n\n")

        for domain_name, records in domains.items():
            if not records:
                continue
            output.write(f"--- {domain_name} Domain ---\n")
            # 写入 CSV
            fieldnames = list(records[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow(record)
            output.write("\n")

        return output.getvalue()

    async def export_adam(self, project_id: UUID) -> Dict[str, Any]:
        """导出 ADaM 数据集（基于 SDTM 派生）

        ADSL（Subject-Level）、ADRS（Response Analysis）、ADAE（Adverse Events）
        """
        sdtm = await self.export(project_id)
        domains = sdtm.get("domains", {})

        # ADSL — Subject-Level Analysis Dataset
        dm = domains.get("DM", [])
        adsl = []
        for rec in dm:
            adsl.append({
                "STUDYID": rec["STUDYID"],
                "USUBJID": rec["USUBJID"],
                "TRTSDT": rec.get("RFICDTC", ""),
                "ARM": rec.get("ARM", ""),
                "ITTFL": "Y",  # Intent-to-Treat Flag
            })

        # ADRS — Response Analysis Dataset
        rs = domains.get("RS", [])
        adrs = []
        for rec in rs:
            adrs.append({
                "STUDYID": rec["STUDYID"],
                "USUBJID": rec["USUBJID"],
                "PARAM": f"Target_{rec['RSTEST']}",
                "AVAL": float(rec.get("RSSTRESC", 0)),
                "AVALC": rec.get("RSORRES", ""),
                "PARAMCD": rec["RSTEST"][:8],
            })

        # ADAE — Adverse Events（从失败实验派生）
        experiments = (await self.db.execute(
            select(Experiment).where(Experiment.project_id == project_id)
            .where(Experiment.status == ExperimentStatus.FAILED)
        )).scalars().all()

        adae = []
        for exp in experiments:
            adae.append({
                "STUDYID": sdtm["metadata"]["study_id"],
                "USUBJID": str(project_id),
                "AEDECOD": exp.name,
                "AETERM": f"Experiment failed: {exp.exp_type}",
                "AESEV": "MODERATE",
                "AEDTC": exp.created_at.isoformat() if exp.created_at else "",
            })

        return {
            "datasets": {
                "ADSL": adsl,
                "ADRS": adrs,
                "ADAE": adae,
            },
            "metadata": {
                **sdtm["metadata"],
                "adam_version": "ADaMIG 1.1",
                "dataset_counts": {
                    "ADSL": len(adsl),
                    "ADRS": len(adrs),
                    "ADAE": len(adae),
                },
            },
        }
