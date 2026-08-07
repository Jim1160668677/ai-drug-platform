"""synthesis 7 端点专项边界测试 — 覆盖 max_routes/SMILES 合法性/cost 边界/分页

覆盖：
1. POST /plan — max_routes 边界（0/1/100）、target_scale_grams 边界、invalid SMILES
2. POST /routes — invalid SMILES 降级
3. POST /feasibility — routes={} 降级默认值
4. POST /cost — routes={routes:[]}、sa_score 边界（0/10/负数）
5. GET /plans — 分页边界、case_id 过滤、空列表
6. GET /plans/{plan_id} — 非法 UUID 格式
7. GET /engines — 引擎状态返回结构

预期：边界值不崩溃，invalid 输入降级或返回 400
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import UserRole, hash_password
from app.db.session import get_db
from app.models.user import User


async def _make_client(async_db_session, role=UserRole.FOUNDER):
    from app.main import app

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    suffix = f"syn-{role.value}-{id(async_db_session) & 0xffff}"
    user = User(
        email=f"{suffix}@ai-drug.com",
        name="Synthesis Boundary Tester",
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


# ========== POST /plan max_routes 边界 ==========

class TestPlanMaxRoutesBoundary:
    """max_routes 数值边界"""

    @pytest.mark.asyncio
    async def test_max_routes_zero_succeeds(self, async_db_session):
        """max_routes=0 → 应不崩溃（服务层会处理，可能返回 0 或默认值）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "max_routes": 0}, headers=headers)
            # max_routes=0 不在端点层校验，传给服务层
            assert resp.status_code in (200, 400), f"max_routes=0 应 200 或 400: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_max_routes_one_succeeds(self, async_db_session):
        """max_routes=1 → 200，返回 1 条路线"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "max_routes": 1}, headers=headers)
            assert resp.status_code == 200, f"max_routes=1 应成功: {resp.text}"
            data = resp.json()["data"]
            assert "plan_id" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_max_routes_large_value_succeeds(self, async_db_session):
        """max_routes=100 → 应不崩溃（服务层会限制实际返回数）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "max_routes": 100}, headers=headers)
            assert resp.status_code == 200, f"max_routes=100 应不崩溃: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_target_scale_grams_minimum_succeeds(self, async_db_session):
        """target_scale_grams=0.001（最小）→ 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "target_scale_grams": 0.001},
                                    headers=headers)
            assert resp.status_code == 200, f"最小 scale 应成功: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_target_scale_grams_zero_succeeds(self, async_db_session):
        """target_scale_grams=0 → 应不崩溃（可能产生 0 成本）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "target_scale_grams": 0.0},
                                    headers=headers)
            assert resp.status_code in (200, 400), f"scale=0 应 200 或 400: {resp.text}"
        finally:
            await _close(client)


# ========== POST /routes SMILES 合法性 ==========

class TestRoutesSmilesValidity:
    """invalid SMILES 应降级（不崩溃）"""

    @pytest.mark.asyncio
    async def test_invalid_smiles_does_not_crash(self, async_db_session):
        """SMILES='invalid_smiles_string' → 应不崩溃，返回空或降级路线"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/routes",
                                    json={"smiles": "invalid_smiles_string"}, headers=headers)
            # Mock 模式可能不校验 SMILES 合法性，直接返回 mock 路线
            assert resp.status_code == 200, f"invalid SMILES 应不崩溃: {resp.text}"
            data = resp.json()["data"]
            assert "routes" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_unicode_smiles_does_not_crash(self, async_db_session):
        """SMILES 含 Unicode → 应不崩溃"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/routes",
                                    json={"smiles": "中文🎉SMILES"}, headers=headers)
            assert resp.status_code == 200, f"Unicode SMILES 应不崩溃: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_long_smiles_does_not_crash(self, async_db_session):
        """超长 SMILES（1000 字符）→ 应不崩溃"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/routes",
                                    json={"smiles": "C" * 1000}, headers=headers)
            assert resp.status_code == 200, f"超长 SMILES 应不崩溃: {resp.text}"
        finally:
            await _close(client)


# ========== POST /feasibility routes 降级 ==========

class TestFeasibilityRoutesBoundary:
    """routes={} 应降级到默认值"""

    @pytest.mark.asyncio
    async def test_empty_routes_dict_succeeds(self, async_db_session):
        """routes={} → 200，使用默认 SA score"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/feasibility",
                                    json={"smiles": "CCO", "routes": {}}, headers=headers)
            assert resp.status_code == 200, f"空 routes dict 应成功: {resp.text}"
            data = resp.json()["data"]
            assert "sa_score" in data
            assert "feasibility_label" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_routes_with_empty_list_succeeds(self, async_db_session):
        """routes={routes:[]} → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/feasibility",
                                    json={"smiles": "CCO", "routes": {"routes": []}},
                                    headers=headers)
            assert resp.status_code == 200, f"空 routes list 应成功: {resp.text}"
        finally:
            await _close(client)


# ========== POST /cost sa_score 边界 ==========

class TestCostSaScoreBoundary:
    """sa_score 数值边界"""

    @pytest.mark.asyncio
    async def test_sa_score_zero_succeeds(self, async_db_session):
        """sa_score=0 → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 1}]},
                                          "sa_score": 0.0, "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"sa_score=0 应成功: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_sa_score_max_succeeds(self, async_db_session):
        """sa_score=10（最大）→ 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 1}]},
                                          "sa_score": 10.0, "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"sa_score=10 应成功: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_sa_score_negative_does_not_crash(self, async_db_session):
        """sa_score=-1 → 应不崩溃（可能产生异常成本但不应 500）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 1}]},
                                          "sa_score": -1.0, "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"负 sa_score 应不崩溃: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_sa_score_none_defaults(self, async_db_session):
        """不传 sa_score → 默认 5.0"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 1}]},
                                          "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"默认 sa_score 应成功: {resp.text}"
        finally:
            await _close(client)


# ========== GET /plans 分页边界 ==========

class TestPlansPaginationBoundary:
    """GET /synthesis/plans 分页参数边界"""

    @pytest.mark.asyncio
    async def test_first_page_succeeds(self, async_db_session):
        """page=1, page_size=10 → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans?page=1&page_size=10",
                                    headers=headers)
            assert resp.status_code == 200
            assert "data" in resp.json()
            assert "total" in resp.json().get("meta", {})
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_page_size_one_succeeds(self, async_db_session):
        """page_size=1 → 200，最多 1 条"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            # 先创建 2 个 plan
            await client.post("/api/v1/synthesis/plan",
                              json={"smiles": "CCO", "max_routes": 1}, headers=headers)
            await client.post("/api/v1/synthesis/plan",
                              json={"smiles": "CCN", "max_routes": 1}, headers=headers)

            resp = await client.get("/api/v1/synthesis/plans?page=1&page_size=1",
                                    headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) <= 1
            assert data["meta"]["total"] >= 2
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_large_page_returns_empty(self, async_db_session):
        """page=999 → 空列表"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans?page=999&page_size=10",
                                    headers=headers)
            assert resp.status_code == 200
            assert resp.json()["data"] == []
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_page_zero_returns_422(self, async_db_session):
        """page=0 违反 ge=1 → 422"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans?page=0", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_page_size_over_limit_returns_422(self, async_db_session):
        """page_size=1000 违反 le=100 → 422"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans?page_size=1000", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)


# ========== GET /plans/{plan_id} UUID 边界 ==========

class TestPlanUUIDBoundary:
    """GET /synthesis/plans/{plan_id} UUID 格式边界"""

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_422(self, async_db_session):
        """plan_id='not-a-uuid' → 422（FastAPI UUID 路径参数校验）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans/not-a-uuid", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_valid_uuid_nonexistent_returns_404(self, async_db_session):
        """plan_id=合法但不存在 → 404"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            nonexistent = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/synthesis/plans/{nonexistent}", headers=headers)
            assert resp.status_code == 404
        finally:
            await _close(client)


# ========== GET /engines 引擎状态 ==========

class TestEnginesStatus:
    """GET /synthesis/engines 返回结构"""

    @pytest.mark.asyncio
    async def test_engines_status_structure(self, async_db_session):
        """engines 端点返回 {aizynthfinder, rdkit}"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/engines", headers=headers)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert "aizynthfinder" in data
            assert data["aizynthfinder"] in ("mock", "real")
            assert data["rdkit"] == "available"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_cells_engines_status(self, async_db_session):
        """GET /cells/engines 返回 scgpt 状态"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/cells/engines", headers=headers)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert "scgpt" in data
        finally:
            await _close(client)
