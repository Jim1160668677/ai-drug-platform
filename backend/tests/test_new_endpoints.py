"""新端点综合测试 — privacy / efficacy / federated / feedback / system / ws

覆盖 P1.3 新增的 6 个端点模块，使用 httpx.AsyncClient + ASGITransport 直接对
FastAPI app 进行异步 HTTP 测试；WebSocket 端点使用 starlette.testclient.TestClient。

测试维度：
- 授权（带 JWT）与未授权（期望 401 UNAUTHORIZED）场景
- 成功路径（200 + ApiResponse 信封 success=true）
- 错误路径（404 NOT_FOUND / 400 VALIDATION_ERROR / 502 UPSTREAM_ERROR）
- 统一响应信封 ApiResponse{success, data, meta:{request_id, duration_ms}}
- 统一错误信封 ErrorResponse{success:false, error:{code, message, details}, meta}

技术要点：
- JWT token 通过 app.core.security.create_access_token 直接生成
  （subject="test-user-id", role=UserRole.RESEARCHER）
- get_current_user 依赖被覆盖为 mock 实现：仍校验 JWT 签名（缺/非法 token → 401），
  但跳过 DB 查找与 bcrypt（避免 passlib/bcrypt 版本兼容问题），返回 SimpleNamespace
- get_db 依赖被覆盖为内存 SQLite 会话（供 feedback / efficacy 等直接查 DB 的端点使用）
- privacy / federated / ws 模块级单例在每个测试前重置以保证隔离
"""
import os
import sys
import uuid
from types import SimpleNamespace
from typing import AsyncGenerator

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
from app.core.security import UserRole, create_access_token, decode_token  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401 — register all models on metadata
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)


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
async def auth_token() -> str:
    """JWT token for API auth (signature valid; get_current_user is mocked)."""
    return create_access_token(
        subject="test-user-id", role=UserRole.RESEARCHER
    )


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with get_db + get_current_user overridden.

    - get_current_user: mock that still validates JWT signature (so missing /
      invalid tokens → 401) but skips DB lookup + bcrypt. Returns a
      SimpleNamespace stand-in for the User model.
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
        return SimpleNamespace(
            id=user_id,
            email="test@newendpoints.com",
            name="Test User",
            role=role,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ============================================================
# 1. Privacy endpoints  (/api/v1/privacy/*)
# ============================================================

class TestPrivacyEndpoints:
    """隐私计算端点 — 隐私域 / 数据集 / 计算 / 脱敏 / 差分隐私 / 预算"""

    @pytest.mark.asyncio
    async def test_create_domain_unauthorized(self, client: AsyncClient):
        """未带 token 调用 POST /privacy/domains 应返回 401"""
        resp = await client.post("/api/v1/privacy/domains", json={"name": "D"})
        assert resp.status_code == 401
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_create_domain_success(self, client: AsyncClient, auth_headers):
        """带 token 创建隐私域应返回信封成功响应，data 包含 domain_id"""
        resp = await client.post(
            "/api/v1/privacy/domains",
            json={"name": "TestDomain", "data_schema": {"patient_id": "string"}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["name"] == "TestDomain"
        assert "domain_id" in body["data"]

    @pytest.mark.asyncio
    async def test_create_domain_missing_field(self, client: AsyncClient, auth_headers):
        """缺 name 字段应触发 Pydantic 校验错误 400"""
        resp = await client.post(
            "/api/v1/privacy/domains", json={}, headers=auth_headers
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_register_dataset_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/privacy/datasets",
            json={"domain_id": "d1", "dataset_id": "ds1", "columns": ["a"]},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_register_dataset_nonexistent_domain(self, client: AsyncClient, auth_headers):
        """注册到不存在的域应返回 404 NotFoundError"""
        resp = await client.post(
            "/api/v1/privacy/datasets",
            json={
                "domain_id": "nonexistent-domain-id",
                "dataset_id": "ds-1",
                "columns": ["col1", "col2"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_register_dataset_success(self, client: AsyncClient, auth_headers):
        """先创建域再注册数据集应成功，data.dataset_id 与入参一致"""
        dom = await client.post(
            "/api/v1/privacy/domains",
            json={"name": "DomainForDS"},
            headers=auth_headers,
        )
        domain_id = dom.json()["data"]["domain_id"]
        resp = await client.post(
            "/api/v1/privacy/datasets",
            json={
                "domain_id": domain_id,
                "dataset_id": "ds-test-001",
                "columns": ["patient_id", "age", "diagnosis"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["dataset_id"] == "ds-test-001"

    @pytest.mark.asyncio
    async def test_submit_compute_and_get_result(self, client: AsyncClient, auth_headers):
        """提交计算请求后用 request_id 取结果，应返回同一 request_id"""
        dom = await client.post(
            "/api/v1/privacy/domains",
            json={"name": "ComputeDom"},
            headers=auth_headers,
        )
        domain_id = dom.json()["data"]["domain_id"]
        await client.post(
            "/api/v1/privacy/datasets",
            json={"domain_id": domain_id, "dataset_id": "ds-c", "columns": ["v"]},
            headers=auth_headers,
        )
        resp = await client.post(
            "/api/v1/privacy/compute",
            json={
                "domain_id": domain_id,
                "dataset_id": "ds-c",
                "code": "result = sum(data['v'])",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        request_id = resp.json()["data"]["request_id"]

        r2 = await client.get(
            f"/api/v1/privacy/results/{request_id}", headers=auth_headers
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["request_id"] == request_id

    @pytest.mark.asyncio
    async def test_get_result_not_found(self, client: AsyncClient, auth_headers):
        """不存在的 request_id 应返回 404"""
        resp = await client.get(
            "/api/v1/privacy/results/nonexistent-req-id", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_result_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/privacy/results/any-id")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_mask_data_success(self, client: AsyncClient, auth_headers):
        """数据脱敏应返回与输入等长的脱敏记录列表"""
        records = [
            {"patient_name": "张三", "ssn": "123-45-6789", "diagnosis": "NSCLC"},
            {"patient_name": "李四", "ssn": "987-65-4321", "diagnosis": "Breast"},
        ]
        resp = await client.post(
            "/api/v1/privacy/mask-data",
            json={"records": records},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["count"] == 2
        assert len(body["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_mask_data_empty_records(self, client: AsyncClient, auth_headers):
        """空记录列表应返回 count=0"""
        resp = await client.post(
            "/api/v1/privacy/mask-data",
            json={"records": []},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_laplace_mechanism_success(self, client: AsyncClient, auth_headers):
        """Laplace 机制应在原始值附近返回带噪结果并扣除预算"""
        resp = await client.post(
            "/api/v1/privacy/differential/laplace",
            json={"value": 100.0, "sensitivity": 1.0, "epsilon": 0.5},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["method"] == "laplace"
        assert body["data"]["original"] == 100.0
        assert isinstance(body["data"]["noisy"], (int, float))
        assert body["data"]["epsilon_used"] == 0.5
        assert body["data"]["remaining_epsilon"] >= 0

    @pytest.mark.asyncio
    async def test_laplace_invalid_epsilon_zero(self, client: AsyncClient, auth_headers):
        """epsilon 必须 > 0：传 0 应触发 Pydantic 校验错误 400"""
        resp = await client.post(
            "/api/v1/privacy/differential/laplace",
            json={"value": 100.0, "sensitivity": 1.0, "epsilon": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_gaussian_mechanism_success(self, client: AsyncClient, auth_headers):
        """Gaussian 机制应返回带噪结果并扣除预算"""
        resp = await client.post(
            "/api/v1/privacy/differential/gaussian",
            json={"value": 50.0, "sensitivity": 1.0, "epsilon": 1.0, "delta": 1e-5},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["method"] == "gaussian"
        assert body["data"]["delta"] == 1e-5
        assert isinstance(body["data"]["noisy"], (int, float))

    @pytest.mark.asyncio
    async def test_gaussian_invalid_delta_out_of_range(self, client: AsyncClient, auth_headers):
        """delta 必须 ∈ (0,1)：传 1.5 应触发校验错误 400"""
        resp = await client.post(
            "/api/v1/privacy/differential/gaussian",
            json={"value": 50.0, "sensitivity": 1.0, "epsilon": 1.0, "delta": 1.5},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_budget(self, client: AsyncClient, auth_headers):
        """GET /privacy/budget 应返回预算状态字段"""
        resp = await client.get("/api/v1/privacy/budget", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "total_epsilon" in body["data"]
        assert "remaining_epsilon" in body["data"]
        assert "is_exhausted" in body["data"]

    @pytest.mark.asyncio
    async def test_get_budget_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/privacy/budget")
        assert resp.status_code == 401


# ============================================================
# 2. Efficacy endpoints  (/api/v1/efficacy/*)
# ============================================================

class TestEfficacyEndpoints:
    """疗效监测端点 — 全局汇总 / RECIST 1.1 分类"""

    @pytest.mark.asyncio
    async def test_global_summary_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/efficacy/global-summary")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_global_summary_success(self, client: AsyncClient, auth_headers):
        """全局汇总（空库）应返回 orr=0 / dcr=0 与 ae_distribution"""
        resp = await client.get("/api/v1/efficacy/global-summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "orr" in body["data"]
        assert "dcr" in body["data"]
        assert "ae_distribution" in body["data"]
        assert body["data"]["total_treatments"] == 0

    @pytest.mark.asyncio
    async def test_global_summary_with_project_filter(self, client: AsyncClient, auth_headers):
        """带 project_id 查询参数应正常返回（不存在的项目 → 0 治疗）"""
        resp = await client.get(
            "/api/v1/efficacy/global-summary",
            params={"project_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_treatments"] == 0

    @pytest.mark.asyncio
    async def test_recist_classify_pr(self, client: AsyncClient, auth_headers):
        """病灶缩小 >= 30% 应分类为 PR（部分缓解）"""
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={"lesions": [{"baseline_mm": 100, "current_mm": 60}]},  # -40%
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["classification"] == "PR"
        assert body["data"]["lesions_count"] == 1

    @pytest.mark.asyncio
    async def test_recist_classify_pd(self, client: AsyncClient, auth_headers):
        """病灶增大 >= 20% 应分类为 PD（进展）"""
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={"lesions": [{"baseline_mm": 100, "current_mm": 130}]},  # +30%
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["classification"] == "PD"

    @pytest.mark.asyncio
    async def test_recist_classify_cr(self, client: AsyncClient, auth_headers):
        """所有病灶消失（current_sum=0）应分类为 CR（完全缓解）"""
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={"lesions": [{"baseline_mm": 50, "current_mm": 0}]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["classification"] == "CR"

    @pytest.mark.asyncio
    async def test_recist_classify_empty_lesions(self, client: AsyncClient, auth_headers):
        """空病灶列表应返回 SD（service 默认值）"""
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={"lesions": []},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["classification"] == "SD"

    @pytest.mark.asyncio
    async def test_recist_classify_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={"lesions": [{"baseline_mm": 10, "current_mm": 5}]},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_recist_classify_missing_field(self, client: AsyncClient, auth_headers):
        """缺 lesions 字段应触发 Pydantic 校验错误 400"""
        resp = await client.post(
            "/api/v1/efficacy/recist-classify",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ============================================================
# 3. Federated endpoints  (/api/v1/federated/*)
# ============================================================

class TestFederatedEndpoints:
    """联邦学习端点 — 任务 CRUD / 客户端注册"""

    @pytest.mark.asyncio
    async def test_list_jobs_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/federated/jobs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client: AsyncClient, auth_headers):
        """空库查询应返回 count=0"""
        resp = await client.get("/api/v1/federated/jobs", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["count"] == 0
        assert body["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_create_job_success(self, client: AsyncClient, auth_headers):
        """创建 FL 任务应返回 job_id 与 pending 状态"""
        resp = await client.post(
            "/api/v1/federated/jobs",
            json={"project_id": "proj-001", "num_rounds": 5, "min_clients": 2},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "job_id" in body["data"]
        assert body["data"]["status"] == "pending"
        assert body["data"]["num_rounds"] == 5

    @pytest.mark.asyncio
    async def test_create_job_invalid_num_rounds(self, client: AsyncClient, auth_headers):
        """num_rounds 必须 >= 1：传 0 应触发校验错误 400"""
        resp = await client.post(
            "/api/v1/federated/jobs",
            json={"project_id": "proj-bad", "num_rounds": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_jobs_after_create(self, client: AsyncClient, auth_headers):
        """创建后列表应包含该任务"""
        await client.post(
            "/api/v1/federated/jobs",
            json={"project_id": "proj-list"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/federated/jobs", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["count"] >= 1
        assert any(j.get("project_id") == "proj-list" for j in body["data"]["items"])

    @pytest.mark.asyncio
    async def test_list_jobs_filter_by_project(self, client: AsyncClient, auth_headers):
        """按 project_id 过滤应只返回对应任务"""
        await client.post(
            "/api/v1/federated/jobs",
            json={"project_id": "proj-filter"},
            headers=auth_headers,
        )
        resp = await client.get(
            "/api/v1/federated/jobs",
            params={"project_id": "proj-filter"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["project_id"] == "proj-filter"

    @pytest.mark.asyncio
    async def test_stop_job_not_found(self, client: AsyncClient, auth_headers):
        """停止不存在的任务应返回 404"""
        resp = await client.post(
            "/api/v1/federated/jobs/nonexistent-job/stop",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_stop_job_success(self, client: AsyncClient, auth_headers):
        """停止已存在任务应返回 stopped 状态"""
        create = await client.post(
            "/api/v1/federated/jobs",
            json={"project_id": "proj-stop"},
            headers=auth_headers,
        )
        job_id = create.json()["data"]["job_id"]
        resp = await client.post(
            f"/api/v1/federated/jobs/{job_id}/stop",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_register_client_success(self, client: AsyncClient, auth_headers):
        """注册客户端应返回 client_id 与 registered 状态"""
        resp = await client.post(
            "/api/v1/federated/clients/register",
            json={
                "client_id": "client-001",
                "endpoint": "https://client-001.example.com",
                "capabilities": {"gpu": True, "max_rounds": 10},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["client_id"] == "client-001"
        assert body["data"]["status"] == "registered"

    @pytest.mark.asyncio
    async def test_list_clients_after_register(self, client: AsyncClient, auth_headers):
        """注册后列表应包含该客户端"""
        await client.post(
            "/api/v1/federated/clients/register",
            json={"client_id": "client-list", "endpoint": "https://c.example.com"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/federated/clients", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["count"] >= 1
        assert any(
            c.get("client_id") == "client-list" for c in body["data"]["items"]
        )

    @pytest.mark.asyncio
    async def test_register_client_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/federated/clients/register",
            json={"client_id": "x", "endpoint": "https://x.example.com"},
        )
        assert resp.status_code == 401


# ============================================================
# 4. Feedback endpoints  (/api/v1/feedback/*)
# ============================================================

class TestFeedbackEndpoints:
    """反馈闭环端点 — 实验 / 偏差检测 / 状态机 / LIMS 导入"""

    @pytest.mark.asyncio
    async def test_summary_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/feedback/summary")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_summary_empty(self, client: AsyncClient, auth_headers):
        """空库 feedback_summary 应返回 0 实验、0 反馈率"""
        resp = await client.get("/api/v1/feedback/summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["total_experiments"] == 0
        assert body["data"]["feedback_applied"] == 0
        assert body["data"]["feedback_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_list_experiments_empty(self, client: AsyncClient, auth_headers):
        resp = await client.get("/api/v1/feedback/experiments", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["count"] == 0
        assert body["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_list_experiments_with_filters(self, client: AsyncClient, auth_headers):
        """带 target_symbol + limit 查询参数应正常返回"""
        resp = await client.get(
            "/api/v1/feedback/experiments",
            params={"target_symbol": "EGFR", "limit": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_recalibrate_success(self, client: AsyncClient, auth_headers):
        """重新校准应返回信封成功响应（空库 → no_data）"""
        resp = await client.post(
            "/api/v1/feedback/recalibrate",
            json={"target_symbol": "EGFR"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["target_symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_recalibrate_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/feedback/recalibrate",
            json={"target_symbol": "EGFR"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_recalibrate_missing_field(self, client: AsyncClient, auth_headers):
        """缺 target_symbol 字段应触发 400"""
        resp = await client.post(
            "/api/v1/feedback/recalibrate",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_detect_bias_success(self, client: AsyncClient, auth_headers):
        """偏差检测应返回信封成功响应（空库 → insufficient_samples）"""
        resp = await client.get(
            "/api/v1/feedback/bias-detection/EGFR",
            params={"min_samples": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["target_symbol"] == "EGFR"

    @pytest.mark.asyncio
    async def test_detect_bias_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/feedback/bias-detection/EGFR")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_tracker_get_not_found(self, client: AsyncClient, auth_headers):
        """查询不存在实验的状态机应返回 404"""
        resp = await client.get(
            "/api/v1/feedback/experiments/tracker",
            params={"experiment_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_tracker_invalid_uuid(self, client: AsyncClient, auth_headers):
        """非法 UUID 应触发 400 校验错误"""
        resp = await client.get(
            "/api/v1/feedback/experiments/tracker",
            params={"experiment_id": "not-a-uuid"},
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ============================================================
# 5. System endpoints  (/api/v1/health, /api/v1/metrics)
# ============================================================

class TestSystemEndpoints:
    """系统端点 — 信封健康检查 + Prometheus 指标（均无需认证）"""

    @pytest.mark.asyncio
    async def test_health_envelope_no_auth_required(self, client: AsyncClient):
        """GET /api/v1/health 不需要认证，应返回信封成功响应"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "healthy"
        assert body["data"]["app"] == "precision-drug-design"
        assert "uptime_sec" in body["data"]
        assert "mock_mode" in body["data"]

    @pytest.mark.asyncio
    async def test_metrics_no_auth_required(self, client: AsyncClient):
        """GET /api/v1/metrics 返回 Prometheus 文本格式"""
        resp = await client.get("/api/v1/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        text = resp.text
        assert "precision_drug_uptime_seconds" in text
        assert "precision_drug_http_requests_total" in text

    @pytest.mark.asyncio
    async def test_root_health_no_envelope(self, client: AsyncClient):
        """GET /health (root) 应返回无信封的简化健康检查（K8s 探针用）"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        # root /health 不返回 success/data 信封
        assert "success" not in body


# ============================================================
# 6. WebSocket endpoint  (WS /api/v1/tasks/{task_id})
# ============================================================

class TestWebSocketEndpoints:
    """WebSocket 端点测试 — 使用 starlette.testclient.TestClient（同步）。

    httpx 原生不支持 WebSocket，FastAPI 官方推荐用 TestClient 测试 WS 端点。
    WS 握手阶段从 query 参数 ?token=xxx 校验 JWT（仅验签名 + sub 存在，
    不查 DB），因此可用 create_access_token 直接生成 token。
    """

    @pytest.fixture
    def ws_client(self):
        from starlette.testclient import TestClient
        from app.api.v1.endpoints import ws as ws_mod
        # Reset progress manager singleton before each WS test
        ws_mod._progress_manager = ws_mod.TaskProgressManager()
        with TestClient(app) as c:
            yield c

    @pytest.fixture
    def ws_token(self) -> str:
        """JWT token for WS handshake (signature valid; user need not exist in DB)."""
        return create_access_token(
            subject="ws-test-user", role=UserRole.RESEARCHER
        )

    def test_ws_reject_missing_token(self, ws_client):
        """WS 握手缺 token 应被拒绝（close code 4401）"""
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_client.websocket_connect("/api/v1/tasks/task-no-token"):
                pass
        assert exc_info.value.code == 4401

    def test_ws_reject_invalid_token(self, ws_client):
        """WS 握手 token 非法应被拒绝（close code 4401）"""
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_client.websocket_connect(
                "/api/v1/tasks/task-bad-token?token=not-a-jwt"
            ):
                pass
        assert exc_info.value.code == 4401

    def test_ws_accept_valid_token_pushes_pending(self, ws_client, ws_token):
        """WS 握手 token 合法时应接受连接并推送首条进度（pending 占位）"""
        with ws_client.websocket_connect(
            f"/api/v1/tasks/task-valid?token={ws_token}"
        ) as ws:
            msg = ws.receive_json()
            assert msg["task_id"] == "task-valid"
            assert msg["status"] == "pending"
            assert "percent" in msg
            assert "updated_at" in msg

    def test_ws_pushes_existing_progress(self, ws_client, ws_token):
        """已注册的任务进度应被立即推送（非 pending 占位）"""
        from app.api.v1.endpoints.ws import get_progress_manager
        mgr = get_progress_manager()
        mgr.update_progress("task-existing", 42.0, "处理中", "running")
        with ws_client.websocket_connect(
            f"/api/v1/tasks/task-existing?token={ws_token}"
        ) as ws:
            msg = ws.receive_json()
            assert msg["task_id"] == "task-existing"
            assert msg["percent"] == 42.0
            assert msg["status"] == "running"
            assert msg["message"] == "处理中"

    @pytest.mark.asyncio
    async def test_get_task_status_not_found(self, client: AsyncClient, auth_headers):
        """HTTP 查询不存在的 task_id 应返回 404"""
        resp = await client.get(
            "/api/v1/tasks/nonexistent-task/status",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_task_status_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/v1/tasks/any-task/status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_task_status_after_update(self, client: AsyncClient, auth_headers):
        """通过 manager 更新进度后，HTTP 查询应返回该进度"""
        from app.api.v1.endpoints.ws import get_progress_manager
        mgr = get_progress_manager()
        mgr.update_progress("task-http", 75.0, "即将完成", "running")
        resp = await client.get(
            "/api/v1/tasks/task-http/status",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["percent"] == 75.0
        assert body["data"]["status"] == "running"
        assert body["data"]["message"] == "即将完成"
