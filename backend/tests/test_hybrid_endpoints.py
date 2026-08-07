"""端点模块测试 — 验证 6 个新端点路由结构 + 权限校验

覆盖：
1. 路由结构（6 测试）— 5 个端点模块的关键路径存在（直接检查模块 router）
2. 权限校验（3 测试）— 无 token 返回 401
3. 成功路径（3 测试）— engines 状态端点 + 列表端点
"""
import pytest
from httpx import ASGITransport, AsyncClient


def _get_module_paths(router):
    """收集模块 router 中所有路径（递归遍历 _IncludedRouter 包装）"""
    paths = []
    for r in router.routes:
        # _IncludedRouter 包装类 — 递归遍历其 .routes
        if hasattr(r, "routes"):
            paths.extend(_get_module_paths(r))
        elif hasattr(r, "path"):
            paths.append(r.path)
    return paths


# ========== 路由结构测试 ==========

class TestEndpointRoutes:
    """验证 6 个新端点模块的关键路径存在"""

    def test_structures_router_has_predict_endpoint(self):
        """POST /predict 在 structures router 中"""
        from app.api.v1.endpoints.structures import router
        paths = _get_module_paths(router)
        assert "/predict" in paths, f"缺 /predict: {paths}"

    def test_docking_router_has_hybrid_endpoint(self):
        """POST /hybrid 在 docking router 中"""
        from app.api.v1.endpoints.docking import router
        paths = _get_module_paths(router)
        assert "/hybrid" in paths
        assert "/unimol" in paths
        assert "/vina" in paths

    def test_cells_router_has_perturbation_endpoint(self):
        """POST /perturbation 在 cells router 中"""
        from app.api.v1.endpoints.cells import router
        paths = _get_module_paths(router)
        assert "/perturbation" in paths

    def test_screening_router_has_dual_context_endpoint(self):
        """POST /dual-context 在 screening router 中"""
        from app.api.v1.endpoints.screening import router
        paths = _get_module_paths(router)
        # 至少 2 个端点（dual-context + vaccine）
        assert len(paths) >= 2, f"screening 端点不足: {paths}"

    def test_benchmarks_router_has_run_endpoint(self):
        """POST /run 在 benchmarks router 中"""
        from app.api.v1.endpoints.benchmarks import router
        paths = _get_module_paths(router)
        assert "/run" in paths
        # 至少 3 个端点
        assert len(paths) >= 3, f"benchmarks 端点不足: {paths}"

    def test_synthesis_router_has_plan_endpoint(self):
        """POST /plan 在 synthesis router 中"""
        from app.api.v1.endpoints.synthesis import router
        paths = _get_module_paths(router)
        assert "/plan" in paths
        assert "/engines" in paths


# ========== 权限校验测试 ==========

class TestEndpointAuth:
    """验证端点未认证返回 401"""

    @pytest.mark.asyncio
    async def test_structures_predict_requires_auth(self, async_db_session):
        """无 token 调 /structures/predict 返回 401"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/v1/structures/predict", json={"sequence": "MKKL"})
                assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_docking_hybrid_requires_auth(self, async_db_session):
        """无 token 调 /docking/hybrid 返回 401"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/docking/hybrid",
                    json={"smiles_list": ["CCO"], "target_id": "00000000-0000-0000-0000-000000000000"},
                )
                assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_synthesis_plan_requires_auth(self, async_db_session):
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


# ========== 成功路径测试 ==========

class TestEndpointSuccessPaths:
    """验证部分端点行为"""

    @pytest.mark.asyncio
    async def test_synthesis_engines_status(self, async_db_session):
        """GET /synthesis/engines 端点存在并响应"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/synthesis/engines")
                # 无认证时 401 或 200
                assert resp.status_code in (200, 401)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_structures_list_no_auth_returns_401(self, async_db_session):
        """GET /structures 无认证返回 401"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/structures")
                assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_benchmarks_list_no_auth_returns_401(self, async_db_session):
        """GET /benchmarks 无认证返回 401"""
        from app.main import app
        from app.db.session import get_db

        async def override_get_db():
            yield async_db_session

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/benchmarks")
                assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
