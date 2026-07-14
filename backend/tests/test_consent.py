"""知情同意管理服务单元测试

覆盖：
- 授予同意
- 撤回同意
- 过期同意
- 校验同意状态
- 跨项目隔离
- 列表过滤
"""
from datetime import datetime, timedelta

import pytest

from app.services.consent.manager import ConsentManager
from app.models.consent import ConsentStatus, ConsentType


@pytest.fixture
async def manager(async_db_session):
    return ConsentManager(async_db_session)


@pytest.fixture
async def project_id():
    import uuid
    return str(uuid.uuid4())


class TestGrantConsent:
    """测试授予同意"""

    @pytest.mark.asyncio
    async def test_grant_basic(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="药物研发数据分析",
        )
        assert consent.status == ConsentStatus.GRANTED
        assert consent.consent_type == ConsentType.DATA_USE
        assert consent.purpose == "药物研发数据分析"
        assert consent.id is not None

    @pytest.mark.asyncio
    async def test_grant_with_expiry(self, manager, project_id):
        expires = datetime.utcnow() + timedelta(days=365)
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.SHARING,
            purpose="数据共享",
            expires_at=expires,
        )
        assert consent.expires_at is not None

    @pytest.mark.asyncio
    async def test_grant_with_constraints(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.PUBLICATION,
            purpose="学术发表",
            constraints={"max_anonymity_level": "k-5", "exclude_genomic": True},
        )
        assert consent.constraints == {"max_anonymity_level": "k-5", "exclude_genomic": True}

    @pytest.mark.asyncio
    async def test_grant_with_created_by(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
            granted_by="user-001",
        )
        assert consent.granted_by == "user-001"


class TestRevokeConsent:
    """测试撤回同意"""

    @pytest.mark.asyncio
    async def test_revoke_basic(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        revoked = await manager.revoke(str(consent.id))
        assert revoked.status == ConsentStatus.WITHDRAWN
        assert revoked.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_with_reason(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        revoked = await manager.revoke(str(consent.id), reason="患者主动撤回")
        assert revoked.revoke_reason == "患者主动撤回"

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_raises(self, manager):
        import uuid
        with pytest.raises(ValueError, match="不存在"):
            await manager.revoke(str(uuid.uuid4()))


class TestCheckConsent:
    """测试校验同意状态"""

    @pytest.mark.asyncio
    async def test_check_granted_returns_true(self, manager, project_id):
        await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        result = await manager.check(project_id, "PATIENT-001", ConsentType.DATA_USE)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_no_consent_returns_false(self, manager, project_id):
        result = await manager.check(project_id, "PATIENT-999", ConsentType.DATA_USE)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_revoked_returns_false(self, manager, project_id):
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        await manager.revoke(str(consent.id))
        result = await manager.check(project_id, "PATIENT-001", ConsentType.DATA_USE)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_expired_returns_false(self, manager, project_id):
        """过期同意返回 False"""
        expired = datetime.utcnow() - timedelta(days=1)
        await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
            expires_at=expired,
        )
        result = await manager.check(project_id, "PATIENT-001", ConsentType.DATA_USE)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_different_consent_type_returns_false(self, manager, project_id):
        """授权 data_use 但检查 sharing"""
        await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        result = await manager.check(project_id, "PATIENT-001", ConsentType.SHARING)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_future_expiry_returns_true(self, manager, project_id):
        """未过期的同意返回 True"""
        future = datetime.utcnow() + timedelta(days=365)
        await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
            expires_at=future,
        )
        result = await manager.check(project_id, "PATIENT-001", ConsentType.DATA_USE)
        assert result is True


class TestListConsents:
    """测试同意列表"""

    @pytest.mark.asyncio
    async def test_list_by_project(self, manager, project_id):
        await manager.grant(project_id, "P-001", ConsentType.DATA_USE, "研究")
        await manager.grant(project_id, "P-002", ConsentType.SHARING, "共享")
        result = await manager.list_consents(project_id)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_patient(self, manager, project_id):
        await manager.grant(project_id, "P-001", ConsentType.DATA_USE, "研究")
        await manager.grant(project_id, "P-001", ConsentType.SHARING, "共享")
        await manager.grant(project_id, "P-002", ConsentType.DATA_USE, "研究")
        result = await manager.list_consents(project_id, patient_pseudonym="P-001")
        assert len(result) == 2
        assert all(c.patient_pseudonym == "P-001" for c in result)


class TestCrossProjectIsolation:
    """测试跨项目隔离"""

    @pytest.mark.asyncio
    async def test_check_isolated(self, manager, project_id):
        """项目 A 的同意在项目 B 中无效"""
        project_b = "project-b-uuid"
        await manager.grant(
            project_id=project_id,
            patient_pseudonym="PATIENT-001",
            consent_type=ConsentType.DATA_USE,
            purpose="研究",
        )
        result = await manager.check(project_b, "PATIENT-001", ConsentType.DATA_USE)
        assert result is False

    @pytest.mark.asyncio
    async def test_list_isolated(self, manager, project_id):
        """项目 A 的记录不出现在项目 B 的列表中"""
        project_b = "project-b-uuid"
        await manager.grant(project_id, "P-001", ConsentType.DATA_USE, "研究")
        result = await manager.list_consents(project_b)
        assert len(result) == 0


class TestGetConsent:
    """测试获取同意详情"""

    @pytest.mark.asyncio
    async def test_get_existing(self, manager, project_id):
        consent = await manager.grant(
            project_id, "P-001", ConsentType.DATA_USE, "研究",
        )
        found = await manager.get_consent(str(consent.id))
        assert found is not None
        assert found.patient_pseudonym == "P-001"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, manager):
        import uuid
        result = await manager.get_consent(str(uuid.uuid4()))
        assert result is None
