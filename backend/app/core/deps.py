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


def require_function_role(*functions: str):
    """职能角色校验依赖（正交于 require_role）

    用于按职能细分的端点（如验证任务、可开发性评估）。
    function_role 为 NULL 的用户（向后兼容）会被拒绝。
    """
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if not current_user.function_role or current_user.function_role not in functions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要职能角色: {list(functions)}",
            )
        return current_user
    return checker


def require_role_or_function(roles, functions):
    """复合校验：满足职级或职能之一即可（过渡期兼容）"""
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        role_ok = current_user.role in roles
        func_ok = (
            current_user.function_role is not None
            and current_user.function_role in functions
        )
        if not role_ok and not func_ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色 {list(roles)} 或职能 {list(functions)}",
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


# ========== Agnes 模型降级链路 ==========


def get_agnes_fallback_client():
    """获取 Agnes 备用模型客户端（agnes-2.0-flash）

    当主模型 agnes-2.5-flash 不可用/低质量时，自动切换到 agnes-2.0-flash。
    两者使用相同的 API 端点和 API Key，仅模型名不同。
    """
    from app.clients.real.llm_real import RealLLMClient
    api_key = settings.AGNES_API_KEY or settings.OPENAI_API_KEY
    if not api_key:
        raise RuntimeError("Agnes API Key 未配置。请在 .env 设置 AGNES_API_KEY")
    return RealLLMClient(
        base_url=settings.LLM_BASE_URL,
        api_key=api_key,
        upstream_protocol="chat_completions",
        default_model=settings.AGNES_FALLBACK_MODEL,
        timeout_sec=settings.AGNES_FALLBACK_TIMEOUT_SEC,
    )


def get_zhipu_client():
    """获取智谱 GLM 客户端（OpenAI 兼容协议，作为第三级备用模型）"""
    from app.clients.real.llm_real import RealLLMClient
    if not settings.ZHIPU_API_KEY:
        raise RuntimeError("智谱 API Key 未配置。请在 .env 设置 ZHIPU_API_KEY")
    return RealLLMClient(
        base_url=settings.ZHIPU_BASE_URL,
        api_key=settings.ZHIPU_API_KEY,
        upstream_protocol="chat_completions",
        default_model=settings.ZHIPU_MODEL,
        timeout_sec=settings.ZHIPU_TIMEOUT_SEC,
    )


async def get_llm_client_with_fallback(db: AsyncSession = None):
    """获取带三级降级机制的 LLM 客户端

    降级链路：
    Level 1: agnes-2.5-flash（主模型）→ agnes-2.0-flash（同 API 备用）
    Level 2: Level 1 结果 → 智谱 GLM-4.7-Flash（不同 API，最终兜底）

    当 Agnes API 整体不可达时，自动降级到智谱 GLM 作为最终兜底。
    对上层完全透明：返回的客户端实现 LLMClient 接口。

    Args:
        db: 数据库会话（传入时优先使用数据库激活的 LLM 配置作为主模型）
    """
    if settings.is_mock:
        from app.clients.mock.llm_mock import MockLLMClient
        return MockLLMClient()

    # 获取主模型客户端
    if db is not None:
        primary = await get_llm_client_with_config(db)
    else:
        primary = get_llm_client()

    # 降级未启用时返回主模型（行为不变）
    if not settings.LLM_FALLBACK_ENABLED:
        return primary

    from app.core.llm.fallback import FallbackLLMClient
    agnes_key = settings.AGNES_API_KEY or settings.OPENAI_API_KEY
    zhipu_available = bool(settings.ZHIPU_API_KEY)

    # 构造三级降级链
    # Level 1: agnes-2.5-flash → agnes-2.0-flash（同 API，不同模型名）
    if agnes_key:
        agnes_fallback = get_agnes_fallback_client()
        agnes_chain = FallbackLLMClient(
            primary_client=primary,
            fallback_client=agnes_fallback,
        )
        # Level 2: Agnes 链路 → 智谱 GLM-4.7-Flash（完全不同的 API）
        if zhipu_available:
            zhipu_fallback = get_zhipu_client()
            return FallbackLLMClient(
                primary_client=agnes_chain,
                fallback_client=zhipu_fallback,
            )
        return agnes_chain

    # 无 Agnes Key，直接用智谱作为主（如有）
    if zhipu_available:
        return FallbackLLMClient(
            primary_client=primary,
            fallback_client=get_zhipu_client(),
        )

    return primary



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


def get_ncbi_client():
    """获取 NCBI E-utilities 客户端

    覆盖 PubMed / ClinVar / Gene / SNP / Protein / Nucleotide 等数据库。
    Real 模式支持 API Key、速率限制、指数退避重试和持久化缓存。
    """
    if settings.is_mock:
        from app.clients.mock.ncbi_mock import MockNcbiClient
        return MockNcbiClient()
    else:
        from app.clients.real.ncbi_real import RealNcbiClient
        return RealNcbiClient()


# ========== 学术资源客户端工厂 ==========
# 4 个学术数据源(bioRxiv/arXiv/Semantic Scholar/CrossRef)用于科学推理助手
# 统一遵循 USE_MOCK 开关:True=返回预置文献,False=调用真实 API


def get_biorxiv_client():
    """获取 bioRxiv 客户端(预印本生物学文献)"""
    if settings.is_mock:
        from app.clients.mock.biorxiv_mock import MockBiorxivClient
        return MockBiorxivClient()
    else:
        from app.clients.real.biorxiv_real import RealBiorxivClient
        return RealBiorxivClient()


def get_arxiv_client():
    """获取 arXiv 客户端(预印本计算生物学/ML 文献)"""
    if settings.is_mock:
        from app.clients.mock.arxiv_mock import MockArxivClient
        return MockArxivClient()
    else:
        from app.clients.real.arxiv_real import RealArxivClient
        return RealArxivClient()


def get_semantic_scholar_client():
    """获取 Semantic Scholar 客户端(高被引文献 + 影响力指标)

    Real 模式支持 SEMANTIC_SCHOLAR_API_KEY(可选,提升速率限制)
    """
    if settings.is_mock:
        from app.clients.mock.semantic_scholar_mock import MockSemanticScholarClient
        return MockSemanticScholarClient()
    else:
        from app.clients.real.semantic_scholar_real import RealSemanticScholarClient
        return RealSemanticScholarClient()


def get_crossref_client():
    """获取 CrossRef 客户端(已发表论文 + DOI 元数据)

    Real 模式支持 CROSSREF_MAILTO(polite pool,50 req/s;无则 2 req/s)
    """
    if settings.is_mock:
        from app.clients.mock.crossref_mock import MockCrossrefClient
        return MockCrossrefClient()
    else:
        from app.clients.real.crossref_real import RealCrossrefClient
        return RealCrossrefClient()
