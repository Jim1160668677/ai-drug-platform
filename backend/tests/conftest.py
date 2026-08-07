"""pytest 配置 — 测试 fixtures"""
import asyncio
import os
import sys
from typing import AsyncGenerator, Dict, Any

# 测试环境强制 Mock 模式
os.environ["USE_MOCK"] = "true"
os.environ["APP_ENV"] = "testing"

# 确保测试用 SQLite
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# 测试环境启用 Fernet 加密（32 字节 URL-safe base64 密钥）
# 使 encrypt()/decrypt() 在测试中真实加解密，而非明文降级
os.environ["API_KEY_ENCRYPTION_KEY"] = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2VZ6JbXJc="

# 强制计算引擎使用 Mock 模式（测试无需 GPU）
os.environ["ESMFOLD_USE_MOCK"] = "true"
os.environ["UNIMOL_USE_MOCK"] = "true"
os.environ["VINA_USE_MOCK"] = "true"
os.environ["SCGPT_USE_MOCK"] = "true"
os.environ["MHCFLURRY_USE_MOCK"] = "true"
os.environ["AIZYNTH_USE_MOCK"] = "true"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ========== LLM 流式响应 mock 辅助函数 ==========
# AgentEngine 现在调用 llm_router.stream_complete()（异步生成器）而非 complete()。
# 本辅助函数将传统的 {content, usage, cost_usd} 响应包装为流式 chunk 序列，
# 让测试 mock 自动适配新的流式接口，无需每个测试重写。

async def _stream_complete_generator(response: Dict[str, Any]):
    """将传统 chat 响应转换为流式 chunk 序列

    yield:
      {"type": "token", "content": <完整内容>} — 单个 token（整段作为一次推送）
      {"type": "done", "content": <完整内容>, "usage": {...}, "model": "...",
       "cost_usd": float, "duration_sec": float} — 完成事件
    """
    content = response.get("content", "")
    usage = response.get("usage", {}) or {}
    cost_usd = response.get("cost_usd", 0.0) or 0.0
    model = response.get("model", "test-model")

    # 单次推送整段内容（测试场景，不需要逐 token）
    if content:
        yield {"type": "token", "content": content}
    yield {
        "type": "done",
        "content": content,
        "usage": usage,
        "model": model,
        "cost_usd": cost_usd,
        "duration_sec": 0.001,
        "guardrail": {"passed": True, "blocked": False, "reasons": [], "sanitized": False},
    }


def make_llm_router_mock(response: Dict[str, Any]):
    """构造一个同时支持 complete 和 stream_complete 的 LLMRouter mock

    Args:
        response: {content, usage, cost_usd, model?} 形式的响应字典

    Returns:
        MagicMock，已配置 complete（AsyncMock）和 stream_complete（异步生成器函数）
    """
    from unittest.mock import MagicMock, AsyncMock

    router = MagicMock()
    router.complete = AsyncMock(return_value=response)
    # stream_complete 必须是普通函数（返回异步生成器），不能用 AsyncMock
    # 因为 `async for chunk in router.stream_complete(...)` 期望返回 async generator
    def _stream_factory(*args, **kwargs):
        return _stream_complete_generator(response)
    router.stream_complete = _stream_factory
    router.select_model = MagicMock(return_value=response.get("model", "test-model"))
    return router


def make_streaming_llm_router_mock(response: Dict[str, Any]):
    """make_llm_router_mock 的别名（语义更明确）"""
    return make_llm_router_mock(response)


def make_multi_response_llm_router_mock(responses):
    """构造按顺序返回多个响应的 LLMRouter mock

    Args:
        responses: List[Dict] — 每次 stream_complete 调用依次返回一个响应

    用于多步 ReAct 循环测试（每次 LLM 调用返回不同的 thought/action）。
    """
    from unittest.mock import MagicMock, AsyncMock

    router = MagicMock()
    call_state = {"idx": 0}

    def _stream_factory(*args, **kwargs):
        idx = call_state["idx"]
        call_state["idx"] += 1
        resp = responses[min(idx, len(responses) - 1)]
        return _stream_complete_generator(resp)

    router.stream_complete = _stream_factory
    router.complete = AsyncMock(side_effect=lambda *a, **kw: responses[min(call_state["idx"] - 1, len(responses) - 1)])
    router.select_model = MagicMock(return_value="test-model")
    return router

# 确保后端代码可导入
backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, backend_dir)

from app.db.session import get_db  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401 — 确保所有模型注册
    user, organization, project, dataset, target, molecule, developability, translation,
    validation,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    data_lineage, consent,
    failure_knowledge,
)
from app.models.protein_structure import ProteinStructure  # noqa: E402, F401
from app.models.compute_job import ComputeJob  # noqa: E402, F401
from app.models.benchmark_report import BenchmarkReport  # noqa: E402, F401
from app.models.neoantigen import Neoantigen  # noqa: E402, F401
from app.models.synthesis_plan import SynthesisPlan  # noqa: E402, F401
from app.models.analysis_template import AnalysisTemplate  # noqa: E402, F401
from app.models.agent_session import AgentSession, SessionStatus  # noqa: E402, F401
from app.models.agent_task import AgentTask, TaskStatus  # noqa: E402, F401
from app.models.context_memory import ContextMemory  # noqa: E402, F401
from app.models.coscientist_insight import CoScientistInsight  # noqa: E402, F401
from app.models.coscientist_run import CoScientistRun  # noqa: E402, F401
from app.models.llm_config import LLMConfig  # noqa: E402, F401
from app.models.model_switch_log import ModelSwitchLog  # noqa: E402, F401
from app.models.multimodal_asset import MultimodalAsset  # noqa: E402, F401
from app.models.personal_genome import PersonalGenome, RiskAssessment  # noqa: E402, F401
from app.models.pipeline_run import PipelineRun  # noqa: E402, F401
from app.models.prompt_template import PromptTemplate  # noqa: E402, F401
from app.models.reasoning_rule import ReasoningRule  # noqa: E402, F401
from app.models.reasoning_trace import ReasoningTrace  # noqa: E402, F401
from app.models.report import TargetReport  # noqa: E402, F401
from app.models.sandbox_execution import SandboxExecution  # noqa: E402, F401
from app.models.snp_locus import SnpLocus  # noqa: E402, F401
from app.models.trait import Trait  # noqa: E402, F401
from app.models.unified_session import UnifiedSession  # noqa: E402, F401
from app.models.user_llm_config import UserLLMConfig  # noqa: E402, F401


@pytest.fixture(scope="session")
def event_loop():
    """全局事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_rate_limiter_storage():
    """每个测试前清空 slowapi 限流器存储，避免测试间相互影响"""
    try:
        from app.core.limiter import limiter
        storage = limiter._storage
        if storage is not None and hasattr(storage, "reset"):
            storage.reset()
    except Exception:
        pass
    yield


@pytest_asyncio.fixture
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite in-memory 数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    await engine.dispose()


@pytest_asyncio.fixture
async def client(async_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP 测试客户端"""
    from app.main import app

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient, async_db_session: AsyncSession) -> str:
    """注册并登录获取 JWT token

    测试夹具直接在 DB 创建 founder 用户（绕过注册端点的角色限制），
    因为许多测试需要高权限角色来测试 LLM 配置等受保护端点。
    """
    from app.core.security import hash_password, UserRole
    from app.models.user import User

    # 直接在 DB 创建 founder 用户（测试夹具特权）
    user = User(
        email="test@ai-drug.com",
        name="Test User",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    # 登录
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@ai-drug.com", "password": "test123456"},
    )
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    """带认证的请求头"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def test_project(client: AsyncClient, auth_headers: dict) -> dict:
    """创建测试项目"""
    resp = await client.post("/api/v1/projects", json={
        "name": "Test NSCLC Project",
        "patient_pseudonym": "TEST-001",
        "cancer_type": "NSCLC",
        "stage": "IV",
        "description": "测试用 NSCLC 个性化治疗项目",
    }, headers=auth_headers)
    assert resp.status_code == 200, f"创建项目失败: {resp.text}"
    return resp.json()
