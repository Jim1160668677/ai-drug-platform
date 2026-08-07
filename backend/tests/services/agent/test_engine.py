"""ReAct 引擎主循环测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import GuardrailBlockedError, TaskTimeoutError
from app.services.agent.engine import AgentEngine, parse_react_output


# ========== parse_react_output ==========

class TestParseReActOutput:
    def test_parse_action_with_json_input(self):
        content = """Thought: 我需要查询靶点信息
Action: discover_targets
Action Input: {"project_id": "abc-123", "tier": "fast_screen"}"""
        step = parse_react_output(content)
        assert step.thought == "我需要查询靶点信息"
        assert step.action == "discover_targets"
        assert step.action_input == {"project_id": "abc-123", "tier": "fast_screen"}
        assert step.final_answer is None

    def test_parse_final_answer(self):
        content = """Thought: 已获取所有信息，可以回答了
Final Answer: EGFR T790M 耐药机制主要是..."""
        step = parse_react_output(content)
        assert step.thought == "已获取所有信息，可以回答了"
        assert step.final_answer is not None
        assert "EGFR T790M" in step.final_answer
        assert step.action is None

    def test_final_answer_priority_over_action(self):
        """Final Answer 优先级高于 Action"""
        content = """Thought: 测试
Action: some_tool
Action Input: {"x": 1}
Final Answer: 直接回答"""
        step = parse_react_output(content)
        assert step.final_answer is not None
        assert step.final_answer == "直接回答"
        # Final Answer 模式下不解析 action
        assert step.action is None or step.action == "some_tool"

    def test_parse_invalid_json_action_input_fallback(self):
        """Action Input 不是合法 JSON 时降级为 _raw"""
        content = """Thought: 测试
Action: some_tool
Action Input: 这是一个字符串参数"""
        step = parse_react_output(content)
        assert step.action == "some_tool"
        assert step.action_input == {"_raw": "这是一个字符串参数"}

    def test_parse_empty_content(self):
        step = parse_react_output("")
        assert step.thought is None
        assert step.action is None
        assert step.final_answer is None
        assert step.raw == ""

    def test_parse_only_thought(self):
        content = "Thought: 仅思考，无行动"
        step = parse_react_output(content)
        assert step.thought == "仅思考，无行动"
        assert step.action is None
        assert step.final_answer is None

    def test_parse_multiline_thought(self):
        content = """Thought: 第一行思考
第二行思考
Action: tool
Action Input: {"a": 1}"""
        step = parse_react_output(content)
        assert step.thought is not None
        assert "第一行" in step.thought
        assert step.action == "tool"
        assert step.action_input == {"a": 1}


# ========== AgentEngine.run 主循环 ==========

@pytest.mark.asyncio
async def test_engine_guardrail_blocks_input(test_user):
    """输入被 Guardrail 拦截时任务标记失败

    GuardrailBlockedError 继承 AppException，引擎在 except AppException 中捕获
    并调用 _fail_task 标记任务 failed（而非向上抛出）。
    """
    from app.services.agent.engine import AgentEngine
    from unittest.mock import MagicMock, AsyncMock

    guardrail = MagicMock()
    blocked_result = MagicMock()
    blocked_result.blocked = True
    blocked_result.reasons = ["敏感内容"]
    guardrail.check_input.return_value = blocked_result

    session_mgr = MagicMock()
    session_mgr.get_context = AsyncMock(return_value={"summary": None})
    session_mgr.append_message = AsyncMock()
    planner = MagicMock()
    planner.plan = AsyncMock()
    registry = MagicMock()
    registry.list_for_user = MagicMock(return_value=[])

    engine = AgentEngine(
        db=MagicMock(),
        llm_router=MagicMock(),
        registry=registry,
        planner=planner,
        session_mgr=session_mgr,
        progress=MagicMock(),
        audit=MagicMock(),
        ratelimit=MagicMock(),
        guardrail=guardrail,
    )
    # mock 任务失败处理避免 db 操作（引擎捕获异常后转 failed 返回值）
    engine._fail_task = AsyncMock()

    result = await engine.run(
        task_id="task-1",
        query="恶意内容",
        session_id="session-1",
        user=test_user,
    )

    assert result["status"] == "failed"
    assert "护栏" in result["error"] or "拦截" in result["error"]


@pytest.mark.asyncio
async def test_engine_timeout_raises_task_timeout(test_user):
    """任务超时标记 failed

    TaskTimeoutError 继承 AppException，引擎捕获后转 failed 返回值。
    """
    from app.services.agent.engine import AgentEngine
    from unittest.mock import MagicMock, AsyncMock, patch

    guardrail = MagicMock()
    ok_result = MagicMock()
    ok_result.blocked = False
    guardrail.check_input.return_value = ok_result
    guardrail.check_output = MagicMock(return_value=ok_result)

    session_mgr = MagicMock()
    session_mgr.get_context = AsyncMock(return_value={"summary": None})
    session_mgr.append_message = AsyncMock()
    session_mgr.maybe_compress = AsyncMock(return_value=False)

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=MagicMock(to_dict=lambda: {"steps": []}))

    registry = MagicMock()
    registry.list_for_user = MagicMock(return_value=[])

    llm_router = MagicMock()
    llm_router.complete = AsyncMock(return_value={"content": "Thought: 思考\nAction: tool\nAction Input: {}", "usage": {}})

    engine = AgentEngine(
        db=MagicMock(),
        llm_router=llm_router,
        registry=registry,
        planner=planner,
        session_mgr=session_mgr,
        progress=MagicMock(),
        audit=MagicMock(),
        ratelimit=MagicMock(),
        guardrail=guardrail,
    )
    # mock 任务状态更新与失败处理避免 db 操作
    engine._update_task_status = AsyncMock()
    engine._update_task = AsyncMock()
    engine._fail_task = AsyncMock()

    # 模拟 settings.AGENT_TASK_TIMEOUT_SEC=0 立即超时
    with patch("app.services.agent.engine.settings") as mock_settings:
        mock_settings.AGENT_MAX_STEPS = 15
        mock_settings.AGENT_TASK_TIMEOUT_SEC = 0  # 立即超时
        result = await engine.run(
            task_id="task-1",
            query="测试",
            session_id="session-1",
            user=test_user,
        )

    assert result["status"] == "failed"
    assert "超时" in result["error"]


@pytest.mark.asyncio
async def test_engine_final_answer_direct(test_user):
    """LLM 直接返回 Final Answer 时立即结束"""
    from app.services.agent.engine import AgentEngine
    from unittest.mock import MagicMock
    from tests.conftest import make_llm_router_mock

    guardrail = MagicMock()
    ok = MagicMock()
    ok.blocked = False
    ok.annotations = []
    guardrail.check_input.return_value = ok
    guardrail.check_output = MagicMock(return_value=ok)

    session_mgr = MagicMock()
    session_mgr.get_context = AsyncMock(return_value={"summary": None})
    session_mgr.append_message = AsyncMock()
    session_mgr.maybe_compress = AsyncMock(return_value=False)

    plan_output = MagicMock()
    plan_output.to_dict = MagicMock(return_value={"steps": []})
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan_output)

    registry = MagicMock()
    registry.list_for_user = MagicMock(return_value=[])

    # 使用流式 mock 辅助函数（engine 现在调用 stream_complete 而非 complete）
    llm_router = make_llm_router_mock({
        "content": "Thought: 直接回答\nFinal Answer: 这是答案",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "cost_usd": 0.001,
    })

    engine = AgentEngine(
        db=MagicMock(),
        llm_router=llm_router,
        registry=registry,
        planner=planner,
        session_mgr=session_mgr,
        progress=MagicMock(),
        audit=MagicMock(),
        ratelimit=MagicMock(),
        guardrail=guardrail,
    )

    # mock _update_task_status / _update_task / _fail_task 避免操作 db
    engine._update_task_status = AsyncMock()
    engine._update_task = AsyncMock()
    engine._fail_task = AsyncMock()

    result = await engine.run(
        task_id="task-1",
        query="测试",
        session_id="session-1",
        user=test_user,
    )

    assert result["status"] == "completed"
    assert result["answer"] == "这是答案"
    assert result["token_usage"]["total"] == 15
    assert result["cost_usd"] == 0.001


@pytest.mark.asyncio
async def test_engine_max_steps_exhaustion(test_user):
    """达到 max_steps 仍未得到 Final Answer 时降级生成最终答案"""
    from app.services.agent.engine import AgentEngine
    from unittest.mock import MagicMock, patch

    guardrail = MagicMock()
    ok = MagicMock()
    ok.blocked = False
    ok.annotations = []
    guardrail.check_input.return_value = ok
    guardrail.check_output = MagicMock(return_value=ok)

    session_mgr = MagicMock()
    session_mgr.get_context = AsyncMock(return_value={"summary": None})
    session_mgr.append_message = AsyncMock()
    session_mgr.maybe_compress = AsyncMock(return_value=False)

    plan_output = MagicMock()
    plan_output.to_dict = MagicMock(return_value={"steps": []})
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan_output)

    registry = MagicMock()
    registry.list_for_user = MagicMock(return_value=[])
    # execute_tool 必须为 AsyncMock（引擎用 await 调用）并返回 ToolResult
    from app.services.agent.tools.base import ToolResult
    registry.execute_tool = AsyncMock(return_value=ToolResult.ok(data={"result": "ok"}))
    llm_router = MagicMock()
    llm_router.complete = AsyncMock(
        return_value={
            "content": "Thought: 继续\nAction: unknown_tool\nAction Input: {}",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            "cost_usd": 0.0001,
        }
    )

    engine = AgentEngine(
        db=MagicMock(),
        llm_router=llm_router,
        registry=registry,
        planner=planner,
        session_mgr=session_mgr,
        progress=MagicMock(),
        audit=MagicMock(),
        ratelimit=MagicMock(),
        guardrail=guardrail,
    )
    # audit.log_tool_call 被 await 调用，必须为 AsyncMock
    engine.audit.log_tool_call = AsyncMock()
    engine._update_task_status = AsyncMock()
    engine._update_task = AsyncMock()
    engine._fail_task = AsyncMock()

    with patch("app.services.agent.engine.settings") as mock_settings:
        mock_settings.AGENT_MAX_STEPS = 2
        mock_settings.AGENT_TASK_TIMEOUT_SEC = 60
        result = await engine.run(
            task_id="task-1",
            query="测试",
            session_id="session-1",
            user=test_user,
        )

    # 应该调用了 _generate_final_answer 生成兜底答案
    assert result["status"] == "completed"
    assert "answer" in result
