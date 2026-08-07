"""ProgressManager 单元测试 — WS 事件分发"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.agent.progress import ProgressManager


@pytest.fixture
def progress():
    """构造 ProgressManager，Mock 内部 _mgr"""
    mgr = ProgressManager()
    mgr._mgr = MagicMock()
    mgr._mgr.get_progress.return_value = {"percent": 50.0}
    return mgr


def _captured_event(mock_mgr):
    """提取 update_progress 调用参数，从 message 字段解出事件 JSON"""
    mock_mgr.update_progress.assert_called()
    kwargs = mock_mgr.update_progress.call_args.kwargs
    return json.loads(kwargs["message"])


# ========== push_task_started ==========


def test_push_task_started(progress):
    progress.push_task_started("task-1", plan={"steps": [{"id": "s1"}]}, owner_id="u1")
    event = _captured_event(progress._mgr)
    assert event["type"] == "task_started"
    assert event["task_id"] == "task-1"
    assert event["payload"]["plan"]["steps"][0]["id"] == "s1"
    # update_progress 参数
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 0.0
    assert kwargs["status"] == "running"
    assert kwargs["owner_id"] == "u1"


# ========== push_plan ==========


def test_push_plan_with_steps(progress):
    progress.push_plan("task-2", {"steps": [{"id": "a"}, {"id": "b"}]})
    event = _captured_event(progress._mgr)
    assert event["type"] == "plan"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 5.0


def test_push_plan_empty(progress):
    progress.push_plan("task-3", None)
    event = _captured_event(progress._mgr)
    assert event["type"] == "plan"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 0.0


# ========== push_thought ==========


def test_push_thought_progress_scale(progress):
    """step=3, max_steps=10 → percent = 5 + 3/10*90 = 32.0"""
    progress.push_thought("task-4", "思考中...", step=3, max_steps=10)
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert abs(kwargs["percent"] - 32.0) < 0.01


def test_push_thought_max_step(progress):
    """step=max_steps → percent = 95.0"""
    progress.push_thought("task-5", "完成", step=10, max_steps=10)
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert abs(kwargs["percent"] - 95.0) < 0.01


# ========== push_tool_call ==========


def test_push_tool_call(progress):
    progress.push_tool_call("task-6", "discover_targets", {"project_id": "p"}, step=1)
    event = _captured_event(progress._mgr)
    assert event["type"] == "tool_call"
    assert event["payload"]["tool"] == "discover_targets"
    assert event["payload"]["args"] == {"project_id": "p"}
    assert event["payload"]["step"] == 1


# ========== push_tool_result ==========


def test_push_tool_result_success(progress):
    progress.push_tool_result("task-7", "x", success=True, data={"a": 1}, step=1)
    event = _captured_event(progress._mgr)
    assert event["type"] == "tool_result"
    assert event["payload"]["success"] is True
    assert event["payload"]["data"] == {"a": 1}
    assert event["payload"]["error"] is None


def test_push_tool_result_failed(progress):
    progress.push_tool_result("task-8", "x", success=False, error="出错了")
    event = _captured_event(progress._mgr)
    assert event["payload"]["success"] is False
    assert event["payload"]["error"] == "出错了"


# ========== push_confirmation_required ==========


def test_push_confirmation_required(progress):
    progress.push_confirmation_required(
        "task-9", "execute_code", {"code": "x"}, "执行代码", risk_level="high", step=2
    )
    event = _captured_event(progress._mgr)
    assert event["type"] == "confirmation_required"
    assert event["payload"]["risk_level"] == "high"
    assert event["payload"]["description"] == "执行代码"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["status"] == "awaiting"


# ========== push_final_response ==========


def test_push_final_response(progress):
    progress.push_final_response("task-10", "最终答案", owner_id="u2")
    event = _captured_event(progress._mgr)
    assert event["type"] == "final_response"
    assert event["payload"]["answer"] == "最终答案"
    assert event["payload"]["references"] == []
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 100.0
    assert kwargs["status"] == "completed"
    assert kwargs["owner_id"] == "u2"


# ========== push_error ==========


def test_push_error(progress):
    progress.push_error("task-11", "出错了", error_code="TIMEOUT", owner_id="u3")
    event = _captured_event(progress._mgr)
    assert event["type"] == "error"
    assert event["payload"]["error"] == "出错了"
    assert event["payload"]["error_code"] == "TIMEOUT"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["owner_id"] == "u3"


# ========== push_task_completed ==========


def test_push_task_completed(progress):
    progress.push_task_completed("task-12", {"summary": "ok"}, owner_id="u4")
    event = _captured_event(progress._mgr)
    assert event["type"] == "task_completed"
    assert event["payload"]["result"]["summary"] == "ok"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 100.0
    assert kwargs["status"] == "completed"


# ========== push_task_cancelled ==========


def test_push_task_cancelled(progress):
    progress.push_task_cancelled("task-13", owner_id="u5")
    event = _captured_event(progress._mgr)
    assert event["type"] == "task_cancelled"
    assert event["payload"]["reason"] == "user_cancelled"
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["status"] == "cancelled"
    assert kwargs["owner_id"] == "u5"


# ========== get_progress 委托 ==========


def test_get_progress_delegates(progress):
    progress._mgr.get_progress.return_value = {"percent": 75.0, "status": "running"}
    result = progress.get_progress("task-14")
    assert result["percent"] == 75.0
    progress._mgr.get_progress.assert_called_with("task-14")


# ========== _emit 无 percent 时回退 ==========


def test_emit_without_percent_uses_current(progress):
    """percent=None 时读取当前进度作为回退"""
    progress._mgr.get_progress.return_value = {"percent": 42.0}
    progress.push_tool_call("task-15", "x", {}, step=1)  # 不传 percent
    kwargs = progress._mgr.update_progress.call_args.kwargs
    assert kwargs["percent"] == 42.0


# ========== 事件结构完整性 ==========


def test_event_payload_contains_required_fields(progress):
    """所有 push 方法的事件含 type/task_id/timestamp/payload 四个字段"""
    progress._mgr.get_progress.return_value = {"percent": 0.0}
    progress.push_task_started("task-16")
    event = _captured_event(progress._mgr)
    assert set(event.keys()) >= {"type", "task_id", "timestamp", "payload"}
    # timestamp 能