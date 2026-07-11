"""认证模块测试"""
import pytest

from app.core.security import (
    UserRole,
    create_access_token,
    create_refresh_token,
    decode_token,
)


@pytest.mark.asyncio
async def test_register(client):
    """测试用户注册"""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser@ai-drug.com",
        "name": "New User",
        "password": "password123",
        "role": "researcher",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "newuser@ai-drug.com"
    assert data["name"] == "New User"
    assert data["role"] == "researcher"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_login(client):
    """测试用户登录"""
    # 先注册
    await client.post("/api/v1/auth/register", json={
        "email": "login@ai-drug.com",
        "name": "Login User",
        "password": "pass123",
        "role": "researcher",
    })
    # 登录
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@ai-drug.com", "password": "pass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["access_token"] != data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["email"] == "login@ai-drug.com"


@pytest.mark.asyncio
async def test_login_tokens_carry_correct_type_claim(client):
    """登录返回的 access/refresh token 必须携带正确的 type 声明"""
    await client.post("/api/v1/auth/register", json={
        "email": "typeclaim@ai-drug.com",
        "name": "Type Claim",
        "password": "pass123",
        "role": "researcher",
    })
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "typeclaim@ai-drug.com", "password": "pass123"},
    )
    data = resp.json()
    access_payload = decode_token(data["access_token"])
    refresh_payload = decode_token(data["refresh_token"])
    assert access_payload["type"] == "access"
    assert refresh_payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_token_returns_new_access_token(client):
    """/auth/refresh 接受 refresh token 返回新 access token"""
    await client.post("/api/v1/auth/register", json={
        "email": "refresh@ai-drug.com",
        "name": "Refresh User",
        "password": "pass123",
        "role": "researcher",
    })
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "refresh@ai-drug.com", "password": "pass123"},
    )
    refresh_jwt = login_resp.json()["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_jwt},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    new_access = body["data"]["access_token"]
    assert new_access != refresh_jwt
    payload = decode_token(new_access)
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client):
    """/auth/refresh 必须拒绝 access token（type=access）作为 refresh token"""
    await client.post("/api/v1/auth/register", json={
        "email": "reject-access@ai-drug.com",
        "name": "Reject Access",
        "password": "pass123",
        "role": "researcher",
    })
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "reject-access@ai-drug.com", "password": "pass123"},
    )
    access_jwt = login_resp.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_jwt},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_garbage_token(client):
    """/auth/refresh 拒绝无效字符串"""
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not.a.valid.jwt"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_disabled_user(client, async_db_session):
    """用户被禁用后，即便 refresh token 未过期也不能换取新 access token"""
    from app.core.security import hash_password
    from app.models.user import User

    user = User(
        email="disabled@ai-drug.com",
        name="Disabled User",
        hashed_password=hash_password("pass123"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@ai-drug.com", "password": "pass123"},
    )
    refresh_jwt = login_resp.json()["refresh_token"]

    # 禁用用户
    user.is_active = False
    await async_db_session.flush()

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_jwt},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_unit_decodes_as_refresh_type():
    """单元测试：create_refresh_token 产出 type=refresh 的 JWT"""
    token = create_refresh_token(subject="user-123", role=UserRole.FOUNDER)
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "founder"
    assert payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_access_token_unit_decodes_as_access_type():
    """单元测试：create_access_token 产出 type=access 的 JWT"""
    token = create_access_token(subject="user-456", role=UserRole.RESEARCHER)
    payload = decode_token(token)
    assert payload["sub"] == "user-456"
    assert payload["role"] == "researcher"
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_after_threshold(client):
    """登录端点限流：超过 LOGIN_RATE_LIMIT_PER_MINUTE 后返回 429"""
    from app.core.config import settings

    await client.post("/api/v1/auth/register", json={
        "email": "ratelimit@ai-drug.com",
        "name": "Rate Limit",
        "password": "pass123",
        "role": "researcher",
    })

    limit = settings.LOGIN_RATE_LIMIT_PER_MINUTE
    # 前 N 次登录应成功（200）
    for i in range(limit):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit@ai-drug.com", "password": "pass123"},
        )
        assert resp.status_code == 200, f"第 {i + 1} 次登录意外失败: {resp.status_code}"

    # 第 N+1 次应被限流
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit@ai-drug.com", "password": "pass123"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_me(client, auth_headers):
    """测试获取当前用户"""
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@ai-drug.com"


@pytest.mark.asyncio
async def test_invalid_credentials(client):
    """测试错误凭据"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@ai-drug.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_register(client):
    """测试重复注册"""
    payload = {
        "email": "dup@ai-drug.com",
        "name": "Dup User",
        "password": "pass123",
        "role": "researcher",
    }
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409  # ConflictError → 409 Conflict（统一异常体系）
