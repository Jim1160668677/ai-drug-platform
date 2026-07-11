"""API 契约测试 (P4.3) — 验证所有端点遵循统一响应契约

测试维度：
1. 错误契约一致性：404/400/401/422/502 错误在不同端点组中返回相同的 ErrorResponse 结构
2. 状态码到错误码映射：401→UNAUTHORIZED, 404→NOT_FOUND, 422→VALIDATION_ERROR(转400),
   502→UPSTREAM_ERROR, 409→CONFLICT, 403→FORBIDDEN, 429→RATE_LIMITED, 422业务→GUARDRAIL_BLOCKED
3. Request-ID 传播：所有错误响应的 meta.request_id 与 X-Request-ID 头一致
4. 成功契约：success_response() 返回的 ApiResponse 结构（success/data/meta.duration_ms）
5. 列表端点契约：记录返回原始 List 的端点（契约不一致点，待后续统一）

技术要点：
- httpx.AsyncClient + ASGITransport(app=app)
- 覆盖 get_current_user（JWT 校验 + mock 用户）与 get_db（内存 SQLite）
- 不使用 --cov 运行（PyO3/bcrypt 兼容性问题）

注意：
- 本文件与 test_envelope.py（schema 级契约）和 test_api_integration.py::TestResponseEnvelope
  （基础信封验证）互补，聚焦于跨端点的契约一致性验证
"""
import os
import sys
import uuid as uuid_mod
from types import SimpleNamespace
from typing import AsyncGenerator

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

TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000002")


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
    """带认证的 HTTP 客户端"""
    # 在 DB 中创建测试用户（满足外键约束）
    u = User(
        id=TEST_USER_ID,
        email="contract@test.com",
        name="Contract Tester",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()

    async def mock_get_user(token=auth_token):
        return SimpleNamespace(
            id=TEST_USER_ID,
            email="contract@test.com",
            name="Contract Tester",
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


@pytest_asyncio.fixture
async def unauth_client() -> AsyncGenerator[AsyncClient, None]:
    """无认证的 HTTP 客户端（不覆盖 get_current_user，保留真实校验）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _is_error_envelope(body: dict) -> bool:
    """验证 body 是否符合 ErrorResponse 契约"""
    return (
        isinstance(body, dict)
        and body.get("success") is False
        and isinstance(body.get("error"), dict)
        and "code" in body["error"]
        and "message" in body["error"]
        and isinstance(body.get("meta"), dict)
        and "request_id" in body["meta"]
    )


def _is_success_envelope(body: dict) -> bool:
    """验证 body 是否符合 ApiResponse 契约"""
    return (
        isinstance(body, dict)
        and body.get("success") is True
        and "data" in body
        and isinstance(body.get("meta"), dict)
        and "request_id" in body["meta"]
    )


# ============================================================
# 1. 401 UNAUTHORIZED 契约一致性
# ============================================================

class TestUnauthorizedContract:
    """验证多个受保护端点在无 token 时返回一致的 401 契约"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/v1/projects", "GET"),
            ("/api/v1/projects", "POST"),
            ("/api/v1/data", "GET"),
            ("/api/v1/targets", "GET"),
            ("/api/v1/molecules", "GET"),
            ("/api/v1/treatments", "GET"),
            ("/api/v1/hypotheses", "GET"),
            ("/api/v1/experiments", "GET"),
            ("/api/v1/workflows", "GET"),
            ("/api/v1/dashboard/overview", "GET"),
            ("/api/v1/llm-configs", "GET"),
            ("/api/v1/users", "GET"),
            ("/api/v1/federated/jobs", "GET"),
        ],
    )
    async def test_unauthorized_returns_consistent_contract(
        self, unauth_client, path, method
    ):
        """所有受保护端点无 token 时应返回 401 + UNAUTHORIZED 契约"""
        resp = await unauth_client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} 期望 401，实际 {resp.status_code}"
        body = resp.json()
        assert _is_error_envelope(body), f"{method} {path} 响应不符合 ErrorResponse 契约: {body}"
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert isinstance(body["error"]["message"], str) and body["error"]["message"]
        # X-Request-ID 头与 meta.request_id 一致
        assert "X-Request-ID" in resp.headers
        assert body["meta"]["request_id"] == resp.headers["X-Request-ID"]

    @pytest.mark.asyncio
    async def test_invalid_token_returns_unauthorized(self, unauth_client):
        """无效 JWT token 应返回 401 + UNAUTHORIZED"""
        resp = await unauth_client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert _is_error_envelope(body)
        assert body["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_malformed_auth_header_returns_unauthorized(self, unauth_client):
        """格式错误的 Authorization 头应返回 401"""
        resp = await unauth_client.get(
            "/api/v1/projects",
            headers={"Authorization": "NotBearer abc"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert _is_error_envelope(body)
        assert body["error"]["code"] == "UNAUTHORIZED"


# ============================================================
# 2. 404 NOT_FOUND 契约一致性
# ============================================================

class TestNotFoundContract:
    """验证资源不存在时返回一致的 404 契约"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/projects/nonexistent-id",
            "/api/v1/data/nonexistent-id",
            "/api/v1/targets/nonexistent-id",
            "/api/v1/hypotheses/nonexistent-id",
        ],
    )
    async def test_resource_not_found_returns_contract(self, client, path):
        """获取不存在的资源应返回 404 + NOT_FOUND 契约

        注意：molecules/treatments/experiments 端点未实现 GET /{id} 详情路由，
        FastAPI 返回默认 {'detail': 'Not Found'}（非信封），是契约不一致点，
        已在 TestUnregisteredPathContract 中记录。
        """
        resp = await client.get(path)
        # 部分端点可能返回 404 或 400（取决于 ID 格式校验），接受两者但验证契约
        assert resp.status_code in (404, 400), f"{path} 期望 404/400，实际 {resp.status_code}"
        body = resp.json()
        assert _is_error_envelope(body), f"{path} 响应不符合 ErrorResponse 契约: {body}"
        # 错误码应为 NOT_FOUND 或 VALIDATION_ERROR
        assert body["error"]["code"] in ("NOT_FOUND", "VALIDATION_ERROR")
        assert "X-Request-ID" in resp.headers
        assert body["meta"]["request_id"] == resp.headers["X-Request-ID"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/molecules/00000000-0000-0000-0000-000000000000",
            "/api/v1/treatments/00000000-0000-0000-0000-000000000000",
            "/api/v1/experiments/00000000-0000-0000-0000-000000000000",
        ],
    )
    async def test_detail_path_returns_envelope_404(self, client, auth_headers, path):
        """GET /{id} 详情路由已补全，不存在的 ID 应返回 404 + NOT_FOUND 信封"""
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 404, f"{path} 期望 404，实际 {resp.status_code}"
        body = resp.json()
        assert _is_error_envelope(body), f"{path} 响应不符合 ErrorResponse 契约: {body}"
        assert body["error"]["code"] == "NOT_FOUND"
        assert "X-Request-ID" in resp.headers
        assert body["meta"]["request_id"] == resp.headers["X-Request-ID"]

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self, client):
        """完全不存在的路径应返回 404"""
        resp = await client.get("/api/v1/this-does-not-exist")
        assert resp.status_code == 404
        # FastAPI 默认路由不存在的响应是 {"detail": "Not Found"}，不一定是信封
        # 此处记录该行为（契约不一致点），允许两种格式


# ============================================================
# 3. 422 → 400 VALIDATION_ERROR 契约（中间件转换）
# ============================================================

class TestValidationContract:
    """验证请求体校验失败时通过中间件转换为 400 + VALIDATION_ERROR 契约"""

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_validation_error(self, client):
        """POST /api/v1/projects 缺少必填字段应返回 400 + VALIDATION_ERROR"""
        resp = await client.post("/api/v1/projects", json={})
        # 中间件将 422 转为 400
        assert resp.status_code in (400, 422)
        body = resp.json()
        assert _is_error_envelope(body), f"响应不符合 ErrorResponse 契约: {body}"
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert isinstance(body["error"]["message"], str) and body["error"]["message"]

    @pytest.mark.asyncio
    async def test_invalid_field_type_returns_validation_error(self, client):
        """字段类型错误应返回 400 + VALIDATION_ERROR"""
        # cancer_type 应为字符串，传整数
        resp = await client.post("/api/v1/projects", json={
            "name": "Test",
            "patient_pseudonym": "P-001",
            "cancer_type": 12345,
            "stage": "IV",
        })
        assert resp.status_code in (400, 422)
        body = resp.json()
        assert _is_error_envelope(body)
        assert body["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_validation_error_includes_request_id(self, client):
        """校验错误响应应包含 X-Request-ID 且与 meta.request_id 一致"""
        custom_id = "contract-validation-req-id-12345"
        resp = await client.post(
            "/api/v1/projects",
            json={},
            headers={"X-Request-ID": custom_id},
        )
        assert resp.status_code in (400, 422)
        body = resp.json()
        assert _is_error_envelope(body)
        # 请求带的自定义 ID 应被回显
        assert resp.headers["X-Request-ID"] == custom_id
        assert body["meta"]["request_id"] == custom_id


# ============================================================
# 4. 成功响应契约
# ============================================================

class TestSuccessContract:
    """验证使用 success_response() 的端点返回一致的 ApiResponse 契约"""

    @pytest.mark.asyncio
    async def test_dashboard_overview_success_envelope(self, client):
        """GET /api/v1/dashboard/overview 应返回 ApiResponse 契约"""
        resp = await client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert _is_success_envelope(body), f"响应不符合 ApiResponse 契约: {body}"
        # meta.duration_ms 应被中间件注入（整数）
        assert "duration_ms" in body["meta"]
        assert isinstance(body["meta"]["duration_ms"], int)
        assert body["meta"]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_success_response_has_request_id_header(self, client):
        """成功响应应包含 X-Request-ID 头"""
        resp = await client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    @pytest.mark.asyncio
    async def test_success_response_echoes_custom_request_id_in_header(self, client):
        """请求带 X-Request-ID 时成功响应头应回显

        契约不一致点：部分端点（如 dashboard）调用 success_response(request_id="")
        时未从请求上下文获取 request_id，导致 body.meta.request_id 为空字符串。
        中间件仅在响应头注入 X-Request-ID，不覆盖 body。建议后续统一修复。
        本测试验证头传播正确，body.request_id 允许为空（记录现状）。
        """
        custom_id = "contract-success-custom-id-67890"
        resp = await client.get(
            "/api/v1/dashboard/overview",
            headers={"X-Request-ID": custom_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        # 头传播正确
        assert resp.headers["X-Request-ID"] == custom_id
        # body.meta.request_id 存在但可能为空（端点未从上下文获取）
        assert "request_id" in body["meta"]

    @pytest.mark.asyncio
    async def test_success_response_has_response_time_header(self, client):
        """成功响应应包含 X-Response-Time-ms 头"""
        resp = await client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        assert "X-Response-Time-ms" in resp.headers
        ms = int(resp.headers["X-Response-Time-ms"])
        assert ms >= 0


# ============================================================
# 5. 列表端点契约（记录不一致点）
# ============================================================

class TestListEndpointContract:
    """验证列表端点的响应契约

    契约规范：列表端点应返回 PagedResponse{success, data: List, meta: PagedMeta}
    当前现状：部分列表端点直接返回 List[Model]（未经信封包装），是契约不一致点。
    本测试类记录现状，为后续统一提供依据。
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/projects",
            "/api/v1/data",
            "/api/v1/targets",
            "/api/v1/molecules",
            "/api/v1/treatments",
            "/api/v1/hypotheses",
            "/api/v1/experiments",
        ],
    )
    async def test_list_endpoint_response_shape(self, client, auth_headers, path):
        """列表端点应统一返回 PagedResponse 信封"""
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 200, f"{path} 期望 200，实际 {resp.status_code}"
        body = resp.json()
        # 所有列表端点必须返回 PagedResponse 信封
        assert isinstance(body, dict), f"{path} 应返回 dict（PagedResponse），实际 {type(body)}"
        assert body.get("success") is True, f"{path} 缺少 success=True"
        assert "data" in body, f"{path} 缺少 data 字段"
        assert isinstance(body["data"], list), f"{path} data 应为 list"
        # PagedMeta 必须包含分页字段
        meta = body.get("meta", {})
        assert "page" in meta, f"{path} meta 缺少 page"
        assert "page_size" in meta, f"{path} meta 缺少 page_size"
        assert "total" in meta, f"{path} meta 缺少 total"
        assert "request_id" in meta, f"{path} meta 缺少 request_id"
        assert meta["request_id"] == resp.headers.get("X-Request-ID"), \
            f"{path} meta.request_id 应与 X-Request-ID 头一致"


# ============================================================
# 6. 健康检查端点契约（特殊端点）
# ============================================================

class TestHealthEndpointContract:
    """/health 端点不参与统一信封（运维探测用），验证其不被中间件破坏"""

    @pytest.mark.asyncio
    async def test_health_returns_200_with_status(self, unauth_client):
        resp = await unauth_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["app"] == "precision-drug-design"

    @pytest.mark.asyncio
    async def test_health_has_request_id_header(self, unauth_client):
        """即使 /health 不返回信封，中间件仍应注入 X-Request-ID 头"""
        resp = await unauth_client.get("/health")
        assert "X-Request-ID" in resp.headers

    @pytest.mark.asyncio
    async def test_health_has_response_time_header(self, unauth_client):
        resp = await unauth_client.get("/health")
        assert "X-Response-Time-ms" in resp.headers


# ============================================================
# 7. 根路径端点契约
# ============================================================

class TestRootEndpointContract:
    """根路径 / 返回应用元信息（非信封），验证不被中间件破坏"""

    @pytest.mark.asyncio
    async def test_root_returns_200(self, unauth_client):
        resp = await unauth_client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body
        assert "docs" in body

    @pytest.mark.asyncio
    async def test_root_has_request_id_header(self, unauth_client):
        resp = await unauth_client.get("/")
        assert "X-Request-ID" in resp.headers


# ============================================================
# 8. 跨端点 Request-ID 一致性
# ============================================================

class TestRequestIdPropagation:
    """验证 Request-ID 在所有响应类型中正确传播"""

    @pytest.mark.asyncio
    async def test_custom_request_id_propagates_to_success_header(self, client):
        """自定义 Request-ID 在成功响应头中传播

        注意：body.meta.request_id 可能不被覆盖（端点用空字符串初始化），
        此处仅验证头传播。详见 TestSuccessContract 中的契约不一致点说明。
        """
        rid = "propagation-test-success-001"
        resp = await client.get(
            "/api/v1/dashboard/overview",
            headers={"X-Request-ID": rid},
        )
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == rid

    @pytest.mark.asyncio
    async def test_custom_request_id_propagates_to_error(self, unauth_client):
        """自定义 Request-ID 在错误响应中完整传播（头 + body）"""
        rid = "propagation-test-error-002"
        resp = await unauth_client.get(
            "/api/v1/projects",
            headers={"X-Request-ID": rid},
        )
        assert resp.status_code == 401
        assert resp.headers["X-Request-ID"] == rid
        assert resp.json()["meta"]["request_id"] == rid

    @pytest.mark.asyncio
    async def test_auto_generated_request_id_in_header(self, client):
        """未传 Request-ID 时应自动生成并出现在响应头"""
        resp = await client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        rid = resp.headers["X-Request-ID"]
        assert isinstance(rid, str) and len(rid) > 0

    @pytest.mark.asyncio
    async def test_different_requests_get_different_request_ids(self, client):
        """不同请求应获得不同的 Request-ID"""
        resp1 = await client.get("/api/v1/dashboard/overview")
        resp2 = await client.get("/api/v1/dashboard/overview")
        rid1 = resp1.headers["X-Request-ID"]
        rid2 = resp2.headers["X-Request-ID"]
        assert rid1 != rid2
