"""ContextMemoryStore — 持久化上下文记忆服务

设计来源：Nature Co-Scientist 论文的「持久化 Context Memory」组件 +
karpathy/autoresearch 的「实验结果追踪」理念（results.tsv → context_memory）。

核心能力：
1. 跨模式上下文共享：chat / reasoning / agent 三模式读写同一会话的记忆
2. 故障重启恢复：Supervisor 每轮写快照，重启时从最近快照恢复
3. 上下文压缩：importance 分级 + expires_at 自动清理
4. 实验日志追踪（autoresearch 理念）：记录每轮推理的「假设→评估→保留/丢弃」决策

autoresearch 整合点：
- autoresearch 的 results.tsv 记录每次实验的 metric（val_bpb）与 keep/discard 决策
- 本 Store 的 save_snapshot + append_message 等价于 autoresearch 的实验日志
- decision_basis 字段（在 reasoning_trace 中）记录 keep/discard 的原因
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_memory import ContextMemory, MemoryType

logger = logging.getLogger(__name__)


class ContextMemoryStore:
    """持久化上下文记忆存储

    用法：
        store = ContextMemoryStore()
        await store.append_message(session_id, role="user", content="分析靶点")
        snapshot = await store.get_last_snapshot(run_id)
        prompt = await store.build_context_prompt(session_id)
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        """初始化上下文记忆存储

        Args:
            db: 可选的数据库会话。若为 None，每次操作自动创建临时会话。
                传入 db 时需调用方管理会话生命周期（commit/close）。
        """
        self._db = db

    async def _get_session(self) -> AsyncSession:
        """获取数据库会话（内部使用）"""
        if self._db is not None:
            return self._db
        from app.db.session import async_session_factory
        return async_session_factory()

    async def _should_close(self, session: AsyncSession) -> bool:
        """判断是否应由本方法关闭会话"""
        return self._db is None

    # ========== 消息类记忆 ==========

    async def append_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_results: Optional[List[Dict]] = None,
        token_count: int = 0,
        importance: float = 0.5,
        run_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> ContextMemory:
        """追加一条消息记忆（不可变）

        Args:
            session_id: 统一会话 ID
            role: 消息角色（user/assistant/tool）
            content: 消息内容
            tool_calls: 工具调用列表（assistant 消息）
            tool_results: 工具返回结果（tool 消息）
            token_count: 消息 token 数
            importance: 重要性 0-1（压缩时优先丢弃低重要性）
            run_id: 关联的 CoScientistRun ID（reasoning 模式）
            project_id: 项目 ID（跨会话共享）
            user_id: 用户 ID
        """
        content_data: Dict[str, Any] = {
            "role": role,
            "content": content,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if tool_calls:
            content_data["tool_calls"] = tool_calls
        if tool_results:
            content_data["tool_results"] = tool_results

        # 消息类记忆默认 30 天过期
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        session = await self._get_session()
        try:
            memory = ContextMemory(
                session_id=session_id,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                memory_type=MemoryType.MESSAGE,
                key=f"msg_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
                content=content_data,
                token_count=token_count,
                importance=importance,
                expires_at=expires_at,
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            return memory
        except Exception as e:
            await session.rollback()
            logger.error("追加消息记忆失败: %s", e)
            raise
        finally:
            if await self._should_close(session):
                await session.close()

    # ========== 快照类记忆（故障重启） ==========

    async def save_snapshot(
        self,
        run_id: UUID,
        round_num: int,
        phase: str,
        hypotheses: List[Dict[str, Any]],
        context_summary: str = "",
        session_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        importance: float = 0.9,
    ) -> ContextMemory:
        """保存推理过程快照（用于故障重启）

        autoresearch 整合：等价于 autoresearch 每次实验后记录 results.tsv，
        本方法记录每轮推理的假设状态，支持从最近快照恢复。

        Args:
            run_id: CoScientistRun ID
            round_num: 当前轮次
            phase: 当前阶段
            hypotheses: 当前假设列表（含 text/elo/rank）
            context_summary: 上下文摘要
            session_id: 统一会话 ID
            project_id: 项目 ID
            importance: 重要性（快照默认 0.9，高优先级保留）
        """
        content_data = {
            "round": round_num,
            "phase": phase,
            "hypotheses": hypotheses,
            "context_summary": context_summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 快照类记忆默认 7 天过期（比消息短，避免堆积）
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        session = await self._get_session()
        try:
            memory = ContextMemory(
                session_id=session_id,
                run_id=run_id,
                project_id=project_id,
                memory_type=MemoryType.SNAPSHOT,
                key=f"snapshot_round_{round_num}",
                content=content_data,
                token_count=0,
                importance=importance,
                expires_at=expires_at,
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            logger.info("保存快照: run=%s round=%d phase=%s hypotheses=%d",
                        run_id, round_num, phase, len(hypotheses))
            return memory
        except Exception as e:
            await session.rollback()
            logger.error("保存快照失败: %s", e)
            raise
        finally:
            if await self._should_close(session):
                await session.close()

    async def get_last_snapshot(self, run_id: UUID) -> Optional[Dict[str, Any]]:
        """获取最近一次快照（故障重启用）

        Returns:
            快照内容字典，或 None（无快照时）
            {"round": int, "phase": str, "hypotheses": [...], "context_summary": str}
        """
        session = await self._get_session()
        try:
            stmt = (
                select(ContextMemory)
                .where(
                    and_(
                        ContextMemory.run_id == run_id,
                        ContextMemory.memory_type == MemoryType.SNAPSHOT,
                    )
                )
                .order_by(desc(ContextMemory.created_at))
                .limit(1)
            )
            result = await session.execute(stmt)
            memory = result.scalar_one_or_none()
            if memory is None:
                return None
            return memory.content
        finally:
            if await self._should_close(session):
                await session.close()

    # ========== 实体引用类记忆 ==========

    async def save_entity_ref(
        self,
        session_id: UUID,
        entity_type: str,
        entity_id: UUID,
        relation: str = "",
        project_id: Optional[UUID] = None,
        importance: float = 0.7,
    ) -> ContextMemory:
        """保存实体引用（构建数据知识图谱）

        Args:
            session_id: 统一会话 ID
            entity_type: 实体类型（target/molecule/hypothesis/dataset）
            entity_id: 实体 ID
            relation: 关系描述
            project_id: 项目 ID
        """
        content_data = {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "relation": relation,
        }

        session = await self._get_session()
        try:
            memory = ContextMemory(
                session_id=session_id,
                project_id=project_id,
                memory_type=MemoryType.ENTITY_REF,
                key=f"{entity_type}_{entity_id}",
                content=content_data,
                token_count=0,
                importance=importance,
                expires_at=None,  # 实体引用永不过期
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            return memory
        except Exception as e:
            await session.rollback()
            logger.error("保存实体引用失败: %s", e)
            raise
        finally:
            if await self._should_close(session):
                await session.close()

    # ========== 检索与上下文构建 ==========

    async def retrieve(
        self,
        session_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        memory_types: Optional[List[str]] = None,
        limit: int = 50,
        min_importance: float = 0.0,
    ) -> List[ContextMemory]:
        """检索记忆条目

        至少传入 session_id / run_id / project_id 中的一个。
        """
        session = await self._get_session()
        try:
            conditions = []
            if session_id is not None:
                conditions.append(ContextMemory.session_id == session_id)
            if run_id is not None:
                conditions.append(ContextMemory.run_id == run_id)
            if project_id is not None:
                conditions.append(ContextMemory.project_id == project_id)
            if memory_types:
                conditions.append(ContextMemory.memory_type.in_(memory_types))
            if min_importance > 0:
                conditions.append(ContextMemory.importance >= min_importance)

            if not conditions:
                return []

            stmt = (
                select(ContextMemory)
                .where(and_(*conditions))
                .order_by(desc(ContextMemory.importance), desc(ContextMemory.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
        finally:
            if await self._should_close(session):
                await session.close()

    async def build_context_prompt(
        self,
        session_id: UUID,
        max_tokens: int = 4000,
        include_types: Optional[List[str]] = None,
    ) -> str:
        """构建上下文提示词

        按重要性排序，截取不超过 max_tokens 的记忆构建提示词。
        包含：消息历史 + 研究目标 + 假设状态 + 数据特征。

        autoresearch 整合：类似 autoresearch 将 program.md + 历史实验结果
        注入 agent 上下文，本方法将历史记忆注入 LLM 上下文。
        """
        if include_types is None:
            include_types = [
                MemoryType.RESEARCH_GOAL,
                MemoryType.HYPOTHESIS_STATE,
                MemoryType.MESSAGE,
                MemoryType.DATA_FEATURE,
            ]

        memories = await self.retrieve(
            session_id=session_id,
            memory_types=include_types,
            limit=100,
            min_importance=0.3,
        )

        if not memories:
            return ""

        sections: List[str] = []
        total_tokens = 0

        # 优先放研究目标和假设状态
        for mem in memories:
            if mem.memory_type == MemoryType.RESEARCH_GOAL:
                goal_text = f"[研究目标] {mem.content.get('goal', '')}"
                if total_tokens + len(goal_text) // 4 > max_tokens:
                    break
                sections.append(goal_text)
                total_tokens += len(goal_text) // 4

        for mem in memories:
            if mem.memory_type == MemoryType.HYPOTHESIS_STATE:
                hyps = mem.content.get("hypotheses", [])
                hyp_text = f"[当前假设状态] 共 {len(hyps)} 个假设"
                for h in hyps[:5]:
                    hyp_text += f"\n  - {h.get('text', '')[:100]} (Elo: {h.get('elo', 0)})"
                if total_tokens + len(hyp_text) // 4 > max_tokens:
                    break
                sections.append(hyp_text)
                total_tokens += len(hyp_text) // 4

        # 消息历史（按时间正序）
        msg_memories = [m for m in memories if m.memory_type == MemoryType.MESSAGE]
        msg_memories.sort(key=lambda m: m.created_at)
        msg_lines: List[str] = ["[对话历史]"]
        for mem in msg_memories:
            role = mem.content.get("role", "?")
            content = mem.content.get("content", "")[:200]
            line = f"  {role}: {content}"
            if total_tokens + len(line) // 4 > max_tokens:
                break
            msg_lines.append(line)
            total_tokens += len(line) // 4
        if len(msg_lines) > 1:
            sections.append("\n".join(msg_lines))

        # 数据特征
        for mem in memories:
            if mem.memory_type == MemoryType.DATA_FEATURE:
                summary = mem.content.get("summary", "")
                feat_text = f"[数据特征] {summary[:200]}"
                if total_tokens + len(feat_text) // 4 > max_tokens:
                    break
                sections.append(feat_text)
                total_tokens += len(feat_text) // 4

        return "\n\n".join(sections) if sections else ""

    # ========== 过期清理 ==========

    async def cleanup_expired(self, batch_size: int = 100) -> int:
        """清理过期记忆

        Returns:
            清理的记录数
        """
        session = await self._get_session()
        try:
            now = datetime.now(timezone.utc)
            stmt = (
                delete(ContextMemory)
                .where(
                    and_(
                        ContextMemory.expires_at.isnot(None),
                        ContextMemory.expires_at < now,
                    )
                )
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            await session.commit()
            deleted = result.rowcount or 0
            if deleted > 0:
                logger.info("清理过期记忆: %d 条", deleted)
            return deleted
        except Exception as e:
            await session.rollback()
            logger.error("清理过期记忆失败: %s", e)
            return 0
        finally:
            if await self._should_close(session):
                await session.close()

    # ========== 研究目标管理 ==========

    async def save_research_goal(
        self,
        session_id: UUID,
        goal: str,
        constraints: Optional[List[str]] = None,
        updated_by: str = "user",
        project_id: Optional[UUID] = None,
    ) -> ContextMemory:
        """保存/更新研究目标

        研究目标在会话内唯一（key="research_goal"），重复保存会追加新版本。
        """
        content_data = {
            "goal": goal,
            "constraints": constraints or [],
            "updated_by": updated_by,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        session = await self._get_session()
        try:
            memory = ContextMemory(
                session_id=session_id,
                project_id=project_id,
                memory_type=MemoryType.RESEARCH_GOAL,
                key="research_goal",
                content=content_data,
                token_count=len(goal) // 4,
                importance=1.0,  # 研究目标最重要
                expires_at=None,  # 永不过期
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            return memory
        except Exception as e:
            await session.rollback()
            logger.error("保存研究目标失败: %s", e)
            raise
        finally:
            if await self._should_close(session):
                await session.close()
