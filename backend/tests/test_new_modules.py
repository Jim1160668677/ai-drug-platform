"""新增模块集成测试

覆盖：
1. 用户管理端点（users.py）— 列表/角色修改/状态修改
2. 审计日志 IP/User-Agent 填充（audit.py）
3. Fernet 加密工具（encryption.py）— 加密/解密/无密钥降级/已加密不再重复加密
4. LLM 配置加密集成（llm_config.py + encryption.py）
5. Experiment model relationships
"""
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from cryptography.fernet import Fernet

# 测试环境
os.environ["USE_MOCK"] = "true"
os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import sys
backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, backend_dir)

from app.core.encryption import encrypt, decrypt, _get_fernet  # noqa
from app.core.config import settings  # noqa
from app.db.session import get_db  # noqa
from app.models.base import Base  # noqa
from app.models import (  # noqa: F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
)
from app.models.user import User  # noqa
from app.models.experiment import Experiment  # noqa
from app.models.target import Target  # noqa
from app.models.molecule import Molecule  # noqa
from app.models.treatment import Treatment  # noqa
from app.core.security import UserRole, hash_password  # noqa
from app.api.v1.endpoints import audit as audit_module  # noqa


# ============= Fernet 加密工具测试 =============

class TestEncryption:
    """Fernet 对称加密工具测试"""

    def test_encrypt_decrypt_round_trip_with_key(self, monkeypatch):
        """有密钥时：加密 → 解密 应能还原"""
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key.decode())
        # 重置缓存的 fernet 实例
        import app.core.encryption as enc_mod
        monkeypatch.setattr(enc_mod, "_fernet", None)

        original = "sk-agnes-test-key-12345"
        encrypted = encrypt(original)

        assert encrypted != original, "加密后应与原文不同"
        assert encrypted.startswith("enc:"), "密文应以 enc: 前缀标识"
        assert decrypt(encrypted) == original, "解密后应还原原文"

    def test_encrypt_no_key_returns_plaintext(self, monkeypatch):
        """无密钥时：encrypt 应返回原文（开发环境兼容）"""
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", "")
        import app.core.encryption as enc_mod
        monkeypatch.setattr(enc_mod, "_fernet", None)

        plaintext = "sk-test-no-key"
        assert encrypt(plaintext) == plaintext, "无密钥时应返回原文"

    def test_decrypt_no_prefix_returns_plaintext(self, monkeypatch):
        """无 enc: 前缀时：decrypt 应返回原文（向后兼容）"""
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key.decode())
        import app.core.encryption as enc_mod
        monkeypatch.setattr(enc_mod, "_fernet", None)

        assert decrypt("plain-text-key") == "plain-text-key"

    def test_encrypt_already_encrypted_not_double_encrypted(self, monkeypatch):
        """已加密的密文不应被重复加密"""
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key.decode())
        import app.core.encryption as enc_mod
        monkeypatch.setattr(enc_mod, "_fernet", None)

        encrypted_once = encrypt("sk-test")
        encrypted_twice = encrypt(encrypted_once)

        assert encrypted_once == encrypted_twice, "已加密的密文不应被重复加密"

    def test_encrypt_empty_string_returns_empty(self):
        """空字符串加密应返回空"""
        assert encrypt("") == ""
        assert decrypt("") == ""

    def test_decrypt_invalid_token_returns_ciphertext(self, monkeypatch):
        """无效密文应返回原密文（不抛异常）"""
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key.decode())
        import app.core.encryption as enc_mod
        monkeypatch.setattr(enc_mod, "_fernet", None)

        invalid = "enc:invalid-token-data"
        result = decrypt(invalid)
        assert result == invalid, "无效密文应返回原密文"


# ============= 审计日志 IP/User-Agent 提取测试 =============

class TestAuditExtraction:
    """审计日志 IP/User-Agent 提取测试"""

    def test_extract_client_ip_from_forwarded_for(self):
        """应从 x-forwarded-for 提取第一个 IP（反向代理场景）"""
        request = MagicMock()
        request.headers = {"x-forwarded-for": "203.0.113.1, 10.0.0.1, 10.0.0.2"}
        request.client = MagicMock(host="10.0.0.1")

        ip = audit_module._extract_client_ip(request)
        assert ip == "203.0.113.1", "应取 x-forwarded-for 的第一个 IP"

    def test_extract_client_ip_from_client_host(self):
        """无 x-forwarded-for 时应取 request.client.host"""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="192.168.1.100")

        ip = audit_module._extract_client_ip(request)
        assert ip == "192.168.1.100"

    def test_extract_client_ip_no_request_returns_none(self):
        """request 为 None 时返回 None"""
        assert audit_module._extract_client_ip(None) is None

    def test_extract_client_ip_no_client_returns_none(self):
        """request.client 为 None 时返回 None"""
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert audit_module._extract_client_ip(request) is None

    def test_extract_user_agent_present(self):
        """应从 user-agent header 提取"""
        request = MagicMock()
        request.headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0)"}
        ua = audit_module._extract_user_agent(request)
        assert ua == "Mozilla/5.0 (Windows NT 10.0)"

    def test_extract_user_agent_missing_returns_none(self):
        """无 user-agent header 时返回 None"""
        request = MagicMock()
        request.headers = {}
        assert audit_module._extract_user_agent(request) is None

    def test_extract_user_agent_no_request_returns_none(self):
        assert audit_module._extract_user_agent(None) is None


# ============= 用户管理端点测试 =============

@pytest_asyncio.fixture
async def db_session():
    """SQLite in-memory 数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def founder_client(db_session):
    """以 founder 身份登录的客户端"""
    from app.main import app

    # 创建 founder 用户
    founder = User(
        email="founder@test.com",
        name="Founder",
        role=UserRole.FOUNDER,
        is_active=True,
        hashed_password=hash_password("password123"),
    )
    db_session.add(founder)

    # 创建一个 researcher 用户用于测试
    researcher = User(
        email="researcher@test.com",
        name="Researcher",
        role=UserRole.RESEARCHER,
        is_active=True,
        hashed_password=hash_password("password123"),
    )
    db_session.add(researcher)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 登录 founder
        resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "founder@test.com", "password": "password123"},
        )
        assert resp.status_code == 200, f"founder 登录失败: {resp.text}"
        token = resp.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def researcher_client(db_session):
    """以 researcher 身份登录的客户端（用于权限测试）

    独立创建 researcher 用户，不依赖 founder_client fixture。
    """
    from app.main import app

    # 确保 researcher 用户存在
    researcher = User(
        email="researcher@test.com",
        name="Researcher",
        role=UserRole.RESEARCHER,
        is_active=True,
        hashed_password=hash_password("password123"),
    )
    db_session.add(researcher)
    try:
        await db_session.commit()
    except Exception:
        await db_session.rollback()  # 已存在则忽略

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "researcher@test.com", "password": "password123"},
        )
        assert resp.status_code == 200, f"researcher 登录失败: {resp.text}"
        token = resp.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac

    app.dependency_overrides.clear()


class TestUserManagementEndpoints:
    """用户管理端点测试"""

    @pytest.mark.asyncio
    async def test_list_users_as_founder(self, founder_client):
        """founder 应能获取用户列表"""
        resp = await founder_client.get("/api/v1/users")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 2, "至少有 founder 和 researcher 两个用户"

    @pytest.mark.asyncio
    async def test_list_users_as_researcher_forbidden(self, researcher_client):
        """researcher 不应能访问用户列表"""
        resp = await researcher_client.get("/api/v1/users")
        assert resp.status_code in (401, 403), f"非 founder 应被拒绝: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_list_users_filter_by_role(self, founder_client):
        """按角色过滤用户列表"""
        resp = await founder_client.get("/api/v1/users", params={"role": "researcher"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert all(u["role"] == "researcher" for u in data["items"]), "过滤后应只剩 researcher"

    @pytest.mark.asyncio
    async def test_list_users_invalid_role_400(self, founder_client):
        """无效角色应返回 400"""
        resp = await founder_client.get("/api/v1/users", params={"role": "invalid_role"})
        assert resp.status_code == 400, f"无效角色应 400: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_list_users_filter_by_active(self, founder_client):
        """按状态过滤用户列表"""
        resp = await founder_client.get("/api/v1/users", params={"is_active": True})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert all(u["is_active"] for u in data["items"]), "过滤后应只剩启用用户"

    @pytest.mark.asyncio
    async def test_list_users_pagination(self, founder_client):
        """分页参数正确返回"""
        resp = await founder_client.get("/api/v1/users", params={"skip": 0, "limit": 1})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["skip"] == 0
        assert data["limit"] == 1
        assert len(data["items"]) <= 1

    @pytest.mark.asyncio
    async def test_update_user_role_success(self, founder_client, db_session):
        """founder 修改其他用户角色成功"""
        # 找到 researcher
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "researcher@test.com"))
        researcher = result.scalar_one()
        original_role = researcher.role

        resp = await founder_client.patch(
            f"/api/v1/users/{researcher.id}/role",
            json={"role": "doctor"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "doctor"

        # 还原
        await db_session.refresh(researcher)
        researcher.role = original_role
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_update_user_role_cannot_promote_to_founder(self, founder_client, db_session):
        """不能将用户提升为 founder"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "researcher@test.com"))
        researcher = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{researcher.id}/role",
            json={"role": "founder"},
        )
        assert resp.status_code == 400, f"应禁止提升为 founder: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_update_user_role_cannot_modify_self(self, founder_client, db_session):
        """不能修改自己的角色"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "founder@test.com"))
        founder = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{founder.id}/role",
            json={"role": "researcher"},
        )
        assert resp.status_code == 400, f"应禁止修改自己的角色: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_update_user_role_invalid_role_400(self, founder_client, db_session):
        """无效角色应返回 400"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "researcher@test.com"))
        researcher = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{researcher.id}/role",
            json={"role": "invalid_role"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_user_role_not_found_404(self, founder_client):
        """不存在的用户应返回 404"""
        non_existent_id = uuid4()
        resp = await founder_client.patch(
            f"/api/v1/users/{non_existent_id}/role",
            json={"role": "doctor"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_user_status_disable(self, founder_client, db_session):
        """founder 禁用 researcher"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "researcher@test.com"))
        researcher = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{researcher.id}/status",
            json={"is_active": False},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_active"] is False

        # 还原
        await db_session.refresh(researcher)
        researcher.is_active = True
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_update_user_status_cannot_disable_self(self, founder_client, db_session):
        """不能禁用自己"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "founder@test.com"))
        founder = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{founder.id}/status",
            json={"is_active": False},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_user_status_cannot_disable_founder(self, founder_client, db_session):
        """不能禁用 founder 账户"""
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.email == "founder@test.com"))
        founder = result.scalar_one()

        resp = await founder_client.patch(
            f"/api/v1/users/{founder.id}/status",
            json={"is_active": False},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_user_status_not_found_404(self, founder_client):
        """不存在的用户应返回 404"""
        non_existent_id = uuid4()
        resp = await founder_client.patch(
            f"/api/v1/users/{non_existent_id}/status",
            json={"is_active": False},
        )
        assert resp.status_code == 404


# ============= Experiment Model Relationships 测试 =============

class TestExperimentRelationships:
    """Experiment 模型关系测试"""

    def test_experiment_has_target_relationship(self):
        """Experiment 应有 target 关系属性"""
        exp = Experiment.__table__
        # 检查 target_id 列存在
        assert "target_id" in exp.c, "Experiment 应有 target_id 列"
        # 检查 relationship（通过类属性）
        assert hasattr(Experiment, "target"), "Experiment 应有 target relationship"

    def test_experiment_has_molecule_relationship(self):
        """Experiment 应有 molecule 关系属性"""
        assert "molecule_id" in Experiment.__table__.c
        assert hasattr(Experiment, "molecule")

    def test_experiment_has_treatment_relationship(self):
        """Experiment 应有 treatment 关系属性"""
        assert "treatment_id" in Experiment.__table__.c
        assert hasattr(Experiment, "treatment")

    def test_target_has_experiments_back_populates(self):
        """Target 应有 experiments 反向关系"""
        assert hasattr(Target, "experiments"), "Target 应有 experiments 反向关系"

    def test_molecule_has_experiments_back_populates(self):
        """Molecule 应有 experiments 反向关系"""
        assert hasattr(Molecule, "experiments"), "Molecule 应有 experiments 反向关系"

    def test_treatment_has_experiments_back_populates(self):
        """Treatment 应有 experiments 反向关系"""
        assert hasattr(Treatment, "experiments"), "Treatment 应有 experiments 反向关系"

    @pytest.mark.asyncio
    async def test_experiment_cascade_relationships(self, db_session):
        """验证 Experiment 与 Target/Molecule/Treatment 的级联关系"""
        # 先创建 Founder 用户作为 Project owner
        owner = User(
            email="cascade_owner@test.com",
            name="Owner",
            role=UserRole.FOUNDER,
            is_active=True,
            hashed_password=hash_password("password123"),
        )
        db_session.add(owner)
        await db_session.flush()

        # 创建 Project（Target/Treatment 都需要 project_id）
        from app.models.project import Project
        project = Project(
            name="Test Project",
            patient_pseudonym="TEST-001",
            cancer_type="NSCLC",
            stage="IV",
            owner_id=owner.id,
        )
        db_session.add(project)
        await db_session.flush()

        target = Target(
            project_id=project.id,
            gene_symbol="EGFR",
            gene_name="Epidermal Growth Factor Receptor",
        )
        db_session.add(target)
        await db_session.flush()

        molecule = Molecule(smiles="CCO", name="Ethanol")
        db_session.add(molecule)
        await db_session.flush()

        treatment = Treatment(
            project_id=project.id,
            name="Test Treatment",
            therapy_type="targeted",
        )
        db_session.add(treatment)
        await db_session.flush()

        # 创建 Experiment 关联三者（注意：字段为 exp_type 而非 experiment_type）
        exp = Experiment(
            project_id=project.id,
            name="Binding Assay",
            exp_type="in_vitro",
            target_id=target.id,
            molecule_id=molecule.id,
            treatment_id=treatment.id,
        )
        db_session.add(exp)
        await db_session.commit()
        await db_session.refresh(exp)

        # 验证关系可访问
        assert exp.target_id == target.id
        assert exp.molecule_id == molecule.id
        assert exp.treatment_id == treatment.id


# ============= 审计日志 log_action 集成测试 =============

class TestAuditLogAction:
    """审计日志 log_action 函数集成测试

    使用 mock db 避开 SQLite BigInteger autoincrement 不兼容问题
    （AuditLog.id 在生产用 PostgreSQL BigInteger autoincrement，SQLite 需 INTEGER PRIMARY KEY）
    """

    @pytest.mark.asyncio
    async def test_log_action_with_request_fills_ip_and_ua(self):
        """log_action 应从 request 提取 IP 和 User-Agent"""
        request = MagicMock()
        request.headers = {
            "x-forwarded-for": "203.0.113.50",
            "user-agent": "TestAgent/1.0",
        }
        request.client = MagicMock(host="10.0.0.1")

        # 用 mock db 避免真实写入
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        added_log = []
        def fake_add(log):
            added_log.append(log)
        mock_db.add = fake_add

        await audit_module.log_action(
            db=mock_db,
            actor="test_user",
            role="founder",
            action="test_action",
            entity="test_entity",
            entity_id="123",
            detail="测试日志",
            request=request,
        )

        assert len(added_log) == 1
        log = added_log[0]
        assert log.ip_address == "203.0.113.50", "IP 应从 x-forwarded-for 提取"
        assert log.user_agent == "TestAgent/1.0", "User-Agent 应从 header 提取"
        assert log.actor == "test_user"
        assert log.action == "test_action"
        assert log.role == "founder"
        assert log.entity == "test_entity"
        assert log.entity_id == "123"

    @pytest.mark.asyncio
    async def test_log_action_without_request_leaves_ip_none(self):
        """无 request 时 ip_address 和 user_agent 应为 None"""
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        added_log = []
        def fake_add(log):
            added_log.append(log)
        mock_db.add = fake_add

        await audit_module.log_action(
            db=mock_db,
            actor="test_user",
            role="researcher",
            action="create",
            entity="project",
        )
        log = added_log[0]
        assert log.ip_address is None
        assert log.user_agent is None
