"""反馈闭环端点 — 干湿实验闭环 / 偏差检测 / LIMS 导入 / 实验状态机

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/反馈环服务层.md
           app/services/workflow/feedback_loop.py

本模块封装三个紧密相关的反馈环组件到统一的 HTTP 接口：
- FeedbackLoop：摄入湿实验结果，检测预测偏差并触发模型重新校准
- ExperimentTracker：实验状态机（pending -> running -> completed / failed）
- LimsImporter：从 CSV/JSON 批量导入 LIMS 实验数据

所有端点遵循统一响应信封（success_response）与统一异常体系（AppException 子类）。
"""
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import (
    AppException,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import success_response

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 请求体模型 ==========


class ExperimentResultIngest(BaseModel):
    """提交湿实验结果请求体"""

    experiment_id: UUID = Field(..., description="实验 ID")
    result: Dict[str, Any] = Field(
        ...,
        description="实验结果 {measured: {...}, notes: ..., success: bool}",
    )


class RecalibrateRequest(BaseModel):
    """模型重新校准请求体"""

    target_symbol: str = Field(..., description="靶点基因符号，如 EGFR/BRCA1")


class TrackerCreateRequest(BaseModel):
    """实验状态机创建请求体"""

    experiment_id: UUID = Field(..., description="实验 ID")
    initial_state: str = Field(
        "pending",
        description="初始状态（pending/running/completed/failed，默认 pending）",
    )


class TransitionRequest(BaseModel):
    """实验状态转换请求体"""

    new_status: str = Field(
        ...,
        description="目标状态：pending/running/completed/failed",
    )


# ========== 端点 ==========


@router.post("/experiments", summary="提交湿实验结果")
async def ingest_experiment_result(
    payload: ExperimentResultIngest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交湿实验结果，触发反馈环

    流程：
    1. 写入 experiment.result
    2. 比对 predicted vs measured，计算 MAE/RMSE/MAPE
    3. 标记 feedback_applied=True
    4. 若 MAPE 超阈值（默认 30%），标记 needs_recalibration=True
    """
    from app.services.workflow.feedback_loop import FeedbackLoop

    try:
        loop = FeedbackLoop(db)
        result = await loop.ingest_experiment_result(
            experiment_id=payload.experiment_id,
            result=payload.result,
        )
    except Exception as e:
        await db.rollback()
        logger.error("反馈环摄入失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"反馈环摄入失败: {e}",
            service="feedback_loop",
        )

    # 先检查 not_found，再决定是否 commit（避免 commit 后再 raise 导致状态不一致）
    if result.get("status") == "not_found":
        raise NotFoundError(
            f"实验不存在: {payload.experiment_id}",
            details={"experiment_id": str(payload.experiment_id)},
        )

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("反馈环 commit 失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"反馈环 commit 失败: {e}",
            service="feedback_loop",
        )

    return success_response(data=result)


@router.get("/experiments", summary="查询实验记录")
async def list_experiments(
    target_symbol: Optional[str] = Query(
        None, description="按靶点基因符号过滤（如 EGFR）"
    ),
    project_id: Optional[UUID] = Query(None, description="按项目 ID 过滤"),
    limit: int = Query(50, ge=1, le=500, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询实验记录，支持按靶点 / 项目过滤"""
    from sqlalchemy import select

    from app.models.experiment import Experiment
    from app.models.target import Target

    stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit)
    if target_symbol:
        stmt = stmt.join(Target, Experiment.target_id == Target.id).where(
            Target.gene_symbol == target_symbol
        )
    if project_id:
        stmt = stmt.where(Experiment.project_id == project_id)

    result = await db.execute(stmt)
    experiments = result.scalars().all()

    data = [
        {
            "id": str(e.id),
            "name": e.name,
            "exp_type": e.exp_type,
            "status": str(e.status) if e.status else None,
            "feedback_applied": bool(e.feedback_applied),
            "success": bool(e.success) if e.success is not None else None,
            "lab_source": e.lab_source,
            "project_id": str(e.project_id) if e.project_id else None,
            "target_id": str(e.target_id) if e.target_id else None,
        }
        for e in experiments
    ]
    return success_response(data={"items": data, "count": len(data)})


@router.post("/recalibrate", summary="手动重新校准模型")
async def recalibrate(
    payload: RecalibrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对指定靶点触发模型重新校准

    先检测偏差，再调用联邦学习器更新权重（FL 不可用时降级为框架态）。
    """
    from app.services.workflow.feedback_loop import FeedbackLoop

    try:
        loop = FeedbackLoop(db)
        result = await loop.recalibrate(target_symbol=payload.target_symbol)
    except Exception as e:
        logger.error("重新校准失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"重新校准失败: {e}",
            service="feedback_loop",
        )

    return success_response(data=result)


@router.get("/bias-detection/{target_symbol}", summary="偏差检测")
async def detect_bias(
    target_symbol: str,
    min_samples: int = Query(5, ge=1, description="最小样本数，默认 5"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检测某靶点的系统偏差（汇总 MAPE 与阈值比较）"""
    from app.services.workflow.feedback_loop import FeedbackLoop

    try:
        loop = FeedbackLoop(db)
        result = await loop.detect_bias(
            target_symbol=target_symbol,
            min_samples=min_samples,
        )
    except Exception as e:
        logger.error("偏差检测失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"偏差检测失败: {e}",
            service="feedback_loop",
        )

    return success_response(data=result)


@router.get("/summary", summary="反馈汇总统计")
async def feedback_summary(
    project_id: Optional[UUID] = Query(None, description="按项目过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """反馈闭环汇总统计

    聚合统计：
    - 总实验数 / 已反馈数 / 成功数
    - 按实验状态分组计数
    - 按靶点统计反馈样本量
    """
    from sqlalchemy import select

    from app.models.experiment import Experiment
    from app.models.target import Target

    base = select(Experiment)
    if project_id:
        base = base.where(Experiment.project_id == project_id)

    rows = (await db.execute(base)).scalars().all()

    total = len(rows)
    feedback_applied = sum(1 for r in rows if r.feedback_applied)
    successful = sum(1 for r in rows if r.success)

    by_status: Dict[str, int] = {}
    for r in rows:
        key = str(r.status) if r.status else "unknown"
        by_status[key] = by_status.get(key, 0) + 1

    by_target: Dict[str, int] = {}
    if rows:
        target_ids = {r.target_id for r in rows if r.target_id}
        if target_ids:
            t_rows = (
                await db.execute(
                    select(Target).where(Target.id.in_(target_ids))
                )
            ).scalars().all()
            id_to_symbol = {str(t.id): t.gene_symbol for t in t_rows}
            for r in rows:
                if r.feedback_applied and r.target_id:
                    symbol = id_to_symbol.get(str(r.target_id), str(r.target_id))
                    by_target[symbol] = by_target.get(symbol, 0) + 1

    data = {
        "project_id": str(project_id) if project_id else None,
        "total_experiments": total,
        "feedback_applied": feedback_applied,
        "successful": successful,
        "feedback_rate": round(feedback_applied / total, 4) if total else 0.0,
        "success_rate": round(successful / total, 4) if total else 0.0,
        "by_status": by_status,
        "by_target": by_target,
    }
    return success_response(data=data)


@router.post("/lims-import", summary="LIMS CSV/JSON 导入")
async def lims_import(
    file: UploadFile = File(..., description="CSV 或 JSON 文件"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """LIMS 数据导入 — 根据文件扩展名或 content_type 选择 CSV / JSON 导入器

    - CSV：每行一个实验，列名对应 Experiment 字段
    - JSON：{experiments: [{...}, ...]} 结构
    """
    from app.services.workflow.feedback_loop import LimsImporter

    content = await file.read()
    if not content:
        raise ValidationError("上传文件为空")

    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()
    use_json = "json" in content_type or filename.endswith(".json")
    use_csv = "csv" in content_type or filename.endswith(".csv")

    if not (use_json or use_csv):
        try:
            import json as _json

            _json.loads(content.decode("utf-8"))
            use_json = True
        except Exception:
            use_csv = True

    suffix = ".json" if use_json else ".csv"
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=suffix, delete=False, prefix="lims_import_"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
    except OSError as e:
        raise UpstreamError(
            f"临时文件写入失败: {e}",
            service="lims_importer",
        )

    try:
        importer = LimsImporter(db)
        if use_json:
            result = await importer.import_json(tmp_path)
        else:
            result = await importer.import_csv(tmp_path)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("LIMS 导入失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"LIMS 导入失败: {e}",
            service="lims_importer",
        )
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return success_response(data=result)


@router.post("/experiments/tracker", summary="实验状态机创建/初始化")
async def create_tracker(
    payload: TrackerCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """初始化实验状态机

    服务层 ExperimentTracker 不显式 create（实验入库即隐式初始化为 pending）。
    本端点验证实验存在并返回当前状态，相当于"状态机就绪"语义。
    若实验当前状态与请求的 initial_state 不同，则尝试 transition 到 initial_state。
    """
    from app.services.workflow.feedback_loop import ExperimentTracker

    try:
        tracker = ExperimentTracker(db)
        state = await tracker.get_state(payload.experiment_id)
        if state.get("status") == "not_found":
            raise NotFoundError(
                f"实验不存在: {payload.experiment_id}",
                details={"experiment_id": str(payload.experiment_id)},
            )

        current = state.get("current_status", "")
        if current and current != payload.initial_state:
            transition_result = await tracker.transition(
                payload.experiment_id, payload.initial_state
            )
            await db.commit()
            return success_response(
                data={
                    "experiment_id": str(payload.experiment_id),
                    "initial_state": payload.initial_state,
                    "previous_state": current,
                    "transition": transition_result,
                    "status": "initialized",
                }
            )

        return success_response(
            data={
                "experiment_id": str(payload.experiment_id),
                "initial_state": current or payload.initial_state,
                "status": "already_initialized",
                "state_detail": state,
            }
        )
    except AppException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("状态机初始化失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"状态机初始化失败: {e}",
            service="experiment_tracker",
        )


@router.get("/experiments/tracker", summary="查询实验状态机")
async def get_tracker(
    experiment_id: UUID = Query(..., description="实验 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询实验状态机当前状态、是否终态、合法后继状态"""
    from app.services.workflow.feedback_loop import ExperimentTracker

    try:
        tracker = ExperimentTracker(db)
        state = await tracker.get_state(experiment_id)
    except Exception as e:
        logger.error("状态机查询失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"状态机查询失败: {e}",
            service="experiment_tracker",
        )

    if state.get("status") == "not_found":
        raise NotFoundError(
            f"实验不存在: {experiment_id}",
            details={"experiment_id": str(experiment_id)},
        )

    return success_response(data=state)


@router.post("/experiments/{experiment_id}/transition", summary="实验状态转换")
async def transition_experiment(
    experiment_id: UUID,
    payload: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行实验状态转换

    合法转换：
    - pending -> running
    - running -> completed
    - running -> failed
    - failed -> pending（重新入队）

    非法转换返回 invalid_transition（不抛异常，业务可继续）。
    """
    from app.services.workflow.feedback_loop import ExperimentTracker

    try:
        tracker = ExperimentTracker(db)
        result = await tracker.transition(experiment_id, payload.new_status)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("状态转换失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"状态转换失败: {e}",
            service="experiment_tracker",
        )

    if result.get("status") == "not_found":
        raise NotFoundError(
            f"实验不存在: {experiment_id}",
            details={"experiment_id": str(experiment_id)},
        )

    return success_response(data=result)


# ========== 患者用药反馈端点 ==========


class PatientFeedbackCreate(BaseModel):
    """患者用药反馈创建请求体"""

    treatment_id: str = Field(..., description="关联的治疗方案 ID")
    patient_code: Optional[str] = Field(None, description="患者编码（脱敏）")
    age: Optional[int] = Field(None, ge=0, le=150, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    diagnosis: Optional[str] = Field(None, description="诊断")
    stage: Optional[str] = Field(None, description="分期")
    drug_name: Optional[str] = Field(None, description="药物名称")
    dosage: Optional[str] = Field(None, description="剂量")
    duration_days: Optional[int] = Field(None, ge=0, description="用药天数")
    efficacy: Optional[str] = Field(
        None,
        description="疗效评价: complete/partial/stable/progressive",
    )
    tumor_shrinkage_pct: Optional[float] = Field(None, ge=-100, le=100, description="肿瘤缩小百分比")
    pfs_days: Optional[int] = Field(None, ge=0, description="无进展生存期（天）")
    os_days: Optional[int] = Field(None, ge=0, description="总生存期（天）")
    adverse_events: Optional[List[Dict[str, Any]]] = Field(
        None, description="不良反应列表 [{event, severity, action}]"
    )
    biomarker_changes: Optional[Dict[str, Any]] = Field(None, description="生物标志物变化")
    notes: Optional[str] = Field(None, description="备注")


@router.post("/patient", summary="提交患者用药反馈")
async def create_patient_feedback(
    payload: PatientFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交患者用药反馈

    录入患者基本信息、用药方案、治疗效果及不良反应等数据。
    建立标准化的数据采集，实现实验数据与临床数据的有效关联。
    """
    from app.services.workflow.patient_feedback import PatientFeedbackService

    try:
        service = PatientFeedbackService(db)
        feedback = await service.create(
            treatment_id=payload.treatment_id,
            patient_code=payload.patient_code,
            age=payload.age,
            gender=payload.gender,
            diagnosis=payload.diagnosis,
            stage=payload.stage,
            drug_name=payload.drug_name,
            dosage=payload.dosage,
            duration_days=payload.duration_days,
            efficacy=payload.efficacy,
            tumor_shrinkage_pct=payload.tumor_shrinkage_pct,
            pfs_days=payload.pfs_days,
            os_days=payload.os_days,
            adverse_events=payload.adverse_events,
            biomarker_changes=payload.biomarker_changes,
            notes=payload.notes,
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("患者反馈创建失败: %s", e, exc_info=True)
        raise UpstreamError(f"患者反馈创建失败: {e}", service="patient_feedback")

    return success_response(data={
        "id": str(feedback.id),
        "treatment_id": feedback.treatment_id,
        "patient_code": feedback.patient_code,
        "efficacy": feedback.efficacy,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    })


@router.get("/patient", summary="查询患者用药反馈列表")
async def list_patient_feedback(
    treatment_id: Optional[str] = Query(None, description="按治疗方案过滤"),
    target_symbol: Optional[str] = Query(None, description="按靶点基因符号过滤"),
    limit: int = Query(100, ge=1, le=500, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询患者用药反馈列表

    支持按治疗方案 ID 或靶点基因符号过滤。
    """
    from app.services.workflow.patient_feedback import PatientFeedbackService

    service = PatientFeedbackService(db)

    if target_symbol:
        items = await service.list_by_target(target_symbol, limit)
        return success_response(data={"items": items, "count": len(items), "filter": "target_symbol"})
    elif treatment_id:
        feedbacks = await service.list_by_treatment(treatment_id, limit)
        items = [
            {
                "id": str(f.id),
                "treatment_id": f.treatment_id,
                "patient_code": f.patient_code,
                "age": f.age,
                "gender": f.gender,
                "efficacy": f.efficacy,
                "adverse_reactions": f.adverse_reactions,
                "biomarker_changes": f.biomarker_changes,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedbacks
        ]
        return success_response(data={"items": items, "count": len(items), "filter": "treatment_id"})
    else:
        from sqlalchemy import select as _select
        from app.models.treatment import ClinicalFeedback
        result = await db.execute(
            _select(ClinicalFeedback)
            .order_by(ClinicalFeedback.created_at.desc())
            .limit(limit)
        )
        feedbacks = list(result.scalars().all())
        items = [
            {
                "id": str(f.id),
                "treatment_id": f.treatment_id,
                "patient_code": f.patient_code,
                "age": f.age,
                "gender": f.gender,
                "efficacy": f.efficacy,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedbacks
        ]
        return success_response(data={"items": items, "count": len(items), "filter": "all"})


@router.get("/patient/{feedback_id}", summary="患者反馈详情")
async def get_patient_feedback(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取患者用药反馈详情"""
    from app.models.treatment import ClinicalFeedback

    feedback = await db.get(ClinicalFeedback, feedback_id)
    if not feedback:
        raise NotFoundError(f"患者反馈不存在: {feedback_id}")

    return success_response(data={
        "id": str(feedback.id),
        "treatment_id": feedback.treatment_id,
        "patient_code": feedback.patient_code,
        "age": feedback.age,
        "gender": feedback.gender,
        "dosage": feedback.dosage,
        "duration_days": feedback.duration_days,
        "efficacy": feedback.efficacy,
        "adverse_reactions": feedback.adverse_reactions,
        "biomarker_changes": feedback.biomarker_changes,
        "notes": feedback.notes,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    })


@router.get("/patient/stats/{target_symbol}", summary="按靶点统计有效率/不良反应率")
async def get_patient_feedback_stats(
    target_symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按靶点统计患者用药反馈数据

    返回有效率（complete+partial）、不良反应率、疗效分布。
    """
    from app.services.workflow.patient_feedback import PatientFeedbackService

    service = PatientFeedbackService(db)
    stats = await service.get_statistics(target_symbol)
    return success_response(data=stats)


@router.get("/patient/template", summary="下载标准化数据采集模板")
async def download_patient_feedback_template(
    current_user: User = Depends(get_current_user),
):
    """下载患者用药反馈标准化数据采集模板（CSV）

    用于临床医生批量录入患者用药反馈数据。
    """
    from app.services.workflow.patient_feedback import PatientFeedbackService

    content = PatientFeedbackService.generate_template("csv")
    return success_response(data={
        "format": "csv",
        "size_bytes": len(content),
        "preview": content[:500].decode("utf-8", errors="ignore"),
        "instructions": "下载后删除注释行（#开头），填入数据后通过 /feedback/patient 端点批量提交",
    })
