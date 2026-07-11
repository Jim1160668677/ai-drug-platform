"""联邦学习端点 — 多中心隐私保护联邦模型训练

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/优化器服务层.md
           app/services/optimizer/federated_learning.py

提供 FL 任务的创建/列表/详情/停止、客户端注册、权重提交等接口。
为保持内存态任务/客户端跨请求可见，本模块使用模块级单例 FederatedLearningService。
生产环境可替换为 Flower + Redis 持久化实现。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError, UpstreamError
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import success_response

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_fl_service():
    """获取模块级单例 FederatedLearningService

    内存态 _jobs / _clients 需要跨请求持久化，
    因此每个进程持有一个 service 实例。
    """
    from app.services.optimizer.federated_learning import FederatedLearningService

    global _FL_SERVICE
    if _FL_SERVICE is None:
        _FL_SERVICE = FederatedLearningService()
    return _FL_SERVICE


_FL_SERVICE = None  # type: Optional[Any]


# ========== 请求体模型 ==========


class CreateJobRequest(BaseModel):
    """创建 FL 任务请求体"""

    project_id: str = Field(..., description="项目 ID")
    target_id: Optional[str] = Field(None, description="关联靶点 ID（可选）")
    num_rounds: Optional[int] = Field(None, ge=1, description="训练轮数，默认从 settings 读取")
    min_clients: Optional[int] = Field(None, ge=1, description="最少客户端数，默认从 settings 读取")
    config: Optional[Dict[str, Any]] = Field(None, description="额外配置")


class SubmitWeightsRequest(BaseModel):
    """客户端提交权重请求体"""

    client_id: str = Field(..., description="客户端 ID")
    weights: Dict[str, Any] = Field(..., description="模型权重（层名 -> 数值）")
    num_samples: int = Field(1, ge=1, description="本地训练样本数")
    metrics: Optional[Dict[str, Any]] = Field(None, description="训练指标")


class RegisterClientRequest(BaseModel):
    """客户端注册请求体"""

    client_id: str = Field(..., description="客户端唯一标识")
    endpoint: str = Field(..., description="客户端地址")
    capabilities: Optional[Dict[str, Any]] = Field(None, description="客户端能力描述")


# ========== 端点 ==========


@router.post("/jobs", summary="创建联邦学习任务")
async def create_job(
    payload: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建联邦学习训练任务

    返回任务 ID 与初始配置。任务进入 pending 状态，
    待客户端提交权重达到 min_clients 后转 running，最终 completed。
    """
    service = _get_fl_service()
    try:
        result = await service.create_job(
            project_id=payload.project_id,
            target_id=payload.target_id,
            num_rounds=payload.num_rounds,
            min_clients=payload.min_clients,
            config=payload.config,
        )
    except Exception as e:
        logger.error("创建 FL 任务失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"创建 FL 任务失败: {e}",
            service="federated_learning",
        )

    return success_response(data=result)


@router.get("/jobs", summary="联邦学习任务列表")
async def list_jobs(
    project_id: Optional[str] = Query(None, description="按项目 ID 过滤"),
    status: Optional[str] = Query(
        None, description="按状态过滤：pending/running/completed/stopped/failed"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出联邦学习任务，支持按项目 / 状态过滤"""
    service = _get_fl_service()
    try:
        jobs = await service.list_jobs(project_id=project_id, status=status)
    except Exception as e:
        logger.error("查询 FL 任务列表失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"查询 FL 任务列表失败: {e}",
            service="federated_learning",
        )

    return success_response(data={"items": jobs, "count": len(jobs)})

@router.get("/jobs/{job_id}", summary="联邦学习任务详情")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取联邦学习任务详情"""
    service = _get_fl_service()
    try:
        job = await service.get_job(job_id)
    except Exception as e:
        logger.error("查询 FL 任务详情失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"查询 FL 任务详情失败: {e}",
            service="federated_learning",
        )

    if not job:
        raise NotFoundError(
            f"FL 任务不存在: {job_id}",
            details={"job_id": job_id},
        )

    return success_response(data=job)


@router.post("/jobs/{job_id}/stop", summary="停止联邦学习任务")
async def stop_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止联邦学习任务（设置状态为 stopped）"""
    service = _get_fl_service()
    try:
        result = await service.stop_job(job_id)
    except Exception as e:
        logger.error("停止 FL 任务失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"停止 FL 任务失败: {e}",
            service="federated_learning",
        )

    if result.get("error"):
        raise NotFoundError(
            result["error"],
            details={"job_id": job_id},
        )

    return success_response(data=result)


@router.post("/jobs/{job_id}/weights", summary="客户端提交本轮权重")
async def submit_weights(
    job_id: str,
    payload: SubmitWeightsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """客户端提交本轮训练权重

    达到 min_clients 时触发 FedAvg 聚合（含 MAD 拜占庭剔除）。
    返回当前轮次与任务状态。
    """
    service = _get_fl_service()
    try:
        result = await service.submit_weights(
            job_id=job_id,
            client_id=payload.client_id,
            weights=payload.weights,
            num_samples=payload.num_samples,
            metrics=payload.metrics,
        )
    except Exception as e:
        logger.error("提交权重失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"提交权重失败: {e}",
            service="federated_learning",
        )

    if result.get("error"):
        raise NotFoundError(
            result["error"],
            details={"job_id": job_id},
        )

    return success_response(data=result)


@router.post("/clients/register", summary="联邦学习客户端注册")
async def register_client(
    payload: RegisterClientRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """注册联邦学习客户端（含能力声明）"""
    service = _get_fl_service()
    try:
        result = await service.register_client(
            client_id=payload.client_id,
            endpoint=payload.endpoint,
            capabilities=payload.capabilities,
        )
    except Exception as e:
        logger.error("客户端注册失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"客户端注册失败: {e}",
            service="federated_learning",
        )

    return success_response(data=result)


@router.get("/clients", summary="联邦学习客户端列表")
async def list_clients(
    status: Optional[str] = Query(
        None, description="按状态过滤：active/inactive"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出注册的联邦学习客户端"""
    service = _get_fl_service()
    try:
        clients = await service.list_clients(status=status)
    except Exception as e:
        logger.error("查询客户端列表失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"查询客户端列表失败: {e}",
            service="federated_learning",
        )

    return success_response(data={"items": clients, "count": len(clients)})