"""用户级 LLM 配置端点 — BYO Key 模式

设计来源：参照 Trae 论坛方案，用户可在个人中心绑定自有 API Key
路径前缀：/api/v1/users/me/llm-configs
权限：仅 owner 可访问自己的配置
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.encryption import decrypt, encrypt
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.db.session import get_db
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig
from app.api.v1.schemas import (
    UserLLMConfigCreate,
    UserLLMConfigUpdate,
    UserLLMConfigResponse,
    UserLLMTestRequest,
    UserLLMTestResponse,
)
from app.schemas.common import PagedResponse, paged_response, success_response
from app.services.llm.user_router import _mask_key, test_user_llm_connectivity

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(cfg: UserLLMConfig) -> dict:
    """ORM → 响应字典"""
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt(cfg.api_key)),
        "model_name": cfg.model_name,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout_sec": cfg.timeout_sec,
        "is_active": cfg.is_active,
        "last_test_at": cfg.last_test_at,
        "last_test_success": cfg.last_test_success,
        "last_test_message": cfg.last_test_message,
        "created_at": cfg.created_at,
        "updated_at": cfg.updated_at,
    }


@router.get("", response_model=PagedResponse[dict], summary="当前用户的 LLM 配置列表")
async def list_user_llm_configs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有 LLM 配置（仅自己的）"""
    skip = (page - 1) * page_size
    stmt = (
        select(UserLLMConfig)
        .where(UserLLMConfig.owner_id == current_user.id)
        .offset(skip)
        .limit(page_size)
        .order_by(UserLLMConfig.created_at.desc())
    )
    result = await db.execute(stmt)
    items = [_to_response(c) for c in result.scalars().all()]

    count_stmt = select(func.count()).select_from(UserLLMConfig).where(
        UserLLMConfig.owner_id == current_user.id
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/active", summary="获取当前用户激活的 LLM 配置")
async def get_active_user_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户激活的 LLM 配置（不传则使用系统默认）"""
    result = await db.execute(
        select(UserLLMConfig)
        .where(UserLLMConfig.owner_id == current_user.id)
        .where(UserLLMConfig.is_active == True)  # noqa: E712
        .limit(1)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return success_response({"use_default": True, "message": "未配置用户 LLM，将使用系统默认（Agnes）"})
    return success_response(_to_response(cfg))


@router.post("", response_model=dict, summary="创建用户 LLM 配置")
async def create_user_llm_config(
    payload: UserLLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新的用户级 LLM 配置（API Key 加密存储）"""
    cfg = UserLLMConfig(
        owner_id=current_user.id,
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=encrypt(payload.api_key),
        model_name=payload.model_name,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_sec=payload.timeout_sec,
        is_active=payload.is_active,
    )
    db.add(cfg)
    await db.flush()

    # 若设为激活，先把该用户其他配置置为非激活
    if payload.is_active:
        await db.execute(
            update(UserLLMConfig)
            .where(UserLLMConfig.id != cfg.id)
            .where(UserLLMConfig.owner_id == current_user.id)
            .where(UserLLMConfig.is_active == True)  # noqa: E712
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )
        await db.refresh(cfg)

    return _to_response(cfg)


@router.put("/{config_id}", response_model=dict, summary="更新用户 LLM 配置")
async def update_user_llm_config(
    config_id: UUID,
    payload: UserLLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新用户级 LLM 配置（仅 owner 可访问）"""
    cfg = await db.get(UserLLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")
    if cfg.owner_id != current_user.id:
        raise ForbiddenError("无权访问他人 LLM 配置")

    update_data = payload.model_dump(exclude_unset=True)

    if "api_key" in update_data:
        update_data["api_key"] = encrypt(update_data["api_key"])

    if update_data.get("is_active") is True:
        await db.execute(
            update(UserLLMConfig)
            .where(UserLLMConfig.id != config_id)
            .where(UserLLMConfig.owner_id == current_user.id)
            .where(UserLLMConfig.is_active == True)  # noqa: E712
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )

    for k, v in update_data.items():
        setattr(cfg, k, v)

    await db.flush()
    await db.refresh(cfg)
    return _to_response(cfg)


@router.delete("/{config_id}", summary="删除用户 LLM 配置")
async def delete_user_llm_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除用户级 LLM 配置（不能删当前激活的）"""
    cfg = await db.get(UserLLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")
    if cfg.owner_id != current_user.id:
        raise ForbiddenError("无权删除他人 LLM 配置")
    if cfg.is_active:
        raise ValidationError("不能删除当前激活的配置，请先切换到其他配置")
    await db.delete(cfg)
    return success_response({"message": f"配置 '{cfg.name}' 已删除"})


@router.post("/{config_id}/activate", summary="激活用户 LLM 配置")
async def activate_user_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """激活指定 LLM 配置（其他自动置为非激活）"""
    cfg = await db.get(UserLLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")
    if cfg.owner_id != current_user.id:
        raise ForbiddenError("无权激活他人 LLM 配置")

    await db.execute(
        update(UserLLMConfig)
        .where(UserLLMConfig.id != config_id)
        .where(UserLLMConfig.owner_id == current_user.id)
        .where(UserLLMConfig.is_active == True)  # noqa: E712
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    cfg.is_active = True
    await db.flush()
    await db.refresh(cfg)
    return success_response({"message": f"配置 '{cfg.name}' 已激活", "name": cfg.name})


@router.post("/test", response_model=UserLLMTestResponse, summary="测试用户 LLM 配置连通性")
async def test_user_llm_config(
    payload: UserLLMTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试用户级 LLM 配置连通性

    - 不传 config_id 时测试当前用户激活配置
    - SSRF 防护：拒绝指向内网/回环/保留地址
    """
    cfg: Optional[UserLLMConfig] = None
    if payload.config_id:
        cfg = await db.get(UserLLMConfig, payload.config_id)
        if not cfg:
            raise NotFoundError("配置不存在")
        if cfg.owner_id != current_user.id:
            raise ForbiddenError("无权测试他人 LLM 配置")
    else:
        result = await db.execute(
            select(UserLLMConfig)
            .where(UserLLMConfig.owner_id == current_user.id)
            .where(UserLLMConfig.is_active == True)  # noqa: E712
            .limit(1)
        )
        cfg = result.scalar_one_or_none()

    if not cfg:
        return UserLLMTestResponse(
            success=False,
            message="未找到可测试的配置（无 config_id 且无激活配置）",
        )

    message = payload.custom_message or "ping"
    result = await test_user_llm_connectivity(cfg, message)

    # 记录测试结果
    cfg.last_test_at = datetime.now(timezone.utc)
    cfg.last_test_success = result.get("success", False)
    cfg.last_test_message = result.get("message", "")
    await db.flush()

    return UserLLMTestResponse(
        success=result["success"],
        message=result["message"],
        model=result.get("model"),
        response_text=result.get("response_text"),
        duration_sec=result.get("duration_sec"),
    )


__all__ = ["router"]
