"""端点直接单元测试 — 直接调用 async 端点函数以正确追踪覆盖率

本文件不通过 HTTP 客户端测试，而是直接调用端点函数，
确保 coverage.py 能正确追踪代码执行。
"""
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core.security import UserRole, create_access_token, hash_password
from app.models.base import Base
from app.models import (
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)
from app.models.llm_config import LLMConfig, AccessMode, UpstreamProtocol
from app.models.user import User
from app.models.project import Project
from app.models.audit import AuditLog
from app.models.dataset import Dataset, DataType, ParseStatus
from app.models.experiment import Experiment, ExperimentStatus


@pytest_asyncio.fixture
async def db_session():
    """SQLite in-memory 数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def founder_user(db_session):
    """创建 founder 用户"""
    user = User(
        email="founder@test.com",
        name="Founder",
        hashed_password=hash_password("pass123"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def chief_user(db_session):
    """创建 chief 用户"""
    user = User(
        email="chief@test.com",
        name="Chief",
        hashed_password=hash_password("pass123"),
        role=UserRole.CHIEF_RESEARCHER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_project(db_session, founder_user):
    """创建测试项目"""
    proj = Project(
        name="Test Project",
        patient_pseudonym="P-001",
        cancer_type="NSCLC",
        stage="IV",
        owner_id=founder_user.id,
    )
    db_session.add(proj)
    await db_session.flush()
    return proj


# ============================================================
# auth.py 端点
# ============================================================

def _mock_request() -> Request:
    """构造一个最小可用的 starlette Request，供 slowapi 限流装饰器使用"""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_login_success(self, db_session, founder_user):
        from app.api.v1.endpoints.auth import login, LoginRequest
        result = await login(
            _mock_request(),
            LoginRequest(email="founder@test.com", password="pass123"),
            db=db_session,
        )
        assert result.access_token
        assert result.role == "founder"
        assert result.email == "founder@test.com"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, db_session, founder_user):
        from app.core.exceptions import UnauthorizedError
        from app.api.v1.endpoints.auth import login, LoginRequest
        with pytest.raises(UnauthorizedError) as exc_info:
            await login(_mock_request(), LoginRequest(email="founder@test.com", password="wrong"), db=db_session)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, db_session):
        from app.core.exceptions import UnauthorizedError
        from app.api.v1.endpoints.auth import login, LoginRequest
        with pytest.raises(UnauthorizedError) as exc_info:
            await login(_mock_request(), LoginRequest(email="nobody@test.com", password="pass"), db=db_session)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_disabled_user(self, db_session):
        from app.core.exceptions import ForbiddenError
        from app.api.v1.endpoints.auth import login, LoginRequest
        user = User(
            email="disabled@test.com",
            name="Disabled",
            hashed_password=hash_password("pass123"),
            role=UserRole.RESEARCHER,
            is_active=False,
        )
        db_session.add(user)
        await db_session.flush()
        with pytest.raises(ForbiddenError) as exc_info:
            await login(_mock_request(), LoginRequest(email="disabled@test.com", password="pass123"), db=db_session)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_register_success(self, db_session):
        from app.api.v1.endpoints.auth import register
        from app.api.v1.schemas import UserCreate
        payload = UserCreate(
            email="new@test.com",
            name="New User",
            password="pass123",
            role="researcher",
        )
        result = await register(payload, db=db_session)
        assert result.email == "new@test.com"
        assert result.role == "researcher"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, db_session, founder_user):
        from app.core.exceptions import ConflictError
        from app.api.v1.endpoints.auth import register
        from app.api.v1.schemas import UserCreate
        payload = UserCreate(
            email="founder@test.com",
            name="Dup",
            password="pass",
            role="researcher",
        )
        with pytest.raises(ConflictError) as exc_info:
            await register(payload, db=db_session)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_register_invalid_role_defaults_to_researcher(self, db_session):
        from app.api.v1.endpoints.auth import register
        from app.api.v1.schemas import UserCreate
        payload = UserCreate(
            email="role@test.com",
            name="Role Test",
            password="pass123",
            role="invalid_role",
        )
        result = await register(payload, db=db_session)
        assert result.role == "researcher"

    @pytest.mark.asyncio
    async def test_get_me(self, founder_user):
        from app.api.v1.endpoints.auth import get_me
        result = await get_me(current_user=founder_user)
        assert result.email == "founder@test.com"


# ============================================================
# audit.py 端点
# ============================================================

class TestAuditEndpoints:
    @pytest.mark.asyncio
    async def test_list_audit_logs_empty(self, db_session, founder_user):
        from app.api.v1.endpoints.audit import list_audit_logs
        result = await list_audit_logs(
            actor=None, action=None, entity=None,
            skip=0, limit=100,
            db=db_session, current_user=founder_user,
        )
        assert result["success"] is True
        assert result["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_audit_logs_with_data(self, db_session, founder_user):
        """使用 mock 方式注入审计日志数据（AuditLog 使用 BigInt 自增主键，SQLite 兼容性差）"""
        from app.api.v1.endpoints.audit import list_audit_logs
        from app.models.audit import AuditLog

        # 直接在 DB 中插入数据（绕过 ORM 的 id 自动生成）
        log1 = AuditLog(actor="user1", role="founder", action="create", entity="project")
        log2 = AuditLog(actor="user2", role="researcher", action="update", entity="target")
        # 手动设置 id
        log1.id = 1
        log2.id = 2
        db_session.add(log1)
        db_session.add(log2)
        await db_session.flush()

        result = await list_audit_logs(
            actor=None, action=None, entity=None,
            skip=0, limit=100,
            db=db_session, current_user=founder_user,
        )
        assert result["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_actor(self, db_session, founder_user):
        from app.api.v1.endpoints.audit import list_audit_logs
        from app.models.audit import AuditLog

        log1 = AuditLog(actor="user1", role="founder", action="create", entity="project")
        log2 = AuditLog(actor="user2", role="researcher", action="update", entity="target")
        log1.id = 1
        log2.id = 2
        db_session.add(log1)
        db_session.add(log2)
        await db_session.flush()

        result = await list_audit_logs(
            actor="user1", action=None, entity=None,
            skip=0, limit=100,
            db=db_session, current_user=founder_user,
        )
        assert result["data"]["total"] == 1
        assert result["data"]["logs"][0]["actor"] == "user1"

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_action(self, db_session, founder_user):
        from app.api.v1.endpoints.audit import list_audit_logs
        from app.models.audit import AuditLog

        log1 = AuditLog(actor="user1", role="founder", action="create", entity="project")
        log2 = AuditLog(actor="user2", role="researcher", action="update", entity="target")
        log1.id = 1
        log2.id = 2
        db_session.add(log1)
        db_session.add(log2)
        await db_session.flush()

        result = await list_audit_logs(
            actor=None, action="update", entity=None,
            skip=0, limit=100,
            db=db_session, current_user=founder_user,
        )
        assert result["data"]["total"] == 1
        assert result["data"]["logs"][0]["action"] == "update"

    @pytest.mark.asyncio
    async def test_list_audit_logs_filter_by_entity(self, db_session, founder_user):
        from app.api.v1.endpoints.audit import list_audit_logs
        from app.models.audit import AuditLog

        log1 = AuditLog(actor="user1", role="founder", action="create", entity="project")
        log2 = AuditLog(actor="user2", role="researcher", action="update", entity="target")
        log1.id = 1
        log2.id = 2
        db_session.add(log1)
        db_session.add(log2)
        await db_session.flush()

        result = await list_audit_logs(
            actor=None, action=None, entity="target",
            skip=0, limit=100,
            db=db_session, current_user=founder_user,
        )
        assert result["data"]["total"] == 1
        assert result["data"]["logs"][0]["entity"] == "target"

    @pytest.mark.asyncio
    async def test_log_action_returns_log(self):
        """log_action 内部会 flush，AuditLog 的 BigInt 主键在 SQLite 不自动递增，使用 mock DB"""
        from app.api.v1.endpoints.audit import log_action
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        log = await log_action(
            mock_db, actor="user1", role="founder", action="create",
            entity="project", entity_id="p1", detail="Created project",
        )
        assert log.actor == "user1"
        assert log.action == "create"
        assert log.entity == "project"
        mock_db.add.assert_called_once()


# ============================================================
# chat.py 端点
# ============================================================

class TestChatEndpoints:
    @pytest.mark.asyncio
    async def test_list_tiers(self, founder_user):
        from app.api.v1.endpoints.chat import list_tiers
        result = await list_tiers(current_user=founder_user)
        assert result["success"] is True
        assert len(result["data"]["tiers"]) == 2
        assert result["data"]["tiers"][0]["name"] == "fast_screen"
        assert result["data"]["tiers"][1]["name"] == "deep_insight"

    @pytest.mark.asyncio
    async def test_chat_fast_screen(self, db_session, founder_user):
        from app.api.v1.endpoints.chat import chat
        from app.api.v1.schemas import ChatRequest
        payload = ChatRequest(message="什么是 EGFR？", tier="fast_screen")
        result = await chat(payload, db=db_session, current_user=founder_user)
        assert result.answer
        assert result.tier == "fast_screen"

    @pytest.mark.asyncio
    async def test_analyze_with_nl(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.chat import analyze_with_nl
        result = await analyze_with_nl(
            message="分析 EGFR 表达",
            project_id=str(test_project.id),
            tier="fast_screen",
            db=db_session,
            current_user=founder_user,
        )
        assert result.success is True
        assert result.data is not None


# ============================================================
# dashboard.py 端点
# ============================================================

class TestDashboardEndpoint:
    @pytest.mark.asyncio
    async def test_dashboard_overview_empty(self, db_session, founder_user):
        from app.api.v1.endpoints.dashboard import dashboard_overview
        result = await dashboard_overview(db=db_session, current_user=founder_user)
        assert result["success"] is True
        assert result["data"]["global"]["projects"] == 0
        assert result["data"]["global"]["datasets"] == 0
        assert result["data"]["by_cancer_type"] == {}
        assert result["data"]["projects"] == []

    @pytest.mark.asyncio
    async def test_dashboard_overview_with_data(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.dashboard import dashboard_overview
        result = await dashboard_overview(db=db_session, current_user=founder_user)
        assert result["data"]["global"]["projects"] == 1
        assert result["data"]["by_cancer_type"]["NSCLC"] == 1
        assert len(result["data"]["projects"]) == 1
        assert result["data"]["projects"][0]["name"] == "Test Project"
        assert result["data"]["projects"][0]["counts"]["datasets"] == 0


# ============================================================
# data.py 端点
# ============================================================

class TestDataEndpoints:
    @pytest.mark.asyncio
    async def test_list_datasets_empty(self, db_session, founder_user):
        from app.api.v1.endpoints.data import list_datasets
        result = await list_datasets(project_id=None, data_type=None, page=1, page_size=50, db=db_session, current_user=founder_user)
        assert result["data"] == []
        assert result["meta"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_datasets_with_data(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.data import list_datasets
        ds = Dataset(
            project_id=test_project.id,
            name="Test RNA-seq",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        result = await list_datasets(project_id=None, data_type=None, page=1, page_size=50, db=db_session, current_user=founder_user)
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Test RNA-seq"

    @pytest.mark.asyncio
    async def test_list_datasets_filter_by_project(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.data import list_datasets
        ds = Dataset(
            project_id=test_project.id,
            name="Test RNA-seq",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        result = await list_datasets(project_id=test_project.id, data_type=None, page=1, page_size=50, db=db_session, current_user=founder_user)
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_dataset_found(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.data import get_dataset
        ds = Dataset(
            project_id=test_project.id,
            name="Test",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        result = await get_dataset(dataset_id=ds.id, db=db_session, current_user=founder_user)
        assert result.name == "Test"

    @pytest.mark.asyncio
    async def test_get_dataset_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.data import get_dataset
        with pytest.raises(NotFoundError) as exc_info:
            await get_dataset(dataset_id=uuid4(), db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_dataset_forbidden_non_owner(self, db_session, founder_user, chief_user, test_project):
        """水平越权防护：非 owner 且非 FOUNDER 的用户不能访问他人数据集"""
        from app.core.exceptions import ForbiddenError
        from app.api.v1.endpoints.data import get_dataset
        ds = Dataset(
            project_id=test_project.id,
            name="Owner Only",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        with pytest.raises(ForbiddenError):
            await get_dataset(dataset_id=ds.id, db=db_session, current_user=chief_user)

    @pytest.mark.asyncio
    async def test_delete_dataset_forbidden_non_owner(self, db_session, founder_user, chief_user, test_project):
        """水平越权防护：非 owner 不能删除他人数据集"""
        from app.core.exceptions import ForbiddenError
        from app.api.v1.endpoints.data import delete_dataset
        ds = Dataset(
            project_id=test_project.id,
            name="Owner Only",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.PENDING,
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        with pytest.raises(ForbiddenError):
            await delete_dataset(dataset_id=ds.id, db=db_session, current_user=chief_user)

    @pytest.mark.asyncio
    async def test_quality_report_found(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.data import quality_report
        ds = Dataset(
            project_id=test_project.id,
            name="Test",
            data_type=DataType.RNA_SEQ,
            storage_path="/data/test.csv",
            file_format="csv",
            parse_status=ParseStatus.COMPLETED,
            quality_metrics={"total_reads": 1000},
            parsed_summary={"genes": 500},
            uploaded_by=founder_user.id,
        )
        db_session.add(ds)
        await db_session.flush()

        result = await quality_report(dataset_id=ds.id, db=db_session, current_user=founder_user)
        assert result["data"]["quality_metrics"]["total_reads"] == 1000
        assert result["data"]["parse_status"] == "completed"

    @pytest.mark.asyncio
    async def test_quality_report_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.data import quality_report
        with pytest.raises(NotFoundError) as exc_info:
            await quality_report(dataset_id=uuid4(), db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404


# ============================================================
# experiments.py 端点
# ============================================================

class TestExperimentEndpoints:
    @pytest.mark.asyncio
    async def test_list_experiments_empty(self, db_session, founder_user):
        from app.api.v1.endpoints.experiments import list_experiments
        result = await list_experiments(project_id=None, exp_type=None, status=None, page=1, page_size=50, db=db_session, current_user=founder_user)
        assert result["data"] == []
        assert result["meta"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_experiments_with_data(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.experiments import list_experiments
        exp = Experiment(
            project_id=test_project.id,
            name="Test Exp",
            exp_type="dry_lab",
        )
        db_session.add(exp)
        await db_session.flush()

        result = await list_experiments(project_id=None, exp_type=None, status=None, page=1, page_size=50, db=db_session, current_user=founder_user)
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Test Exp"

    @pytest.mark.asyncio
    async def test_create_experiment(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.experiments import create_experiment, ExperimentCreate
        payload = ExperimentCreate(
            project_id=str(test_project.id),
            name="New Exp",
            exp_type="dry_lab",
        )
        result = await create_experiment(payload, db=db_session, current_user=founder_user)
        assert result.success is True
        assert "id" in result.data

    @pytest.mark.asyncio
    async def test_submit_result_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.experiments import submit_result, ExperimentResultUpdate
        payload = ExperimentResultUpdate(result={"val": 1}, success=True)
        with pytest.raises(NotFoundError) as exc_info:
            await submit_result(experiment_id=uuid4(), payload=payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_loop_status(self, db_session, founder_user, test_project):
        from app.api.v1.endpoints.experiments import loop_status
        exp = Experiment(
            project_id=test_project.id,
            name="Test",
            exp_type="dry_lab",
            status=ExperimentStatus.COMPLETED,
            success=True,
        )
        db_session.add(exp)
        await db_session.flush()

        result = await loop_status(project_id=test_project.id, db=db_session, current_user=founder_user)
        assert result["data"]["total_experiments"] == 1
        assert result["data"]["completed"] == 1
        assert result["data"]["successful"] == 1

    @pytest.mark.asyncio
    async def test_import_lims(self, db_session, founder_user):
        from app.api.v1.endpoints.experiments import import_lims
        result = await import_lims(
            payload={"experiments": [{"name": "LIMS-1"}]},
            db=db_session,
            current_user=founder_user,
        )
        assert result.success is True


# ============================================================
# llm_config.py 端点 — 直接调用覆盖所有分支
# ============================================================

class TestLLMConfigEndpoints:
    @pytest.mark.asyncio
    async def test_list_llm_configs_empty(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import list_llm_configs
        result = await list_llm_configs(page=1, page_size=50, db=db_session, current_user=founder_user)
        assert result["data"] == []
        assert result["meta"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_llm_configs_with_data(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import list_llm_configs, _to_response
        cfg = LLMConfig(
            name="TestLLM",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1",
            api_key="sk-testkey1234567890abcdef",
            test_model="gpt-4o-mini",
        )
        db_session.add(cfg)
        await db_session.flush()

        result = await list_llm_configs(page=1, page_size=50, db=db_session, current_user=founder_user)
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "TestLLM"

    @pytest.mark.asyncio
    async def test_get_active_config_none(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import get_active_config
        result = await get_active_config(db=db_session, current_user=founder_user)
        assert result.success is False
        assert result.data["use_default"] is True

    @pytest.mark.asyncio
    async def test_get_active_config_found(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import get_active_config
        cfg = LLMConfig(
            name="ActiveLLM",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1",
            api_key="sk-testkey1234567890abcdef",
            test_model="gpt-4o-mini",
            is_active=True,
        )
        db_session.add(cfg)
        await db_session.flush()

        result = await get_active_config(db=db_session, current_user=founder_user)
        assert result["success"] is True
        assert result["data"]["name"] == "ActiveLLM"

    @pytest.mark.asyncio
    async def test_create_llm_config_success(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import create_llm_config
        from app.api.v1.schemas import LLMConfigCreate
        payload = LLMConfigCreate(
            name="NewLLM",
            provider="openai_compatible",
            access_mode="api_only",
            upstream_protocol="chat_completions",
            base_url="https://api.new.com/v1",
            api_key="sk-newkey1234567890abcdef",
            test_model="gpt-4o-mini",
            is_active=False,
        )
        result = await create_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.name == "NewLLM"
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_create_llm_config_active_deactivates_others(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import create_llm_config
        from app.api.v1.schemas import LLMConfigCreate
        # 先创建一个激活配置
        cfg1 = LLMConfig(
            name="LLM1",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.1.com/v1",
            api_key="sk-key111111111111111111",
            test_model="m1",
            is_active=True,
        )
        db_session.add(cfg1)
        await db_session.flush()

        # 创建新的激活配置
        payload = LLMConfigCreate(
            name="LLM2",
            provider="openai_compatible",
            access_mode="api_only",
            upstream_protocol="chat_completions",
            base_url="https://api.2.com/v1",
            api_key="sk-key222222222222222222",
            test_model="m2",
            is_active=True,
        )
        result = await create_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.is_active is True

        # 验证 LLM1 被取消激活
        await db_session.refresh(cfg1)
        assert cfg1.is_active is False

    @pytest.mark.asyncio
    async def test_create_llm_config_duplicate_name(self, db_session, founder_user):
        from app.core.exceptions import ConflictError
        from app.api.v1.endpoints.llm_config import create_llm_config
        from app.api.v1.schemas import LLMConfigCreate
        cfg = LLMConfig(
            name="DupLLM",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1",
            api_key="sk-key999999999999999999",
            test_model="m1",
        )
        db_session.add(cfg)
        await db_session.flush()

        payload = LLMConfigCreate(
            name="DupLLM",
            provider="openai_compatible",
            access_mode="api_only",
            upstream_protocol="chat_completions",
            base_url="https://api.test.com/v1",
            api_key="sk-key888888888888888888",
            test_model="m2",
        )
        with pytest.raises(ConflictError) as exc_info:
            await create_llm_config(payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_llm_config_invalid_enum(self, db_session, founder_user):
        from app.core.exceptions import ValidationError
        from app.api.v1.endpoints.llm_config import create_llm_config
        from app.api.v1.schemas import LLMConfigCreate
        payload = LLMConfigCreate(
            name="BadEnum",
            provider="openai_compatible",
            access_mode="invalid_mode",
            upstream_protocol="chat_completions",
            base_url="https://api.test.com/v1",
            api_key="sk-key777777777777777777",
            test_model="m1",
        )
        with pytest.raises(ValidationError) as exc_info:
            await create_llm_config(payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_llm_config_success(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import update_llm_config
        from app.api.v1.schemas import LLMConfigUpdate
        cfg = LLMConfig(
            name="UpdateLLM",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1",
            api_key="sk-key666666666666666666",
            test_model="m1",
        )
        db_session.add(cfg)
        await db_session.flush()

        payload = LLMConfigUpdate(description="Updated", temperature=0.3)
        result = await update_llm_config(config_id=cfg.id, payload=payload, db=db_session, current_user=founder_user)
        assert result.description == "Updated"
        assert result.temperature == 0.3

    @pytest.mark.asyncio
    async def test_update_llm_config_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.llm_config import update_llm_config
        from app.api.v1.schemas import LLMConfigUpdate
        payload = LLMConfigUpdate(description="Updated")
        with pytest.raises(NotFoundError) as exc_info:
            await update_llm_config(config_id=uuid4(), payload=payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_llm_config_duplicate_name(self, db_session, founder_user):
        from app.core.exceptions import ConflictError
        from app.api.v1.endpoints.llm_config import update_llm_config
        from app.api.v1.schemas import LLMConfigUpdate
        cfg1 = LLMConfig(
            name="LLM-A",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.a.com/v1",
            api_key="sk-key555555555555555555",
            test_model="m1",
        )
        cfg2 = LLMConfig(
            name="LLM-B",
            provider="openai_compatible",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.b.com/v1",
            api_key="sk-key444444444444444444",
            test_model="m2",
        )
        db_session.add_all([cfg1, cfg2])
        await db_session.flush()

        payload = LLMConfigUpdate(name="LLM-A")
        with pytest.raises(ConflictError) as exc_info:
            await update_llm_config(config_id=cfg2.id, payload=payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_llm_config_activate(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import update_llm_config
        from app.api.v1.schemas import LLMConfigUpdate
        cfg1 = LLMConfig(
            name="Act-A", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.a.com/v1", api_key="sk-key333333333333333333",
            test_model="m1", is_active=True,
        )
        cfg2 = LLMConfig(
            name="Act-B", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.b.com/v1", api_key="sk-key222222222222222222",
            test_model="m2", is_active=False,
        )
        db_session.add_all([cfg1, cfg2])
        await db_session.flush()

        payload = LLMConfigUpdate(is_active=True)
        result = await update_llm_config(config_id=cfg2.id, payload=payload, db=db_session, current_user=founder_user)
        assert result.is_active is True
        await db_session.refresh(cfg1)
        assert cfg1.is_active is False

    @pytest.mark.asyncio
    async def test_update_llm_config_invalid_access_mode(self, db_session, founder_user):
        from app.core.exceptions import ValidationError
        from app.api.v1.endpoints.llm_config import update_llm_config
        from app.api.v1.schemas import LLMConfigUpdate
        cfg = LLMConfig(
            name="BadUpdate", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-key111111111111111111",
            test_model="m1",
        )
        db_session.add(cfg)
        await db_session.flush()

        payload = LLMConfigUpdate(access_mode="invalid")
        with pytest.raises(ValidationError) as exc_info:
            await update_llm_config(config_id=cfg.id, payload=payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_llm_config_success(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import delete_llm_config
        cfg = LLMConfig(
            name="DeleteLLM", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-key000000000000000000",
            test_model="m1", is_active=False,
        )
        db_session.add(cfg)
        await db_session.flush()

        result = await delete_llm_config(config_id=cfg.id, db=db_session, current_user=founder_user)
        assert "已删除" in result.message

    @pytest.mark.asyncio
    async def test_delete_llm_config_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.llm_config import delete_llm_config
        with pytest.raises(NotFoundError) as exc_info:
            await delete_llm_config(config_id=uuid4(), db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_llm_config_active_blocked(self, db_session, founder_user):
        from app.core.exceptions import ValidationError
        from app.api.v1.endpoints.llm_config import delete_llm_config
        cfg = LLMConfig(
            name="ActiveDelete", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-key121212121212121212",
            test_model="m1", is_active=True,
        )
        db_session.add(cfg)
        await db_session.flush()

        with pytest.raises(ValidationError) as exc_info:
            await delete_llm_config(config_id=cfg.id, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_activate_config_success(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import activate_config
        cfg1 = LLMConfig(
            name="Old", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.old.com/v1", api_key="sk-key343434343434343434",
            test_model="m1", is_active=True,
        )
        cfg2 = LLMConfig(
            name="New", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.new.com/v1", api_key="sk-key565656565656565656",
            test_model="m2", is_active=False,
        )
        db_session.add_all([cfg1, cfg2])
        await db_session.flush()

        result = await activate_config(config_id=cfg2.id, db=db_session, current_user=founder_user)
        assert "已激活" in result.message
        await db_session.refresh(cfg1)
        assert cfg1.is_active is False
        await db_session.refresh(cfg2)
        assert cfg2.is_active is True

    @pytest.mark.asyncio
    async def test_activate_config_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.llm_config import activate_config
        with pytest.raises(NotFoundError) as exc_info:
            await activate_config(config_id=uuid4(), db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_test_llm_config_no_config(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        payload = LLMTestRequest()
        result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_test_llm_config_config_not_found(self, db_session, founder_user):
        from app.core.exceptions import NotFoundError
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        payload = LLMTestRequest(config_id=uuid4())
        with pytest.raises(NotFoundError) as exc_info:
            await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_test_llm_config_unsupported_protocol(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="AnthropicCfg", provider="anthropic",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.ANTHROPIC,
            base_url="https://api.anthropic.com/v1", api_key="sk-ant787878787878787878",
            test_model="claude-3", is_active=True,
        )
        db_session.add(cfg)
        await db_session.flush()

        payload = LLMTestRequest()
        result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False
        assert "暂不支持" in result.message

    @pytest.mark.asyncio
    async def test_test_llm_config_http_success(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="SuccessCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-succ909090909090909090",
            test_model="gpt-4o-mini", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "model": "gpt-4o-mini",
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = LLMTestRequest()
            result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is True
        assert result.model == "gpt-4o-mini"
        assert result.response_text == "Hello!"

    @pytest.mark.asyncio
    async def test_test_llm_config_http_error(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="ErrCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-err121212121212121212",
            test_model="gpt-4o-mini", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = LLMTestRequest()
            result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False
        assert "HTTP 401" in result.message

    @pytest.mark.asyncio
    async def test_test_llm_config_exception(self, db_session, founder_user):
        """异常时返回脱敏错误消息（不泄露内部异常详情）"""
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="ExcCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-exc343434343434343434",
            test_model="gpt-4o-mini", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        with patch("httpx.AsyncClient", side_effect=Exception("Connection refused")):
            payload = LLMTestRequest(custom_message="hello")
            result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False
        # 脱敏：对外消息不应包含内部异常详情
        assert "Connection refused" not in result.message
        assert "内部错误" in result.message

    @pytest.mark.asyncio
    async def test_test_llm_config_connect_error(self, db_session, founder_user):
        """httpx.ConnectError 应返回友好的连接失败消息"""
        import httpx
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="ConnErrCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-cerr34343434343434343",
            test_model="gpt-4o-mini", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("DNS resolution failed")):
            payload = LLMTestRequest(custom_message="hello")
            result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False
        assert "连接失败" in result.message
        assert "DNS resolution failed" not in result.message

    @pytest.mark.asyncio
    async def test_test_llm_config_completions_protocol(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="ComplCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-comp565656565656565656",
            test_model="text-davinci-003", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"text": "Hello from completions!"}],
            "model": "text-davinci-003",
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            payload = LLMTestRequest()
            result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is True
        assert result.response_text == "Hello from completions!"

    def test_mask_key_short(self):
        from app.api.v1.endpoints.llm_config import _mask_key
        assert _mask_key("short") == "***"

    def test_mask_key_long(self):
        from app.api.v1.endpoints.llm_config import _mask_key
        masked = _mask_key("sk-abcdefghij1234567890")
        assert masked.startswith("sk-abc")
        assert masked.endswith("7890")
        assert "..." in masked

    def test_mask_key_empty(self):
        from app.api.v1.endpoints.llm_config import _mask_key
        assert _mask_key("") == "***"

    def test_ssrf_blocks_private_ipv4(self):
        from app.api.v1.endpoints.llm_config import _is_ssrf_risky_url
        assert _is_ssrf_risky_url("http://192.168.1.1/admin") is True
        assert _is_ssrf_risky_url("http://10.0.0.1/internal") is True
        assert _is_ssrf_risky_url("http://172.16.0.1/x") is True

    def test_ssrf_blocks_loopback(self):
        from app.api.v1.endpoints.llm_config import _is_ssrf_risky_url
        assert _is_ssrf_risky_url("http://127.0.0.1:8080/") is True
        assert _is_ssrf_risky_url("http://localhost/") is True

    def test_ssrf_allows_public_domain(self):
        from app.api.v1.endpoints.llm_config import _is_ssrf_risky_url
        assert _is_ssrf_risky_url("https://api.openai.com/v1") is False
        assert _is_ssrf_risky_url("https://api.test.com/v1") is False

    @pytest.mark.asyncio
    async def test_test_llm_config_ssrf_blocked(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import test_llm_config
        from app.api.v1.schemas import LLMTestRequest
        cfg = LLMConfig(
            name="SsrfCfg", provider="openai_compatible",
            access_mode=AccessMode.API_ONLY, upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="http://192.168.1.100/v1", api_key="sk-ssrf909090909090909090",
            test_model="gpt-4o-mini", is_active=True, timeout_sec=10,
        )
        db_session.add(cfg)
        await db_session.flush()

        payload = LLMTestRequest()
        result = await test_llm_config(payload, db=db_session, current_user=founder_user)
        assert result.success is False
        assert "SSRF" in result.message

    @pytest.mark.asyncio
    async def test_to_response_converts_enums(self, db_session, founder_user):
        from app.api.v1.endpoints.llm_config import _to_response
        cfg = LLMConfig(
            name="ConvTest", provider="openai_compatible",
            access_mode=AccessMode.LOCAL_DEPLOY, upstream_protocol=UpstreamProtocol.COMPLETIONS,
            base_url="https://api.test.com/v1", api_key="sk-conv787878787878787878",
            test_model="m1",
        )
        db_session.add(cfg)
        await db_session.flush()
        result = _to_response(cfg)
        assert result.access_mode == "local_deploy"
        assert result.upstream_protocol == "completions"
        assert "***" not in result.api_key_masked
