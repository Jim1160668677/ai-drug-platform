"""Agent 进度推送管理器 — WebSocket 事件分发

设计来源：2026-07-18-agent-functional-design.md §6 / §2

委托 backend/app/api/v1/endpoints/ws.py 的 TaskProgressManager 单例，
复用其 owner_id 校验与 TTL 清理机制。
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.api.v1.endpoints.ws import get_progress_manager

logger = logging.getLogger(__name__)


class ProgressManager:
    """Agent 进度推送包装器

    将 Agent 引擎产生的事件转换为 TaskProgressManager 的进度更新。
    前端 WebSocket 客户端订阅 task_id 后，能感知到这些进度变化。

    事件 JSON 格式（推送给前端）：
    {
        "type": "tool_call" | "tool_result" | "thought" | "plan" | ...,
        "task_id": "...",
        "timestamp": "...",
        "payload": {<事件特定字段>}
    }

    注：TaskProgressManager 内部只存储 percent/message/status，
    完整事件流由前端通过对比 signature 变化感知。
    本包装器将关键事件序列化为 message 字段，前端解析 JSON 即可。
    """

    def __init__(self):
        self._mgr = get_progress_manager()

    def _emit(
        self,
        task_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        percent: Optional[float] = None,
        status: str = "running",
        owner_id: Optional[str] = None,
    ) -> None:
        """内部：发射一个事件"""
        event = {
            "type": event_type,
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        # 将事件序列化为 message 字段（前端解析 JSON）
        import json

        message = json.dumps(event, ensure_ascii=False, default=str)
        # 如果未提供 percent，保持现状
        if percent is None:
            current = self._mgr.get_progress(task_id)
            percent = current["percent"] if current else 0.0
        self._mgr.update_progress(
            task_id=task_id,
            percent=percent,
            message=message,
            status=status,
            owner_id=owner_id,
        )

    def push_task_started(
        self,
        task_id: str,
        plan: Optional[Dict] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        """任务开始"""
        self._emit(
            task_id,
            "task_started",
            {"plan": plan},
            percent=0.0,
            status="running",
            owner_id=owner_id,
        )

    def push_plan(self, task_id: str, plan: Dict) -> None:
        """规划完成"""
        steps_count = len(plan.get("steps", [])) if plan else 0
        percent = 5.0 if steps_count > 0 else 0.0
        self._emit(task_id, "plan", {"plan": plan}, percent=percent)

    def push_thought(self, task_id: str, thought: str, step: int, max_steps: int) -> None:
        """LLM 思考过程"""
        # 思考阶段：5% ~ 95% 按步数线性
        percent = 5.0 + (step / max(max_steps, 1)) * 90.0
        self._emit(
            task_id,
            "thought",
            {"thought": thought, "step": step, "max_steps": max_steps},
            percent=percent,
        )

    def push_tool_call(
        self, task_id: str, tool: str, args: Dict[str, Any], step: int
    ) -> None:
        """工具调用开始"""
        self._emit(
            task_id,
            "tool_call",
            {"tool": tool, "args": args, "step": step},
        )

    def push_tool_result(
        self,
        task_id: str,
        tool: str,
        success: bool,
        data: Any = None,
        error: Optional[str] = None,
        step: int = 0,
        duration_ms: Optional[int] = None,
    ) -> None:
        """工具执行结果"""
        self._emit(
            task_id,
            "tool_result",
            {
                "tool": tool,
                "success": success,
                "data": data,
                "error": error,
                "step": step,
                "duration_ms": duration_ms,
            },
        )

    def push_confirmation_required(
        self,
        task_id: str,
        tool: str,
        args: Dict[str, Any],
        description: str,
        risk_level: str = "medium",
        step: int = 0,
    ) -> None:
        """需要用户确认副作用操作"""
        self._emit(
            task_id,
            "confirmation_required",
            {
                "tool": tool,
                "args": args,
                "description": description,
                "risk_level": risk_level,
                "step": step,
            },
            status="awaiting",
        )

    def push_final_response(
        self,
        task_id: str,
        answer: str,
        references: Optional[list] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        """最终答案"""
        self._emit(
            task_id,
            "final_response",
            {"answer": answer, "references": references or []},
            percent=100.0,
            status="completed",
            owner_id=owner_id,
        )

    def push_error(
        self,
        task_id: str,
        error: str,
        error_code: str = "INTERNAL_ERROR",
        owner_id: Optional[str] = None,
    ) -> None:
        """错误事件"""
        self._emit(
            task_id,
            "error",
            {"error": error, "error_code": error_code},
            status="failed",
            owner_id=owner_id,
        )

    def push_task_completed(
        self,
        task_id: str,
        result: Dict[str, Any],
        owner_id: Optional[str] = None,
    ) -> None:
        """任务完成（区别于 final_response：这是元数据级完成信号）"""
        self._emit(
            task_id,
            "task_completed",
            {"result": result},
            percent=100.0,
            status="completed",
            owner_id=owner_id,
        )

    def push_task_cancelled(self, task_id: str, owner_id: Optional[str] = None) -> None:
        """任务被取消"""
        self._emit(
            task_id,
            "task_cancelled",
            {"reason": "user_cancelled"},
            status="cancelled",
            owner_id=owner_id,
        )

    def push_token(
        self,
        task_id: str,
        token: str,
        step: int = 0,
        owner_id: Optional[str] = None,
    ) -> None:
        """推送 LLM 流式 token（增量内容）

        用于 ReAct 循环中的 LLM 流式响应，让前端能逐 token 显示思考/答案，
        显著降低首字延迟（从 3-8s 降到 200-500ms）。

        Args:
            task_id: 任务 ID
            token: 本次增量 token 文本
            step: 当前 ReAct 步数
            owner_id: 任务归属用户 ID（鉴权用）
        """
        self._emit(
            task_id,
            "token",
            {"token": token, "step": step},
            owner_id=owner_id,
        )

    def get_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取当前进度（HTTP 轮询回退方案用）"""
        return self._mgr.get_progress(task_id)
