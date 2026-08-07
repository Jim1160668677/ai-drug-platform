"""Agent 会话管理器 — 上下文存储与压缩

设计来源：2026-07-18-agent-functional-design.md §1.1 / §3
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_session import AgentSession, SessionStatus

logger = logging.getLogger(__name__)


class SessionManager:
    """会话/上下文管理器

    上下文结构（存储在 AgentSession.context JSON 字段）：
    {
        "messages": [
            {"role": "user", "content": "...", "ts": "..."},
            {"role": "assistant", "content": "...", "tool_calls": [...], "ts": "..."},
            {"role": "tool", "tool": "...", "result": {...}, "ts": "..."}
        ],
        "summary": "<历史摘要（压缩后）>",
        "token_count": 1234
    }
    """

    # 单消息最大保留长度（超出截断）
    MAX_MESSAGE_CONTENT_LEN = 4000

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: UUID,
        title: Optional[str] = None,
        project_id: Optional[UUID] = None,
    ) -> AgentSession:
        """创建新会话"""
        session = AgentSession(
            user_id=user_id,
            project_id=project_id,
            title=title or "新会话",
            status=SessionStatus.ACTIVE,
            context={"messages": [], "summary": None, "token_count": 0},
            message_count=0,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get(self, session_id: UUID, user_id: UUID) -> Optional[AgentSession]:
        """获取会话（含归属校验）"""
        session = await self.db.get(AgentSession, session_id)
        if session is None:
            return None
        if session.user_id != user_id:
            return None  # 越权返回 None（不暴露存在性）
        return session

    async def list_sessions(
        self,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        include_archived: bool = False,
    ) -> tuple[List[AgentSession], int]:
        """列出用户会话"""
        stmt = select(AgentSession).where(AgentSession.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(AgentSession.status == SessionStatus.ACTIVE)
        stmt = stmt.order_by(AgentSession.last_message_at.desc().nullslast())

        # 计数
        from sqlalchemy import func
        count_stmt = (
            select(func.count())
            .select_from(AgentSession)
            .where(AgentSession.user_id == user_id)
        )
        if not include_archived:
            count_stmt = count_stmt.where(AgentSession.status == SessionStatus.ACTIVE)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # 分页
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def archive(self, session_id: UUID, user_id: UUID) -> bool:
        """归档会话"""
        session = await self.get(session_id, user_id)
        if session is None:
            return False
        session.status = SessionStatus.ARCHIVED
        await self.db.flush()
        return True

    async def append_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_results: Optional[List[Dict]] = None,
    ) -> None:
        """追加一条消息到上下文，并更新会话元数据

        Args:
            role: user / assistant / tool
            content: 消息文本（超出 MAX_MESSAGE_CONTENT_LEN 截断）
            tool_calls: 工具调用列表（assistant 角色）
            tool_results: 工具结果列表（tool 角色）
        """
        session = await self.db.get(AgentSession, session_id)
        if session is None:
            logger.warning(f"会话不存在: {session_id}")
            return

        ctx = session.context or {"messages": [], "summary": None, "token_count": 0}
        messages = ctx.get("messages", [])

        # 截断超长内容
        truncated = content[: self.MAX_MESSAGE_CONTENT_LEN]
        if len(content) > self.MAX_MESSAGE_CONTENT_LEN:
            truncated += "...[truncated]"

        msg = {
            "role": role,
            "content": truncated,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if tool_results:
            msg["tool_results"] = tool_results

        messages.append(msg)
        ctx["messages"] = messages
        # 粗略 token 估算：1 token ≈ 4 字符
        ctx["token_count"] = sum(len(m.get("content", "")) for m in messages) // 4
        session.context = ctx
        session.message_count = len(messages)
        session.last_message_at = msg["ts"]
        await self.db.flush()

    async def get_context(self, session_id: UUID) -> Dict[str, Any]:
        """获取会话上下文"""
        session = await self.db.get(AgentSession, session_id)
        if session is None:
            return {"messages": [], "summary": None, "token_count": 0}
        return session.context or {"messages": [], "summary": None, "token_count": 0}

    async def maybe_compress(
        self,
        session_id: UUID,
        llm_router=None,
    ) -> bool:
        """上下文压缩：超过阈值时调用 LLM 生成摘要替换历史

        Returns:
            是否触发了压缩
        """
        ctx = await self.get_context(session_id)
        token_count = ctx.get("token_count", 0)
        threshold = settings.AGENT_CONTEXT_COMPRESS_THRESHOLD

        if token_count < threshold:
            return False

        if llm_router is None:
            # 无 LLM 时降级为简单截断：保留首尾若干条
            messages = ctx.get("messages", [])
            if len(messages) <= 6:
                return False
            kept = messages[:2] + messages[-4:]
            ctx["messages"] = kept
            ctx["summary"] = (ctx.get("summary") or "") + " [早期对话已截断]"
            ctx["token_count"] = sum(len(m.get("content", "")) for m in kept) // 4
            session = await self.db.get(AgentSession, session_id)
            if session:
                session.context = ctx
                await self.db.flush()
            return True

        # 用 LLM 生成摘要
        from app.services.agent.prompts import CONTEXT_COMPRESSION_PROMPT

        history = "\n\n".join(
            f"[{m['role']}] {m.get('content', '')}" for m in ctx.get("messages", [])
        )
        prompt = CONTEXT_COMPRESSION_PROMPT.format(history=history[:8000])
        try:
            result = await llm_router.quick(prompt)
            summary = result.get("content", "")[:1000]
        except Exception as e:
            logger.warning(f"上下文压缩 LLM 调用失败，降级截断: {e}")
            summary = "[压缩失败，已截断早期对话]"

        # 保留最近 4 条消息 + 摘要
        messages = ctx.get("messages", [])
        kept = messages[-4:]
        ctx["messages"] = kept
        ctx["summary"] = summary
        ctx["token_count"] = (
            len(summary) + sum(len(m.get("content", "")) for m in kept)
        ) // 4

        session = await self.db.get(AgentSession, session_id)
        if session:
            session.context = ctx
            await self.db.flush()
        return True
