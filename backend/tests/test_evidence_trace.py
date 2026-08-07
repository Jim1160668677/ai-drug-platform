"""Evidence Traceability 测试 — 验证 getTrace 端点返回 tool_call 步骤的 evidence 数据

测试维度：
1. tool_call 步骤应包含 evidence 字段（query/sources/total_hits/papers）
2. 非 tool_call 步骤 evidence 应为 None
3. 端到端：通过 API 调用验证响应结构
"""
import os
import sys
import uuid as uuid_mod
from types import SimpleNamespace
from typing import AsyncGenerator
from uuid import UUID, uuid4

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
from app.core.security import UserRole, create_access_token, hash_password  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)
from app.models.reasoning_trace import ReasoningTrace  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000003")


# ============================================================
# Fixtures
# ============================================================

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
    return create_access_token(
        subject=str(TEST_USER_ID), role=UserRole.CHIEF_RESEARCHER
    )


@pytest_asyncio.fixture
async def client(db_session, auth_token) -> AsyncGenerator[AsyncClient, None]:
    u = User(
        id=TEST_USER_ID,
        email="evidence@test.com",
        name="Evidence Tester",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()

    async def mock_get_user(token=auth_token):
        return SimpleNamespace(
            id=TEST_USER_ID,
            email="evidence@test.com",
            name="Evidence Tester",
            role=UserRole.CHIEF_RESEARCHER,
            is_active=True,
        )

    async def mock_get_db():
        yield db_session

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[oauth2_scheme] = mock_get_user
    app.dependency_overrides[get_db] = mock_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _create_trace_step(
    db_session: AsyncSession,
    session_id: UUID,
    step_type: str,
    input_data: dict = None,
    output_data: dict = None,
) -> UUID:
    """辅助函数：创建一条 ReasoningTrace 记录"""
    step_id = uuid4()
    trace = ReasoningTrace(
        id=step_id,
        session_id=session_id,
        step_type=step_type,
        input_data=input_data,
        output_data=output_data,
        status="completed",
    )
    db_session.add(trace)
    return step_id


# ============================================================
# 单元测试：_extract_evidence 函数
# ============================================================

class TestExtractEvidence:
    """直接测试 _extract_evidence 辅助函数"""

    def test_tool_call_step_returns_evidence(self):
        from app.services.intelligence.orchestrator import _extract_evidence

        step = SimpleNamespace(
            step_type="tool_call",
            input_data={
                "query": "KRAS G12D drug discovery",
                "sources": ["bioRxiv", "arXiv"],
            },
            output_data={
                "total_hits": {"bioRxiv": 15, "arXiv": 8},
                "papers": [
                    {"title": "KRAS inhibitors review", "doi": "10.1234/test"},
                    {"title": "G12D mutation analysis", "doi": "10.5678/test"},
                ],
            },
        )
        result = _extract_evidence(step)
        assert result is not None
        assert result["query"] == "KRAS G12D drug discovery"
        assert result["sources"] == ["bioRxiv", "arXiv"]
        assert result["total_hits"] == {"bioRxiv": 15, "arXiv": 8}
        assert len(result["papers"]) == 2
        assert result["papers"][0]["title"] == "KRAS inhibitors review"

    def test_non_tool_call_steps_return_none(self):
        from app.services.intelligence.orchestrator import _extract_evidence

        for step_type in ["user_message", "assistant_message", "agent_call",
                          "llm_call", "decision_point", "phase_start"]:
            step = SimpleNamespace(
                step_type=step_type,
                input_data={"query": "should be ignored"},
                output_data={"papers": ["should be ignored"]},
            )
            assert _extract_evidence(step) is None

    def test_tool_call_with_missing_fields_returns_defaults(self):
        from app.services.intelligence.orchestrator import _extract_evidence

        step = SimpleNamespace(
            step_type="tool_call",
            input_data=None,
            output_data=None,
        )
        result = _extract_evidence(step)
        assert result is not None
        assert result["query"] == ""
        assert result["sources"] == []
        assert result["total_hits"] == {}
        assert result["papers"] == []

    def test_tool_call_with_partial_data(self):
        from app.services.intelligence.orchestrator import _extract_evidence

        step = SimpleNamespace(
            step_type="tool_call",
            input_data={"query": "partial test"},
            output_data={"papers": [{"title": "Only one paper"}]},
        )
        result = _extract_evidence(step)
        assert result["query"] == "partial test"
        assert result["sources"] == []
        assert result["total_hits"] == {}
        assert len(result["papers"]) == 1


# ============================================================
# 集成测试：API 端到端
# ============================================================

class TestEvidenceTraceAPI:
    """通过 API 验证 evidence 字段在 trace 端点中正确序列化"""

    @pytest.mark.asyncio
    async def test_trace_includes_evidence_for_tool_call(self, client, db_session):
        """tool_call 步骤应在 trace 响应中包含 evidence 数据"""
        session_id = uuid4()
        # 创建一条 tool_call trace
        _create_trace_step(
            db_session, session_id, "tool_call",
            input_data={
                "query": "BRCA1 targeted therapy",
                "sources": ["bioRxiv", "Semantic Scholar"],
            },
            output_data={
                "total_hits": {"bioRxiv": 23, "Semantic Scholar": 45},
                "papers": [{"title": "BRCA1 and PARP inhibitors"}],
            },
        )
        await db_session.commit()

        # 创建会话记录（_get_session_or_404 需要）
        from app.models.unified_session import UnifiedSession
        sess = UnifiedSession(
            id=session_id,
            user_id=TEST_USER_ID,
            title="Evidence Test Session",
            status="active",
            primary_mode="reasoning",
        )
        db_session.add(sess)
        await db_session.commit()

        resp = await client.get(f"/api/v1/intelligence/sessions/{session_id}/trace")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "traces" in body["data"]
        assert len(body["data"]["traces"]) >= 1

        tool_step = body["data"]["traces"][0]
        assert tool_step["step_type"] == "tool_call"
        assert "evidence" in tool_step
        assert tool_step["evidence"] is not None
        assert tool_step["evidence"]["query"] == "BRCA1 targeted therapy"
        assert tool_step["evidence"]["sources"] == ["bioRxiv", "Semantic Scholar"]
        assert tool_step["evidence"]["total_hits"] == {"bioRxiv": 23, "Semantic Scholar": 45}
        assert len(tool_step["evidence"]["papers"]) == 1

    @pytest.mark.asyncio
    async def test_trace_evidence_none_for_non_tool_call(self, client, db_session):
        """非 tool_call 步骤 evidence 应为 None"""
        session_id = uuid4()
        _create_trace_step(
            db_session, session_id, "user_message",
            input_data={"message": "Hello"},
            output_data={"response": "Hi"},
        )
        await db_session.commit()

        from app.models.unified_session import UnifiedSession
        sess = UnifiedSession(
            id=session_id,
            user_id=TEST_USER_ID,
            title="Non-tool Test",
            status="active",
            primary_mode="chat",
        )
        db_session.add(sess)
        await db_session.commit()

        resp = await client.get(f"/api/v1/intelligence/sessions/{session_id}/trace")
        assert resp.status_code == 200
        body = resp.json()
        traces = body["data"]["traces"]
        assert len(traces) >= 1

        step = traces[0]
        assert step["step_type"] == "user_message"
        assert step["evidence"] is None

    @pytest.mark.asyncio
    async def test_trace_mixed_step_types(self, client, db_session):
        """混合步骤类型：只有 tool_call 有 evidence"""
        session_id = uuid4()
        _create_trace_step(db_session, session_id, "user_message")
        _create_trace_step(
            db_session, session_id, "tool_call",
            input_data={"query": "EGFR resistance"},
            output_data={"papers": [{"title": "EGFR T790M"}]},
        )
        _create_trace_step(db_session, session_id, "assistant_message")
        await db_session.commit()

        from app.models.unified_session import UnifiedSession
        sess = UnifiedSession(
            id=session_id,
            user_id=TEST_USER_ID,
            title="Mixed Steps Test",
            status="active",
            primary_mode="reasoning",
        )
        db_session.add(sess)
        await db_session.commit()

        resp = await client.get(f"/api/v1/intelligence/sessions/{session_id}/trace")
        assert resp.status_code == 200
        traces = resp.json()["data"]["traces"]

        # 至少找到 3 个步骤
        assert len(traces) >= 3

        for step in traces:
            if step["step_type"] == "tool_call":
                assert step["evidence"] is not None
                assert step["evidence"]["query"] == "EGFR resistance"
            else:
                assert step["evidence"] is None
