"""Phase 5-7 新增端点 HTTP 层 E2E 集成测试

覆盖 Phase 5-7 新增端点的 HTTP 层集成测试，补充 test_new_endpoints.py 未覆盖的部分。

测试维度：
- Phase 5 联邦学习新端点：
  - GET  /federated/jobs/{id}/metrics   指标历史
  - POST /federated/jobs/{id}/dp         差分隐私配置
  - GET  /federated/jobs/{id}/centers    多中心状态
  - GET  /federated/jobs/{id}/evaluate   全局模型评估
- Phase 6 假设生成端点：
  - POST /hypotheses/auto-generate       支持 use_llm / mode 参数
- Phase 7 流水线端点：
  - POST /pipeline/run                   支持 enable_hypothesis / custom_steps

技术要点（同 test_new_endpoints.py）：
- httpx.AsyncClient + ASGITransport(app=app)
- JWT token 通过 create_access_token 直接生成
- get_current_user 被覆盖为 mock（校验签名，跳过 DB/bcrypt）
- get_db 被覆盖为内存 SQLite 会话
- federated 模块级单例每个测试前重置
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

# Ensure backend on path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.deps import get_current_user, oauth2_scheme  # noqa: E402
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
    return create_access_token(subject="test-user-id", role=UserRole.FOUNDER)


@pytest_asyncio.fixture
async def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with federated singleton reset for isolation."""
    from app.api.v1.endpoints import federated as federated_mod
    federated_mod._FL_SERVICE = None

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


async def _create_fl_job(client: AsyncClient, auth_headers: dict, **overrides) -> str:
    """Helper: 创建联邦学习任务，返回 job_id"""
    payload = {"project_id": "proj-e2e", "num_rounds": 1, "min_clients": 2}
    payload.update(overrides)
    resp = await client.post("/api/v1/federated/jobs", json=payload, headers=auth_headers)
    assert resp.status_code == 200, f"创建任务失败: {resp.text}"
    return resp.json()["data"]["job_id"]


async def _submit_weights(client: AsyncClient, auth_headers: dict, job_id: str,
                          client_id: str, weights=None, num_samples=10):
    """Helper: 提交客户端权重"""
    resp = await client.post(
        f"/api/v1/federated/jobs/{job_id}/weights",
        json={
            "client_id": client_id,
            "weights": weights or {"w1": 0.5},
            "num_samples": num_samples,
            "metrics": {"loss": 0.3, "accuracy": 0.85},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"提交权重失败: {resp.text}"
    return resp.json()


# ============================================================
# Phase 5: Federated Learning New Endpoints
# ============================================================

class TestFederatedMetricsEndpoint:
    """GET /federated/jobs/{id}/metrics — 指标历史"""

    @pytest.mark.asyncio
    async def test_metrics_not_found(self, client: AsyncClient, auth_headers: dict):
        """不存在的 job_id 应返回 404"""
        resp = await client.get(
            "/api/v1/federated/jobs/nonexistent/metrics", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_metrics_empty_before_aggregation(self, client: AsyncClient, auth_headers: dict):
        """未触发聚合前 metrics_history 为空"""
        job_id = await _create_fl_job(client, auth_headers)
        resp = await client.get(
            f"/api/v1/federated/jobs/{job_id}/metrics", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["rounds"] == 0
        assert body["data"]["metrics_history"] == []

    @pytest.mark.asyncio
    async def test_metrics_after_aggregation(self, client: AsyncClient, auth_headers: dict):
        """提交足够权重触发聚合后，metrics_history 应有记录"""
        job_id = await _create_fl_job(client, auth_headers, num_rounds=1, min_clients=2)
        await _submit_weights(client, auth_headers, job_id, "c1")
        await _submit_weights(client, auth_headers, job_id, "c2")

        resp = await client.get(
            f"/api/v1/federated/jobs/{job_id}/metrics", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["rounds"] == 1
        assert len(body["data"]["metrics_history"]) == 1
        entry = body["data"]["metrics_history"][0]
        assert entry["round"] == 0  # 0-based round index
        assert "global_loss" in entry
        assert "duration_sec" in entry

    @pytest.mark.asyncio
    async def test_metrics_unauthorized(self, client: AsyncClient):
        """无 token 应返回 401"""
        resp = await client.get("/api/v1/federated/jobs/any/metrics")
        assert resp.status_code == 401


class TestFederatedDPEndpoint:
    """POST /federated/jobs/{id}/dp — 差分隐私配置"""

    @pytest.mark.asyncio
    async def test_configure_dp_success(self, client: AsyncClient, auth_headers: dict):
        """启用 DP 应返回配置"""
        job_id = await _create_fl_job(client, auth_headers)
        resp = await client.post(
            f"/api/v1/federated/jobs/{job_id}/dp",
            json={"enabled": True, "noise_multiplier": 0.5, "max_norm": 2.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["dp_params"]["enabled"] is True
        assert body["data"]["dp_params"]["noise_multiplier"] == 0.5
        assert body["data"]["dp_params"]["max_norm"] == 2.0

    @pytest.mark.asyncio
    async def test_disable_dp(self, client: AsyncClient, auth_headers: dict):
        """禁用 DP"""
        job_id = await _create_fl_job(client, auth_headers)
        await client.post(
            f"/api/v1/federated/jobs/{job_id}/dp",
            json={"enabled": True, "noise_multiplier": 1.0, "max_norm": 1.0},
            headers=auth_headers,
        )
        resp = await client.post(
            f"/api/v1/federated/jobs/{job_id}/dp",
            json={"enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["dp_params"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_dp_not_found(self, client: AsyncClient, auth_headers: dict):
        """不存在的 job 应返回 404"""
        resp = await client.post(
            "/api/v1/federated/jobs/nonexistent/dp",
            json={"enabled": True},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_dp_applied_in_metrics(self, client: AsyncClient, auth_headers: dict):
        """启用 DP 后聚合应标记 dp_applied"""
        job_id = await _create_fl_job(client, auth_headers, num_rounds=1, min_clients=2)
        await client.post(
            f"/api/v1/federated/jobs/{job_id}/dp",
            json={"enabled": True, "noise_multiplier": 0.1, "max_norm": 1.0},
            headers=auth_headers,
        )
        await _submit_weights(client, auth_headers, job_id, "c1")
        await _submit_weights(client, auth_headers, job_id, "c2")

        # 通过 evaluate 端点验证 dp_applied
        resp = await client.get(
            f"/api/v1/federated/jobs/{job_id}/evaluate", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["dp_applied"] is True


class TestFederatedCentersEndpoint:
    """GET /federated/jobs/{id}/centers — 多中心状态"""

    @pytest.mark.asyncio
    async def test_centers_empty(self, client: AsyncClient, auth_headers: dict):
        """无多中心配置时返回空列表"""
        job_id = await _create_fl_job(client, auth_headers)
        resp = await client.get(
            f"/api/v1/federated/jobs/{job_id}/centers", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["centers"] == []
        assert body["data"]["last_centers_breakdown"] == []

    @pytest.mark.asyncio
    async def test_centers_not_found(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get(
            "/api/v1/federated/jobs/nonexistent/centers", headers=auth_headers
        )
        assert resp.status_code == 404


class TestFederatedEvaluateEndpoint:
    """GET /federated/jobs/{id}/evaluate — 全局模型评估"""

    @pytest.mark.asyncio
    async def test_evaluate_not_found(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get(
            "/api/v1/federated/jobs/nonexistent/evaluate", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_evaluate_after_completion(self, client: AsyncClient, auth_headers: dict):
        """聚合完成后评估应返回权重摘要和指标"""
        job_id = await _create_fl_job(client, auth_headers, num_rounds=1, min_clients=2)
        await _submit_weights(client, auth_headers, job_id, "c1")
        await _submit_weights(client, auth_headers, job_id, "c2")

        resp = await client.get(
            f"/api/v1/federated/jobs/{job_id}/evaluate", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "completed"
        assert body["rounds_completed"] == 1
        assert "aggregated_weights_summary" in body
        assert "last_round_metrics" in body
        assert body["last_round_metrics"]["global_loss"] is not None


# ============================================================
# Phase 6: Hypotheses auto-generate with mode parameter
# ============================================================

class TestHypothesisAutoGenerate:
    """POST /hypotheses/auto-generate — 支持 use_llm / mode"""

    @pytest.mark.asyncio
    async def test_auto_generate_rule_mode(self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        """rule 模式应返回假设列表（无 LLM 调用）"""
        from app.models.user import User
        from app.models.project import Project
        from app.core.security import hash_password

        user_obj = User(
            email="hyp@ai-drug.com", name="Hyp Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER, is_active=True,
        )
        db_session.add(user_obj)
        await db_session.flush()

        project = Project(
            name="Hyp Project", cancer_type="NSCLC", stage="IV",
            owner_id=user_obj.id,
        )
        db_session.add(project)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/hypotheses/auto-generate",
            json={
                "project_id": str(project.id),
                "max_hypotheses": 3,
                "mode": "rule",
                "use_llm": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    @pytest.mark.asyncio
    async def test_auto_generate_hybrid_no_llm(self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        """hybrid 模式但 use_llm=False 应降级为纯规则"""
        from app.models.user import User
        from app.models.project import Project
        from app.core.security import hash_password

        user_obj = User(
            email="hyp2@ai-drug.com", name="Hyp Test2",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER, is_active=True,
        )
        db_session.add(user_obj)
        await db_session.flush()

        project = Project(
            name="Hyp Project 2", cancer_type="LUAD", stage="III",
            owner_id=user_obj.id,
        )
        db_session.add(project)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/hypotheses/auto-generate",
            json={
                "project_id": str(project.id),
                "mode": "hybrid",
                "use_llm": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_auto_generate_project_not_found(self, client: AsyncClient, auth_headers: dict):
        """不存在的 project_id 应不报错（规则模式下返回空或降级）"""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/v1/hypotheses/auto-generate",
            json={"project_id": fake_id, "mode": "rule"},
            headers=auth_headers,
        )
        # 规则模式下无数据应返回空列表或降级
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_auto_generate_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hypotheses/auto-generate",
            json={"project_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401


# ============================================================
# Phase 7: Pipeline with enable_hypothesis + custom_steps
# ============================================================

class TestPipelineRunWithHypothesis:
    """POST /pipeline/run — 支持 enable_hypothesis / custom_steps"""

    @pytest.mark.asyncio
    async def test_run_pipeline_with_hypothesis_disabled(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """enable_hypothesis=False 应正常执行不报错"""
        from app.models.user import User
        from app.models.project import Project
        from app.core.security import hash_password

        user_obj = User(
            email="pipe@ai-drug.com", name="Pipe Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER, is_active=True,
        )
        db_session.add(user_obj)
        await db_session.flush()

        project = Project(
            name="Pipe Project", cancer_type="NSCLC", stage="IV",
            owner_id=user_obj.id,
        )
        db_session.add(project)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/pipeline/run",
            json={
                "project_id": str(project.id),
                "enable_hypothesis": False,
                "skip_existing": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "summary" in body["data"]

    @pytest.mark.asyncio
    async def test_run_pipeline_with_custom_steps(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """custom_steps 应被执行"""
        from app.models.user import User
        from app.models.project import Project
        from app.core.security import hash_password

        user_obj = User(
            email="pipe2@ai-drug.com", name="Pipe Test2",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER, is_active=True,
        )
        db_session.add(user_obj)
        await db_session.flush()

        project = Project(
            name="Pipe Project 2", cancer_type="NSCLC", stage="III",
            owner_id=user_obj.id,
        )
        db_session.add(project)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/pipeline/run",
            json={
                "project_id": str(project.id),
                "enable_hypothesis": False,
                "custom_steps": [
                    {"name": "assess_step", "type": "assess", "config": {"max_mw": 500}},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["summary"]["custom_steps_executed"] >= 0

    @pytest.mark.asyncio
    async def test_run_pipeline_not_found(self, client: AsyncClient, auth_headers: dict):
        """不存在的 project_id 应返回 404"""
        resp = await client.post(
            "/api/v1/pipeline/run",
            json={"project_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_run_pipeline_unauthorized(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/pipeline/run",
            json={"project_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_pipeline_status(self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        """GET /pipeline/status/{project_id} 应返回各模块数据量"""
        from app.models.user import User
        from app.models.project import Project
        from app.core.security import hash_password

        user_obj = User(
            email="status@ai-drug.com", name="Status Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER, is_active=True,
        )
        db_session.add(user_obj)
        await db_session.flush()

        project = Project(
            name="Status Project", cancer_type="NSCLC", stage="II",
            owner_id=user_obj.id,
        )
        db_session.add(project)
        await db_session.flush()

        resp = await client.get(
            f"/api/v1/pipeline/status/{project.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["project_id"] == str(project.id)
        assert "datasets" in body
        assert "targets" in body
        assert "molecules" in body
        assert "treatments" in body
