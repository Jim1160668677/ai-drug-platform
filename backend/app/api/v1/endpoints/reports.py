"""报告端点 — CDISC SDTM 导出与报告生成"""
import logging
from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import AppException, NotFoundError
from app.db.session import get_db
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, success_response

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{project_id}/sdtm", summary="导出 CDISC SDTM")
async def export_sdtm(
    project_id: UUID,
    format: str = Query("json", description="输出格式: json(默认,含域预览) 或 csv(纯 CSV 下载)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 CDISC SDTM 格式数据（FDA 认可的临床试验数据标准）

    - format=json（默认）：返回 JSON 包含 csv 文本 + 结构化域数据（前端表格展示）
    - format=csv：直接返回 text/csv 文件（前端触发下载）
    """
    from app.services.cdisc.sdtm_exporter import SDTMExporter
    from fastapi.responses import PlainTextResponse

    try:
        exporter = SDTMExporter(db)
        sdtm_data = await exporter.export(project_id)
        csv_content = exporter.to_csv(sdtm_data)
    except AppException:
        raise
    except Exception as e:
        logger.error(f"SDTM 导出失败 (project={project_id}): {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message=f"SDTM 导出失败: {str(e)}",
            data={"project_id": str(project_id), "error": str(e)},
        )

    if format.lower() == "csv":
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sdtm_{project_id}.csv"},
        )

    return StandardResponse(
        message="SDTM 导出完成",
        data={
            "csv": csv_content,
            "domains": sdtm_data.get("domains", {}),
            "metadata": sdtm_data.get("metadata", {}),
            "record_counts": sdtm_data.get("record_counts", {}),
        },
    )


@router.post("/{project_id}/adam", response_model=StandardResponse, summary="导出 CDISC ADaM")
async def export_adam(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 CDISC ADaM 格式（用于统计分析）"""
    from app.services.cdisc.sdtm_exporter import SDTMExporter

    try:
        exporter = SDTMExporter(db)
        result = await exporter.export_adam(project_id)
    except AppException:
        raise
    except Exception as e:
        logger.error(f"ADaM 导出失败 (project={project_id}): {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message=f"ADaM 导出失败: {str(e)}",
            data={"project_id": str(project_id), "error": str(e)},
        )
    return StandardResponse(message="ADaM 导出完成", data=result)


@router.post("/{project_id}/fhir", response_model=StandardResponse, summary="导出 HL7 FHIR R4 Bundle")
async def export_fhir(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 HL7 FHIR R4 Bundle — 与 HIS/EMR 系统互操作

    将项目数据映射为 FHIR R4 资源（Patient/Observation/Condition/MedicationStatement），
    打包为 transaction 类型 Bundle 返回。
    """
    from app.services.cdisc.fhir_exporter import FHIRExporter

    exporter = FHIRExporter(db)
    bundle = await exporter.export_bundle(str(project_id))
    return StandardResponse(message="FHIR R4 导出完成", data=bundle)


@router.post("/{project_id}/sdtm/validate", response_model=StandardResponse, summary="SDTM 校验")
async def validate_sdtm(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """校验 SDTM 数据 — 参考 Pinnacle 21 Community 核心规则集

    先生成 SDTM 数据，再执行 8 条 FDA 核心校验规则（CG0001-CG0008）。
    """
    from app.services.cdisc.sdtm_exporter import SDTMExporter
    from app.services.cdisc.sdtm_validator import SDTMValidator

    exporter = SDTMExporter(db)
    sdtm_data = await exporter.export(project_id)
    validator = SDTMValidator()
    result = validator.validate(sdtm_data)
    return StandardResponse(message="SDTM 校验完成", data=result)


@router.get("/{project_id}/summary", response_model=StandardResponse, summary="项目报告摘要")
async def project_summary(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成项目综合报告摘要"""
    from sqlalchemy import select
    from app.models.target import Target
    from app.models.dataset import Dataset
    from app.models.hypothesis import Hypothesis
    from app.models.experiment import Experiment

    targets = (await db.execute(select(Target).where(Target.project_id == project_id))).scalars().all()
    datasets = (await db.execute(select(Dataset).where(Dataset.project_id == project_id))).scalars().all()
    hyps = (await db.execute(select(Hypothesis).where(Hypothesis.project_id == project_id))).scalars().all()
    exps = (await db.execute(select(Experiment).where(Experiment.project_id == project_id))).scalars().all()

    return success_response({
        "project_id": str(project_id),
        "datasets": {"total": len(datasets), "by_type": {t: sum(1 for d in datasets if d.data_type == t) for t in set(d.data_type for d in datasets)}},
        "targets": {"total": len(targets), "by_grade": {g: sum(1 for t in targets if t.evidence_grade == g) for g in set(t.evidence_grade for t in targets)}},
        "hypotheses": {"total": len(hyps), "completed": sum(1 for h in hyps if h.status == "completed")},
        "experiments": {"total": len(exps), "successful": sum(1 for e in exps if e.success)},
    })


@router.get("/{report_id}/cdisc", response_model=ApiResponse[Dict[str, Any]], summary="CDISC 导出")
async def export_cdisc(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CDISC SDTM 导出（基于 TargetReport）"""
    from app.services.report.cdisc_exporter import CdiscExporter
    exporter = CdiscExporter(db)
    result = await exporter.export(report_id)
    return success_response(result)


@router.post("/{report_id}/regenerate", response_model=ApiResponse[Dict[str, Any]], summary="重新生成报告")
async def regenerate_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新生成报告 — 在 content_json 中标记重新生成请求"""
    from app.models.report import TargetReport
    report = await db.get(TargetReport, report_id)
    if not report:
        raise NotFoundError("报告不存在")
    # TargetReport 无 status 字段，使用 content_json 标记重新生成
    existing = report.content_json or {}
    report.content_json = {
        **existing,
        "_regeneration_status": "regenerating",
        "_regeneration_requested_at": datetime.utcnow().isoformat(),
    }
    await db.commit()
    return success_response({"report_id": str(report_id), "status": "regenerating"})
