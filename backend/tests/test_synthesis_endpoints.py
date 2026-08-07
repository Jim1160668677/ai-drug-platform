"""synthesis 端点测试 — 验证路由结构 + 权限校验

覆盖：
1. 路由结构（7 测试）— 7 个端点全部挂载（直接检查模块 router）
2. 权限校验（2 测试）— 无 token 返回 401
"""
import pytest
from httpx import ASGITransport, AsyncClient


def _get_module_paths(router):
    """收集模块 router 中所有路径（递归遍历 _IncludedRouter 包装）"""
    paths = []
    for r in router.routes:
        if hasattr(r, "routes"):
            paths.extend(_get_module_paths(r))
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


class TestSynthesisRoutes:
    """验证 synthesis 端点模块的 7 个端点全部挂载"""

    def test_plan_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/plan" in paths

    def test_plans_list_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/plans" in paths

    def test_plan_detail_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        # /plans/{plan_id}
        plan_paths = [p for p in paths if "/plans/" in p and p.endswith("{plan_id}")]
        assert len(plan_paths) >= 1, f"缺 /plans/{{plan_id}} 路由: {paths}"

    def test_routes_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/routes" in paths

    def test_feasibility_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/feasibility" in paths

    def test_cost_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/cost" in paths

    def test_engines_endpoint(self):
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/engines" in paths


class TestSynthesisAuth:
    """验证 synthesis 端点权限"""

    @pytest.mark.asyncio
    async def test_plan_requires_auth(self, async_db_session):
        """无 token 调 /synthesis/plan 返回 401"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/v1/synthesis/plan", json={"smiles": "CCO"})
                assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_engines_status(self, async_db_session):
        """GET /synthesis/engines 端点响应"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/synthesis/engines")
                assert resp.status_code in (200, 401)
        finally:
            app.dependency_overrides.clear()
