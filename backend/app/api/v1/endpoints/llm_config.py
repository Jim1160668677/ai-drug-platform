"""LLM 配置端点 — 大模型 API 可视化管理"""
import ipaddress
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.security import UserRole
from app.core.encryption import encrypt, decrypt
from app.db.session import get_db
from app.models.llm_config import LLMConfig, AccessMode, UpstreamProtocol
from app.models.user import User
from app.api.v1.schemas import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMTestRequest,
    LLMTestResponse,
    StandardResponse,
)
from app.schemas.common import PagedResponse, paged_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter()


def _mask_key(key: str) -> str:
    """API key 脱敏：保留前6位和后4位"""
    if not key or len(key) < 12:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


def _is_ssrf_risky_url(url: str) -> bool:
    """检查 URL 是否存在 SSRF 风险（指向内网/回环/保留地址）

    防止 LLM test 端点被用作内网探测跳板。
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return True
        host = host.lower()
        if host in ("localhost",):
            return True
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
        except ValueError:
            # 域名：放行（DNS rebinding 需更深层防护，超出当前范围）
            pass
        return False
    except Exception:
        return True


def _to_response(cfg: LLMConfig) -> LLMConfigResponse:
    """将 ORM 对象转为响应模型"""
    return LLMConfigResponse(
        id=cfg.id,
        name=cfg.name,
        provider=cfg.provider,
        access_mode=cfg.access_mode.value if isinstance(cfg.access_mode, AccessMode) else str(cfg.access_mode),
        upstream_protocol=(
            cfg.upstream_protocol.value
            if isinstance(cfg.upstream_protocol, UpstreamProtocol)
            else str(cfg.upstream_protocol)
        ),
        base_url=cfg.base_url,
        api_key_masked=_mask_key(decrypt(cfg.api_key)),
        test_model=cfg.test_model,
        fast_model=cfg.fast_model,
        deep_model=cfg.deep_model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout_sec=cfg.timeout_sec,
        is_active=cfg.is_active,
        description=cfg.description,
        last_test_at=cfg.last_test_at,
        last_test_success=cfg.last_test_success,
        last_test_message=cfg.last_test_message,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


@router.get("", response_model=PagedResponse[LLMConfigResponse], summary="LLM 配置列表")
async def list_llm_configs(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有 LLM 配置（分页，PagedResponse 信封）"""
    skip = (page - 1) * page_size
    result = await db.execute(
        select(LLMConfig).offset(skip).limit(page_size).order_by(LLMConfig.created_at.desc())
    )
    items = [_to_response(c).model_dump() for c in result.scalars().all()]
    total = (await db.execute(select(func.count()).select_from(LLMConfig))).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/active", response_model=StandardResponse, summary="获取当前激活配置")
async def get_active_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前激活的 LLM 配置（用于前端显示当前使用哪个 LLM）"""
    result = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True).limit(1))  # noqa: E712
    cfg = result.scalar_one_or_none()
    if not cfg:
        return StandardResponse(
            success=False,
            message="无激活配置，系统使用 settings 默认 LLM",
            data={"use_default": True, "mock_mode": True},
        )
    return success_response(_to_response(cfg).model_dump())


@router.post("", response_model=LLMConfigResponse, summary="创建 LLM 配置")
async def create_llm_config(
    payload: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """创建新的 LLM 配置（仅 founder/chief）"""
    # 名称唯一性检查
    existing = await db.execute(select(LLMConfig).where(LLMConfig.name == payload.name))
    if existing.scalar_one_or_none():
        raise ConflictError(f"配置名称 '{payload.name}' 已存在")

    # 校验枚举值
    try:
        access_mode = AccessMode(payload.access_mode)
        upstream_protocol = UpstreamProtocol(payload.upstream_protocol)
    except ValueError as e:
        raise ValidationError(f"参数无效: {e}") from e

    cfg = LLMConfig(
        name=payload.name,
        provider=payload.provider,
        access_mode=access_mode,
        upstream_protocol=upstream_protocol,
        base_url=payload.base_url,
        api_key=encrypt(payload.api_key),
        test_model=payload.test_model,
        fast_model=payload.fast_model,
        deep_model=payload.deep_model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_sec=payload.timeout_sec,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(cfg)
    await db.flush()  # 先 flush 让 cfg 获得 ID

    # 若设为激活，先把其他配置置为非激活（排除当前 cfg）
    if payload.is_active:
        await db.execute(
            update(LLMConfig)
            .where(LLMConfig.id != cfg.id)
            .where(LLMConfig.is_active == True)  # noqa: E712
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )
        await db.refresh(cfg)

    return _to_response(cfg)


@router.get("/{config_id}", response_model=LLMConfigResponse, summary="获取 LLM 配置详情")
async def get_llm_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定 LLM 配置详情"""
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")
    return _to_response(cfg)


@router.put("/{config_id}", response_model=LLMConfigResponse, summary="更新 LLM 配置")
async def update_llm_config(
    config_id: UUID,
    payload: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """更新 LLM 配置（仅 founder/chief）"""
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")

    update_data = payload.model_dump(exclude_unset=True)

    # 名称唯一性
    if "name" in update_data and update_data["name"] != cfg.name:
        existing = await db.execute(select(LLMConfig).where(LLMConfig.name == update_data["name"]))
        if existing.scalar_one_or_none():
            raise ConflictError(f"配置名称 '{update_data['name']}' 已存在")

    # 枚举转换
    if "access_mode" in update_data:
        try:
            update_data["access_mode"] = AccessMode(update_data["access_mode"])
        except ValueError as e:
            raise ValidationError(f"access_mode 无效: {e}") from e
    if "upstream_protocol" in update_data:
        try:
            update_data["upstream_protocol"] = UpstreamProtocol(update_data["upstream_protocol"])
        except ValueError as e:
            raise ValidationError(f"upstream_protocol 无效: {e}") from e

    # 若设为激活，先把其他配置置为非激活
    if update_data.get("is_active") is True:
        await db.execute(
            update(LLMConfig)
            .where(LLMConfig.id != config_id)
            .where(LLMConfig.is_active == True)  # noqa: E712
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )

    # api_key 加密
    if "api_key" in update_data:
        update_data["api_key"] = encrypt(update_data["api_key"])

    for k, v in update_data.items():
        setattr(cfg, k, v)

    await db.flush()
    await db.refresh(cfg)
    return _to_response(cfg)


@router.delete("/{config_id}", response_model=StandardResponse, summary="删除 LLM 配置")
async def delete_llm_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """删除 LLM 配置（仅 founder/chief）"""
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")
    if cfg.is_active:
        raise ValidationError("不能删除当前激活的配置，请先切换到其他配置")
    await db.delete(cfg)
    return StandardResponse(message=f"配置 '{cfg.name}' 已删除")


@router.post("/{config_id}/activate", response_model=StandardResponse, summary="激活配置")
async def activate_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """激活指定 LLM 配置（其他自动置为非激活）"""
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise NotFoundError("配置不存在")

    await db.execute(
        update(LLMConfig)
        .where(LLMConfig.id != config_id)
        .where(LLMConfig.is_active == True)  # noqa: E712
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    cfg.is_active = True
    await db.flush()
    await db.refresh(cfg)
    return StandardResponse(message=f"配置 '{cfg.name}' 已激活", data={"name": cfg.name})


@router.post("/test", response_model=LLMTestResponse, summary="测试 LLM 配置连通性")
async def test_llm_config(
    payload: LLMTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)),
):
    """测试 LLM 配置连通性

    - 不传 config_id 时测试当前激活配置
    - 发送一条 ping 消息，返回 LLM 响应
    """
    cfg: Optional[LLMConfig] = None
    if payload.config_id:
        cfg = await db.get(LLMConfig, payload.config_id)
        if not cfg:
            raise NotFoundError("配置不存在")
    else:
        result = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True).limit(1))  # noqa: E712
        cfg = result.scalar_one_or_none()

    if not cfg:
        return LLMTestResponse(
            success=False,
            message="未找到可测试的配置（无 config_id 且无激活配置）",
        )

    message = payload.custom_message or "ping"
    start = time.time()
    try:
        # 直接用 httpx 调用 Chat Completions API（避免依赖 litellm）
        url = cfg.base_url.rstrip("/")
        if cfg.upstream_protocol == UpstreamProtocol.CHAT_COMPLETIONS:
            url = f"{url}/chat/completions"
        elif cfg.upstream_protocol == UpstreamProtocol.COMPLETIONS:
            url = f"{url}/completions"
        else:
            return LLMTestResponse(
                success=False,
                message=f"暂不支持的协议: {cfg.upstream_protocol}",
            )

        headers = {
            "Authorization": f"Bearer {decrypt(cfg.api_key)}",
            "Content-Type": "application/json",
        }
        body = {
            "model": cfg.test_model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": 50,
            "temperature": 0.1,
        }

        # SSRF 防护：拒绝指向内网/回环/保留地址的 base_url
        if _is_ssrf_risky_url(url):
            return LLMTestResponse(
                success=False,
                message="拒绝测试：base_url 指向内网/回环/保留地址（SSRF 防护）",
            )

        async with httpx.AsyncClient(timeout=cfg.timeout_sec) as client:
            resp = await client.post(url, json=body, headers=headers)

        duration = round(time.time() - start, 3)

        if resp.status_code != 200:
            # 脱敏：对外仅暴露状态码与通用描述，完整响应体记入日志
            status_hint = {
                401: "认证失败（检查 API Key）",
                403: "授权拒绝",
                404: "端点不存在（检查 base_url）",
                429: "请求过多（限流）",
                500: "上游服务内部错误",
                502: "网关错误",
                503: "服务不可用",
            }.get(resp.status_code, "上游服务错误")
            error_msg = f"HTTP {resp.status_code}: {status_hint}"
            logger.warning(
                "LLM 测试失败 [%s] %s — 上游响应: %s",
                cfg.name, resp.status_code, resp.text[:500],
            )
            # 记录测试失败
            cfg.last_test_at = datetime.now(timezone.utc)
            cfg.last_test_success = False
            cfg.last_test_message = error_msg
            await db.flush()
            return LLMTestResponse(success=False, message=error_msg, duration_sec=duration)

        data = resp.json()
        response_text = ""
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            response_text = choice.get("message", {}).get("content", "") or choice.get("text", "")
        model_used = data.get("model", cfg.test_model)

        # 记录测试成功
        cfg.last_test_at = datetime.now(timezone.utc)
        cfg.last_test_success = True
        cfg.last_test_message = f"OK - {len(response_text)} chars"
        await db.flush()

        return LLMTestResponse(
            success=True,
            message=f"连接成功（{duration}s）",
            model=model_used,
            response_text=response_text[:500],
            duration_sec=duration,
        )

    except httpx.TimeoutException:
        duration = round(time.time() - start, 3)
        error_msg = f"连接超时（{cfg.timeout_sec}s）"
        logger.warning("LLM 测试超时 [%s]", cfg.name, exc_info=True)
        cfg.last_test_at = datetime.now(timezone.utc)
        cfg.last_test_success = False
        cfg.last_test_message = error_msg
        await db.flush()
        return LLMTestResponse(success=False, message=error_msg, duration_sec=duration)
    except httpx.ConnectError:
        duration = round(time.time() - start, 3)
        error_msg = "连接失败（检查 base_url 与网络）"
        logger.warning("LLM 测试连接失败 [%s]", cfg.name, exc_info=True)
        cfg.last_test_at = datetime.now(timezone.utc)
        cfg.last_test_success = False
        cfg.last_test_message = error_msg
        await db.flush()
        return LLMTestResponse(success=False, message=error_msg, duration_sec=duration)
    except Exception as e:
        duration = round(time.time() - start, 3)
        # 脱敏：对外仅返回通用错误，内部详情记入日志
        error_msg = "测试失败（内部错误，详见日志）"
        logger.error("LLM 测试未预期异常 [%s]: %s: %s", cfg.name, type(e).__name__, e, exc_info=True)
        cfg.last_test_at = datetime.now(timezone.utc)
        cfg.last_test_success = False
        cfg.last_test_message = f"{type(e).__name__}: {str(e)[:200]}"
        await db.flush()
        return LLMTestResponse(success=False, message=error_msg, duration_sec=duration)
