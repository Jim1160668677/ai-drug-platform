"""职能角色权限校验测试 — require_function_role / require_role_or_function"""
import pytest
from httpx import AsyncClient

from app.core.security import hash_password, UserRole
from app.models.user import User


@pytest.fixture
async def researcher_with_function(async_db_session):
    """有职能的研究员"""
    user = User(
        email="func-researcher@ai-drug.com",
        name="Func Researcher",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        function_role="target_discovery",
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest.fixture
async def researcher_without_function(async_db_session):
    """无职能的研究员（向后兼容场景）"""
    user = User(
        email="nofunc-researcher@ai-drug.com",
        name="NoFunc Researcher",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


async def _login(client: AsyncClient, email: str, password: str = "test123456") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    return resp.json()["access_token"]


class TestOrganizationEndpoints:
    """机构端点访问控制"""

    @pytest.mark.asyncio
    async def test_list_orgs_requires_auth(self, client):
        """未认证访问机构列表返回 401"""
        resp = await client.get("/api/v1/organizations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_orgs_with_token(self, client, auth_headers):
        """认证用户可访问机构列表"""
        resp = await client.get("/api/v1/organizations", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "data" in body

    @pytest.mark.asyncio
    async def test_create_org_requires_chief_or_founder(self, client, async_db_session):
        """普通研究员不能创建机构（403）"""
        user = User(
            email="plain@ai-drug.com",
            name="Plain",
            hashed_password=hash_password("test123456"),
            role=UserRole.RESEARCHER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()
        token = await _login(client, "plain@ai-drug.com")
        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "测试机构", "org_type": "pharma"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_founder_can_create_org(self, client, auth_headers):
        """founder 可创建机构"""
        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "测试药企", "org_type": "pharma", "capabilities": ["synthesis"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["name"] == "测试药企"
        assert body["data"]["org_type"] == "pharma"

    @pytest.mark.asyncio
    async def test_get_function_matrix(self, client, auth_headers):
        """获取职能×机构矩阵"""
        resp = await client.get(
            "/api/v1/organizations/function-matrix", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "matrix" in data
        assert "workspaces" in data
        assert "default_permissions" in data
        assert "target_discovery" in data["matrix"]
        assert len(data["function_roles"]) == 7
        assert len(data["org_types"]) == 6

    @pytest.mark.asyncio
    async def test_get_my_workspace_with_function(
        self, client, async_db_session, researcher_with_function
    ):
        """有职能的用户获取默认工作台"""
        token = await _login(client, "func-researcher@ai-drug.com")
        resp = await client.get(
            "/api/v1/organizations/me/workspace",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["workspace"] == "/workbench/targets"
        assert data["function_role"] == "target_discovery"

    @pytest.mark.asyncio
    async def test_get_my_workspace_without_function(
        self, client, async_db_session, researcher_without_function
    ):
        """无职能的用户获取默认工作台（向后兼容）"""
        token = await _login(client, "nofunc-researcher@ai-drug.com")
        resp = await client.get(
            "/api/v1/organizations/me/workspace",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["workspace"] == "/workbench"
        assert data["function_role"] is None

    @pytest.mark.asyncio
    async def test_assign_user_to_org(self, client, auth_headers, async_db_session):
        """分配用户到机构+职能"""
        # 先创建机构
        org_resp = await client.post(
            "/api/v1/organizations",
            json={"name": "测试医院", "org_type": "hospital"},
            headers=auth_headers,
        )
        org_id = org_resp.json()["data"]["id"]

        # 创建一个待分配用户
        target_user = User(
            email="assign-target@ai-drug.com",
            name="Assign Target",
            hashed_password=hash_password("test123456"),
            role=UserRole.DOCTOR,
            is_active=True,
        )
        async_db_session.add(target_user)
        await async_db_session.flush()

        resp = await client.post(
            f"/api/v1/organizations/{org_id}/assign-user",
            json={
                "user_id": str(target_user.id),
                "function_role": "clinical_guidance",
                "title": "主治医师",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["function_role"] == "clinical_guidance"
        assert data["org_id"] == org_id
        assert data["title"] == "主治医师"

    @pytest.mark.asyncio
    async def test_assign_user_invalid_function_org_pair(
        self, client, auth_headers, async_db_session
    ):
        """用药指导职能不能分配到药企（422 校验失败）"""
        org_resp = await client.post(
            "/api/v1/organizations",
            json={"name": "药企X", "org_type": "pharma"},
            headers=auth_headers,
        )
        org_id = org_resp.json()["data"]["id"]

        target_user = User(
            email="invalid-pair@ai-drug.com",
            name="Invalid Pair",
            hashed_password=hash_password("test123456"),
            role=UserRole.RESEARCHER,
            is_active=True,
        )
        async_db_session.add(target_user)
        await async_db_session.flush()

        resp = await client.post(
            f"/api/v1/organizations/{org_id}/assign-user",
            json={
                "user_id": str(target_user.id),
                "function_role": "clinical_guidance",  # 仅 hospital 合法
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422 or resp.status_code == 400
