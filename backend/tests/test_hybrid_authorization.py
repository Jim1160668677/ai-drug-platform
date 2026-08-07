"""越权访问与权限校验测试 — 验证 owner_id 隔离与角色权限

覆盖：
1. 越权访问 — 用户 B 访问用户 A 的资源 → 404 NotFoundError
2. 权限不足 — VIEWER 角色调写操作 → 403
3. 资源不存在 — GET 不存在的 UUID → 404

涉及端点：
- GET /synthesis/plans/{plan_id}
- GET /docking/jobs/{job_id}
- GET /benchmarks/{report_id}
- GET /structures/{structure_id}
- POST /docking/hybrid / /synthesis/plan / /screening/dual-context（权限校验）
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import UserRole, hash_password
from app.db.session import get_db
from app.models.user import User


# ========== 辅助：创建带多用户的客户端 ==========

async def _make_multi_user_client(async_db_session):
    """创建一个客户端，含两个已登录用户，返回 (client, headersA, headersB, userA, userB)"""
    from app.main import app

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    users = []
    headers = []
    for idx, (email, role) in enumerate([
        ("authz-a@ai-drug.com", UserRole.FOUNDER),
        ("authz-b@ai-drug.com", UserRole.FOUNDER),
    ]):
        user = User(
            email=email,
            name=f"User {idx}",
            hashed_password=hash_password("test123456"),
            role=role,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()
        users.append(user)

        resp = await client.post("/api/v1/auth/login",
                                json={"email": email, "password": "test123456"})
        assert resp.status_code == 200, f"用户 {email} 登录失败: {resp.text}"
        token = resp.json()["access_token"]
        headers.append({"Authorization": f"Bearer {token}"})

    return client, headers[0], headers[1], users[0], users[1]


async def _make_single_client(async_db_session, role=UserRole.DATA_ENGINEER):
    """创建单用户客户端（用于权限不足测试）"""
    from app.main import app

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    user = User(
        email=f"authz-{role.value}-{id(async_db_session) & 0xffff}@ai-drug.com",
        name=f"{role.value} User",
        hashed_password=hash_password("test123456"),
        role=role,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    resp = await client.post("/api/v1/auth/login",
                            json={"email": user.email, "password": "test123456"})
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    token = resp.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}, user


async def _close(client):
    from app.main import app
    await client.aclose()
    app.dependency_overrides.clear()


# ========== 越权访问测试 ==========

class TestCrossUserAccessDenied:
    """用户 B 访问用户 A 的资源应返回 404（不泄露资源存在性）"""

    @pytest.mark.asyncio
    async def test_synthesis_plan_cross_user_404(self, async_db_session):
        """用户 A 创建 plan，用户 B GET → 404"""
        client, hA, hB, _, _ = await _make_multi_user_client(async_db_session)
        try:
            # 用户 A 创建 plan
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "max_routes": 2}, headers=hA)
            assert resp.status_code == 200, f"用户 A 创建 plan 失败: {resp.text}"
            plan_id = resp.json()["data"]["plan_id"]

            # 用户 B 尝试访问 → 404
            resp = await client.get(f"/api/v1/synthesis/plans/{plan_id}", headers=hB)
            assert resp.status_code == 404, f"越权访问应返回 404: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_docking_job_cross_user_404(self, async_db_session):
        """用户 A 创建 docking job，用户 B GET → 404"""
        client, hA, hB, _, _ = await _make_multi_user_client(async_db_session)
        try:
            # 用户 A 跑 hybrid docking（会创建 ComputeJob）
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "00000000-0000-0000-0000-000000000000",
                                          "smiles_list": ["CCO"]}, headers=hA)
            assert resp.status_code == 200, f"用户 A docking 失败: {resp.text}"

            # 获取用户 A 的 job 列表
            resp = await client.get("/api/v1/docking/jobs", headers=hA)
            assert resp.status_code == 200
            jobs = resp.json()["data"]
            if jobs:
                job_id = jobs[0]["id"]
                # 用户 B 访问该 job → 404
                resp = await client.get(f"/api/v1/docking/jobs/{job_id}", headers=hB)
                assert resp.status_code == 404, f"越权访问 job 应 404: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_benchmark_report_cross_user_404(self, async_db_session):
        """用户 A 创建 benchmark，用户 B GET → 404"""
        client, hA, hB, _, _ = await _make_multi_user_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "c1", "mode": "hybrid", "smiles": "CCO"},
                                    headers=hA)
            assert resp.status_code == 200, f"用户 A benchmark 失败: {resp.text}"
            report_id = resp.json()["data"].get("report_id")
            if report_id:
                # 用户 B 访问 → 404
                resp = await client.get(f"/api/v1/benchmarks/{report_id}", headers=hB)
                assert resp.status_code == 404, f"越权访问 report 应 404: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_structure_cross_user_404(self, async_db_session):
        """用户 A 创建 structure，用户 B GET → 404"""
        client, hA, hB, _, _ = await _make_multi_user_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": "MKKLLLIVTAAH"}, headers=hA)
            assert resp.status_code == 200, f"用户 A predict 失败: {resp.text}"
            structure_id = resp.json()["data"].get("structure_id")
            if structure_id:
                resp = await client.get(f"/api/v1/structures/{structure_id}", headers=hB)
                assert resp.status_code == 404, f"越权访问 structure 应 404: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_list_only_returns_own_resources(self, async_db_session):
        """用户 A 列表只返回 A 的资源，不含 B 的"""
        client, hA, hB, _, _ = await _make_multi_user_client(async_db_session)
        try:
            # 用户 A 创建 1 个 plan
            await client.post("/api/v1/synthesis/plan",
                              json={"smiles": "CCO", "max_routes": 1}, headers=hA)
            # 用户 B 创建 2 个 plan
            await client.post("/api/v1/synthesis/plan",
                              json={"smiles": "CCN", "max_routes": 1}, headers=hB)
            await client.post("/api/v1/synthesis/plan",
                              json={"smiles": "c1ccccc1", "max_routes": 1}, headers=hB)

            # 用户 A 列表应只有 1 个
            resp = await client.get("/api/v1/synthesis/plans", headers=hA)
            assert resp.status_code == 200
            assert len(resp.json()["data"]) == 1, f"用户 A 应只见 1 个 plan: {resp.text}"

            # 用户 B 列表应只有 2 个
            resp = await client.get("/api/v1/synthesis/plans", headers=hB)
            assert resp.status_code == 200
            assert len(resp.json()["data"]) == 2, f"用户 B 应只见 2 个 plan: {resp.text}"
        finally:
            await _close(client)


# ========== 资源不存在测试 ==========

class TestResourceNotFound:
    """GET 不存在的资源 → 404"""

    @pytest.mark.asyncio
    async def test_synthesis_plan_not_found_404(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.FOUNDER)
        try:
            nonexistent = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/synthesis/plans/{nonexistent}", headers=headers)
            assert resp.status_code == 404
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_docking_job_not_found_404(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.FOUNDER)
        try:
            nonexistent = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/docking/jobs/{nonexistent}", headers=headers)
            assert resp.status_code == 404
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_benchmark_report_not_found_404(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.FOUNDER)
        try:
            nonexistent = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/benchmarks/{nonexistent}", headers=headers)
            assert resp.status_code == 404
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_structure_not_found_404(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.FOUNDER)
        try:
            nonexistent = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/structures/{nonexistent}", headers=headers)
            assert resp.status_code == 404
        finally:
            await _close(client)


# ========== 权限不足测试 ==========

class TestInsufficientRole:
    """VIEWER 角色调写操作 → 403"""

    @pytest.mark.asyncio
    async def test_viewer_cannot_docking_hybrid(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "00000000-0000-0000-0000-000000000000",
                                          "smiles_list": ["CCO"]}, headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_cannot_synthesis_plan(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO"}, headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_cannot_screening_dual_context(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/screening/dual-context",
                                    json={"smiles_list": ["CCO"]}, headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_cannot_structures_predict(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": "MKKL"}, headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_cannot_cells_perturbation(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/cells/perturbation",
                                    json={"gene": "TP53"}, headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_cannot_benchmarks_run(self, async_db_session):
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "c1", "mode": "hybrid", "smiles": "CCO"},
                                    headers=headers)
            assert resp.status_code == 403, f"VIEWER 应被拒: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_viewer_can_read_engines_status(self, async_db_session):
        """VIEWER 角色可以读 engines 状态（只读端点不限制）"""
        client, headers, _ = await _make_single_client(async_db_session, UserRole.DATA_ENGINEER)
        try:
            resp = await client.get("/api/v1/synthesis/engines", headers=headers)
            # engines 是只读端点，VIEWER 应能访问
            assert resp.status_code == 200, f"VIEWER 应能读 engines: {resp.text}"
        finally:
            await _close(client)

