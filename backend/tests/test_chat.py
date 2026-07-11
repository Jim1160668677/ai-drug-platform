"""AI 问答模块测试"""
import pytest


@pytest.mark.asyncio
async def test_chat_fast_screen(client, auth_headers):
    """测试快速筛查问答"""
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "EGFR T790M 耐药机制是什么？",
            "tier": "fast_screen",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert data["tier"] == "fast_screen"
    assert "cost_usd" in data
    assert "duration_sec" in data
    assert "model" in data
    assert len(data["answer"]) > 0


@pytest.mark.asyncio
async def test_chat_deep_insight(client, auth_headers):
    """测试深度洞察问答"""
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "B7H3 在肿瘤免疫治疗中的作用",
            "tier": "deep_insight",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert data["tier"] == "deep_insight"


@pytest.mark.asyncio
async def test_chat_general(client, auth_headers):
    """测试通用问题（无关键词匹配）"""
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "请介绍一下精准医学的基本概念",
            "tier": "fast_screen",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["answer"]) > 0


@pytest.mark.asyncio
async def test_tiers(client, auth_headers):
    """测试分析层级说明"""
    resp = await client.get("/api/v1/chat/tiers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "tiers" in data
    assert len(data["tiers"]) == 2
    tiers = {t["name"] for t in data["tiers"]}
    assert "fast_screen" in tiers
    assert "deep_insight" in tiers
