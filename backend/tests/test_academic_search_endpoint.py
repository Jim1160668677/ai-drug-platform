"""学术资源聚合检索端点 — 契约测试

验证 POST /api/v1/knowledge/academic-search 的基本契约：
- 200 单源检索
- 200 多源检索
"""
import os
import sys
import uuid as uuid_mod
from types import SimpleNamespace
from typing import AsyncGenerator, Dict, List
from unittest.mock import MagicMock, patch

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
from app.models.user import User  # noqa: E402

TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000003")


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
        email="academic@test.com",
        name="Academic Tester",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()

    async def mock_get_user(token=auth_token):
        return SimpleNamespace(
            id=TEST_USER_ID,
            email="academic@test.com",
            name="Academic Tester",
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


def _make_paper(title: str, source: str, doi: str = None) -> SimpleNamespace:
    """构造模拟的 AcademicPaper 对象"""
    paper = SimpleNamespace(
        title=title,
        authors=["Author A", "Author B"],
        source=source,
        abstract="Test abstract",
        doi=doi,
        year=2024,
        url=f"https://example.com/{source}",
        relevance_score=0.9,
    )
    paper.model_dump = lambda: {
        "title": paper.title,
        "authors": paper.authors,
        "source": paper.source,
        "abstract": paper.abstract,
        "doi": paper.doi,
        "year": paper.year,
        "url": paper.url,
        "relevance_score": paper.relevance_score,
    }
    return paper


def _setup_mock_client(mock_client_cls, search_all_result: Dict[str, List]) -> MagicMock:
    """构造 AcademicSearchClient mock 实例

    注意：sort_by_relevance 在路由中被调用为 AcademicSearchClient.sort_by_relevance(papers)
    （类级别静态方法调用），因此需要在 class mock 上设置。
    """
    mock_instance = MagicMock()

    async def mock_search_all(*args, **kwargs):
        return search_all_result

    mock_instance.search_all = mock_search_all
    mock_instance.deduplicate = lambda papers: papers
    mock_instance.sort_by_relevance = lambda papers: papers
    mock_client_cls.sort_by_relevance = lambda papers: papers
    mock_client_cls.return_value = mock_instance
    return mock_instance


class TestAcademicSearchEndpoint:
    """POST /api/v1/knowledge/academic-search 契约测试"""

    @pytest.mark.asyncio
    @patch("app.services.analyzer.academic_search_client.AcademicSearchClient")
    async def test_single_source_search_returns_200(self, mock_client_cls, client):
        """单源检索应返回 200 + 正确结构"""
        search_result = {
            "pubmed": [_make_paper("EGFR in NSCLC", "pubmed", doi="10.1000/test1")]
        }
        _setup_mock_client(mock_client_cls, search_result)

        resp = await client.post(
            "/api/v1/knowledge/academic-search",
            json={"query": "EGFR lung cancer", "sources": ["pubmed"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        data = body["data"]
        assert data["query"] == "EGFR lung cancer"
        assert "pubmed" in data["sources_queried"]
        assert isinstance(data["total_hits"], dict)
        assert isinstance(data["papers"], list)
        assert isinstance(data["search_time_ms"], int)

    @pytest.mark.asyncio
    @patch("app.services.analyzer.academic_search_client.AcademicSearchClient")
    async def test_multi_source_search_returns_200(self, mock_client_cls, client):
        """多源检索应返回 200 + 聚合结果"""
        search_result = {
            "pubmed": [_make_paper("PubMed Paper", "pubmed", doi="10.1000/p1")],
            "arxiv": [_make_paper("ArXiv Paper", "arxiv", doi="10.48550/a1")],
            "biorxiv": [_make_paper("BioRxiv Paper", "biorxiv", doi="10.1101/b1")],
        }
        _setup_mock_client(mock_client_cls, search_result)

        resp = await client.post(
            "/api/v1/knowledge/academic-search",
            json={
                "query": "CRISPR gene editing",
                "sources": ["pubmed", "arxiv", "biorxiv"],
                "limit_per_source": 5,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["query"] == "CRISPR gene editing"
        assert len(data["sources_queried"]) == 3
        assert data["total_hits"]["pubmed"] == 1
        assert data["total_hits"]["arxiv"] == 1
        assert data["total_hits"]["biorxiv"] == 1
        assert len(data["papers"]) == 3
