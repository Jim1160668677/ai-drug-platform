"""Agent 引擎集成测试 — L1-L4 + E2E 场景

测试 AgentEngine.run() 的端到端行为。mock 外部依赖（LLM/Planner/Registry/
Progress/Audit），保留真实 SessionManager + DB 验证上下文持久化。

测试矩阵：
- L1: 简单问答（无工具，LLM 直接 Final Answer）
- L2: 单工具调用（Action → 工具 → Final Answer）
- L3: 多工具链式调用（2 次 Action → Final Answer）
- L4: 工具失败 / 护栏输入拦截 / 护栏输出标注
- E2E: 上下文持久化 / 审计轨迹 / 超时 / 最大步数耗尽

设计原则：
- 每个测试独立构造 AgentEngine，互不干扰
- mock LLMRouter.complete 用 side_effect 返回序列，模拟多步 ReAct
- mock AuditLogger 避免 SQLite BigInteger autoincrement 不兼容问题
- mock ProgressManager 避免全局 TaskProgressManager 单例状态污染
- 真实 SessionManager + Guardrail 验证核心业务逻辑
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import UserRole, hash_password
from app.models.agent_session import AgentSession, SessionStatus
from app.models.agent_task import AgentTask, TaskStatus
from app.models.user import User
from app.services.agent.engine import AgentEngine
from app.services.agent.planner import PlanStep, PlannerOutput
from app.services.agent.session import SessionManager
from app.services.agent.tools.base import ToolResult
from app.services.llm.guardrail import Guardrail, GuardrailResult


# ========== 辅助函数 ==========


async def _create_user(async_db_session, email: str = "itest@ai-drug.com",
                       role: UserRole = UserRole.FOUNDER) -> User:
    """创建测试用户"""
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password("test123456"),
        role=role,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


async def _create_session(async_db_session, user_id, title="集成测试会话") -> AgentSession:
    """创建测试会话"""
    session = AgentSession(
        user_id=user_id,
        title=title,
        status=SessionStatus.ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    return session


async def _create_task(async_db_session, session_id, user_id,
                       query="分析 EGFR 突变") -> AgentTask:
    """创建测试任务"""
    task = AgentTask(
        session_id=session_id,
        user_id=user_id,
        query=query,
        status=TaskStatus.PENDING,
    )
    async_db_session.add(task)
    await async_db_session.flush()
    return task


def _llm_response(content: str, usage: dict = None, cost: float = 0.0) -> dict:
    """构造 LLM complete 返回值"""
    return {
        "content": content,
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
        "cost_usd": cost,
        "model": "mock-model",
    }


def _react_action(thought: str, tool: str, args: dict) -> str:
    """构造 ReAct Action 格式输出"""
    import json
    return (
        f"Thought: {thought}\n"
        f"Action: {tool}\n"
        f"Action Input: {json.dumps(args, ensure_ascii=False)}"
    )


def _react_final(thought: str, answer: str) -> str:
    """构造 ReAct Final Answer 格式输出"""
    return f"Thought: {thought}\nFinal Answer: {answer}"


def _make_llm_router(responses: list) -> MagicMock:
    """构造 LLMRouter mock — 同时支持 complete 和 stream_complete

    engine.py 现在调用 stream_complete（异步生成器），旧实现仅 mock complete
    会导致 `async for chunk in router.stream_complete(...)` 返回 MagicMock
    （不可异步迭代），所有 ReAct 循环测试失败。本函数让 stream_complete 按
    responses 顺序返回流式 chunk，同时保留 complete 的 side_effect 以兼容
    旧断言（如 await_count、assert_not_awaited）。

    Args:
        responses: LLM 返回值列表，按调用顺序消费
    """
    from tests.conftest import _stream_complete_generator

    router = MagicMock()
    # complete 保留 side_effect 以兼容旧断言（await_count / assert_not_awaited）
    router.complete = AsyncMock(side_effect=list(responses))
    # quick 用于上下文压缩（返回首响应即可）
    router.quick = AsyncMock(return_value=responses[0] if responses else _llm_response("摘要"))

    # stream_complete：按顺序消费 responses，每次返回异步生成器。
    # 用 MagicMock(side_effect=...) 包装以支持 call_count / call_args_list 断言。
    state = {"idx": 0}

    def _stream_factory(*args, **kwargs):
        idx = state["idx"]
        state["idx"] += 1
        resp = responses[min(idx, len(responses) - 1)]
        return _stream_complete_generator(resp)

    router.stream_complete = MagicMock(side_effect=_stream_factory)
    router.select_model = MagicMock(return_value="mock-model")
    return router


def _make_planner(plan_output: PlannerOutput) -> MagicMock:
    """构造 TaskPlanner mock，plan 返回 plan_output"""
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan_output)
    return planner


def _make_registry(tools_info: list = None,
                   tool_results: list = None) -> MagicMock:
    """构造 ToolRegistry mock

    Args:
        tools_info: list_for_user 返回的工具信息列表
        tool_results: execute_tool 按顺序返回的 ToolResult 列表；
                      单个 ToolResult 时所有调用都返回它
    """
    registry = MagicMock()
    registry.list_for_user = MagicMock(return_value=tools_info or [])

    if tool_results is None:
        tool_results = [ToolResult.ok(data={"result": "ok"})]

    if len(tool_results) == 1:
        registry.execute_tool = AsyncMock(return_value=tool_results[0])
    else:
        registry.execute_tool = AsyncMock(side_effect=list(tool_results))

    return registry


def _make_progress() -> MagicMock:
    """构造 ProgressManager mock（避免全局单例污染）"""
    pm = MagicMock()
    for method in (
        "push_task_started", "push_plan", "push_thought",
        "push_tool_call", "push_tool_result", "push_confirmation_required",
        "push_final_response", "push_error", "push_task_completed",
        "push_task_cancelled", "get_progress",
    ):
        setattr(pm, method, MagicMock())
    return pm


def _make_audit() -> MagicMock:
    """构造 AuditLogger mock（避免 SQLite BigInteger autoincrement 问题）"""
    audit = MagicMock()
    for method in (
        "log_action", "log_task_created", "log_tool_call",
        "log_sandbox_exec", "log_confirmation",
    ):
        setattr(audit, method, AsyncMock())
    return audit


def _build_engine(
    async_db_session,
    llm_router,
    planner,
    registry,
    audit=None,
    progress=None,
    guardrail=None,
) -> AgentEngine:
    """构造 AgentEngine 实例

    默认 mock audit/progress，guardrail 用真实实例。
    """
    return AgentEngine(
        db=async_db_session,
        llm_router=llm_router,
        registry=registry,
        planner=planner,
        session_mgr=SessionManager(async_db_session),
        progress=progress or _make_progress(),
        audit=audit or _make_audit(),
        ratelimit=MagicMock(),  # 引擎 run() 不直接用 ratelimit
        guardrail=guardrail or Guardrail(),
    )


# ========== L1: 简单问答（无工具）==========


@pytest.mark.asyncio
async def test_l1_simple_qa_no_tools(async_db_session):
    """L1: LLM 第一步直接返回 Final Answer，无工具调用

    验证：
    - status=completed
    - answer 为 Final Answer 内容
    - registry.execute_tool 未被调用
    - steps 长度为 1
    """
    user = await _create_user(async_db_session, "l1@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_final("分析完成", "EGFR 是 NSCLC 的重要驱动基因")),
    ])
    planner = _make_planner(PlannerOutput.empty(reasoning="无需工具"))
    registry = _make_registry(tools_info=[])
    audit = _make_audit()

    engine = _build_engine(async_db_session, llm_router, planner, registry, audit=audit)

    result = await engine.run(
        task_id=task.id,
        query="分析 EGFR 突变",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert "EGFR" in result["answer"]
    assert len(result["steps"]) == 1
    assert result["steps"][0]["final_answer"] is not None
    # 工具未被调用
    registry.execute_tool.assert_not_awaited()
    # 审计无工具调用记录（L1 无工具）
    audit.log_tool_call.assert_not_awaited()


# ========== L2: 单工具调用 ==========


@pytest.mark.asyncio
async def test_l2_single_tool_call(async_db_session):
    """L2: LLM 第一步 Action，第二步 Final Answer

    验证：
    - registry.execute_tool 被调用 1 次
    - status=completed
    - steps 长度为 2
    - audit.log_tool_call 被调用 1 次
    """
    user = await _create_user(async_db_session, "l2@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_action(
            "需要查询靶点", "discover_targets",
            {"project_id": "test-project"},
        )),
        _llm_response(_react_final("靶点已确认", "EGFR 是推荐靶点")),
    ])
    planner = _make_planner(PlannerOutput(
        steps=[PlanStep(id="s1", tool="discover_targets",
                        args={"project_id": "test-project"})],
        parallel_layers=[["s1"]],
    ))
    registry = _make_registry(
        tools_info=[{"name": "discover_targets", "description": "发现靶点"}],
        tool_results=[ToolResult.ok(data={"targets": ["EGFR"]})],
    )
    audit = _make_audit()

    engine = _build_engine(async_db_session, llm_router, planner, registry, audit=audit)

    result = await engine.run(
        task_id=task.id,
        query="发现 EGFR 靶点",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert len(result["steps"]) == 2
    registry.execute_tool.assert_awaited_once()
    audit.log_tool_call.assert_awaited_once()
    # 验证审计记录工具成功
    assert audit.log_tool_call.call_args.kwargs["success"] is True
    assert audit.log_tool_call.call_args.kwargs["tool"] == "discover_targets"


# ========== L3: 多工具链式调用 ==========


@pytest.mark.asyncio
async def test_l3_multi_tool_chain(async_db_session):
    """L3: LLM 两次 Action，第三次 Final Answer

    验证：
    - registry.execute_tool 被调用 2 次
    - status=completed
    - steps 长度为 3
    - audit.log_tool_call 被调用 2 次
    """
    user = await _create_user(async_db_session, "l3@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_action("第一步：查询靶点", "discover_targets", {})),
        _llm_response(_react_action("第二步：设计分子", "design_molecules", {"target": "EGFR"})),
        _llm_response(_react_final("分子设计完成", "已生成 3 个候选分子")),
    ])
    planner = _make_planner(PlannerOutput(
        steps=[
            PlanStep(id="s1", tool="discover_targets", args={}),
            PlanStep(id="s2", tool="design_molecules", args={"target": "EGFR"},
                     depends_on=["s1"]),
        ],
        parallel_layers=[["s1"], ["s2"]],
    ))
    registry = _make_registry(
        tools_info=[
            {"name": "discover_targets", "description": "发现靶点"},
            {"name": "design_molecules", "description": "设计分子"},
        ],
        tool_results=[
            ToolResult.ok(data={"targets": ["EGFR"]}),
            ToolResult.ok(data={"molecules": ["mol1", "mol2", "mol3"]}),
        ],
    )
    audit = _make_audit()

    engine = _build_engine(async_db_session, llm_router, planner, registry, audit=audit)

    result = await engine.run(
        task_id=task.id,
        query="发现靶点并设计分子",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert len(result["steps"]) == 3
    assert registry.execute_tool.await_count == 2
    assert audit.log_tool_call.await_count == 2


# ========== L4: 工具执行失败 ==========


@pytest.mark.asyncio
async def test_l4_tool_execution_failure(async_db_session):
    """L4: 工具返回 fail，引擎继续循环并最终生成答案

    验证：
    - status=completed（工具失败不终止引擎）
    - audit.log_tool_call 记录 success=False
    - 最终仍生成答案
    """
    user = await _create_user(async_db_session, "l4fail@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_action("查询靶点", "discover_targets", {})),
        _llm_response(_react_final("工具失败但给出兜底答案", "基于已有知识，EGFR 是靶点")),
    ])
    planner = _make_planner(PlannerOutput(
        steps=[PlanStep(id="s1", tool="discover_targets", args={})],
        parallel_layers=[["s1"]],
    ))
    registry = _make_registry(
        tools_info=[{"name": "discover_targets", "description": "发现靶点"}],
        tool_results=[ToolResult.fail(error="数据库连接失败")],
    )
    audit = _make_audit()

    engine = _build_engine(async_db_session, llm_router, planner, registry, audit=audit)

    result = await engine.run(
        task_id=task.id,
        query="发现靶点",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert "EGFR" in result["answer"]
    registry.execute_tool.assert_awaited_once()
    # 审计记录失败
    audit.log_tool_call.assert_awaited_once()
    assert audit.log_tool_call.call_args.kwargs["success"] is False


# ========== L4: 护栏输入拦截 ==========


@pytest.mark.asyncio
async def test_l4_guardrail_input_blocked(async_db_session):
    """L4: 输入被护栏拦截，任务标记失败

    验证：
    - status=failed
    - error 含护栏拦截信息
    - LLM 未被调用
    """
    user = await _create_user(async_db_session, "l4gi@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    # mock guardrail 拦截输入
    guardrail = MagicMock()
    guardrail.check_input = MagicMock(return_value=GuardrailResult(
        passed=False, blocked=True, reasons=["医学红线-诊断请求拦截"],
    ))
    guardrail.check_output = MagicMock(return_value=GuardrailResult(passed=True))

    llm_router = _make_llm_router([_llm_response("不应被调用")])
    planner = _make_planner(PlannerOutput.empty())
    registry = _make_registry()

    engine = _build_engine(
        async_db_session, llm_router, planner, registry, guardrail=guardrail,
    )

    result = await engine.run(
        task_id=task.id,
        query="帮我诊断这个病人是不是得了癌症",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.FAILED
    assert "护栏" in result["error"] or "拦截" in result["error"]
    # LLM 未被调用
    llm_router.stream_complete.assert_not_called()


# ========== L4: 护栏输出标注（非拦截）==========


@pytest.mark.asyncio
async def test_l4_guardrail_output_annotated(async_db_session):
    """L4: 输出含预后预测，护栏添加免责声明标注

    验证：
    - status=completed（标注不拦截）
    - answer 追加免责声明
    """
    user = await _create_user(async_db_session, "l4go@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    # mock guardrail：输入通过，输出含标注
    guardrail = MagicMock()
    guardrail.check_input = MagicMock(return_value=GuardrailResult(passed=True))
    guardrail.check_output = MagicMock(return_value=GuardrailResult(
        passed=True, blocked=False,
        reasons=["预后预测标注"],
        annotations=["【预后免责声明】请结合临床医生综合评估"],
    ))

    llm_router = _make_llm_router([
        _llm_response(_react_final("分析完成", "预计生存期 12 个月")),
    ])
    planner = _make_planner(PlannerOutput.empty())
    registry = _make_registry()

    engine = _build_engine(
        async_db_session, llm_router, planner, registry, guardrail=guardrail,
    )

    result = await engine.run(
        task_id=task.id,
        query="分析预后",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert "免责声明" in result["answer"]
    assert "12 个月" in result["answer"]


# ========== E2E: 上下文持久化 ==========


@pytest.mark.asyncio
async def test_e2e_session_context_persisted(async_db_session):
    """E2E: 任务完成后 AgentSession.context.messages 非空

    验证：
    - session.context.messages 包含 user 消息和 final assistant 消息
    - message_count >= 2
    """
    user = await _create_user(async_db_session, "e2ectx@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_final("完成", "EGFR 靶点分析完成")),
    ])
    planner = _make_planner(PlannerOutput.empty())
    registry = _make_registry()

    engine = _build_engine(async_db_session, llm_router, planner, registry)

    await engine.run(
        task_id=task.id,
        query="分析 EGFR",
        session_id=session.id,
        user=user,
    )
    await async_db_session.commit()

    # 重新查询会话，验证上下文持久化
    refreshed = await async_db_session.get(AgentSession, session.id)
    assert refreshed is not None
    ctx = refreshed.context or {}
    messages = ctx.get("messages", [])
    assert len(messages) >= 2, f"消息数不足: {len(messages)}"
    # 第一条是 user 消息
    assert messages[0]["role"] == "user"
    assert "EGFR" in messages[0]["content"]
    # 最后一条是 final assistant 消息
    assert messages[-1]["role"] == "assistant"
    assert refreshed.message_count >= 2


# ========== E2E: 审计轨迹完整 ==========


@pytest.mark.asyncio
async def test_e2e_audit_trail_complete(async_db_session):
    """E2E: 工具调用后 AuditLogger.log_tool_call 被正确调用

    验证：
    - log_tool_call 被调用，参数含 user_id/role/task_id/tool/success
    - success=True 对应工具成功执行
    """
    user = await _create_user(async_db_session, "e2audit@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    llm_router = _make_llm_router([
        _llm_response(_react_action("查询", "discover_targets", {})),
        _llm_response(_react_final("完成", "靶点已确认")),
    ])
    planner = _make_planner(PlannerOutput(
        steps=[PlanStep(id="s1", tool="discover_targets", args={})],
        parallel_layers=[["s1"]],
    ))
    registry = _make_registry(
        tools_info=[{"name": "discover_targets", "description": "发现靶点"}],
        tool_results=[ToolResult.ok(data={"targets": ["EGFR"]})],
    )
    audit = _make_audit()

    engine = _build_engine(async_db_session, llm_router, planner, registry, audit=audit)

    await engine.run(
        task_id=task.id,
        query="发现靶点",
        session_id=session.id,
        user=user,
    )

    audit.log_tool_call.assert_awaited_once()
    kwargs = audit.log_tool_call.call_args.kwargs
    assert kwargs["tool"] == "discover_targets"
    assert kwargs["success"] is True
    assert kwargs["task_id"] == str(task.id)
    assert kwargs["user_id"] == str(user.id)


# ========== E2E: 任务超时 ==========


@pytest.mark.asyncio
async def test_e2e_task_timeout(async_db_session, monkeypatch):
    """E2E: 任务超时，标记失败

    验证：
    - status=failed
    - error 含 "超时"
    """
    user = await _create_user(async_db_session, "e2to@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    # 设置极短超时，进入循环立即触发
    monkeypatch.setattr(settings, "AGENT_TASK_TIMEOUT_SEC", 0)

    llm_router = _make_llm_router([_llm_response("不应被调用")])
    planner = _make_planner(PlannerOutput.empty())
    registry = _make_registry()

    engine = _build_engine(async_db_session, llm_router, planner, registry)

    result = await engine.run(
        task_id=task.id,
        query="分析靶点",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.FAILED
    assert "超时" in result["error"]
    # LLM 未被调用（超时在 LLM 调用前触发）
    llm_router.stream_complete.assert_not_called()


# ========== E2E: 最大步数耗尽 ==========


@pytest.mark.asyncio
async def test_e2e_max_steps_exhaustion(async_db_session, monkeypatch):
    """E2E: LLM 永不返回 Final Answer，达到 max_steps 后兜底生成答案

    验证：
    - status=completed（兜底生成答案）
    - answer 为兜底内容
    - LLM complete 被调用 max_steps + 1 次（循环 + 兜底）
    """
    user = await _create_user(async_db_session, "e2ms@ai-drug.com")
    session = await _create_session(async_db_session, user.id)
    task = await _create_task(async_db_session, session.id, user.id)
    await async_db_session.commit()

    monkeypatch.setattr(settings, "AGENT_MAX_STEPS", 2)

    # 前 2 次返回 Action（循环耗尽），第 3 次给兜底答案生成
    llm_router = _make_llm_router([
        _llm_response(_react_action("步骤1", "discover_targets", {})),
        _llm_response(_react_action("步骤2", "discover_targets", {})),
        _llm_response("基于已有信息的兜底答案"),
    ])
    planner = _make_planner(PlannerOutput(
        steps=[PlanStep(id="s1", tool="discover_targets", args={})],
        parallel_layers=[["s1"]],
    ))
    registry = _make_registry(
        tools_info=[{"name": "discover_targets", "description": "发现靶点"}],
        tool_results=[ToolResult.ok(data={"result": "ok"})],
    )

    engine = _build_engine(async_db_session, llm_router, planner, registry)

    result = await engine.run(
        task_id=task.id,
        query="分析靶点",
        session_id=session.id,
        user=user,
    )

    assert result["status"] == TaskStatus.COMPLETED
    assert "兜底答案" in result["answer"]
    # 2 次 ReAct 循环 + 1 次兜底生成（引擎现在调用 stream_complete 而非 complete）
    assert llm_router.stream_complete.call_count == 3
