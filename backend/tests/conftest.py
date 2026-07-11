"""pytest 配置 — 测试 fixtures"""
import asyncio
import os
import sys
from typing import AsyncGenerator

# 测试环境强制 Mock 模式
os.environ["USE_MOCK"] = "true"
os.environ["APP_ENV"] = "testing"

# 确保测试用 SQLite
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 确保后端代码可导入
backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, backend_dir)

from app.db.session import get_db  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401 — 确保所有模型注册
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
)


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
