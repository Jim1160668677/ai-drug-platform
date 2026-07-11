"""依赖注入 — DB 会话 / 当前用户 / 客户端工厂"""
import logging
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import UserRole, decode_token, has_permission
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 JWT 解析当前用户

    异常处理策略：
    - JWTError / ValueError / TypeError → 401（凭据无效）
    - DB 异常 → 向上传播触发 500（不掩盖基础设施故障）
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exc
        # SQLAlchemy Uuid(as_uuid=True) 在 SQLite 上接收字符串绑定参数会报错，
        # 这里统一转换为 uuid.UUID 对象，兼容 PostgreSQL / SQLite
        user_uuid = uuid.UUID(user_id)
    except (JWTError, ValueError, TypeError) as exc:
        raise credentials_exc from exc

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exc
    return user


def require_role(*allowed_roles: UserRole):
    """角色权限校验依赖"""
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return checker


def require_permission(permission: str):
    """细粒度权限校验依赖"""
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {permission}",
            )
        return current_user
    return checker


# ========== Mock/Real 客户端工厂 ==========
# 根据 settings.USE_MOCK 返回对应实现，对上层透明

async def get_active_llm_config(db: AsyncSession):
    """从数据库读取当前激活的 LLM 配置

    Returns:
        LLMConfig or None — 无激活配置时返回 None（调用方需回退到 settings 默认）
    """
    from app.models.llm_config import LLMConfig
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.is_active == True).limit(1)  # noqa: E712
    )
    return result.scalar_one_or_none()


def _build_real_llm_client(cfg=None):
    """根据 LLMConfig 构造 RealLLMClient；cfg 为 None 时回退到 settings"""
    from app.clients.real.llm_real import RealLLMClient
    from app.core.encryption import decrypt
    if cfg is not None:
        # 数据库配置优先 — 用激活的 LLMConfig 实例化
        return RealLLMClient(
            base_url=cfg.base_url,
            api_key=decrypt(cfg.api_key),
            upstream_protocol=(
                cfg.upstream_protocol.value
                if hasattr(cfg.upstream_protocol, "value")
                else str(cfg.upstream_protocol)
            ),
            default_model=cfg.deep_model or cfg.test_model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout_sec=cfg.timeout_sec,
        )
    # 回退到 settings 默认值（OPENAI_API_KEY）
    return RealLLMClient()


def get_llm_client():
    """获取大模型客户端（同步版本 — Mock 模式或 settings 默认）

    注意：在 Real 模式下若需使用数据库激活的 LLM 配置，
    请改用 await get_llm_client_with_config(db)。
    """
    if settings.is_mock:
        from app.clients.mock.llm_mock import MockLLMClient
        return MockLLMClient()
    else:
        return _build_real_llm_client(None)


async def get_llm_client_with_config(db: AsyncSession):
    """获取大模型客户端（异步版本 — 优先使用数据库激活配置）

    1. Mock 模式 → 返回 MockLLMClient
    2. Real 模式 + 数据库有激活配置 → 用 LLMConfig 实例化 RealLLMClient
    3. Real 模式 + 无激活配置 → 回退到 settings 默认（OPENAI_API_KEY）
    """
    if settings.is_mock:
        from app.clients.mock.llm_mock import MockLLMClient
        return MockLLMClient()

    cfg = await get_active_llm_config(db)
    return _build_real_llm_client(cfg)


def get_gene_client():
    """获取 MyGene 客户端"""
    if settings.is_mock:
        from app.clients.mock.mygene_mock import MockGeneClient
        return MockGeneClient()
    else:
        from app.clients.real.mygene_real import RealGeneClient
        return RealGeneClient()


def get_variant_client():
    """获取 MyVariant 客户端"""
    if settings.is_mock:
        from app.clients.mock.myvariant_mock import MockVariantClient
        return MockVariantClient()
    else:
        from app.clients.real.myvariant_real import RealVariantClient
        return RealVariantClient()


def get_chembl_client():
    """获取 ChEMBL 客户端"""
    if settings.is_mock:
        from app.clients.mock.chembl_mock import MockChemblClient
        return MockChemblClient()
    else:
        from app.clients.real.chembl_real import RealChemblClient
        return RealChemblClient()


def get_diffdock_client():
    """获取 DiffDock 客户端"""
    if settings.is_mock:
        from app.clients.mock.diffdock_mock import MockDiffdockClient
        return MockDiffdockClient()
    else:
        from app.clients.real.diffdock_real import RealDiffdockClient
        return RealDiffdockClient()
