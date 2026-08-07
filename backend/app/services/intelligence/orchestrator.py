"""UnifiedOrchestrator — 统一编排层（融合 AI 问答 / 科学推理 / Agent 工作台）

设计来源：Nature Co-Scientist 论文的四大组件架构（自然语言接口 + 异步任务框架 +
专业化 agents + 持久化 Context Memory）+ karpathy/autoresearch 的自主实验循环理念。

核心职责：
1. 统一入口：chat(session_id, message, user, project_id, force_mode)
2. 意图路由：IntentRouter keyword + LLM 二级 → chat / reasoning / agent / hybrid
3. 上下文管理：写入 context_memory，构建上下文提示词
4. 推理追溯：写入 reasoning_trace，记录每个步骤
5. 三模式协作：chat → reasoning（连续追问升级）；agent → reasoning（工具产出后生成假设）

autoresearch 整合：
- autoresearch 的 program.md 定义 agent 行为 → IntentRouter 定义意图到模式的映射
- autoresearch 的自主循环 → UnifiedOrchestrator 的 chat 方法编排完整流程
- autoresearch 的 results.tsv → context_memory + reasoning_trace 持久化
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.unified_session import UnifiedSession, UnifiedSessionStatus, PrimaryMode
from app.services.intelligence.context_store import ContextMemoryStore
from app.services.intelligence.trace_store import ReasoningTraceStore
from app.services.intelligence.intent_router import IntentRouter, IntentResult
from app.services.intelligence.channels.chat import ChatChannel
from app.services.intelligence.channels.reasoning import ReasoningChannel
from app.services.intelligence.channels.agent import AgentChannel

logger = logging.getLogger(__name__)


def _extract_evidence(step) -> Optional[Dict[str, Any]]:
    """从推理步骤中提取证据数据（仅 tool_call 步骤）

    Args:
        step: ReasoningTrace 实例

    Returns:
        tool_call 步骤返回证据 dict，其他步骤返回 None
    """
    if step.step_type != "tool_call":
        return None
    return {
        "query": (step.input_data or {}).get("query", ""),
        "sources": (step.input_data or {}).get("sources", []),
        "total_hits": (step.output_data or {}).get("total_hits", {}),
        "papers": (step.output_data or {}).get("papers", []),
    }


class UnifiedOrchestrator:
    """统一编排器 — 融合三模式的统一入口

    用法：
        orchestrator = UnifiedOrchestrator(db, llm_client)
        session = await orchestrator.create_session(user, project_id="...")
        result = await orchestrator.chat(
            session_id=session.id,
            message="帮我分析 EGFR 靶点的功能并生成假设",
            user=user,
        )
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client: Any,
        llm_config: Optional[Any] = None,
    ):
        """初始化统一编排器

        Args:
            db: 数据库会话
            llm_client: LLM 客户端实例（FallbackLLMClient）
            llm_config: 数据库激活的 LLMConfig（可选）
        """
        self.db = db
        self.llm_client = llm_client
        self.llm_config = llm_config

        # 初始化存储层
        self.context_store = ContextMemoryStore(db=db)
        self.trace_store = ReasoningTraceStore(db=db)

        # 初始化意图路由器
        self.intent_router = IntentRouter(llm_client=llm_client)

        # 初始化三个 Channel
        self.chat_channel = ChatChannel(
            llm_client=llm_client,
            context_store=self.context_store,
            trace_store=self.trace_store,
            llm_config=llm_config,
        )
        self.reasoning_channel = ReasoningChannel(
            llm_client=llm_client,
            context_store=self.context_store,
            trace_store=self.trace_store,
        )
        self.agent_channel = AgentChannel(
            db=db,
            llm_router=llm_client,
            context_store=self.context_store,
            trace_store=self.trace_store,
        )

    # ========== 会话管理 ==========

    async def create_session(
        self,
        user: Any,
        project_id: Optional[str] = None,
        title: str = "新会话",
        primary_mode: str = PrimaryMode.AUTO,
    ) -> UnifiedSession:
        """创建统一智能会话"""
        session = UnifiedSession(
            user_id=user.id,
            project_id=UUID(project_id) if project_id else None,
            title=title,
            status=UnifiedSessionStatus.ACTIVE,
            primary_mode=primary_mode,
            context={"messages": [], "summary": None, "token_count": 0},
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("创建统一会话: %s user=%s", session.id, user.id)
        return session

    async def get_session(self, session_id: UUID) -> Optional[UnifiedSession]:
        """获取会话"""
        stmt = select(UnifiedSession).where(UnifiedSession.id == session_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        user: Any,
        project_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[UnifiedSession]:
        """列出用户会话"""
        conditions = [
            UnifiedSession.user_id == user.id,
            UnifiedSession.status == UnifiedSessionStatus.ACTIVE,
        ]
        if project_id:
            conditions.append(UnifiedSession.project_id == UUID(project_id))
        stmt = (
            select(UnifiedSession)
            .where(*conditions)
            .order_by(UnifiedSession.last_message_at.desc().nullslast() if hasattr(UnifiedSession.last_message_at, 'desc') else UnifiedSession.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ========== 统一对话入口 ==========

    async def chat(
        self,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str] = None,
        force_mode: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统一对话入口 — 意图路由 → 分级推理 → 分流 channel → 写 trace

        Args:
            session_id: 统一会话 ID
            message: 用户消息
            user: 当前用户
            project_id: 项目 ID（可选，覆盖会话的 project_id）
            force_mode: 强制模式（chat/reasoning/agent），None 时自动路由
            tier: 推理档位（turbo/standard/deep），None 时自动选择

        Returns:
            {answer, mode, intent, tier, cost_usd, duration_sec, session_id}
        """
        import time
        start = time.time()

        # 1. 加载会话
        session = await self.get_session(session_id)
        if session is None:
            return {"error": "会话不存在", "session_id": str(session_id)}

        # 确定项目 ID
        effective_project_id = project_id or (str(session.project_id) if session.project_id else None)

        # 2. 意图路由
        chat_round_count = session.context.get("chat_round_count", 0) if session.context else 0
        intent = await self.intent_router.route(
            message=message,
            force_mode=force_mode or session.primary_mode,
            chat_round_count=chat_round_count,
        )

        # 3. 解析档位配置
        effective_tier = self._resolve_tier(
            tier=tier,
            message=message,
            intent_mode=intent.mode,
            intent_confidence=intent.confidence,
        )
        tier_config = self._get_tier_config(effective_tier)

        logger.info(
            "意图路由: session=%s mode=%s confidence=%.2f method=%s reason=%s tier=%s(%s)",
            session_id, intent.mode, intent.confidence, intent.method, intent.reason,
            effective_tier, tier_config.get("description", ""),
        )

        # 4. 写入用户消息到 trace
        await self.trace_store.append(
            step_type="user_message",
            session_id=session_id,
            input_data={"message": message[:500]},
            output_data={"intent": intent.to_dict(), "tier": effective_tier},
        )

        # 5. 分流到对应 Channel（应用档位配置）
        result: Dict[str, Any]
        if intent.mode == "chat":
            result = await self.chat_channel.chat(
                session_id=session_id,
                message=message,
                user=user,
                project_id=effective_project_id,
            )
        elif intent.mode == "reasoning":
            result = await self.reasoning_channel.reason(
                session_id=session_id,
                research_goal=message,
                user=user,
                project_id=effective_project_id,
                max_rounds=tier_config.get("max_rounds"),
                evidence_level=tier_config.get("evidence_level"),
                timeout_sec=tier_config.get("timeout_sec"),
            )
        elif intent.mode == "agent":
            result = await self.agent_channel.execute(
                session_id=session_id,
                query=message,
                user=user,
                project_id=effective_project_id,
            )
        elif intent.mode == "hybrid":
            agent_result = await self.agent_channel.execute(
                session_id=session_id,
                query=message,
                user=user,
                project_id=effective_project_id,
            )
            reasoning_result = await self.reasoning_channel.reason(
                session_id=session_id,
                research_goal=message,
                user=user,
                project_id=effective_project_id,
                evidence=agent_result.get("answer", ""),
                max_rounds=tier_config.get("max_rounds"),
                evidence_level=tier_config.get("evidence_level"),
                timeout_sec=tier_config.get("timeout_sec"),
            )
            result = {
                "answer": reasoning_result.get("meta_review", {}).get("summary", "") or agent_result.get("answer", ""),
                "mode": "hybrid",
                "agent_result": agent_result,
                "reasoning_result": reasoning_result,
                "cost_usd": agent_result.get("cost_usd", 0) + reasoning_result.get("total_cost", 0),
            }
        else:
            result = await self.chat_channel.chat(
                session_id=session_id,
                message=message,
                user=user,
                project_id=effective_project_id,
            )

        # 6. 更新会话状态
        duration_sec = round(time.time() - start, 3)
        await self._update_session_stats(
            session=session,
            mode=intent.mode,
            duration_sec=duration_sec,
            cost_usd=result.get("cost_usd", 0),
        )

        # 7. 写入助手回复到 trace
        await self.trace_store.append(
            step_type="assistant_message",
            session_id=session_id,
            input_data={"intent": intent.to_dict(), "tier": effective_tier},
            output_data={"answer": result.get("answer", "")[:500], "mode": result.get("mode", intent.mode)},
            cost_usd=result.get("cost_usd", 0),
            duration_sec=duration_sec,
        )

        return {
            **result,
            "mode": result.get("mode", intent.mode),
            "intent": intent.to_dict(),
            "tier": effective_tier,
            "tier_config": tier_config,
            "session_id": str(session_id),
            "duration_sec": duration_sec,
        }

    async def _update_session_stats(
        self,
        session: UnifiedSession,
        mode: str,
        duration_sec: float,
        cost_usd: float,
    ):
        """更新会话统计信息"""
        try:
            context = session.context or {"messages": [], "summary": None, "token_count": 0}
            # 更新 chat 轮数计数
            chat_round_count = context.get("chat_round_count", 0)
            if mode == "chat":
                chat_round_count += 1
            else:
                chat_round_count = 0  # 非 chat 模式重置计数

            context["chat_round_count"] = chat_round_count
            context["last_mode"] = mode

            # 更新会话
            session.context = context
            session.message_count += 1
            session.last_message_at = datetime.now(timezone.utc)
            self.db.add(session)
            await self.db.commit()
        except Exception as e:
            logger.warning("更新会话统计失败（不影响主流程）: %s", e)
            await self.db.rollback()

    # ========== 档位配置 ==========

    def _get_tier_config(self, tier: str) -> Dict[str, Any]:
        """获取指定档位的配置

        Args:
            tier: 档位名 (turbo/standard/deep)

        Returns:
            档位配置字典
        """
        tiers = getattr(settings, "LLM_TIERS", {})
        if tier not in tiers:
            tier = getattr(settings, "DEFAULT_LLM_TIER", "standard")
        return tiers.get(tier, tiers.get("standard", {}))

    def _resolve_tier(
        self,
        tier: Optional[str],
        message: str,
        intent_mode: str,
        intent_confidence: float,
    ) -> str:
        """解析档位 — 根据用户指定或自动选择

        自动选择策略：
        - reasoning/hybrid 模式 + 高置信度 (>0.8) → deep（深度推理）
        - reasoning/hybrid 模式 + 中等置信度 → standard（标准分析）
        - agent 模式 → standard
        - chat 模式 → turbo（快速筛查）
        - 用户显式指定 → 直接使用指定档位

        Args:
            tier: 用户指定档位（None 或 "auto" 时自动选择）
            message: 用户消息
            intent_mode: 意图模式（chat/reasoning/agent/hybrid）
            intent_confidence: 意图路由置信度

        Returns:
            档位名
        """
        if tier and tier != "auto":
            valid_tiers = ("turbo", "standard", "deep")
            if tier in valid_tiers:
                return tier
            logger.warning("无效档位 '%s'，使用默认档位", tier)

        if intent_mode in ("reasoning", "hybrid"):
            if intent_confidence >= 0.85:
                return "deep"
            return "standard"

        if intent_mode == "agent":
            return "standard"

        return "turbo"

    # ========== 上下文与追溯查询 ==========

    async def get_session_context(self, session_id: UUID) -> Dict[str, Any]:
        """获取会话上下文记忆"""
        memories = await self.context_store.retrieve(
            session_id=session_id,
            limit=50,
        )
        return {
            "session_id": str(session_id),
            "memories": [
                {
                    "id": str(m.id),
                    "type": m.memory_type,
                    "content": m.content,
                    "importance": m.importance,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in memories
            ],
            "context_prompt": await self.context_store.build_context_prompt(session_id),
        }

    async def get_session_trace(self, session_id: UUID) -> Dict[str, Any]:
        """获取会话推理追溯"""
        traces = await self.trace_store.list_by_session(session_id, limit=200)
        return {
            "session_id": str(session_id),
            "total_steps": len(traces),
            "traces": [
                {
                    "id": str(t.id),
                    "step_type": t.step_type,
                    "agent_name": t.agent_name,
                    "phase": t.phase,
                    "round_num": t.round_num,
                    "decision_basis": t.decision_basis,
                    "cost_usd": t.cost_usd,
                    "duration_sec": t.duration_sec,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "evidence": _extract_evidence(t),
                }
                for t in traces
            ],
        }

    async def get_run_trace_tree(self, run_id: UUID) -> Dict[str, Any]:
        """获取推理运行的步骤树"""
        return await self.trace_store.get_trace_tree(run_id)

    async def get_run_cost_breakdown(self, run_id: UUID) -> Dict[str, Any]:
        """获取推理运行的成本分解"""
        return await self.trace_store.get_cost_breakdown(run_id)

    async def get_run_decision_chain(self, run_id: UUID) -> List[Dict[str, Any]]:
        """获取推理运行的决策链"""
        return await self.trace_store.get_decision_chain(run_id)
