"""合作方与转化路径测试 — 资源池化 + 时间线汇总

覆盖：
1. Partner CRUD（创建/重复名/缺类型/分页/过滤/NotFound/更新）
2. TranslationStage CRUD（创建/列表/更新状态/退出条件检查）
3. 时间线汇总（累计成本/时长/完成百分比计算）
4. 委托合作方（成功/NotFound）
5. 端点权限（未认证 401、RESEARCHER 不能创建 Partner 403、FOUNDER 可创建）
"""
import uuid

import pytest

from app.core.security import hash_password, UserRole
from app.models.project import Project
from app.models.translation import (
    Partner,
    TranslationStage,
    TranslationStageStatus,
)
from app.models.user import User
from app.services.translation import PartnerService, TranslationStageService


# ========== 辅助 fixture ==========

@pytest.fixture
def partner_payload():
    return {
        "name": "药明康德 CRO",
        "partner_type": "cro",
        "capabilities": ["toxicity_study", "in_vitro", "in_vivo", "phase1_trial"],
        "contact_name": "张经理",
        "contact_email": "zhang@wuxi.com",
        "contact_phone": "13800138000",
        "lead_time_days": 45,
        "cost_per_unit_usd": 5000.0,
        "quality_rating": 4.5,
    }


@pytest.fixture
async def test_project_obj(async_db_session):
    """直接 ORM 创建项目（避免依赖 API）"""
    user = User(
        email="trans-test@ai-drug.com",
        name="Trans Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    project = Project(name="转化路径测试项目", owner_id=user.id)
    async_db_session.add(project)
    await async_db_session.flush()
    return {"user": user, "project": project}


# ========== Partner CRUD 单元测试 ==========

class TestPartnerCRUD:
    @pytest.mark.asyncio
    async def test_create_partner(self, async_db_session, partner_payload):
        svc = PartnerService(async_db_session)
        partner = await svc.create_partner(partner_payload)
        assert partner.id is not None
        assert partner.name == "药明康德 CRO"
        assert partner.partner_type == "cro"
        assert partner.capabilities == ["toxicity_study", "in_vitro", "in_vivo", "phase1_trial"]
        assert partner.lead_time_days == 45
        assert partner.quality_rating == 4.5
        assert partner.is_active is True

    @pytest.mark.asyncio
    async def test_create_partner_duplicate_name_raises(self, async_db_session, partner_payload):
        svc = PartnerService(async_db_session)
        await svc.create_partner(partner_payload)
        with pytest.raises(Exception, match="合作方名称已存在"):
            await svc.create_partner(partner_payload)

    @pytest.mark.asyncio
    async def test_create_partner_empty_name_raises(self, async_db_session):
        svc = PartnerService(async_db_session)
        with pytest.raises(Exception, match="合作方名称不能为空"):
            await svc.create_partner({"name": "", "partner_type": "cro"})

    @pytest.mark.asyncio
    async def test_create_partner_missing_type_raises(self, async_db_session):
        svc = PartnerService(async_db_session)
        with pytest.raises(Exception, match="合作方类型不能为空"):
            await svc.create_partner({"name": "测试机构"})

    @pytest.mark.asyncio
    async def test_list_partners_pagination(self, async_db_session):
        svc = PartnerService(async_db_session)
        for i in range(5):
            await svc.create_partner({
                "name": f"CRO_{i}",
                "partner_type": "cro",
            })
        partners, total = await svc.list_partners(page=1, size=3)
        assert len(partners) == 3
        assert total == 5

    @pytest.mark.asyncio
    async def test_list_partners_filter_by_type(self, async_db_session):
        svc = PartnerService(async_db_session)
        await svc.create_partner({"name": "CRO-1", "partner_type": "cro"})
        await svc.create_partner({"name": "CDMO-1", "partner_type": "cdmo"})
        await svc.create_partner({"name": "CRO-2", "partner_type": "cro"})

        partners, total = await svc.list_partners(partner_type="cro")
        assert total == 2
        assert all(p.partner_type == "cro" for p in partners)

    @pytest.mark.asyncio
    async def test_get_partner_not_found(self, async_db_session):
        svc = PartnerService(async_db_session)
        with pytest.raises(Exception, match="合作方不存在"):
            await svc.get_partner(str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_update_partner(self, async_db_session, partner_payload):
        svc = PartnerService(async_db_session)
        partner = await svc.create_partner(partner_payload)
        updated = await svc.update_partner(str(partner.id), {
            "quality_rating": 5.0,
            "notes": "服务质量提升",
        })
        assert updated.quality_rating == 5.0
        assert updated.notes == "服务质量提升"


# ========== TranslationStage CRUD 单元测试 ==========

class TestTranslationStageCRUD:
    @pytest.mark.asyncio
    async def test_create_stage(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        stage = await svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "EGFR 靶点验证",
            "description": "通过 siRNA 敲降验证 EGFR 对 A549 细胞活力的影响",
            "cost_usd": 15000.0,
            "duration_days": 30,
            "order_index": 1,
        })
        assert stage.id is not None
        assert stage.stage_type == "target_validation"
        assert stage.status == TranslationStageStatus.NOT_STARTED
        assert stage.cost_usd == 15000.0
        assert stage.order_index == 1

    @pytest.mark.asyncio
    async def test_create_stage_missing_project_raises(self, async_db_session):
        svc = TranslationStageService(async_db_session)
        with pytest.raises(Exception, match="项目 ID 不能为空"):
            await svc.create_stage({
                "stage_type": "target_validation",
                "stage_name": "测试",
            })

    @pytest.mark.asyncio
    async def test_list_stages_by_project(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        for i, stage_type in enumerate(["target_validation", "preclinical_adme", "preclinical_tox"]):
            await svc.create_stage({
                "project_id": project_id,
                "stage_type": stage_type,
                "stage_name": f"阶段 {i+1}",
                "order_index": i,
            })
        stages = await svc.list_stages(project_id)
        assert len(stages) == 3
        # 按 order_index 升序
        assert stages[0].order_index == 0
        assert stages[2].order_index == 2

    @pytest.mark.asyncio
    async def test_update_stage_status(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        stage = await svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "验证阶段",
        })
        updated = await svc.update_stage(str(stage.id), {
            "status": TranslationStageStatus.IN_PROGRESS,
            "findings": "实验进行中",
        })
        assert updated.status == TranslationStageStatus.IN_PROGRESS
        assert updated.findings == "实验进行中"

    @pytest.mark.asyncio
    async def test_update_stage_exit_criteria(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        stage = await svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "验证阶段",
            "exit_criteria": ["细胞活力下降 >30%", "Western blot 确认敲降效率 >80%"],
        })
        updated = await svc.update_stage(str(stage.id), {
            "exit_criteria_met": True,
            "go_no_go": "go",
            "status": TranslationStageStatus.COMPLETED,
        })
        assert updated.exit_criteria_met is True
        assert updated.go_no_go == "go"
        assert updated.status == TranslationStageStatus.COMPLETED


# ========== 时间线汇总测试 ==========

class TestTimelineSummary:
    @pytest.mark.asyncio
    async def test_timeline_aggregation(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)

        # 创建 3 个阶段：1 完成、1 进行中、1 未开始
        await svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "靶点验证",
            "status": TranslationStageStatus.COMPLETED,
            "cost_usd": 10000.0,
            "duration_days": 30,
            "order_index": 0,
        })
        await svc.create_stage({
            "project_id": project_id,
            "stage_type": "preclinical_adme",
            "stage_name": "ADME",
            "status": TranslationStageStatus.IN_PROGRESS,
            "cost_usd": 20000.0,
            "duration_days": 45,
            "order_index": 1,
        })
        await svc.create_stage({
            "project_id": project_id,
            "stage_type": "preclinical_tox",
            "stage_name": "毒理",
            "status": TranslationStageStatus.NOT_STARTED,
            "cost_usd": 30000.0,
            "duration_days": 60,
            "order_index": 2,
        })

        timeline = await svc.get_timeline(project_id)
        assert timeline["total_cost_usd"] == 60000.0
        assert timeline["total_duration_days"] == 135
        assert timeline["total_stages"] == 3
        assert timeline["completed_stages"] == 1
        assert timeline["completion_pct"] == round(1 / 3 * 100, 1)

    @pytest.mark.asyncio
    async def test_timeline_empty_project(self, async_db_session, test_project_obj):
        svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        timeline = await svc.get_timeline(project_id)
        assert timeline["total_stages"] == 0
        assert timeline["total_cost_usd"] == 0
        assert timeline["completion_pct"] == 0.0


# ========== 委托合作方测试 ==========

class TestAssignPartner:
    @pytest.mark.asyncio
    async def test_assign_partner_success(self, async_db_session, test_project_obj, partner_payload):
        partner_svc = PartnerService(async_db_session)
        partner = await partner_svc.create_partner(partner_payload)

        stage_svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        stage = await stage_svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "委托测试",
        })

        assigned = await stage_svc.assign_partner(str(stage.id), str(partner.id))
        assert assigned.partner_id == partner.id

    @pytest.mark.asyncio
    async def test_assign_partner_not_found(self, async_db_session, test_project_obj):
        stage_svc = TranslationStageService(async_db_session)
        project_id = str(test_project_obj["project"].id)
        stage = await stage_svc.create_stage({
            "project_id": project_id,
            "stage_type": "target_validation",
            "stage_name": "委托测试",
        })
        with pytest.raises(Exception, match="合作方不存在"):
            await stage_svc.assign_partner(str(stage.id), str(uuid.uuid4()))


# ========== 端点测试 ==========

class TestTranslationEndpoints:
    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, client):
        resp = await client.get("/api/v1/translations/partners")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_partner_endpoint(self, client, auth_headers, partner_payload):
        resp = await client.post(
            "/api/v1/translations/partners",
            json=partner_payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"创建失败: {resp.text}"
        data = resp.json()["data"]
        assert data["name"] == "药明康德 CRO"
        assert data["partner_type"] == "cro"

    @pytest.mark.asyncio
    async def test_list_partners_endpoint(self, client, auth_headers, partner_payload):
        # 先创建 2 个
        await client.post("/api/v1/translations/partners", json=partner_payload, headers=auth_headers)
        await client.post("/api/v1/translations/partners", json={
            "name": "恒瑞 CDMO",
            "partner_type": "cdmo",
        }, headers=auth_headers)

        resp = await client.get("/api/v1/translations/partners", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # paged_response 把 total 放在 meta 下
        assert body["meta"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_partners_filter_endpoint(self, client, auth_headers):
        await client.post("/api/v1/translations/partners", json={
            "name": "CRO-A", "partner_type": "cro",
        }, headers=auth_headers)
        await client.post("/api/v1/translations/partners", json={
            "name": "CDMO-B", "partner_type": "cdmo",
        }, headers=auth_headers)

        resp = await client.get(
            "/api/v1/translations/partners?partner_type=cro",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["partner_type"] == "cro"

    @pytest.mark.asyncio
    async def test_researcher_cannot_create_partner(self, client, async_db_session):
        """RESEARCHER 角色不能创建合作方（403）"""
        # 创建 RESEARCHER 用户
        user = User(
            email="researcher@ai-drug.com",
            name="Researcher",
            hashed_password=hash_password("test123456"),
            role=UserRole.RESEARCHER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        resp = await client.post("/api/v1/auth/login", json={
            "email": "researcher@ai-drug.com",
            "password": "test123456",
        })
        token = resp.json()["access_token"]

        resp = await client.post(
            "/api/v1/translations/partners",
            json={"name": "测试", "partner_type": "cro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_stage_and_timeline_workflow(self, client, auth_headers, test_project):
        """端到端：创建阶段 → 委托 → 时间线汇总"""
        project_id = test_project["id"]

        # 步骤1：创建合作方
        partner_resp = await client.post(
            "/api/v1/translations/partners",
            json={"name": "昆泰 CRO", "partner_type": "cro", "lead_time_days": 60},
            headers=auth_headers,
        )
        assert partner_resp.status_code == 200
        partner_id = partner_resp.json()["data"]["id"]

        # 步骤2：创建阶段
        stage_resp = await client.post(
            f"/api/v1/translations/projects/{project_id}/stages",
            json={
                "stage_type": "target_validation",
                "stage_name": "EGFR 验证",
                "cost_usd": 12000.0,
                "duration_days": 30,
                "order_index": 0,
            },
            headers=auth_headers,
        )
        assert stage_resp.status_code == 200
        stage_id = stage_resp.json()["data"]["id"]

        # 步骤3：委托给合作方
        assign_resp = await client.post(
            f"/api/v1/translations/stages/{stage_id}/assign-partner",
            json={"partner_id": partner_id},
            headers=auth_headers,
        )
        assert assign_resp.status_code == 200
        assert assign_resp.json()["data"]["partner_id"] == partner_id

        # 步骤4：查看时间线
        timeline_resp = await client.get(
            f"/api/v1/translations/projects/{project_id}/timeline",
            headers=auth_headers,
        )
        assert timeline_resp.status_code == 200
        timeline = timeline_resp.json()["data"]
        assert timeline["total_cost_usd"] == 12000.0
        assert timeline["total_stages"] == 1
        assert timeline["stages"][0]["partner_name"] == "昆泰 CRO"
