"""ReasoningTraceStore — 推理过程可追溯服务

设计来源：Nature Co-Scientist 论文的「推理过程可追溯性」要求 +
karpathy/autoresearch 的「实验日志」理念（记录每次修改→训练→评估→保留/丢弃决策）。

核心能力：
1. 步骤追加：每个 agent 调用 / LLM 调用 / 决策点持久化
2. 树形追溯：parent_step_id 构建步骤树
3. 成本分解：按 agent / phase / step_type 统计成本
4. 决策链查询：提取所有 decision_point，含 decision_basis

autoresearch 整合点：
- autoresearch 的核心循环是 modify→train→evaluate→keep/discard
- 本 Store 的 append 方法记录每个步骤，decision_point 类型记录 keep/discard 决策
- decision_basis 字段记录为什么保留或丢弃（autoresearch 的核心价值）
- get_cost_breakdown 等价于 autoresearch 的实验成本统计
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reasoning_trace import ReasoningTrace, StepType, TraceStatus

logger = logging.getLogger(__name__)


def _run_id_to_str(run_id: Optional[UUID]) -> Optional[str]:
    """将 run_id UUID 转为字符串存储"""
    if run_id is None:
        return None
    return str(run_id)


class ReasoningTraceStore:
    """推理过程追溯存储

    用法：
        store = ReasoningTraceStore()
        step_id = await store.append(run_id=run_id, step_type="agent_call",
                                      agent_name="generation", input_data={...})
        await store.append(run_id=run_id, step_type="decision_point",
                           parent_step_id=step_id, decision_basis="保留：Elo提升50分")
        tree = await store.get_trace_tree(run_id)
        cost = await store.get_cost_breakdown(run_id)
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        """初始化推理追溯存储

        Args:
            db: 可选的数据库会话。若为 None，每次操作自动创建临时会话。
        """
        self._db = db

    async def _get_session(self) -> AsyncSession:
        if self._db is not None:
            return self._db
        from app.db.session import async_session_factory
        return async_session_factory()

    async def _should_close(self, session: AsyncSession) -> bool:
        return self._db is None

    # ========== 步骤追加 ==========

    async def append(
        self,
        step_type: str,
        run_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        parent_step_id: Optional[UUID] = None,
        agent_name: Optional[str] = None,
        phase: Optional[str] = None,
        round_num: Optional[int] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        llm_call_id: Optional[str] = None,
        decision_basis: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        duration_sec: Optional[float] = None,
        status: str = TraceStatus.COMPLETED,
        error: Optional[str] = None,
    ) -> UUID:
        """追加一个推理步骤（不可变）

        autoresearch 整合：每个步骤等价于 autoresearch 的一次实验操作
        （修改代码 / 训练 / 评估 / 决策保留或丢弃）。

        Args:
            step_type: 步骤类型（见 StepType 枚举）
            run_id: 关联的 CoScientistRun ID
            session_id: 统一会话 ID
            parent_step_id: 父步骤 ID（构建步骤树）
            agent_name: agent 名称
            phase: Co-Scientist 阶段
            round_num: 轮次
            input_data: 输入数据
            output_data: 输出数据
            llm_call_id: LLM 调用 ID
            decision_basis: 决策依据（step_type=decision_point 时填写）
            prompt_tokens: 输入 token 数
            completion_tokens: 输出 token 数
            cost_usd: 成本（美元）
            duration_sec: 耗时（秒）
            status: 状态
            error: 错误信息

        Returns:
            新创建的步骤 ID
        """
        session = await self._get_session()
        try:
            trace = ReasoningTrace(
                run_id=_run_id_to_str(run_id),
                session_id=session_id,
                parent_step_id=parent_step_id,
                step_type=step_type,
                agent_name=agent_name,
                phase=phase,
                round_num=round_num,
                input_data=input_data,
                output_data=output_data,
                llm_call_id=llm_call_id,
                decision_basis=decision_basis,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                duration_sec=duration_sec,
                status=status,
                error=error,
            )
            session.add(trace)
            await session.commit()
            await session.refresh(trace)
            return trace.id
        except Exception as e:
            await session.rollback()
            logger.error("追加推理步骤失败: %s", e)
            raise
        finally:
            if await self._should_close(session):
                await session.close()

    async def append_llm_call(
        self,
        run_id: Optional[UUID],
        session_id: Optional[UUID],
        agent_name: str,
        phase: Optional[str],
        round_num: Optional[int],
        messages: List[Dict],
        response_content: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_sec: float = 0.0,
        parent_step_id: Optional[UUID] = None,
    ) -> UUID:
        """便捷方法：追加 LLM 调用步骤"""
        return await self.append(
            step_type=StepType.LLM_CALL,
            run_id=run_id,
            session_id=session_id,
            parent_step_id=parent_step_id,
            agent_name=agent_name,
            phase=phase,
            round_num=round_num,
            input_data={"messages": messages[-3:], "model": model},  # 仅保留最近3条
            output_data={"content": response_content[:500]},
            llm_call_id=f"{model}_{int(time.time())}",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            duration_sec=duration_sec,
        )

    async def append_decision(
        self,
        run_id: Optional[UUID],
        session_id: Optional[UUID],
        options: List[str],
        chosen: str,
        reason: str,
        phase: Optional[str] = None,
        round_num: Optional[int] = None,
        agent_name: Optional[str] = None,
        parent_step_id: Optional[UUID] = None,
    ) -> UUID:
        """便捷方法：追加决策点步骤

        autoresearch 整合：等价于 autoresearch 的 keep/discard 决策。
        decision_basis 记录为什么选择此分支，支持推理过程审计。
        """
        return await self.append(
            step_type=StepType.DECISION_POINT,
            run_id=run_id,
            session_id=session_id,
            parent_step_id=parent_step_id,
            agent_name=agent_name,
            phase=phase,
            round_num=round_num,
            input_data={"options": options, "selected": chosen},
            output_data={"chosen": chosen},
            decision_basis=reason,
        )

    # ========== 查询 ==========

    async def list_by_run(
        self,
        run_id: UUID,
        step_types: Optional[List[str]] = None,
        limit: int = 500,
    ) -> List[ReasoningTrace]:
        """按运行 ID 列出推理步骤（时间正序）"""
        session = await self._get_session()
        try:
            run_id_str = _run_id_to_str(run_id)
            conditions = [ReasoningTrace.run_id == run_id_str]
            if step_types:
                conditions.append(ReasoningTrace.step_type.in_(step_types))
            stmt = (
                select(ReasoningTrace)
                .where(and_(*conditions))
                .order_by(ReasoningTrace.created_at)
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
        finally:
            if await self._should_close(session):
                await session.close()

    async def list_by_session(
        self,
        session_id: UUID,
        limit: int = 200,
    ) -> List[ReasoningTrace]:
        """按会话 ID 列出推理步骤（跨运行）"""
        session = await self._get_session()
        try:
            stmt = (
                select(ReasoningTrace)
                .where(ReasoningTrace.session_id == session_id)
                .order_by(desc(ReasoningTrace.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
        finally:
            if await self._should_close(session):
                await session.close()

    async def get_trace_tree(self, run_id: UUID) -> Dict[str, Any]:
        """获取步骤树（按 parent_step_id 构建树形结构）

        Returns:
            {"roots": [step_dict, ...], "total_steps": int, "total_cost": float}
            每个 step_dict 含 children 列表
        """
        traces = await self.list_by_run(run_id, limit=1000)
        if not traces:
            return {"roots": [], "total_steps": 0, "total_cost": 0.0}

        # 构建步骤映射
        step_map: Dict[str, Dict[str, Any]] = {}
        for t in traces:
            step_map[str(t.id)] = {
                "id": str(t.id),
                "step_type": t.step_type,
                "agent_name": t.agent_name,
                "phase": t.phase,
                "round_num": t.round_num,
                "input_data": t.input_data,
                "output_data": t.output_data,
                "decision_basis": t.decision_basis,
                "cost_usd": t.cost_usd or 0.0,
                "duration_sec": t.duration_sec or 0.0,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "children": [],
            }

        # 构建树
        roots = []
        total_cost = 0.0
        for t in traces:
            node = step_map[str(t.id)]
            total_cost += node["cost_usd"]
            if t.parent_step_id and str(t.parent_step_id) in step_map:
                step_map[str(t.parent_step_id)]["children"].append(node)
            else:
                roots.append(node)

        return {
            "roots": roots,
            "total_steps": len(traces),
            "total_cost": round(total_cost, 6),
        }

    async def get_cost_breakdown(self, run_id: UUID) -> Dict[str, Any]:
        """获取成本分解（按 agent / phase / step_type 分组）

        autoresearch 整合：等价于 autoresearch 的实验成本统计。
        """
        traces = await self.list_by_run(run_id, limit=1000)
        if not traces:
            return {"total_cost": 0.0, "total_tokens": 0, "by_agent": {}, "by_phase": {}, "by_step_type": {}}

        by_agent: Dict[str, float] = {}
        by_phase: Dict[str, float] = {}
        by_step_type: Dict[str, float] = {}
        total_cost = 0.0
        total_tokens = 0

        for t in traces:
            cost = t.cost_usd or 0.0
            tokens = (t.prompt_tokens or 0) + (t.completion_tokens or 0)
            total_cost += cost
            total_tokens += tokens

            agent = t.agent_name or "unknown"
            by_agent[agent] = by_agent.get(agent, 0.0) + cost

            phase = t.phase or "unknown"
            by_phase[phase] = by_phase.get(phase, 0.0) + cost

            by_step_type[t.step_type] = by_step_type.get(t.step_type, 0.0) + cost

        return {
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "by_agent": {k: round(v, 6) for k, v in sorted(by_agent.items(), key=lambda x: -x[1])},
            "by_phase": {k: round(v, 6) for k, v in sorted(by_phase.items(), key=lambda x: -x[1])},
            "by_step_type": {k: round(v, 6) for k, v in sorted(by_step_type.items(), key=lambda x: -x[1])},
        }

    async def get_decision_chain(self, run_id: UUID) -> List[Dict[str, Any]]:
        """获取决策链（所有 decision_point 步骤，含 decision_basis）

        autoresearch 整合：等价于 autoresearch 的 keep/discard 决策日志。
        支持审计推理过程中的每个关键决策。
        """
        traces = await self.list_by_run(run_id, step_types=[StepType.DECISION_POINT])
        return [
            {
                "id": str(t.id),
                "phase": t.phase,
                "round_num": t.round_num,
                "agent_name": t.agent_name,
                "options": t.input_data.get("options", []) if t.input_data else [],
                "chosen": t.output_data.get("chosen", "") if t.output_data else "",
                "decision_basis": t.decision_basis or "",
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in traces
        ]

    # ========== trace_callback 桥接（ProgressTracker 集成） ==========

    def create_trace_callback(
        self,
        run_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
    ):
        """创建 trace_callback 供 ProgressTracker 使用

        ProgressTracker.emit 时同步调用此 callback，将事件持久化到 reasoning_trace。

        用法：
            tracker = ProgressTracker(run_id, callback=ws_push)
            store = ReasoningTraceStore()
            tracker.trace_callback = store.create_trace_callback(run_id, session_id)
        """

        async def _callback(event_type: str, payload: Dict, phase: str = "", round_num: int = 0):
            try:
                # 映射事件类型到 step_type
                step_type_map = {
                    "run_started": StepType.PHASE_START,
                    "run_completed": StepType.PHASE_END,
                    "run_failed": StepType.PHASE_END,
                    "round_started": StepType.ROUND_START,
                    "round_completed": StepType.ROUND_END,
                    "phase_started": StepType.PHASE_START,
                    "phase_completed": StepType.PHASE_END,
                    "hypothesis_generated": StepType.AGENT_CALL,
                    "hypothesis_evolved": StepType.EVOLUTION,
                    "ranking_updated": StepType.RANKING,
                    "cost_warning": StepType.DECISION_POINT,
                }
                step_type = step_type_map.get(event_type, StepType.AGENT_CALL)

                await self.append(
                    step_type=step_type,
                    run_id=run_id,
                    session_id=session_id,
                    phase=phase or None,
                    round_num=round_num or None,
                    input_data={"event_type": event_type, "payload": payload},
                    cost_usd=payload.get("cost_usd"),
                    prompt_tokens=payload.get("token_usage", {}).get("prompt") if isinstance(payload.get("token_usage"), dict) else None,
                    completion_tokens=payload.get("token_usage", {}).get("completion") if isinstance(payload.get("token_usage"), dict) else None,
                    status=TraceStatus.FAILED if event_type == "run_failed" else TraceStatus.COMPLETED,
                    error=payload.get("error") if event_type == "run_failed" else None,
                )
            except Exception as e:
                logger.warning("trace_callback 写入失败: %s", e)

        return _callback
