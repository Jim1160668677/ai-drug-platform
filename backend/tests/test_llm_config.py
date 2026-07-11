"""LLM 配置端点测试"""
import pytest


@pytest.mark.asyncio
async def test_list_llm_configs_empty(client, auth_headers):
    """空列表"""
    resp = await client.get("/api/v1/llm-configs", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_create_llm_config(client, auth_headers):
    """创建 LLM 配置"""
    resp = await client.post("/api/v1/llm-configs", json={
        "name": "TestLLM",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890abcdef",
        "test_model": "gpt-4o-mini",
        "fast_model": "gpt-4o-mini",
        "deep_model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 2000,
        "timeout_sec": 60,
        "is_active": True,
    }, headers=auth_headers)
    assert resp.status_code == 200, f"创建失败: {resp.text}"
    data = resp.json()
    assert data["name"] == "TestLLM"
    assert data["is_active"] is True
    # API key 必须脱敏
    assert "sk-test-1234567890abcdef" not in data["api_key_masked"]
    assert data["api_key_masked"].endswith("cdef")


@pytest.mark.asyncio
async def test_create_duplicate_name(client, auth_headers):
    """名称唯一性"""
    payload = {
        "name": "DupLLM",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890abcdef",
        "test_model": "gpt-4o-mini",
    }
    await client.post("/api/v1/llm-configs", json=payload, headers=auth_headers)
    resp = await client.post("/api/v1/llm-configs", json=payload, headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_active_config(client, auth_headers):
    """获取激活配置"""
    # 先创建一个激活配置
    await client.post("/api/v1/llm-configs", json={
        "name": "ActiveLLM",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890abcdef",
        "test_model": "gpt-4o-mini",
        "is_active": True,
    }, headers=auth_headers)

    resp = await client.get("/api/v1/llm-configs/active", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["name"] == "ActiveLLM"


@pytest.mark.asyncio
async def test_activate_config(client, auth_headers):
    """激活配置互斥"""
    # 创建两个配置
    r1 = await client.post("/api/v1/llm-configs", json={
        "name": "LLM-A",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.a.com/v1",
        "api_key": "sk-aaaaaaaaaaaaaaaaaaaa",
        "test_model": "a-model",
        "is_active": True,
    }, headers=auth_headers)
    a_id = r1.json()["id"]

    r2 = await client.post("/api/v1/llm-configs", json={
        "name": "LLM-B",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.b.com/v1",
        "api_key": "sk-bbbbbbbbbbbbbbbbbbbb",
        "test_model": "b-model",
        "is_active": False,
    }, headers=auth_headers)
    b_id = r2.json()["id"]

    # 激活 B
    resp = await client.post(f"/api/v1/llm-configs/{b_id}/activate", headers=auth_headers)
    assert resp.status_code == 200

    # A 应该不再激活
    resp = await client.get("/api/v1/llm-configs/active", headers=auth_headers)
    assert resp.json()["data"]["name"] == "LLM-B"


@pytest.mark.asyncio
async def test_delete_active_config_blocked(client, auth_headers):
    """不能删除激活中的配置"""
    r = await client.post("/api/v1/llm-configs", json={
        "name": "ActiveForDelete",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890abcdef",
        "test_model": "gpt-4o-mini",
        "is_active": True,
    }, headers=auth_headers)
    cfg_id = r.json()["id"]

    resp = await client.delete(f"/api/v1/llm-configs/{cfg_id}", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_config(client, auth_headers):
    """更新配置"""
    r = await client.post("/api/v1/llm-configs", json={
        "name": "UpdateLLM",
        "provider": "openai_compatible",
        "access_mode": "api_only",
        "upstream_protocol": "chat_completions",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234567890abcdef",
        "test_model": "gpt-4o-mini",
    }, headers=auth_headers)
    cfg_id = r.json()["id"]

    resp = await client.put(f"/api/v1/llm-configs/{cfg_id}", json={
        "description": "updated description",
        "temperature": 0.5,
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated description"
    assert resp.json()["temperature"] == 0.5


@pytest.mark.asyncio
async def test_researcher_cannot_create(client, auth_headers):
    """研究员不能创建 — 但测试用例里 auth_headers 是 founder，
    这里测空字段校验"""
    resp = await client.post("/api/v1/llm-configs", json={
        "name": "NoKey",
        "base_url": "https://api.example.com/v1",
        # 缺 api_key 和 test_model
    }, headers=auth_headers)
    # P0.2 改造后 RequestValidationError 被映射到 400 VALIDATION_ERROR
    assert resp.status_code == 400
