"""用户级 LLM 路由器单元测试

覆盖：
- UserLLMRouter.create() — 加载激活配置 / 指定 config_id / 无配置降级
- UserLLMRouter.complete() — 调用 LLM / 异常降级
- _mask_key() — API key 脱敏
- _is_ssrf_risky_url() — SSRF 防护
- test_user_llm_connectivity() — 连通性测试（mock httpx）

设计原则：
- 不调真实 LLM API（用 MockLLMClient 或 monkeypatch）
- 加密往返测试（Fernet encrypt/decrypt）
"""
import os
import sys
import uuid as uuid_mod

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    personal_genome, snp_locus, trait, prompt_template, user_llm_config, llm_config,
)
from app.core.security import hash_password, UserRole  # noqa: E402
from app.core.encryption import encrypt, decrypt  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_llm_config import UserLLMConfig  # noqa: E402

from app.services.llm.user_router import (  # noqa: E402
    UserLLMRouter, _mask_key, _is_ssrf_risky_url,
)
# 别名导入避免 pytest 把 test_* 函数当作测试用例收集（ERROR）
from app.services.llm.user_router import (  # noqa: E402
    test_user_llm_connectivity as _check_connectivity,
)


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture
async def db_session():
    """SQLite 内存数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
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
async def test_user(db_session: AsyncSession):
    """测试用户"""
    user = User(
        id=uuid_mod.uuid4(),
        email="llm-test@ai-drug.com",
        name="LLM Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def active_config(db_session: AsyncSession, test_user):
    """激活的用户 LLM 配置"""
    config = UserLLMConfig(
        owner_id=test_user.id,
        name="我的豆包配置",
        provider="doubao",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=encrypt("sk-test-api-key-1234567890abcdef"),
        model_name="doubao-pro-4k",
        temperature=0.7,
        max_tokens=2000,
        timeout_sec=60,
        is_active=True,
    )
    db_session.add(config)
    await db_session.flush()
    return config


@pytest_asyncio.fixture
async def inactive_config(db_session: AsyncSession, test_user):
    """未激活的用户 LLM 配置"""
    config = UserLLMConfig(
        owner_id=test_user.id,
        name="我的 DeepSeek 配置",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key=encrypt("sk-deepseek-key-1234567890abcdef"),
        model_name="deepseek-chat",
        temperature=0.5,
        max_tokens=1000,
        timeout_sec=30,
        is_active=False,
    )
    db_session.add(config)
    await db_session.flush()
    return config


# ============================================================
# _mask_key 测试
# ============================================================

class TestMaskKey:
    """API key 脱敏"""

    def test_mask_normal_key(self):
        """正常 key 脱敏"""
        key = "sk-1234567890abcdef"
        masked = _mask_key(key)
        assert masked == "sk-123...cdef"
        assert "***" not in masked

    def test_mask_short_key(self):
        """短 key 返回 ***"""
        assert _mask_key("short") == "***"
        assert _mask_key("12345") == "***"

    def test_mask_empty_key(self):
        """空 key 返回 ***"""
        assert _mask_key("") == "***"
        assert _mask_key(None) == "***"

    def test_mask_exact_12_chars(self):
        """12 字符 key 边界"""
        key = "123456789012"
        masked = _mask_key(key)
        assert masked == "123456...9012"


# ============================================================
# _is_ssrf_risky_url 测试
# ============================================================

class TestSsrfCheck:
    """SSRF 防护"""

    def test_ssrf_localhost(self):
        """localhost 拒绝"""
        assert _is_ssrf_risky_url("http://localhost/api") is True
        assert _is_ssrf_risky_url("http://127.0.0.1/api") is True

    def test_ssrf_private_ip(self):
        """内网 IP 拒绝"""
        assert _is_ssrf_risky_url("http://10.0.0.1/api") is True
        assert _is_ssrf_risky_url("http://192.168.1.1/api") is True
        assert _is_ssrf_risky_url("http://172.16.0.1/api") is True

    def test_ssrf_public_url(self):
        """公网 URL 通过"""
        assert _is_ssrf_risky_url("https://api.deepseek.com/v1") is False
        assert _is_ssrf_risky_url("https://ark.cn-beijing.volces.com/api/v3") is False

    def test_ssrf_invalid_url(self):
        """无效 URL 视为风险"""
        assert _is_ssrf_risky_url("not-a-url") is True
        assert _is_ssrf_risky_url("") is True


# ============================================================
# 加密往返测试
# ============================================================

class TestEncryption:
    """Fernet 加密往返"""

    def test_encrypt_decrypt_roundtrip(self):
        """加密解密往返"""
        original = "sk-my-secret-api-key-1234567890"
        encrypted = encrypt(original)
        assert encrypted != original
        assert encrypted.startswith("enc:") or len(encrypted) > len(original)
        decrypted = decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_different_each_time(self):
        """每次加密结果不同（Fernet 随机 IV）"""
        key = "sk-same-key"
        enc1 = encrypt(key)
        enc2 = encrypt(key)
        assert enc1 != enc2  # IV 不同
        assert decrypt(enc1) == decrypt(enc2) == key


# ============================================================
# UserLLMRouter.create 测试
# ============================================================

class TestUserLLMRouterCreate:
    """构造器测试"""

    @pytest.mark.asyncio
    async def test_create_with_active_config(self, db_session, test_user, active_config):
        """加载激活配置"""
        router = await UserLLMRouter.create(db_session, test_user)
        assert router.user_config is not None
        assert router.user_config.id == active_config.id
        assert router.active_model_name == "doubao-pro-4k"
        assert router.active_provider == "doubao"

    @pytest.mark.asyncio
    async def test_create_with_specific_config_id(
        self, db_session, test_user, active_config, inactive_config
    ):
        """指定 config_id 加载未激活配置"""
        router = await UserLLMRouter.create(
            db_session, test_user, user_llm_config_id=str(inactive_config.id)
        )
        assert router.user_config is not None
        assert router.user_config.id == inactive_config.id
        assert router.active_model_name == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_create_no_user_config(self, db_session, test_user):
        """无用户配置 → user_config 为 None，降级到系统"""
        router = await UserLLMRouter.create(db_session, test_user)
        assert router.user_config is None
        # Mock 模式下系统客户端应为 MockLLMClient
        assert router.system_llm_client is not None
        assert router.active_model_name in ("mock", "agnes-2.0-flash", "agnes-2.5-flash")  # 视 settings 而定

    @pytest.mark.asyncio
    async def test_create_config_not_found(self, db_session, test_user):
        """指定不存在的 config_id 抛 NotFoundError"""
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError, match="用户 LLM 配置不存在"):
            await UserLLMRouter.create(
                db_session, test_user,
                user_llm_config_id=str(uuid_mod.uuid4())
            )

    @pytest.mark.asyncio
    async def test_create_with_other_user_config(
        self, db_session, test_user, active_config
    ):
        """用户不能加载他人的配置（owner_id 过滤）"""
        # 创建另一个用户
        other_user = User(
            id=uuid_mod.uuid4(),
            email="other@ai-drug.com",
            name="Other",
            hashed_password=hash_password("pass"),
            role=UserRole.RESEARCHER,
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await UserLLMRouter.create(
                db_session, other_user,
                user_llm_config_id=str(active_config.id)
            )


# ============================================================
# UserLLMRouter.complete 测试
# ============================================================

class TestUserLLMRouterComplete:
    """complete() 方法测试"""

    @pytest.mark.asyncio
    async def test_complete_with_mock_system(self, db_session, test_user):
        """无用户配置 → 系统 Mock LLM 调用"""
        router = await UserLLMRouter.create(db_session, test_user)
        result = await router.complete("你好", tier="fast_screen")
        assert "content" in result
        assert result["provider"] in ("system_default", "mock")
        assert result["model"] is not None

    @pytest.mark.asyncio
    async def test_complete_system_failure(self, db_session, test_user, monkeypatch):
        """系统 LLM 调用失败 → 返回错误信息"""
        router = await UserLLMRouter.create(db_session, test_user)

        # Mock 系统 LLM 抛异常
        async def failing_chat(*args, **kwargs):
            raise RuntimeError("LLM 服务不可用")

        if router.system_llm_client:
            monkeypatch.setattr(router.system_llm_client, "chat", failing_chat)

        result = await router.complete("test", bypass_guardrail=True)
        assert "error" in result or "失败" in result.get("content", "")

    @pytest.mark.asyncio
    async def test_complete_empty_prompt(self, db_session, test_user):
        """空 prompt 通过护栏"""
        router = await UserLLMRouter.create(db_session, test_user)
        result = await router.complete("")
        assert "content" in result


# ============================================================
# test_user_llm_connectivity 测试
# ============================================================

class TestConnectivity:
    """连通性测试"""

    @pytest.mark.asyncio
    async def test_connectivity_ssrf_blocked(self, active_config, monkeypatch):
        """SSRF 风险 URL → 拒绝测试"""
        # 修改 base_url 为 localhost
        active_config.base_url = "http://localhost/api"
        result = await _check_connectivity(active_config, "ping")
        assert result["success"] is False
        assert "SSRF" in result["message"] or "内网" in result["message"]

    @pytest.mark.asyncio
    async def test_connectivity_success(self, active_config, monkeypatch):
        """连通成功"""
        # Mock httpx.AsyncClient
        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "model": "doubao-pro-4k",
                    "choices": [{"message": {"content": "pong"}}],
                }

        class MockClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, *args, **kwargs):
                return MockResponse()

        import app.services.llm.user_router as router_module
        monkeypatch.setattr(router_module.httpx, "AsyncClient", MockClient)

        result = await _check_connectivity(active_config, "ping")
        assert result["success"] is True
        assert "连接成功" in result["message"]
        assert result["model"] == "doubao-pro-4k"
        assert result["response_text"] == "pong"

    @pytest.mark.asyncio
    async def test_connectivity_http_error(self, active_config, monkeypatch):
        """HTTP 错误状态码"""
        class MockResponse:
            status_code = 401
            def json(self):
                return {}

        class MockClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, *args, **kwargs):
                return MockResponse()

        import app.services.llm.user_router as router_module
        monkeypatch.setattr(router_module.httpx, "AsyncClient", MockClient)

        result = await _check_connectivity(active_config)
        assert result["success"] is False
        assert "401" in result["message"]

    @pytest.mark.asyncio
    async def test_connectivity_timeout(self, active_config, monkeypatch):
        """超时"""
        import httpx

        class MockClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, *args, **kwargs):
                raise httpx.TimeoutException("timeout")

        import app.services.llm.user_router as router_module
        monkeypatch.setattr(router_module.httpx, "AsyncClient", MockClient)

        result = await _check_connectivity(active_config)
        assert result["success"] is False
        assert "超时" in result["message"]
