"""AgentChannel — Agent 工作台通道

设计来源：现有 AgentEngine ReAct 模式 + Nature 论文的「异步任务框架」。

核心能力：
1. 复用 AgentEngine.run 执行 ReAct 任务规划与执行
2. 注入 ReasoningTraceStore 记录每个 ReAct step
3. 工具产出数据后可自动切回 reasoning 生成假设

autoresearch 整合：等价于 autoresearch 中 agent 调用工具（搜索文献/查询数据库）
收集数据后进行决策。
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from app.services.intelligence.context_store import ContextMemoryStore
from app.services.intelligence.trace_store import ReasoningTraceStore

logger = logging.getLogger(__name__)


class AgentChannel:
    """Agent 工作台通道 — 调用 AgentEngine 执行工具任务

    用法：
        channel = AgentChannel(db, llm_router, context_store, trace_store)
        result = await channel.execute(session_id, "分析 EGFR 靶点的功能", user)
    """

    def __init__(
        self,
        db: Any,
        llm_router: Any,
        context_store: ContextMemoryStore,
        trace_store: ReasoningTraceStore,
    ):
        self.db = db
        self.llm_router = llm_router
        self.context_store = context_store
        self.trace_store = trace_store

    async def execute(
        self,
        session_id: UUID,
        query: str,
        user: Any,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行 Agent 任务

        Args:
            session_id: 统一会话 ID
            query: 用户查询（自然语言任务描述）
            user: 当前用户
            project_id: 项目 ID

        Returns:
            {answer, tools_used, mode, cost_usd, duration_sec}
        """
        start_time_str = None
        try:
            import time
            start = time.time()

            # 延迟导入避免循环依赖
            from app.services.agent.engine import AgentEngine
            from app.db.session import async_session_factory

            # AgentEngine 需要独立的 db session
            async with async_session_factory() as agent_db:
                engine = AgentEngine(
                    db=agent_db,
                    llm_router=self.llm_router,
                )

                # 注入 trace_store（AgentEngine 改造后支持）
                if hasattr(engine, "trace_store"):
                    engine.trace_store = self.trace_store

                # 创建 agent session
                from app.models.agent_session import AgentSession, SessionStatus
                agent_session = AgentSession(
                    user_id=user.id,
                    project_id=UUID(project_id) if project_id else None,
                    title=query[:100],
                    status=SessionStatus.ACTIVE,
                    unified_session_id=session_id,
                )
                agent_db.add(agent_session)
                await agent_db.commit()
                await agent_db.refresh(agent_session)

                # 执行任务
                result = await engine.run(
                    task_id=str(agent_session.id),
                    query=query,
                    session_id=agent_session.id,
                    user=user,
                )

                duration_sec = round(time.time() - start, 3)

                # 保存结果到上下文记忆
                await self.context_store.append_message(
                    session_id=session_id,
                    role="assistant",
                    content=result.get("answer", "") if isinstance(result, dict) else str(result),
                    tool_calls=result.get("tool_calls") if isinstance(result, dict) else None,
                    tool_results=result.get("tool_results") if isinstance(result, dict) else None,
                    importance=0.7,
                    project_id=UUID(project_id) if project_id else None,
                    user_id=user.id,
                )

                return {
                    "answer": result.get("answer", "") if isinstance(result, dict) else str(result),
                    "tools_used": result.get("tools_used", []) if isinstance(result, dict) else [],
                    "mode": "agent",
                    "cost_usd": result.get("cost_usd", 0.0) if isinstance(result, dict) else 0.0,
                    "duration_sec": duration_sec,
                }

        except Exception as e:
            logger.error("AgentChannel 执行失败: %s", e)
            return {
                "answer": f"Agent 任务执行失败：{str(e)}",
                "tools_used": [],
                "mode": "agent",
                "cost_usd": 0.0,
                "duration_sec": 0.0,
                "error": str(e),
            }
