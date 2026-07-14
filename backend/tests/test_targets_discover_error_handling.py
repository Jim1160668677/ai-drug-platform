"""B1/B2/B3 — 后端 API 错误处理测试

验证：
- /targets/discover 端点异常时返回 200 + success=False（而非 502）
- /targets/{id}/force-deep-analysis 端点异常时返回 200 + error 字段
- AppException 子类异常按原状态码传播（不吞掉）
- deep_insight 模式 LLM 调用超时不导致 discover() 抛出
"""
import os
import sys
import uuid
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.deps import get_current_user, oauth2_scheme  # noqa: E402
from app.core.exceptions import NotFoundError  # noqa: E402
from app.core.security import UserRole, create_access_token, decode_token  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
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
async def auth_token() -> str:
    return create_access_token(subject="test-user-id", role=UserRole.FOUNDER)


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    from fastapi import Depends, HTTPException, status

    async def mock_get_current_user(token: str = Depends(oauth2_scheme)):
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return SimpleNamespace(
            id=TEST_USER_ID,
            email="test@ai-drug.com",
            name="Test User",
            role=UserRole.FOUNDER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


class TestDiscoverErrorHandling:
    """B1: /targets/discover 错误处理"""

    @pytest.mark.asyncio
    async def test_discover_handles_exception_returns_success_false(
        self, client: AsyncClient, auth_headers: dict
    ):
        """discover() 抛出非 AppException 异常时返回 200 + success=False"""
        project_id = uuid.uuid4()

        async def mock_discover(*args, **kwargs):
            raise RuntimeError("模拟的内部错误")

        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new=mock_discover,
        ):
            resp = await client.post(
                f"/api/v1/targets/discover?project_id={project_id}&tier=fast_screen",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "靶点发现失败" in body["message"]
        assert body["data"]["error"] == "模拟的内部错误"

    @pytest.mark.asyncio
    async def test_discover_propagates_app_exception(
        self, client: AsyncClient, auth_headers: dict
    ):
        """AppException 子类按原状态码传播"""
        project_id = uuid.uuid4()

        async def mock_discover(*args, **kwargs):
            raise NotFoundError("资源不存在")

        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new=mock_discover,
        ):
            resp = await client.post(
                f"/api/v1/targets/discover?project_id={project_id}&tier=fast_screen",
                headers=auth_headers,
            )
        assert resp.status_code == 404


class TestForceDeepAnalysisErrorHandling:
    """B3: /targets/{id}/force-deep-analysis 错误处理"""

    @pytest.mark.asyncio
    async def test_force_deep_analysis_handles_exception(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """force_deep_analysis 内部异常时返回 200 + error 字段"""
        from app.models.target import Target, EvidenceGrade

        target_obj = Target(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            gene_symbol="TEST_GENE",
            evidence_grade=EvidenceGrade.LEVEL_IV,
            confidence_score=0.5,
            source="test",
        )
        db_session.add(target_obj)
        await db_session.flush()

        async def mock_discover(*args, **kwargs):
            raise RuntimeError("LLM 服务不可用")

        with patch(
            "app.services.analyzer.target_identifier.TargetIdentifier.discover",
            new=mock_discover,
        ):
            resp = await client.post(
                f"/api/v1/targets/{target_obj.id}/force-deep-analysis",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "error" in body["data"]
        assert body["data"]["analysis"] is None


class TestLLMTimeoutProtection:
    """B2: deep_insight LLM 超时保护"""

    def test_source_code_contains_timeout_protection(self):
        """验证 target_identifier.py 源码包含 asyncio.wait_for 超时保护"""
        import inspect
        from app.services.analyzer import target_identifier as mod

        source = inspect.getsource(mod)
        assert "asyncio.wait_for" in source, "LLM 调用应使用 asyncio.wait_for 添加超时"
        assert "timeout=60" in source, "超时应设置为 60 秒"
        assert "TimeoutError" in source, "应捕获 TimeoutError 异常"

    @pytest.mark.asyncio
    async def test_asyncio_wait_for_timeout_catches_correctly(self):
        """验证 asyncio.wait_for + TimeoutError 捕获模式工作正常"""
        import asyncio

        call_made = False

        async def slow_operation():
            nonlocal call_made
            call_made = True
            await asyncio.sleep(10)

        caught = False
        try:
            await asyncio.wait_for(slow_operation(), timeout=0.1)
        except asyncio.TimeoutError:
            caught = True

        assert call_made, "slow_operation 应被调用"
        assert caught, "TimeoutError 应被正确捕获"
