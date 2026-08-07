"""会话管理器测试"""
import pytest
from uuid import uuid4

from app.services.agent.session import SessionManager


@pytest.mark.asyncio
async def test_create_session(async_db_session, test_user):
    """创建会话"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(
        user_id=test_user.id,
        title="测试会话",
    )
    assert session.id is not None
    assert session.user_id == test_user.id
    assert session.title == "测试会话"
    assert session.status == "active"
    assert session.context == {"messages": [], "summary": None, "token_count": 0}
    assert session.message_count == 0


@pytest.mark.asyncio
async def test_create_session_default_title(async_db_session, test_user):
    """无标题时使用默认值"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)
    assert session.title == "新会话"


@pytest.mark.asyncio
async def test_get_session_owner_check(async_db_session, test_user, researcher_user):
    """归属校验：其他用户拿不到会话"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id, title="A 的会话")

    # 正确归属
    got = await mgr.get(session.id, test_user.id)
    assert got is not None
    assert got.title == "A 的会话"

    # 越权：返回 None 而非抛异常
    got = await mgr.get(session.id, researcher_user.id)
    assert got is None


@pytest.mark.asyncio
async def test_get_nonexistent_session(async_db_session, test_user):
    """获取不存在的会话返回 None"""
    mgr = SessionManager(async_db_session)
    got = await mgr.get(uuid4(), test_user.id)
    assert got is None


@pytest.mark.asyncio
async def test_list_sessions(async_db_session, test_user, researcher_user):
    """列出用户会话（仅自己的）"""
    mgr = SessionManager(async_db_session)
    await mgr.create(user_id=test_user.id, title="会话1")
    await mgr.create(user_id=test_user.id, title="会话2")
    await mgr.create(user_id=researcher_user.id, title="其他用户的会话")

    items, total = await mgr.list_sessions(user_id=test_user.id)
    assert total == 2
    assert len(items) == 2
    titles = [i.title for i in items]
    assert "会话1" in titles
    assert "会话2" in titles


@pytest.mark.asyncio
async def test_list_sessions_pagination(async_db_session, test_user):
    """分页"""
    mgr = SessionManager(async_db_session)
    for i in range(5):
        await mgr.create(user_id=test_user.id, title=f"会话{i}")

    items, total = await mgr.list_sessions(user_id=test_user.id, page=1, page_size=2)
    assert total == 5
    assert len(items) == 2

    items2, _ = await mgr.list_sessions(user_id=test_user.id, page=2, page_size=2)
    assert len(items2) == 2
    # 不同页不应有重复
    ids_page1 = {i.id for i in items}
    ids_page2 = {i.id for i in items2}
    assert not (ids_page1 & ids_page2)


@pytest.mark.asyncio
async def test_archive_session(async_db_session, test_user):
    """归档会话"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id, title="待归档")
    ok = await mgr.archive(session.id, test_user.id)
    assert ok is True

    # 归档后不在默认列表中
    items, total = await mgr.list_sessions(user_id=test_user.id)
    assert total == 0

    # include_archived=True 时能看到
    items2, total2 = await mgr.list_sessions(
        user_id=test_user.id, include_archived=True
    )
    assert total2 == 1


@pytest.mark.asyncio
async def test_archive_nonexistent(async_db_session, test_user):
    """归档不存在的会话返回 False"""
    mgr = SessionManager(async_db_session)
    ok = await mgr.archive(uuid4(), test_user.id)
    assert ok is False


@pytest.mark.asyncio
async def test_append_message(async_db_session, test_user):
    """追加消息"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)

    await mgr.append_message(session.id, role="user", content="你好")
    await mgr.append_message(
        session.id,
        role="assistant",
        content="你好，有什么可以帮你？",
        tool_calls=[{"tool": "t", "args": {}}],
    )

    ctx = await mgr.get_context(session.id)
    assert len(ctx["messages"]) == 2
    assert ctx["messages"][0]["role"] == "user"
    assert ctx["messages"][0]["content"] == "你好"
    assert ctx["messages"][1]["role"] == "assistant"
    assert ctx["messages"][1]["tool_calls"] == [{"tool": "t", "args": {}}]
    assert ctx["token_count"] > 0


@pytest.mark.asyncio
async def test_append_message_truncation(async_db_session, test_user):
    """超长消息被截断"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)
    long_content = "x" * 10000
    await mgr.append_message(session.id, role="user", content=long_content)

    ctx = await mgr.get_context(session.id)
    msg = ctx["messages"][0]
    assert len(msg["content"]) <= mgr.MAX_MESSAGE_CONTENT_LEN + 20  # 含 [truncated] 后缀
    assert msg["content"].endswith("[truncated]")


@pytest.mark.asyncio
async def test_maybe_compress_no_trigger(async_db_session, test_user):
    """token 数未达阈值时不压缩"""
    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)
    await mgr.append_message(session.id, role="user", content="短消息")

    triggered = await mgr.maybe_compress(session.id, llm_router=None)
    assert triggered is False


@pytest.mark.asyncio
async def test_maybe_compress_triggers_truncation(async_db_session, test_user, monkeypatch):
    """无 LLM 时超阈值降级为截断"""
    from app.core.config import settings
    # 降低阈值使 10 条消息能触发压缩（默认 6000，10 条 ~1005 字符消息 token_count ≈ 2512）
    monkeypatch.setattr(settings, "AGENT_CONTEXT_COMPRESS_THRESHOLD", 1000)

    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)

    # 写入多条消息使 token_count 超阈值
    for i in range(10):
        await mgr.append_message(
            session.id, role="user", content=f"消息 {i} " + "x" * 1000
        )

    triggered = await mgr.maybe_compress(session.id, llm_router=None)
    assert triggered is True

    ctx = await mgr.get_context(session.id)
    # 截断后保留首 2 条 + 末 4 条
    assert len(ctx["messages"]) <= 6
    assert ctx["summary"] is not None


@pytest.mark.asyncio
async def test_maybe_compress_with_llm(async_db_session, test_user, monkeypatch):
    """有 LLM 时调用 LLM 生成摘要"""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.config import settings
    # 降低阈值使 10 条消息能触发压缩
    monkeypatch.setattr(settings, "AGENT_CONTEXT_COMPRESS_THRESHOLD", 1000)

    llm_router = MagicMock()
    llm_router.quick = AsyncMock(return_value={"content": "这是对话摘要"})

    mgr = SessionManager(async_db_session)
    session = await mgr.create(user_id=test_user.id)
    for i in range(10):
        await mgr.append_message(
            session.id, role="user", content=f"消息 {i} " + "x" * 1000
        )

    triggered = await mgr.maybe_compress(session.id, llm_router=llm_router)
    assert triggered is True

    ctx = await mgr.get_context(session.id)
    assert ctx["summary"] == "这是对话摘要"
    # 保留最近 4 条
    assert len(ctx["messages"]) == 4
