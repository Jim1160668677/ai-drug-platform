"""机构服务单元测试"""
import uuid

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password, UserRole
from app.models.user import User
from app.services.org.org_service import OrgService
from app.services.org.function_matrix import get_workspace_entry


@pytest.fixture
def org_payload():
    return {
        "name": "中科院上海药物研究所",
        "org_type": "research_institute",
        "license_no": "SH-RI-001",
        "contact_email": "contact@simm.ac.cn",
        "address": "上海市浦东新区张江高科技园区",
        "capabilities": ["target_validation", "in_vitro", "in_vivo"],
        "metadata": {"founded": 2003},
    }


@pytest.fixture
async def test_user(async_db_session):
    user = User(
        email="org-test@ai-drug.com",
        name="Org Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


class TestOrgCRUD:
    """机构增删改查"""

    @pytest.mark.asyncio
    async def test_create_org(self, async_db_session, org_payload):
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        assert org.id is not None
        assert org.name == "中科院上海药物研究所"
        assert org.org_type == "research_institute"
        assert org.capabilities == ["target_validation", "in_vitro", "in_vivo"]
        assert org.extra_metadata == {"founded": 2003}
        assert org.is_active is True

    @pytest.mark.asyncio
    async def test_create_org_duplicate_name_raises(self, async_db_session, org_payload):
        svc = OrgService(async_db_session)
        await svc.create_org(org_payload)
        with pytest.raises(ValidationError, match="机构名称已存在"):
            await svc.create_org(org_payload)

    @pytest.mark.asyncio
    async def test_create_org_empty_name_raises(self, async_db_session):
        svc = OrgService(async_db_session)
        with pytest.raises(ValidationError, match="机构名称不能为空"):
            await svc.create_org({"name": "", "org_type": "pharma"})

    @pytest.mark.asyncio
    async def test_create_org_missing_type_raises(self, async_db_session):
        svc = OrgService(async_db_session)
        with pytest.raises(ValidationError, match="机构类型不能为空"):
            await svc.create_org({"name": "Test Org"})

    @pytest.mark.asyncio
    async def test_list_orgs_pagination(self, async_db_session):
        svc = OrgService(async_db_session)
        for i in range(5):
            await svc.create_org({
                "name": f"药企_{i}",
                "org_type": "pharma",
            })
        res = await svc.list_orgs(org_type="pharma", page=1, page_size=3)
        assert res["total"] == 5
        assert len(res["items"]) == 3
        assert res["page"] == 1

        res2 = await svc.list_orgs(org_type="pharma", page=2, page_size=3)
        assert len(res2["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_orgs_filter_by_type(self, async_db_session):
        svc = OrgService(async_db_session)
        await svc.create_org({"name": "研究所A", "org_type": "research_institute"})
        await svc.create_org({"name": "药企B", "org_type": "pharma"})
        res = await svc.list_orgs(org_type="research_institute")
        assert res["total"] == 1
        assert res["items"][0].name == "研究所A"

    @pytest.mark.asyncio
    async def test_get_org_not_found(self, async_db_session):
        svc = OrgService(async_db_session)
        with pytest.raises(NotFoundError):
            await svc.get_org(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_update_org(self, async_db_session, org_payload):
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        updated = await svc.update_org(org.id, {
            "contact_email": "new@simm.ac.cn",
            "address": "新地址",
        })
        assert updated.contact_email == "new@simm.ac.cn"
        assert updated.address == "新地址"
        assert updated.name == org_payload["name"]  # 未改字段不变

    @pytest.mark.asyncio
    async def test_update_org_not_found(self, async_db_session):
        svc = OrgService(async_db_session)
        with pytest.raises(NotFoundError):
            await svc.update_org(uuid.uuid4(), {"name": "X"})


class TestAssignUserToOrg:
    """用户职能分配"""

    @pytest.mark.asyncio
    async def test_assign_user_with_valid_function(self, async_db_session, test_user, org_payload):
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        user = await svc.assign_user_to_org(
            user_id=test_user.id, org_id=org.id,
            function_role="target_discovery", title="副研究员",
        )
        assert user.org_id == org.id
        assert user.function_role == "target_discovery"
        assert user.title == "副研究员"

    @pytest.mark.asyncio
    async def test_assign_user_with_invalid_function_org_pair(
        self, async_db_session, test_user
    ):
        """用药指导职能不能分配到科研院所"""
        svc = OrgService(async_db_session)
        org = await svc.create_org({"name": "研究所", "org_type": "research_institute"})
        with pytest.raises(ValidationError, match="不匹配"):
            await svc.assign_user_to_org(
                user_id=test_user.id, org_id=org.id,
                function_role="clinical_guidance",
            )

    @pytest.mark.asyncio
    async def test_assign_user_without_function_role(self, async_db_session, test_user, org_payload):
        """不传 function_role 时仅分配机构，不校验"""
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        user = await svc.assign_user_to_org(user_id=test_user.id, org_id=org.id)
        assert user.org_id == org.id
        assert user.function_role is None

    @pytest.mark.asyncio
    async def test_assign_user_not_found(self, async_db_session, org_payload):
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        with pytest.raises(NotFoundError):
            await svc.assign_user_to_org(
                user_id=uuid.uuid4(), org_id=org.id, function_role="target_discovery"
            )

    @pytest.mark.asyncio
    async def test_list_users_by_function(self, async_db_session, org_payload):
        svc = OrgService(async_db_session)
        org = await svc.create_org(org_payload)
        # 创建 2 个用户分配到同机构同职能
        for i in range(2):
            u = User(
                email=f"func-{i}@ai-drug.com",
                name=f"Func {i}",
                hashed_password=hash_password("test123456"),
                role=UserRole.RESEARCHER,
                is_active=True,
            )
            async_db_session.add(u)
            await async_db_session.flush()
            await svc.assign_user_to_org(
                user_id=u.id, org_id=org.id, function_role="target_discovery"
            )
        users = await svc.list_users_by_function("target_discovery", org_id=org.id)
        assert len(users) == 2
        assert all(u.function_role == "target_discovery" for u in users)


class TestWorkspaceRouting:
    """工作台路由"""

    def test_get_workspace_for_target_discovery(self):
        svc = OrgService.__new__(OrgService)  # 不需要 DB
        assert svc.get_workspace_for_function("target_discovery") == "/workbench/targets"

    def test_get_workspace_for_molecule_design(self):
        svc = OrgService.__new__(OrgService)
        assert svc.get_workspace_for_function("molecule_design") == "/workbench/molecules"

    def test_get_workspace_for_clinical_guidance(self):
        svc = OrgService.__new__(OrgService)
        assert svc.get_workspace_for_function("clinical_guidance") == "/workbench/treatments"

    def test_get_workspace_for_experiment_validation(self):
        svc = OrgService.__new__(OrgService)
        assert svc.get_workspace_for_function("experiment_validation") == "/workbench/experiments"

    def test_get_workspace_unknown_returns_default(self):
        svc = OrgService.__new__(OrgService)
        assert svc.get_workspace_for_function("unknown") == "/workbench"
