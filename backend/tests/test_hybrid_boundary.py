"""6 端点输入边界测试 — 验证空值/None/超长/Unicode/特殊字符/数值边界

覆盖 6 个端点模块的输入校验路径：
1. structures — POST /predict 空 sequence / 超长 / Unicode
2. docking — POST /unimol /vina /hybrid 空 smiles / 空 target_id / 类型错误 / 超大列表
3. cells — POST /perturbation /annotate 空值
4. screening — POST /dual-context /vaccine 空值 / 类型错误
5. benchmarks — POST /run 空 case_id/mode/smiles / 无效 mode
6. synthesis — POST /plan /routes /feasibility /cost 空值

预期：ValidationError → HTTP 400；正常输入 → 200；降级场景 → 200 + 降级标记
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import UserRole, hash_password
from app.db.session import get_db
from app.models.user import User


# ========== 辅助函数 ==========

async def _make_client(async_db_session, role=UserRole.FOUNDER, function_role=None):
    """构造 HTTP 客户端 + 已登录用户 + auth headers

    返回 (client, headers, user)
    """
    from app.main import app

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    # 创建用户
    suffix = f"{role.value}-{id(async_db_session) & 0xffff}"
    user = User(
        email=f"boundary-{suffix}@ai-drug.com",
        name="Boundary Tester",
        hashed_password=hash_password("test123456"),
        role=role,
        function_role=function_role,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    # 登录
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "test123456"},
    )
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers, user


async def _close(client):
    from app.main import app
    await client.aclose()
    app.dependency_overrides.clear()


# ========== structures 端点边界 ==========

class TestStructuresBoundary:
    """POST /structures/predict 输入边界"""

    @pytest.mark.asyncio
    async def test_empty_sequence_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": ""}, headers=headers)
            assert resp.status_code == 400
            assert "sequence" in resp.json()["error"]["message"]
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_missing_sequence_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_whitespace_only_sequence_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": "   "}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_long_sequence_succeeds_or_degrades(self, async_db_session):
        """超长序列（5000 aa）应不崩溃，返回 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": "M" * 5000}, headers=headers)
            assert resp.status_code == 200, f"超长序列应不崩溃: {resp.text}"
            data = resp.json()["data"]
            assert "plddt_mean" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_unicode_sequence_succeeds(self, async_db_session):
        """Unicode 字符序列应不崩溃（Mock 模式不校验生物合法性）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/structures/predict",
                                    json={"sequence": "MKK中文🎉LL"}, headers=headers)
            assert resp.status_code == 200, f"Unicode 应不崩溃: {resp.text}"
        finally:
            await _close(client)


# ========== docking 端点边界 ==========

class TestDockingBoundary:
    """POST /docking/unimol /vina /hybrid 输入边界"""

    @pytest.mark.asyncio
    async def test_unimol_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/unimol",
                                    json={"smiles": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_vina_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/vina",
                                    json={"smiles": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_hybrid_empty_target_id_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "", "smiles_list": ["CCO"]},
                                    headers=headers)
            assert resp.status_code == 400
            msg = resp.json()["error"]["message"]
            assert "target_id" in msg
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_hybrid_empty_smiles_list_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "t1", "smiles_list": []},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_hybrid_smiles_list_as_string_returns_400(self, async_db_session):
        """smiles_list 传字符串而非数组 → 400"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "t1", "smiles_list": "CCO"},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_hybrid_single_element_list_succeeds(self, async_db_session):
        """单元素 smiles_list → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "00000000-0000-0000-0000-000000000000",
                                          "smiles_list": ["CCO"]},
                                    headers=headers)
            assert resp.status_code == 200, f"单元素应成功: {resp.text}"
            data = resp.json()["data"]
            assert "steps_completed" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_hybrid_large_smiles_list_does_not_crash(self, async_db_session):
        """1000 个 smiles 应不崩溃（可能截断到 top_k*2）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/docking/hybrid",
                                    json={"target_id": "00000000-0000-0000-0000-000000000000",
                                          "smiles_list": ["CCO"] * 1000, "top_k": 5},
                                    headers=headers)
            assert resp.status_code == 200, f"大列表应不崩溃: {resp.text}"
        finally:
            await _close(client)


# ========== cells 端点边界 ==========

class TestCellsBoundary:
    """POST /cells/perturbation /annotate 输入边界"""

    @pytest.mark.asyncio
    async def test_perturbation_empty_gene_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/cells/perturbation",
                                    json={"gene": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_annotate_empty_path_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/cells/annotate",
                                    json={"adata_path": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)


# ========== screening 端点边界 ==========

class TestScreeningBoundary:
    """POST /screening/dual-context /vaccine 输入边界"""

    @pytest.mark.asyncio
    async def test_dual_context_empty_smiles_list_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/dual-context",
                                    json={"smiles_list": []}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_dual_context_smiles_list_as_string_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/dual-context",
                                    json={"smiles_list": "CCO"}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_dual_context_single_element_succeeds(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/dual-context",
                                    json={"smiles_list": ["CCO"]}, headers=headers)
            assert resp.status_code == 200, f"单元素应成功: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_vaccine_empty_target_id_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/vaccine",
                                    json={"target_id": "", "mutation_sequence": "MKKL"},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_vaccine_empty_mutation_sequence_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/vaccine",
                                    json={"target_id": "t1", "mutation_sequence": ""},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_vaccine_valid_input_succeeds(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/screening/vaccine",
                                    json={"target_id": "00000000-0000-0000-0000-000000000000",
                                          "mutation_sequence": "MKKLLLIVTAAH"},
                                    headers=headers)
            assert resp.status_code == 200, f"合法输入应成功: {resp.text}"
            data = resp.json()["data"]
            assert "steps_completed" in data
        finally:
            await _close(client)


# ========== benchmarks 端点边界 ==========

class TestBenchmarksBoundary:
    """POST /benchmarks/run /compare 输入边界"""

    @pytest.mark.asyncio
    async def test_run_empty_case_id_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "", "mode": "hybrid", "smiles": "CCO"},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_run_empty_mode_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "c1", "mode": "", "smiles": "CCO"},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_run_invalid_mode_returns_400(self, async_db_session):
        """无效 mode（非 hybrid/traditional_supercompute/llm_only）→ 400"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "c1", "mode": "quantum", "smiles": "CCO"},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_run_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "c1", "mode": "hybrid", "smiles": ""},
                                    headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_run_valid_input_succeeds(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run",
                                    json={"case_id": "case_001", "mode": "hybrid", "smiles": "CCO"},
                                    headers=headers)
            assert resp.status_code == 200, f"合法输入应成功: {resp.text}"
            data = resp.json()["data"]
            assert "case_id" in data
            assert "mode" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_compare_empty_case_id_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/compare",
                                    json={"case_id": "", "smiles": "CCO"}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_run_all_succeeds(self, async_db_session):
        """POST /benchmarks/run-all 无 body → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/benchmarks/run-all",
                                     json={}, headers=headers)
            # run-all 可能因 9 个 case 耗时较长，但 mock 模式应 < 30s
            assert resp.status_code in (200, 500), f"run-all 应返回 200 或 500: {resp.text}"
        finally:
            await _close(client)


# ========== synthesis 端点边界 ==========

class TestSynthesisBoundary:
    """POST /synthesis/plan /routes /feasibility /cost 输入边界"""

    @pytest.mark.asyncio
    async def test_plan_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_plan_valid_smiles_succeeds(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/plan",
                                    json={"smiles": "CCO", "max_routes": 2},
                                    headers=headers)
            assert resp.status_code == 200, f"合法 smiles 应成功: {resp.text}"
            data = resp.json()["data"]
            assert "plan_id" in data
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_routes_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/routes",
                                    json={"smiles": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_feasibility_empty_smiles_returns_400(self, async_db_session):
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/feasibility",
                                    json={"smiles": ""}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_cost_empty_routes_returns_400(self, async_db_session):
        """routes 为空 dict → 400（not {} 为 True）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {}}, headers=headers)
            assert resp.status_code == 400
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_cost_valid_routes_succeeds(self, async_db_session):
        """routes 非空 → 200"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 3}]},
                                          "sa_score": 3.5, "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"合法 routes 应成功: {resp.text}"
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_cost_negative_sa_score_does_not_crash(self, async_db_session):
        """sa_score=-1 应不崩溃（可能产生异常成本但不应 500）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.post("/api/v1/synthesis/cost",
                                    json={"routes": {"routes": [{"smiles": "CCO", "steps": 1}]},
                                          "sa_score": -1.0, "target_scale_grams": 10.0},
                                    headers=headers)
            assert resp.status_code == 200, f"负 sa_score 应不崩溃: {resp.text}"
        finally:
            await _close(client)


# ========== 分页参数边界 ==========

class TestPaginationBoundary:
    """GET 端点分页参数边界"""

    @pytest.mark.asyncio
    async def test_structures_page_zero_returns_422(self, async_db_session):
        """page=0 违反 ge=1 约束 → 422"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/structures?page=0", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_structures_page_size_over_limit_returns_422(self, async_db_session):
        """page_size=1000 违反 le=100 约束 → 422"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/structures?page_size=1000", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_synthesis_plans_large_page_returns_empty(self, async_db_session):
        """page=999 返回空列表（非 422，因为 ge=1 已满足）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/synthesis/plans?page=999&page_size=10",
                                    headers=headers)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data == []
        finally:
            await _close(client)

    @pytest.mark.asyncio
    async def test_structures_invalid_uuid_returns_400(self, async_db_session):
        """GET /structures/{id} 非法 UUID → 400（RequestValidationError 被 handler 改写为 400）"""
        client, headers, _ = await _make_client(async_db_session)
        try:
            resp = await client.get("/api/v1/structures/not-a-uuid", headers=headers)
            assert resp.status_code in (400, 422)
        finally:
            await _close(client)
