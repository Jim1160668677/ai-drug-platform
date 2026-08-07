"""Co-Scientist 进度追踪器

追踪多智能体运行进度，通过回调推送 WebSocket 事件。

事件类型：
- run_started: 运行开始
- run_completed: 运行完成
- run_failed: 运行失败
- round_started: 轮次开始
- round_completed: 轮次完成
- phase_started: 阶段开始（generation/reflection/proximity/evolution/debate/ranking/meta_review）
- phase_completed: 阶段完成
- hypothesis_generated: 假设已生成
- hypothesis_evolved: 假设已进化
- ranking_updated: 排名已更新
- awaiting_feedback: 等待专家反馈
- feedback_received: 收到专家反馈
- cost_warning: 成本警告
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvent:
    """进度事件"""
    type: str
    run_id: str
    phase: str = ""
    round_num: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ProgressTracker:
    """Co-Scientist 运行进度追踪器

    用法：
        tracker = ProgressTracker(run_id, callback=ws_push)
        await tracker.emit_run_started(research_goal="...")
        await tracker.emit_round_started(1)
        await tracker.emit_phase_started("generation", 1)
        # ... 执行任务 ...
        await tracker.emit_phase_completed("generation", 1, result_summary={...})
    """

    def __init__(
        self,
        run_id: Any,
        callback: Optional[Callable] = None,
        max_events: int = 1000,
    ):
        """
        Args:
            run_id: 运行 ID（UUID 或 str）
            callback: 异步回调函数 async callback(event: ProgressEvent)
            max_events: 最大事件历史数
        """
        self.run_id = str(run_id)
        self.callback = callback
        self.max_events = max_events
        self.events: List[ProgressEvent] = []
        self.current_round = 0
        self.current_phase = ""
        self.start_time = time.time()
        self.total_cost_usd = 0.0
        self.total_tokens = 0
        # trace_callback: 推理追溯回调（由 ReasoningTraceStore.create_trace_callback 创建）
        # 与 callback（WebSocket 推送）并行，将事件持久化到 reasoning_trace 表
        self.trace_callback: Optional[Callable] = None

    async def emit(self, event_type: str, payload: Optional[Dict] = None, phase: str = "", round_num: int = 0):
        """推送进度事件"""
        event = ProgressEvent(
            type=event_type,
            run_id=self.run_id,
            phase=phase or self.current_phase,
            round_num=round_num or self.current_round,
            payload=payload or {},
        )

        self.events.append(event)
        # 限制历史长度
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        # 累计成本
        if "cost_usd" in event.payload:
            self.total_cost_usd += event.payload["cost_usd"]
        if "token_usage" in event.payload:
            self.total_tokens += event.payload["token_usage"].get("total", 0)

        # 回调推送
        if self.callback:
            try:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(event)
                else:
                    result = self.callback(event)
                    # 兼容 lambda 包装 async 函数：返回 coroutine 时需 await
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as e:
                logger.warning("进度回调失败: %s", e)

        # trace_callback 持久化到 reasoning_trace（与 WebSocket 推送并行）
        if self.trace_callback:
            try:
                await self.trace_callback(event_type, event.payload, event.phase, event.round_num)
            except Exception as e:
                logger.warning("trace_callback 失败: %s", e)

        logger.debug("[progress] %s (round=%d, phase=%s)", event_type, event.round_num, event.phase)

    # ========== 便捷方法 ==========

    async def emit_run_started(self, research_goal: str, max_rounds: int, initial_count: int):
        await self.emit("run_started", {
            "research_goal": research_goal[:200],
            "max_rounds": max_rounds,
            "initial_count": initial_count,
        })

    async def emit_run_completed(self, final_rankings: List, meta_review: Optional[Dict] = None):
        duration = time.time() - self.start_time
        await self.emit("run_completed", {
            "final_rankings": final_rankings,
            "meta_review": meta_review,
            "duration_sec": round(duration, 2),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
        })

    async def emit_run_failed(self, error: str):
        await self.emit("run_failed", {"error": error})

    async def emit_round_started(self, round_num: int):
        self.current_round = round_num
        await self.emit("round_started", {"round": round_num}, round_num=round_num)

    async def emit_round_completed(self, round_num: int, summary: Dict):
        await self.emit("round_completed", {"round": round_num, **summary}, round_num=round_num)

    async def emit_phase_started(self, phase: str, round_num: int = 0):
        self.current_phase = phase
        await self.emit("phase_started", {"phase": phase}, phase=phase, round_num=round_num)

    async def emit_phase_completed(self, phase: str, round_num: int = 0, result_summary: Optional[Dict] = None):
        await self.emit("phase_completed", {"phase": phase, **(result_summary or {})}, phase=phase, round_num=round_num)

    async def emit_hypothesis_generated(self, count: int, round_num: int = 0):
        await self.emit("hypothesis_generated", {"count": count}, round_num=round_num)

    async def emit_hypothesis_evolved(self, evolved_count: int, round_num: int = 0):
        await self.emit("hypothesis_evolved", {"evolved_count": evolved_count}, round_num=round_num)

    async def emit_ranking_updated(self, rankings: List, round_num: int = 0):
        # 只推送前 10 名避免数据过大
        top_rankings = rankings[:10] if len(rankings) > 10 else rankings
        await self.emit("ranking_updated", {"top_rankings": top_rankings, "total": len(rankings)}, round_num=round_num)

    async def emit_awaiting_feedback(self, round_num: int, current_rankings: List):
        await self.emit("awaiting_feedback", {
            "round": round_num,
            "current_rankings": current_rankings[:5],
        }, round_num=round_num)

    async def emit_feedback_received(self, feedback_type: str, feedback_text: str):
        await self.emit("feedback_received", {
            "feedback_type": feedback_type,
            "feedback_text": feedback_text[:500],
        })

    async def emit_cost_warning(self, cost_usd: float, threshold: float):
        await self.emit("cost_warning", {
            "current_cost": round(cost_usd, 4),
            "threshold": threshold,
            "message": f"成本 ${cost_usd:.2f} 接近上限 ${threshold:.2f}",
        })

    async def emit_step_trace(
        self,
        run_id: str,
        step_index: int,
        thought: str = "",
        action: str = "",
        action_input: Optional[Dict] = None,
        observation: str = "",
        duration_ms: int = 0,
        tokens: int = 0,
        cost_usd: float = 0.0,
        status: str = "running",
    ):
        payload = {
            "run_id": str(run_id),
            "step": step_index,
            "thought": thought[:500] if thought else "",
            "action": action,
            "action_input": action_input if action_input and len(str(action_input)) < 800 else None,
            "observation": observation[:600] if observation else "",
            "duration_ms": duration_ms,
            "tokens": tokens,
            "cost_usd": round(float(cost_usd), 5),
            "status": status,
        }
        await self.emit("step_trace", payload)

    async def emit_dag_node_status(
        self,
        phase: str,
        round_num: int = 0,
        status: str = "pending",
        duration_ms: int = 0,
        tokens: int = 0,
        cost_usd: float = 0.0,
        extra: Optional[Dict] = None,
    ):
        payload = {
            "phase": phase,
            "round": round_num,
            "status": status,
            "duration_ms": duration_ms,
            "tokens": tokens,
            "cost_usd": round(float(cost_usd), 5),
            "extra": extra or {},
        }
        await self.emit("dag_node_status", payload, phase=phase, round_num=round_num)

    async def emit_compression_stats(
        self,
        stage: str,
        before_chars: int,
        after_chars: int,
        details: Optional[Dict] = None,
    ):
        ratio = (after_chars / before_chars) if before_chars else 1.0
        payload = {
            "stage": stage,
            "before_chars": before_chars,
            "after_chars": after_chars,
            "saved_chars": max(0, before_chars - after_chars),
            "ratio": round(ratio, 4),
            "details": details or {},
        }
        await self.emit("compression_stats", payload)

    # ========== 查询方法 ==========

    def get_progress(self) -> Dict[str, Any]:
        """获取当前进度摘要"""
        return {
            "run_id": self.run_id,
            "current_round": self.current_round,
            "current_phase": self.current_phase,
            "duration_sec": round(time.time() - self.start_time, 2),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "event_count": len(self.events),
        }

    def get_recent_events(self, n: int = 20) -> List[Dict]:
        """获取最近 N 个事件"""
        recent = self.events[-n:] if n > 0 else self.events
        return [
            {
                "type": e.type,
                "phase": e.phase,
                "round": e.round_num,
                "timestamp": e.timestamp,
                "payload": e.payload,
            }
            for e in recent
        ]