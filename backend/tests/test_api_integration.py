"""HTTP 层端到端集成测试 (P4.2)

覆盖传统端点（auth / projects / data / knowledge / targets / molecules /
chat / dashboard）的 HTTP 层集成测试，补充 test_new_endpoints.py 未覆盖的部分。

测试维度：
- 认证流程：登录成功 / 密码错误 / 邮箱不存在 / 无 token / 无效 token / 有效 token
- 项目生命周期：创建 / 列表 / 详情 / 404 / 未授权
- 数据接入流程：上传 / 列表 / 详情 / 解析 / 质量报告
- 知识库查询：基因 / 变异 / ChEMBL 活性分子
- 靶点发现：发现 / 列表 / 404
- 分子设计：设计 / 列表 / 类药性评估
- 聊天 / LLM：问答 / 层级说明
- 看板：全局聚合
- 错误场景：404 路径不存在 / 400 校验错误 / 502 上游错误
- 响应信封验证：success / data / meta / 响应头

技术要点：
- httpx.AsyncClient + ASGITransport(app=app) 异步 HTTP 测试
- SQLite 内存数据库（每个测试独立引擎）
- JWT token 通过 app.core.security.create_access_token 直接生成
- 覆盖 get_current_user：仍校验 JWT 签名（缺 / 非法 token → 401），
  但跳过 DB 查找与 bcrypt，返回 SimpleNamespace（id 为 uuid.UUID 以兼容 DB 外键）
- 覆盖 get_db：使用内存 SQLite 会话
- 环境变量：USE_MOCK=true, APP_ENV=testing, DATABASE_URL=sqlite+aiosqlite:///:memory:
- 每个测试前重置 privacy / federated / ws 模块级单例以保证隔离

注意：
- 本文件不使用 --cov 运行（PyO3/bcrypt 兼容性问题），用 --no-cov
- 部分任务描述的端点路径与实际实现不符（如 GET /knowledge/genes 实际为
  POST /knowledge/gene），测试按实际实现编写并加注释说明
- 端点返回格式有两种：信封（success_response / StandardResponse）和原始模型
  （ProjectResponse / DatasetResponse 等），信封验证仅对信封响应断言
"""
import os
import sys
import uuid as uuid_mod
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure backend on path (conftest.py also does this, but keep self-contained)
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Test environment (conftest.py also sets these; setdefault is harmless)
os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.deps import get_current_user, oauth2_scheme  # noqa: E402
from app.core.security import (  # noqa: E402
    UserRole,
    create_access_token,
    decode_token,
    hash_password,
)
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401 — register all models on metadata
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)
from app.models.user import User  # noqa: E402

# Fixed test user ID (valid UUID for DB foreign-key compatibility)
TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000001")


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite in-memory DB session with all tables created."""
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
async def db_user(db_session: AsyncSession) -> User:
    """Create a real user in DB for FK constraints (projects.owner_id etc.)."""
    u = User(
        id=TEST_USER_ID,
        email="test@integration.com",
        name="Integration Tester",
        hashed_password=hash_password("pass123"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def auth_token(db_user: User) -> str:
    """JWT token (signature valid; user exists in DB for FK).

    get_current_user is mocked to skip DB lookup, but the user record exists
    so that endpoints creating FK-referenced rows (Project.owner_id etc.)
    succeed.
    """
    return create_access_token(subject=str(TEST_USER_ID), role=UserRole.RESEARCHER)


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with get_db + get_current_user overridden.

    - get_current_user: mock that still validates JWT signature (so missing /
      invalid tokens → 401) but skips DB lookup + bcrypt. Returns a
      SimpleNamespace stand-in for the User model (id is uuid.UUID).
    - get_db: yields the in-memory SQLite session for DB-dependent endpoints.

    Resets privacy / federated / ws module-level singletons before each test.
    """
    # Reset module-level singletons for test isolation
    from app.api.v1.endpoints import privacy as privacy_mod
    from app.api.v1.endpoints import federated as federated_mod
    from app.api.v1.endpoints import ws as ws_mod
    privacy_mod._PRIVACY_LAYER = None
    privacy_mod._PRIVACY_BUDGET = None
    federated_mod._FL_SERVICE = None
    ws_mod._progress_manager = ws_mod.TaskProgressManager()

    async def override_get_db():
        yield db_session

    from fastapi import Depends, HTTPException, status

    async def mock_get_current_user(
        token: str = Depends(oauth2_scheme),
    ):
        """Mock get_current_user: validate JWT signature, skip DB lookup.

        oauth2_scheme raises HTTPException(401) when no Authorization header
        is present, so unauthorized requests still get 401 without reaching
        the function body.
        """
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        role_str = payload.get("role", "researcher")
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.RESEARCHER
        # Convert user_id to UUID for DB foreign-key compatibility
        try:
            uid = uuid_mod.UUID(user_id)
        except (ValueError, TypeError):
            uid = user_id
        return SimpleNamespace(
            id=uid,
            email="test@integration.com",
            name="Integration Tester",
            role=role,
            is_active=True,
            organization=None,
            created_at=datetime.now(timezone.utc),
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ============================================================
# Helpers
# ============================================================

def assert_envelope_success(body: dict, headers: dict) -> None:
    """Assert response is a successful ApiResponse envelope.

    Checks: success=true, data exists, meta exists with duration_ms (int),
    X-Request-ID and X-Response-Time-ms headers present.
    """
    assert body["success"] is True, f"expected success=True, got: {body}"
    assert "data" in body, f"missing 'data' field: {body}"
    assert body.get("meta") is not None, f"missing 'meta' field: {body}"
    assert isinstance(body["meta"].get("duration_ms"), int), \
        f"meta.duration_ms not int: {body.get('meta')}"
    assert "x-request-id" in {k.lower() for k in headers}, \
        f"missing X-Request-ID header: {dict(headers)}"
    assert "x-response-time-ms" in {k.lower() for k in headers}, \
        f"missing X-Response-Time-ms header: {dict(headers)}"


def assert_envelope_error(body: dict, headers: dict, expected_code: str) -> None:
    """Assert response is an error envelope with the expected code."""
    assert body["success"] is False, f"expected success=False, got: {body}"
    assert body["error"]["code"] == expected_code, \
        f"expected error code {expected_code}, got: {body['error']['code']}"
    assert "x-request-id" in {k.lower() for k in headers}, \
        f"missing X-Request-ID header: {dict(headers)}"


def assert_headers_present(headers: dict) -> None:
    """Assert X-Request-ID and X-Response-Time-ms headers are present."""
    lower_keys = {k.lower() for k in headers}
    assert "x-request-id" in lower_keys, "missing X-Request-ID header"
    assert "x-response-time-ms" in lower_keys, "missing X-Response-Time-ms header"


# ============================================================
# 1. 认证流程 (Auth Flow)
# ============================================================

class TestAuthFlow:
    """认证端点 HTTP 层集成测试 — 登录 / token 校验"""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_user: User):
        """login 成功 → 200 + access_token + role + email"""
        # db_user 已创建（密码 hash_password("pass123")），但 login 需要 verify_password
        # 直接用 db_user 的凭据登录
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@integration.com", "password": "pass123"},
        )
        assert resp.status_code == 200, f"login failed: {resp.text}"
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["role"] == "researcher"
        assert body["email"] == "test@integration.com"
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, db_user: User):
        """login 密码错误 → 401 UNAUTHORIZED"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@integration.com", "password": "wrong-password"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert_envelope_error(body, resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_login_nonexistent_email(self, client: AsyncClient):
        """login 邮箱不存在 → 401"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nowhere.com", "password": "anypassword"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert_envelope_error(body, resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_protected_endpoint_no_token(self, client: AsyncClient):
        """受保护端点无 token → 401（oauth2_scheme 在 mock 之前拒绝）"""
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 401
        body = resp.json()
        assert_envelope_error(body, resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_protected_endpoint_invalid_token(self, client: AsyncClient):
        """受保护端点带无效 token → 401（mock 中 decode_token 失败）"""
        resp = await client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert_envelope_error(body, resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_protected_endpoint_valid_token(
        self, client: AsyncClient, auth_headers: dict
    ):
        """受保护端点带有效 token → 200"""
        resp = await client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        assert_headers_present(resp.headers)


# ============================================================
# 2. 项目生命周期 (Project Lifecycle)
# ============================================================

class TestProjectLifecycle:
    """项目端点 HTTP 层集成测试 — 创建 / 列表 / 详情 / 404"""

    @pytest.mark.asyncio
    async def test_create_project(self, client: AsyncClient, auth_headers: dict):
        """POST /projects 创建项目 → 200 + ProjectResponse（原始模型，非信封）"""
        resp = await client.post(
            "/api/v1/projects",
            json={
                "name": "Integration Test Project",
                "patient_pseudonym": "IT-001",
                "cancer_type": "NSCLC",
                "stage": "IV",
                "description": "Integration test project",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"create project failed: {resp.text}"
        body = resp.json()
        # ProjectResponse 原始模型（非 ApiResponse 信封）
        assert body["name"] == "Integration Test Project"
        assert body["cancer_type"] == "NSCLC"
        assert body["stage"] == "IV"
        assert body["status"] == "active"
        assert "id" in body
        assert "owner_id" in body
        assert "created_at" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_list_projects(self, client: AsyncClient, auth_headers: dict):
        """GET /projects 列表 → 200 + PagedResponse 信封"""
        # 先创建一个项目
        await client.post(
            "/api/v1/projects",
            json={"name": "List Test Project"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # PagedResponse 信封
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 1
        assert any(p["name"] == "List Test Project" for p in body["data"])
        assert body["meta"]["total"] >= 1
        assert body["meta"]["page"] == 1
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_get_project_detail(self, client: AsyncClient, auth_headers: dict):
        """GET /projects/{id} 详情 → 200 + ProjectResponse"""
        create = await client.post(
            "/api/v1/projects",
            json={"name": "Detail Test Project", "cancer_type": "Breast"},
            headers=auth_headers,
        )
        project_id = create.json()["id"]
        resp = await client.get(
            f"/api/v1/projects/{project_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == project_id
        assert body["name"] == "Detail Test Project"
        assert body["cancer_type"] == "Breast"
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, client: AsyncClient, auth_headers: dict):
        """GET /projects/{nonexistent} → 404 NOT_FOUND 信封"""
        nonexistent_id = uuid_mod.uuid4()
        resp = await client.get(
            f"/api/v1/projects/{nonexistent_id}", headers=auth_headers
        )
        assert resp.status_code == 404
        body = resp.json()
        assert_envelope_error(body, resp.headers, "NOT_FOUND")

    @pytest.mark.asyncio
    async def test_create_project_unauthorized(self, client: AsyncClient):
        """POST /projects 无 token → 401"""
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "Unauthorized Project"},
        )
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    # 注意：任务描述提到"权限不足（researcher 创建项目，如不允许）→ 403 FORBIDDEN"，
    # 但实际 projects.py 的 create_project 端点无角色限制（任何认证用户均可创建），
    # 因此跳过该测试。


# ============================================================
# 3. 数据接入流程 (Data Pipeline)
# ============================================================

class TestDataPipeline:
    """数据端点 HTTP 层集成测试 — 上传 / 列表 / 详情 / 解析 / 质量报告

    注意：任务描述提到 "POST /api/v1/data 上传数据集元信息"，但实际端点是
    POST /api/v1/data/upload（需要 project_id/name/data_type query 参数 + 文件上传）。
    测试按实际实现编写。
    """

    @pytest.mark.asyncio
    async def test_upload_dataset(self, client: AsyncClient, auth_headers: dict):
        """POST /data/upload 上传数据文件 → 200 + DatasetResponse"""
        # 先创建项目
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Data Upload Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        # 上传 CSV 文件
        csv_content = b"gene,expression\nEGFR,1.5\nKRAS,2.3\nTP53,0.8\n"
        resp = await client.post(
            "/api/v1/data/upload",
            params={
                "project_id": project_id,
                "name": "Test RNA-seq Dataset",
                "data_type": "rna_seq",
            },
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"upload failed: {resp.text}"
        body = resp.json()
        assert body["name"] == "Test RNA-seq Dataset"
        assert body["data_type"] == "rna_seq"
        assert body["parse_status"] == "pending"
        assert "id" in body
        assert "project_id" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_list_datasets(self, client: AsyncClient, auth_headers: dict):
        """GET /data 列表 → 200 + List[DatasetResponse]"""
        # 先创建项目并上传数据
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Data List Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        await client.post(
            "/api/v1/data/upload",
            params={"project_id": project_id, "name": "DS1", "data_type": "rna_seq"},
            files={"file": ("d.csv", b"a,b\n1,2\n", "text/csv")},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/data", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 1
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_get_dataset_detail(self, client: AsyncClient, auth_headers: dict):
        """GET /data/{id} 详情 → 200 + DatasetResponse"""
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Data Detail Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        upload = await client.post(
            "/api/v1/data/upload",
            params={"project_id": project_id, "name": "Detail DS", "data_type": "rna_seq"},
            files={"file": ("d.csv", b"gene,expr\nA,1\n", "text/csv")},
            headers=auth_headers,
        )
        dataset_id = upload.json()["id"]
        resp = await client.get(
            f"/api/v1/data/{dataset_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == dataset_id
        assert body["name"] == "Detail DS"
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_parse_dataset(self, client: AsyncClient, auth_headers: dict):
        """POST /data/{id}/parse 触发解析 → 200（Mock 模式）"""
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Parse Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        upload = await client.post(
            "/api/v1/data/upload",
            params={"project_id": project_id, "name": "Parse DS", "data_type": "rna_seq"},
            files={"file": ("d.csv", b"gene,expr\nA,1\nB,2\n", "text/csv")},
            headers=auth_headers,
        )
        dataset_id = upload.json()["id"]
        resp = await client.post(
            f"/api/v1/data/{dataset_id}/parse", headers=auth_headers
        )
        assert resp.status_code == 200, f"parse failed: {resp.text}"
        body = resp.json()
        # StandardResponse 信封格式
        assert body["success"] is True
        assert "data" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_quality_report(self, client: AsyncClient, auth_headers: dict):
        """GET /data/{id}/quality 获取质量指标 → 200 + ApiResponse 信封"""
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Quality Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        upload = await client.post(
            "/api/v1/data/upload",
            params={"project_id": project_id, "name": "Quality DS", "data_type": "rna_seq"},
            files={"file": ("d.csv", b"gene,expr\nA,1\n", "text/csv")},
            headers=auth_headers,
        )
        dataset_id = upload.json()["id"]
        # 先解析以填充 quality_metrics
        await client.post(
            f"/api/v1/data/{dataset_id}/parse", headers=auth_headers
        )
        resp = await client.get(
            f"/api/v1/data/{dataset_id}/quality", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        # success_response 信封
        assert body["success"] is True
        assert "quality_metrics" in body["data"]
        assert "parse_status" in body["data"]
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_get_dataset_not_found(self, client: AsyncClient, auth_headers: dict):
        """GET /data/{nonexistent} → 404 NOT_FOUND"""
        resp = await client.get(
            f"/api/v1/data/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert_envelope_error(resp.json(), resp.headers, "NOT_FOUND")


# ============================================================
# 4. 知识库查询 (Knowledge Query)
# ============================================================

class TestKnowledgeQuery:
    """知识库端点 HTTP 层集成测试 — 基因 / 变异 / ChEMBL

    注意：任务描述提到 GET /knowledge/genes?q=EGFR 等端点，但实际实现为
    POST /knowledge/gene（body: {gene_symbol}）等 POST 端点。
    测试按实际实现编写。
    """

    @pytest.mark.asyncio
    async def test_query_gene(self, client: AsyncClient, auth_headers: dict):
        """POST /knowledge/gene 搜索基因 → 200 + ApiResponse 信封（Mock）"""
        resp = await client.post(
            "/api/v1/knowledge/gene",
            json={"gene_symbol": "EGFR"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"query gene failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)

    @pytest.mark.asyncio
    async def test_query_gene_unauthorized(self, client: AsyncClient):
        """POST /knowledge/gene 无 token → 401"""
        resp = await client.post(
            "/api/v1/knowledge/gene",
            json={"gene_symbol": "EGFR"},
        )
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_query_variants(self, client: AsyncClient, auth_headers: dict):
        """POST /knowledge/variant 变异注释 → 200 + ApiResponse 信封（Mock）"""
        resp = await client.post(
            "/api/v1/knowledge/variant",
            json={"variants": ["chr7:55259515:T>A"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"query variants failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)

    @pytest.mark.asyncio
    async def test_query_chembl_activity(self, client: AsyncClient, auth_headers: dict):
        """POST /knowledge/chembl/activity ChEMBL 活性分子 → 200 + 信封（Mock）"""
        resp = await client.post(
            "/api/v1/knowledge/chembl/activity",
            json={"target_gene": "EGFR", "activity_type": "IC50", "limit": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"chembl activity failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)

    @pytest.mark.asyncio
    async def test_query_approved_drugs(self, client: AsyncClient, auth_headers: dict):
        """POST /knowledge/chembl/approved 已获批药物 → 200 + 信封（Mock）"""
        resp = await client.post(
            "/api/v1/knowledge/chembl/approved",
            params={"target_gene": "EGFR"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"approved drugs failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)

    # 注意：任务描述提到 GET /knowledge/genes/{gene}/neighbors 和
    # GET /knowledge/pathways/{pathway_id}，但这些端点在 knowledge.py 中不存在。
    # 跳过这些测试。


# ============================================================
# 5. 靶点发现 (Target Discovery)
# ============================================================

class TestTargetDiscovery:
    """靶点端点 HTTP 层集成测试 — 发现 / 列表 / 详情"""

    @pytest.mark.asyncio
    async def test_discover_targets(self, client: AsyncClient, auth_headers: dict):
        """POST /targets/discover → 200（Mock 模式返回候选靶点）"""
        # 先创建项目（无数据集 → discover 返回空靶点列表但成功）
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Target Discovery Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]
        resp = await client.post(
            "/api/v1/targets/discover",
            params={"project_id": project_id, "tier": "fast_screen"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"discover failed: {resp.text}"
        body = resp.json()
        # StandardResponse 信封格式
        assert body["success"] is True
        assert "data" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_discover_targets_unauthorized(self, client: AsyncClient):
        """POST /targets/discover 无 token → 401"""
        resp = await client.post(
            "/api/v1/targets/discover",
            params={"project_id": str(uuid_mod.uuid4())},
        )
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_list_targets(self, client: AsyncClient, auth_headers: dict):
        """GET /targets 列表 → 200 + PagedResponse 信封"""
        resp = await client.get("/api/v1/targets", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body["meta"]
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_get_target_not_found(self, client: AsyncClient, auth_headers: dict):
        """GET /targets/{nonexistent} → 404 NOT_FOUND"""
        resp = await client.get(
            f"/api/v1/targets/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        assert_envelope_error(resp.json(), resp.headers, "NOT_FOUND")


# ============================================================
# 6. 分子设计 (Molecule Design)
# ============================================================

class TestMoleculeDesign:
    """分子端点 HTTP 层集成测试 — 设计 / 列表 / 类药性"""

    @pytest.mark.asyncio
    async def test_design_molecule(self, client: AsyncClient, auth_headers: dict):
        """POST /molecules/design → 200（Mock 模式 / 框架响应）"""
        resp = await client.post(
            "/api/v1/molecules/design",
            json={"target_id": "test-target", "smiles": "CCO"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"design failed: {resp.text}"
        body = resp.json()
        # StandardResponse 信封格式
        assert body["success"] is True
        assert "data" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_design_molecule_unauthorized(self, client: AsyncClient):
        """POST /molecules/design 无 token → 401"""
        resp = await client.post(
            "/api/v1/molecules/design",
            json={"smiles": "CCO"},
        )
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_list_molecules(self, client: AsyncClient, auth_headers: dict):
        """GET /molecules 列表 → 200 + PagedResponse 信封"""
        resp = await client.get("/api/v1/molecules", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body["meta"]
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_assess_druglikeness(self, client: AsyncClient, auth_headers: dict):
        """POST /molecules/assess 类药性评估 → 200 + ApiResponse 信封"""
        resp = await client.post(
            "/api/v1/molecules/assess",
            params={"smiles": "CCO"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"assess failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)

    @pytest.mark.asyncio
    async def test_list_models(self, client: AsyncClient, auth_headers: dict):
        """GET /molecules/models 可用模型列表 → 200 + 信封"""
        resp = await client.get("/api/v1/molecules/models", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        assert "models" in body["data"]

    @pytest.mark.asyncio
    async def test_predict_properties(self, client: AsyncClient, auth_headers: dict):
        """POST /molecules/predict-properties ADMET 预测 → 200 + ApiResponse 信封"""
        resp = await client.post(
            "/api/v1/molecules/predict-properties",
            json={"smiles": "CCO"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"predict-properties failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        assert "logS" in body["data"]
        assert "bbb_permeability" in body["data"]
        assert "pains_alerts" in body["data"]

    @pytest.mark.asyncio
    async def test_explain_molecule(self, client: AsyncClient, auth_headers: dict):
        """POST /molecules/explain 分子可解释性 → 200 + ApiResponse 信封"""
        resp = await client.post(
            "/api/v1/molecules/explain",
            json={"smiles": "CCO"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"explain failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        assert "functional_groups" in body["data"]
        assert "rings" in body["data"]
        assert "atom_counts" in body["data"]


# ============================================================
# 7. 聊天 / LLM (Chat)
# ============================================================

class TestChat:
    """聊天端点 HTTP 层集成测试 — 问答 / 层级说明

    注意：流式响应端点在 chat.py 中不存在（POST /chat 返回 ChatResponse），
    跳过流式测试。
    """

    @pytest.mark.asyncio
    async def test_chat(self, client: AsyncClient, auth_headers: dict):
        """POST /chat 发送消息 → 200（Mock 模式返回 ChatResponse）"""
        resp = await client.post(
            "/api/v1/chat",
            json={
                "message": "EGFR 靶点有什么已获批药物？",
                "tier": "fast_screen",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"chat failed: {resp.text}"
        body = resp.json()
        # ChatResponse 原始模型（非信封）
        assert "answer" in body
        assert "tier" in body
        assert body["tier"] == "fast_screen"
        assert "model" in body
        assert "cost_usd" in body
        assert "duration_sec" in body
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_chat_unauthorized(self, client: AsyncClient):
        """POST /chat 无 token → 401"""
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "test"},
        )
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_chat_missing_message(self, client: AsyncClient, auth_headers: dict):
        """POST /chat 缺 message 字段 → 400 VALIDATION_ERROR"""
        resp = await client.post(
            "/api/v1/chat",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert_envelope_error(resp.json(), resp.headers, "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_chat_tiers(self, client: AsyncClient, auth_headers: dict):
        """GET /chat/tiers 分析层级说明 → 200 + ApiResponse 信封"""
        resp = await client.get("/api/v1/chat/tiers", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        assert "tiers" in body["data"]
        assert len(body["data"]["tiers"]) == 2

    @pytest.mark.asyncio
    async def test_chat_history(self, client: AsyncClient, auth_headers: dict):
        """GET /chat/history 聊天历史 → 200 + ApiResponse 信封"""
        resp = await client.get("/api/v1/chat/history", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        assert "history" in body["data"]

    @pytest.mark.asyncio
    async def test_chat_cost_summary(self, client: AsyncClient, auth_headers: dict):
        """GET /chat/cost-summary 成本汇总 → 200 + ApiResponse 信封"""
        resp = await client.get("/api/v1/chat/cost-summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert_envelope_success(body, resp.headers)


# ============================================================
# 8. 看板 (Dashboard)
# ============================================================

class TestDashboard:
    """看板端点 HTTP 层集成测试 — 全局聚合统计

    注意：任务描述提到 GET /api/v1/dashboard/stats，但 dashboard.py 中
    仅有 GET /dashboard/overview。跳过 /stats 测试。
    """

    @pytest.mark.asyncio
    async def test_dashboard_overview(self, client: AsyncClient, auth_headers: dict):
        """GET /dashboard/overview → 200 + ApiResponse 信封"""
        resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert resp.status_code == 200, f"dashboard failed: {resp.text}"
        body = resp.json()
        assert_envelope_success(body, resp.headers)
        # 验证聚合统计字段
        assert "global" in body["data"]
        assert "by_cancer_type" in body["data"]
        assert "by_status" in body["data"]
        assert "projects" in body["data"]
        assert "recent_experiments" in body["data"]
        # 空库应返回 0
        assert body["data"]["global"]["projects"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_overview_unauthorized(self, client: AsyncClient):
        """GET /dashboard/overview 无 token → 401"""
        resp = await client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 401
        assert_envelope_error(resp.json(), resp.headers, "UNAUTHORIZED")

    @pytest.mark.asyncio
    async def test_dashboard_overview_with_data(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /dashboard/overview 有数据后应正确聚合"""
        # 创建项目
        await client.post(
            "/api/v1/projects",
            json={"name": "Dashboard Project", "cancer_type": "NSCLC"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["global"]["projects"] == 1
        assert "NSCLC" in body["data"]["by_cancer_type"]


# ============================================================
# 9. 错误场景 (Error Scenarios)
# ============================================================

class TestErrorScenarios:
    """错误场景 HTTP 层集成测试 — 404 / 400 / 502"""

    @pytest.mark.asyncio
    async def test_404_path_not_found(self, client: AsyncClient):
        """不存在的路径 → 404

        注意：未匹配路由的 404 使用 FastAPI 默认格式 {"detail": "Not Found"}，
        不经过自定义 HTTPException 处理器（仅路由内部抛出的 HTTPException 才被转换）。
        但中间件仍注入 X-Request-ID / X-Response-Time-ms 响应头。
        """
        resp = await client.get("/api/v1/nonexistent-path")
        assert resp.status_code == 404
        # 中间件仍注入追踪头
        assert_headers_present(resp.headers)

    @pytest.mark.asyncio
    async def test_422_validation_error_becomes_400(
        self, client: AsyncClient, auth_headers: dict
    ):
        """请求体校验失败 → 400 VALIDATION_ERROR 信封（中间件转换 422 → 400）"""
        # POST /projects 需要 name 字段；传空 body 应触发 Pydantic 校验错误
        resp = await client.post(
            "/api/v1/projects",
            json={},  # 缺必填字段 name
            headers=auth_headers,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert_envelope_error(body, resp.headers, "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_400_validation_error_login_missing_fields(self, client: AsyncClient):
        """POST /auth/login 缺字段 → 400 VALIDATION_ERROR"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={},  # 缺 email 和 password
        )
        assert resp.status_code == 400
        assert_envelope_error(resp.json(), resp.headers, "VALIDATION_ERROR")

    @pytest.mark.asyncio
    async def test_502_upstream_error(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """上游服务异常 → 502 UPSTREAM_ERROR 信封

        通过 mock parser 抛出异常来触发 data.py 中的 UpstreamError。
        """
        from app.models.project import Project
        from app.models.dataset import Dataset, DataType, ParseStatus

        # 直接在 DB 中创建项目和数据集（绕过文件上传）
        project = Project(
            name="Upstream Error Project",
            owner_id=TEST_USER_ID,
        )
        db_session.add(project)
        await db_session.flush()

        dataset = Dataset(
            project_id=project.id,
            name="Error DS",
            data_type=DataType.RNA_SEQ,
            storage_path="/nonexistent/path.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=TEST_USER_ID,
        )
        db_session.add(dataset)
        await db_session.flush()

        # Mock parser 抛出异常 → 端点捕获后 raise UpstreamError
        with patch(
            "app.services.parser.base.parse_dataset",
            new_callable=AsyncMock,
        ) as mock_parse:
            mock_parse.side_effect = Exception("Mock parser failure")
            resp = await client.post(
                f"/api/v1/data/{dataset.id}/parse",
                headers=auth_headers,
            )
        assert resp.status_code == 502, f"expected 502, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert_envelope_error(body, resp.headers, "UPSTREAM_ERROR")

    @pytest.mark.asyncio
    async def test_404_project_not_found_envelope(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /projects/{nonexistent} → 404 NOT_FOUND 信封（含 error.code）"""
        resp = await client.get(
            f"/api/v1/projects/{uuid_mod.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        body = resp.json()
        assert_envelope_error(body, resp.headers, "NOT_FOUND")
        # 验证错误信封结构完整
        assert "message" in body["error"]
        assert "details" in body["error"]


# ============================================================
# 10. 响应信封验证 (Response Envelope Validation)
# ============================================================

class TestResponseEnvelope:
    """响应信封验证 — 对所有信封响应统一校验 success/data/meta/headers"""

    @pytest.mark.asyncio
    async def test_envelope_knowledge_gene(self, client: AsyncClient, auth_headers: dict):
        """知识库基因查询信封验证"""
        resp = await client.post(
            "/api/v1/knowledge/gene",
            json={"gene_symbol": "EGFR"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert_envelope_success(resp.json(), resp.headers)

    @pytest.mark.asyncio
    async def test_envelope_dashboard_overview(
        self, client: AsyncClient, auth_headers: dict
    ):
        """看板概览信封验证"""
        resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert resp.status_code == 200
        assert_envelope_success(resp.json(), resp.headers)

    @pytest.mark.asyncio
    async def test_envelope_chat_tiers(self, client: AsyncClient, auth_headers: dict):
        """聊天层级说明信封验证"""
        resp = await client.get("/api/v1/chat/tiers", headers=auth_headers)
        assert resp.status_code == 200
        assert_envelope_success(resp.json(), resp.headers)

    @pytest.mark.asyncio
    async def test_envelope_molecules_models(
        self, client: AsyncClient, auth_headers: dict
    ):
        """分子模型列表信封验证"""
        resp = await client.get("/api/v1/molecules/models", headers=auth_headers)
        assert resp.status_code == 200
        assert_envelope_success(resp.json(), resp.headers)

    @pytest.mark.asyncio
    async def test_envelope_chat_cost_summary(
        self, client: AsyncClient, auth_headers: dict
    ):
        """聊天成本汇总信封验证"""
        resp = await client.get("/api/v1/chat/cost-summary", headers=auth_headers)
        assert resp.status_code == 200
        assert_envelope_success(resp.json(), resp.headers)

    @pytest.mark.asyncio
    async def test_envelope_error_has_request_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        """错误信封的 X-Request-ID 响应头应存在且非空"""
        resp = await client.get(
            f"/api/v1/projects/{uuid_mod.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        lower_headers = {k.lower(): v for k, v in resp.headers.items()}
        request_id = lower_headers.get("x-request-id", "")
        assert request_id, f"X-Request-ID empty or missing: {dict(resp.headers)}"

    @pytest.mark.asyncio
    async def test_envelope_duration_ms_is_integer(
        self, client: AsyncClient, auth_headers: dict
    ):
        """信封 meta.duration_ms 应为整数"""
        resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        duration_ms = body["meta"]["duration_ms"]
        assert isinstance(duration_ms, int), f"duration_ms not int: {type(duration_ms)}"
        assert duration_ms >= 0

    @pytest.mark.asyncio
    async def test_custom_request_id_echoed(
        self, client: AsyncClient, auth_headers: dict
    ):
        """自定义 X-Request-ID 请求头应被回显在响应头中"""
        custom_rid = "test-request-id-12345"
        resp = await client.get(
            "/api/v1/dashboard/overview",
            headers={**auth_headers, "X-Request-ID": custom_rid},
        )
        assert resp.status_code == 200
        lower_headers = {k.lower(): v for k, v in resp.headers.items()}
        assert lower_headers.get("x-request-id") == custom_rid, \
            f"X-Request-ID not echoed: {dict(resp.headers)}"

    @pytest.mark.asyncio
    async def test_response_time_header_present_on_all_statuses(
        self, client: AsyncClient, auth_headers: dict
    ):
        """X-Response-Time-ms 应在所有状态码响应中存在（200/400/401/404）"""
        # 200
        resp_ok = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert "x-response-time-ms" in {k.lower() for k in resp_ok.headers}
        # 401
        resp_401 = await client.get("/api/v1/dashboard/overview")
        assert "x-response-time-ms" in {k.lower() for k in resp_401.headers}
        # 404
        resp_404 = await client.get(
            f"/api/v1/projects/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert "x-response-time-ms" in {k.lower() for k in resp_404.headers}
        # 400
        resp_400 = await client.post(
            "/api/v1/projects", json={}, headers=auth_headers
        )
        assert "x-response-time-ms" in {k.lower() for k in resp_400.headers}
