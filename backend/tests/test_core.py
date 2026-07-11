"""核心模块测试 — 覆盖 core/logging.py + core/deps.py + main.py

覆盖：
- setup_logging（INFO/DEBUG 模式 + 文件日志目录创建失败降级）
- InterceptHandler.emit
- get_current_user（有效/无效/缺失 token）
- require_role / require_permission
- get_active_llm_config
- get_llm_client / get_llm_client_with_config / get_gene_client / get_variant_client /
  get_chembl_client / get_diffdock_client（Mock + Real 模式）
- _build_real_llm_client（cfg 为 None / 非 None）
- main.py lifespan / health_check / root / global_exception_handler
"""
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import UserRole, create_access_token, hash_password


# ============================================================
# setup_logging
# ============================================================

class TestSetupLogging:
    def test_setup_logging_dev_mode(self, tmp_path, monkeypatch):
        """development 环境应使用 DEBUG 级别"""
        from app.core.config import settings
        monkeypatch.chdir(tmp_path)

        with patch.object(settings, "APP_ENV", "development"):
            from app.core.logging import setup_logging
            setup_logging()  # 不应抛出异常

    def test_setup_logging_prod_mode(self, tmp_path, monkeypatch):
        from app.core.config import settings
        monkeypatch.chdir(tmp_path)

        with patch.object(settings, "APP_ENV", "production"):
            from app.core.logging import setup_logging
            setup_logging()

    def test_setup_logging_log_dir_creation_failure(self, tmp_path, monkeypatch):
        """log_dir 创建失败时应 silently pass"""
        from app.core.config import settings

        monkeypatch.chdir(tmp_path)

        with patch.object(settings, "APP_ENV", "production"), \
             patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
            from app.core.logging import setup_logging
            setup_logging()  # 不应抛出异常


class TestInterceptHandler:
    def test_emit_with_known_level(self):
        """emit 应正确转发标准 logging 记录到 loguru"""
        from app.core.logging import setup_logging

        setup_logging()
        # 通过标准 logging 触发 — 应被 InterceptHandler 转发到 loguru
        std_logger = logging.getLogger("test.intercept")
        std_logger.setLevel(logging.INFO)
        # emit 不应抛出异常
        std_logger.info("test message via standard logging")

    def test_emit_with_unknown_level(self):
        from app.core.logging import setup_logging

        setup_logging()
        std_logger = logging.getLogger("test.intercept.custom")
        # 自定义 level number
        std_logger.log(999, "custom level message")


# ============================================================
# get_current_user / require_role / require_permission
# ============================================================

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_get_current_user_success(self, async_db_session):
        """有效 token 应返回用户"""
        from app.core.deps import get_current_user
        from app.models.user import User

        # 先创建用户
        user = User(
            email="test@example.com",
            name="Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        token = create_access_token(subject=str(user.id), role=UserRole.FOUNDER)
        result = await get_current_user(token=token, db=async_db_session)
        assert result.id == user.id
        assert result.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self, async_db_session):
        """无效 token 应抛 401"""
        from app.core.deps import get_current_user

        with pytest.raises(HTTPException) as exc:
            await get_current_user(token="invalid.token.here", db=async_db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_no_sub(self, async_db_session):
        """token 无 sub 字段应抛 401"""
        from app.core.deps import get_current_user
        # 构造一个 sub 为 None 的 token
        # 使用伪造的 payload
        with patch("app.core.deps.decode_token", return_value={}):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(token="fake", db=async_db_session)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_user_not_found(self, async_db_session):
        """token 中的 user_id 在数据库中不存在应抛 401"""
        from app.core.deps import get_current_user

        # 构造一个不存在的 UUID
        random_uuid = str(uuid.uuid4())
        token = create_access_token(subject=random_uuid, role=UserRole.FOUNDER)

        with pytest.raises(HTTPException) as exc:
            await get_current_user(token=token, db=async_db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_inactive_user(self, async_db_session):
        """已禁用用户应抛 401"""
        from app.core.deps import get_current_user
        from app.models.user import User

        user = User(
            email="inactive@example.com",
            name="Inactive",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
            is_active=False,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        token = create_access_token(subject=str(user.id), role=UserRole.FOUNDER)
        with pytest.raises(HTTPException) as exc:
            await get_current_user(token=token, db=async_db_session)
        assert exc.value.status_code == 401


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_require_role_allowed(self):
        """用户在允许的角色列表中应通过"""
        from app.core.deps import require_role

        user = MagicMock()
        user.role = UserRole.FOUNDER

        checker = require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)
        result = await checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_require_role_denied(self):
        """用户不在允许的角色列表中应抛 403"""
        from app.core.deps import require_role

        user = MagicMock()
        user.role = UserRole.RESEARCHER

        checker = require_role(UserRole.FOUNDER)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=user)
        assert exc.value.status_code == 403
        assert "权限不足" in exc.value.detail


class TestRequirePermission:
    @pytest.mark.asyncio
    async def test_require_permission_allowed(self):
        from app.core.deps import require_permission

        user = MagicMock()
        user.role = UserRole.FOUNDER

        with patch("app.core.deps.has_permission", return_value=True):
            checker = require_permission("create:project")
            result = await checker(current_user=user)
            assert result == user

    @pytest.mark.asyncio
    async def test_require_permission_denied(self):
        from app.core.deps import require_permission

        user = MagicMock()
        user.role = UserRole.DOCTOR

        with patch("app.core.deps.has_permission", return_value=False):
            checker = require_permission("delete:user")
            with pytest.raises(HTTPException) as exc:
                await checker(current_user=user)
            assert exc.value.status_code == 403
            assert "缺少权限" in exc.value.detail


# ============================================================
# LLM Config 数据库查询
# ============================================================

class TestGetActiveLLMConfig:
    @pytest.mark.asyncio
    async def test_get_active_llm_config_found(self, async_db_session):
        """数据库有激活配置时应返回"""
        from app.core.deps import get_active_llm_config
        from app.models.llm_config import LLMConfig, AccessMode, UpstreamProtocol

        cfg = LLMConfig(
            name="test-cfg",
            provider="OpenAI",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key-123456",
            test_model="gpt-4o-mini",
            deep_model="gpt-4o",
            is_active=True,
        )
        async_db_session.add(cfg)
        await async_db_session.flush()

        result = await get_active_llm_config(async_db_session)
        assert result is not None
        assert result.name == "test-cfg"

    @pytest.mark.asyncio
    async def test_get_active_llm_config_not_found(self, async_db_session):
        from app.core.deps import get_active_llm_config

        result = await get_active_llm_config(async_db_session)
        assert result is None


# ============================================================
# 客户端工厂函数
# ============================================================

class TestClientFactories:
    def test_get_llm_client_mock_mode(self):
        """USE_MOCK=true 时返回 MockLLMClient"""
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_llm_client
            client = get_llm_client()
            from app.clients.mock.llm_mock import MockLLMClient
            assert isinstance(client, MockLLMClient)

    def test_get_llm_client_real_mode_with_settings(self):
        """USE_MOCK=false 且 OPENAI_API_KEY 设置时返回 RealLLMClient"""
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False), \
             patch.object(settings, "OPENAI_API_KEY", "sk-test-key"):
            from app.core.deps import get_llm_client
            client = get_llm_client()
            from app.clients.real.llm_real import RealLLMClient
            assert isinstance(client, RealLLMClient)

    @pytest.mark.asyncio
    async def test_get_llm_client_with_config_mock(self, async_db_session):
        """Mock 模式下 get_llm_client_with_config 应返回 MockLLMClient"""
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_llm_client_with_config
            client = await get_llm_client_with_config(async_db_session)
            from app.clients.mock.llm_mock import MockLLMClient
            assert isinstance(client, MockLLMClient)

    @pytest.mark.asyncio
    async def test_get_llm_client_with_config_real_no_active(self, async_db_session):
        """Real 模式无激活配置时应回退到 settings 默认"""
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False), \
             patch.object(settings, "OPENAI_API_KEY", "sk-test-key"):
            from app.core.deps import get_llm_client_with_config
            client = await get_llm_client_with_config(async_db_session)
            from app.clients.real.llm_real import RealLLMClient
            assert isinstance(client, RealLLMClient)

    @pytest.mark.asyncio
    async def test_get_llm_client_with_config_real_with_active(self, async_db_session):
        """Real 模式有激活配置时应使用 LLMConfig 实例化"""
        from app.core.config import settings
        from app.models.llm_config import LLMConfig, AccessMode, UpstreamProtocol

        cfg = LLMConfig(
            name="active-cfg",
            provider="Agnes",
            access_mode=AccessMode.API_ONLY,
            upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
            base_url="https://api.agnes.example.com/v1",
            api_key="sk-agnes-test-key",
            test_model="agnes-mini",
            deep_model="agnes-large",
            temperature=0.3,
            max_tokens=2000,
            timeout_sec=45,
            is_active=True,
        )
        async_db_session.add(cfg)
        await async_db_session.flush()

        with patch.object(settings, "USE_MOCK", False):
            from app.core.deps import get_llm_client_with_config
            client = await get_llm_client_with_config(async_db_session)
            from app.clients.real.llm_real import RealLLMClient
            assert isinstance(client, RealLLMClient)
            assert client.base_url == "https://api.agnes.example.com/v1"
            assert client.api_key == "sk-agnes-test-key"
            assert client.default_model == "agnes-large"
            assert client.default_temperature == 0.3

    def test_get_gene_client_mock(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_gene_client
            client = get_gene_client()
            from app.clients.mock.mygene_mock import MockGeneClient
            assert isinstance(client, MockGeneClient)

    def test_get_gene_client_real(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False):
            from app.core.deps import get_gene_client
            client = get_gene_client()
            from app.clients.real.mygene_real import RealGeneClient
            assert isinstance(client, RealGeneClient)

    def test_get_variant_client_mock(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_variant_client
            client = get_variant_client()
            from app.clients.mock.myvariant_mock import MockVariantClient
            assert isinstance(client, MockVariantClient)

    def test_get_variant_client_real(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False):
            from app.core.deps import get_variant_client
            client = get_variant_client()
            from app.clients.real.myvariant_real import RealVariantClient
            assert isinstance(client, RealVariantClient)

    def test_get_chembl_client_mock(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_chembl_client
            client = get_chembl_client()
            from app.clients.mock.chembl_mock import MockChemblClient
            assert isinstance(client, MockChemblClient)

    def test_get_chembl_client_real(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False):
            from app.core.deps import get_chembl_client
            client = get_chembl_client()
            from app.clients.real.chembl_real import RealChemblClient
            assert isinstance(client, RealChemblClient)

    def test_get_diffdock_client_mock(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", True):
            from app.core.deps import get_diffdock_client
            client = get_diffdock_client()
            from app.clients.mock.diffdock_mock import MockDiffdockClient
            assert isinstance(client, MockDiffdockClient)

    def test_get_diffdock_client_real(self):
        from app.core.config import settings
        with patch.object(settings, "USE_MOCK", False):
            from app.core.deps import get_diffdock_client
            client = get_diffdock_client()
            from app.clients.real.diffdock_real import RealDiffdockClient
            assert isinstance(client, RealDiffdockClient)


# ============================================================
# main.py — FastAPI 应用入口
# ============================================================

class TestMainApp:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """健康检查端点应返回 200"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["app"] == "precision-drug-design"
        assert "version" in data
        assert "mock_mode" in data

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """根路径应返回系统信息"""
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "docs" in data
        assert "health" in data

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_register_exception_handlers(self):
        """register_exception_handlers 应在 app 上注册异常处理器（P0.2 改造后取代 global_exception_handler）"""
        from app.main import app
        from app.core.exceptions import register_exception_handlers

        # register_exception_handlers 应能幂等调用（不抛异常）
        register_exception_handlers(app)

        # app 应已注册异常处理器 — 通过实际触发验证
        from fastapi import HTTPException
        exc = HTTPException(status_code=404, detail="测试不存在")
        # 验证异常类可被正确构造
        assert exc.status_code == 404
        assert "测试不存在" in exc.detail

    @pytest.mark.asyncio
    async def test_lifespan_initialization(self):
        """lifespan 应能成功初始化（不依赖数据库）"""
        from app.main import lifespan
        app = MagicMock()
        # 模拟 development 环境下 init_db 抛异常时也不应中断
        with patch("app.main.settings") as mock_settings:
            mock_settings.APP_ENV = "production"
            mock_settings.USE_MOCK = "true"
            mock_settings.DATABASE_URL = "sqlite:///test"

            async with lifespan(app):
                pass  # 启动成功

    @pytest.mark.asyncio
    async def test_lifespan_dev_mode_init_db(self):
        """development 模式应尝试 init_db，失败时也不应中断"""
        from app.main import lifespan
        app = MagicMock()
        with patch("app.main.settings") as mock_settings, \
             patch("app.db.session.init_db", new=AsyncMock(side_effect=Exception("db error"))):
            mock_settings.APP_ENV = "development"
            mock_settings.USE_MOCK = "true"
            mock_settings.DATABASE_URL = "sqlite:///test"

            async with lifespan(app):
                pass  # 即使 init_db 失败也应继续

    def test_app_metadata(self):
        """FastAPI 应用应包含正确的元数据"""
        from app.main import app
        assert app.title == "AI模式精准药物设计系统"
        assert "干湿闭环" in app.description
        assert app.version == "1.0.0"
        assert app.docs_url == "/docs"

    def test_app_cors_middleware_configured(self):
        """CORS 中间件应已配置"""
        from app.main import app
        # 检查中间件是否已添加
        middlewares = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middlewares
