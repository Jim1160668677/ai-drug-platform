"""隐私计算端点 — 隐私域 / 数据脱敏 / 差分隐私 / 隐私预算

设计来源：repowiki/zh/content/安全与合规/隐私计算框架.md
           repowiki/zh/content/安全与合规/差分隐私机制.md
           repowiki/zh/content/安全与合规/HIPAA脱敏规则.md
           app/services/privacy/{privacy_layer,differential_privacy,data_masker}.py

封装三类隐私保护能力：
- PrivacyLayer：隐私域 / 数据集注册 / 计算请求 / 审批 / 结果取回
- DifferentialPrivacy：Laplace / Gaussian / 随机响应机制
- DataMasker：HIPAA Safe Harbor 18 项标识符脱敏

为保持跨请求状态，PrivacyLayer 与 PrivacyBudget 使用模块级单例。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError, UpstreamError
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import success_response

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_privacy_layer():
    """获取模块级单例 PrivacyLayer（保持域/数据集/请求跨请求可见）"""
    from app.services.privacy.privacy_layer import PrivacyLayer

    global _PRIVACY_LAYER
    if _PRIVACY_LAYER is None:
        _PRIVACY_LAYER = PrivacyLayer()
    return _PRIVACY_LAYER


def _get_privacy_budget():
    """获取模块级单例 PrivacyBudget

    默认 epsilon=10.0, delta=1e-5。
    生产环境应改为按用户/项目隔离的预算账户。
    """
    from app.services.privacy.differential_privacy import PrivacyBudget

    global _PRIVACY_BUDGET
    if _PRIVACY_BUDGET is None:
        _PRIVACY_BUDGET = PrivacyBudget(epsilon=10.0, delta=1e-5)
    return _PRIVACY_BUDGET


_PRIVACY_LAYER = None  # type: Optional[Any]
_PRIVACY_BUDGET = None  # type: Optional[Any]


# ========== 请求体模型 ==========


class CreateDomainRequest(BaseModel):
    """创建隐私域请求体"""

    name: str = Field(..., description="隐私域名称")
    data_schema: Optional[Dict[str, Any]] = Field(
        None, description="数据模式（列名 -> 类型描述）"
    )


class RegisterDatasetRequest(BaseModel):
    """注册数据集请求体"""

    domain_id: str = Field(..., description="隐私域 ID")
    dataset_id: str = Field(..., description="数据集 ID（外部唯一标识）")
    columns: List[str] = Field(..., description="列名列表")


class SubmitComputeRequest(BaseModel):
    """提交隐私计算请求体"""

    domain_id: str = Field(..., description="隐私域 ID")
    dataset_id: str = Field(..., description="数据集 ID")
    code: str = Field(..., description="计算代码（Python 字符串）")


class MaskDataRequest(BaseModel):
    """数据脱敏请求体"""

    records: List[Dict[str, Any]] = Field(..., description="原始记录列表")
    rules: Optional[Dict[str, str]] = Field(
        None,
        description="字段名 -> 标识符类型 的映射；None 时按字段名自动推断",
    )


class LaplaceRequest(BaseModel):
    """Laplace 机制请求体"""

    value: float = Field(..., description="原始查询结果")
    sensitivity: float = Field(..., ge=0, description="查询的 L1 全局敏感度")
    epsilon: float = Field(..., gt=0, description="单次查询的 ε")


class GaussianRequest(BaseModel):
    """Gaussian 机制请求体"""

    value: float = Field(..., description="原始查询结果")
    sensitivity: float = Field(..., ge=0, description="查询的 L2 全局敏感度")
    epsilon: float = Field(..., gt=0, description="ε 参数")
    delta: float = Field(..., gt=0, lt=1, description="δ 参数（0,1）")

# ========== 端点：隐私域 / 数据集 / 计算 ==========


@router.post("/domains", summary="创建隐私域")
async def create_domain(
    payload: CreateDomainRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建隐私域（P3 阶段接入 PySyft，当前内存态）"""
    service = _get_privacy_layer()
    try:
        result = service.create_domain(name=payload.name, schema=payload.data_schema)
    except Exception as e:
        logger.error("创建隐私域失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"创建隐私域失败: {e}",
            service="privacy_layer",
        )

    return success_response(data=result)


@router.post("/datasets", summary="注册数据集到隐私域")
async def register_dataset(
    payload: RegisterDatasetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """注册数据集到指定隐私域"""
    service = _get_privacy_layer()
    try:
        result = service.register_dataset(
            domain_id=payload.domain_id,
            dataset_id=payload.dataset_id,
            columns=payload.columns,
        )
    except KeyError as e:
        raise NotFoundError(
            str(e).strip("'"),
            details={"domain_id": payload.domain_id},
        )
    except Exception as e:
        logger.error("注册数据集失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"注册数据集失败: {e}",
            service="privacy_layer",
        )

    return success_response(data=result)


@router.post("/compute", summary="提交隐私计算请求")
async def submit_compute(
    payload: SubmitComputeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交隐私计算请求（等待审批后执行）"""
    service = _get_privacy_layer()
    try:
        result = service.submit_compute(
            domain_id=payload.domain_id,
            dataset_id=payload.dataset_id,
            code=payload.code,
        )
    except KeyError as e:
        raise NotFoundError(
            str(e).strip("'"),
            details={
                "domain_id": payload.domain_id,
                "dataset_id": payload.dataset_id,
            },
        )
    except Exception as e:
        logger.error("提交计算请求失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"提交计算请求失败: {e}",
            service="privacy_layer",
        )

    return success_response(data=result)


@router.get("/results/{request_id}", summary="获取隐私计算结果")
async def get_result(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取隐私计算结果（未审批/未完成时返回当前状态）"""
    service = _get_privacy_layer()
    try:
        result = service.get_result(request_id)
    except KeyError as e:
        raise NotFoundError(
            str(e).strip("'"),
            details={"request_id": request_id},
        )
    except Exception as e:
        logger.error("获取计算结果失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"获取计算结果失败: {e}",
            service="privacy_layer",
        )

    return success_response(data=result)

# ========== 端点：数据脱敏 / 差分隐私 / 预算 ==========


@router.post("/mask-data", summary="数据脱敏")
async def mask_data(
    payload: MaskDataRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量脱敏记录（HIPAA Safe Harbor 18 项标识符）

    根据 rules 映射或字段名自动推断标识符类型，应用对应的脱敏策略：
    哈希 / 掩码 / 泛化 / 删除。
    """
    from app.services.privacy.data_masker import DataMasker

    try:
        masker = DataMasker()
        masked = masker.mask_records(records=payload.records, rules=payload.rules)
    except Exception as e:
        logger.error("数据脱敏失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"数据脱敏失败: {e}",
            service="data_masker",
        )

    return success_response(data={"items": masked, "count": len(masked)})


@router.post("/differential/laplace", summary="Laplace 差分隐私机制")
async def laplace_mechanism(
    payload: LaplaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Laplace 机制 — 数值型查询加噪

    noise ~ Laplace(0, sensitivity / ε)
    返回 value + noise。同时从隐私预算中扣除 ε。
    """
    from app.services.privacy.differential_privacy import DifferentialPrivacy

    budget = _get_privacy_budget()
    try:
        # 扣除预算
        budget.consume(payload.epsilon)
        dp = DifferentialPrivacy()
        noisy_value = dp.laplace(
            value=payload.value,
            sensitivity=payload.sensitivity,
            epsilon=payload.epsilon,
        )
    except ValueError as e:
        # 预算不足或参数非法
        raise UpstreamError(
            f"Laplace 机制失败: {e}",
            service="differential_privacy",
        )
    except Exception as e:
        logger.error("Laplace 机制失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"Laplace 机制失败: {e}",
            service="differential_privacy",
        )

    return success_response(
        data={
            "original": payload.value,
            "noisy": noisy_value,
            "noise": noisy_value - payload.value,
            "epsilon_used": payload.epsilon,
            "remaining_epsilon": budget.remaining(),
            "method": "laplace",
        }
    )


@router.post("/differential/gaussian", summary="Gaussian 差分隐私机制")
async def gaussian_mechanism(
    payload: GaussianRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gaussian 机制 — (ε, δ)-DP

    σ = sqrt(2 * ln(1.25/δ)) * sensitivity / ε
    noise ~ N(0, σ²)
    返回 value + noise。同时从隐私预算中扣除 ε。
    """
    from app.services.privacy.differential_privacy import DifferentialPrivacy

    budget = _get_privacy_budget()
    try:
        budget.consume(payload.epsilon)
        dp = DifferentialPrivacy()
        noisy_value = dp.gaussian(
            value=payload.value,
            sensitivity=payload.sensitivity,
            epsilon=payload.epsilon,
            delta=payload.delta,
        )
    except ValueError as e:
        raise UpstreamError(
            f"Gaussian 机制失败: {e}",
            service="differential_privacy",
        )
    except Exception as e:
        logger.error("Gaussian 机制失败: %s", e, exc_info=True)
        raise UpstreamError(
            f"Gaussian 机制失败: {e}",
            service="differential_privacy",
        )

    return success_response(
        data={
            "original": payload.value,
            "noisy": noisy_value,
            "noise": noisy_value - payload.value,
            "epsilon_used": payload.epsilon,
            "delta": payload.delta,
            "remaining_epsilon": budget.remaining(),
            "method": "gaussian",
        }
    )


@router.get("/budget", summary="隐私预算查询")
async def get_budget(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前隐私预算状态（剩余 ε / 是否耗尽）"""
    budget = _get_privacy_budget()
    return success_response(
        data={
            "total_epsilon": budget.epsilon,
            "total_delta": budget.delta,
            "remaining_epsilon": budget.remaining(),
            "is_exhausted": budget.is_exhausted(),
        }
    )