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
from typing import Any, Dict, Optional
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
