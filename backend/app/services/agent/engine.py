"""Agent ReAct 引擎 — 推理 + 行动主循环

设计来源：2026-07-18-agent-react-design.md §3 / 2026-07-18-agent-functional-design.md §3

主循环：
1. 加载会话上下文
2. 输入 Guardrail 校验
3. Planner 生成 DAG 计划
4. while step < MAX_STEPS and not done:
   - LLM 推理 → thought / action / action_input (或 final_answer)
   - 工具调用：权限校验 → 副作用确认 → 执行 → 观察结果
   - 上下文压缩
5. 输出 Guardrail 校验
6. 生成最终答案
7. 更新任务/会话/审计
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    GuardrailBlockedError,
    TaskTimeoutError,
)
from app.core.security import UserRole
from app.models.agent_task import AgentTask, TaskStatus
from app.models.user import User
from app.services.agent.audit import AuditLogger
from app.services.agent.dag_executor import DagExecutor, DagExecutionResult
from app.services.agent.knowledge_gap import GapDetectionResult, KnowledgeGapDetector
from app.services.agent.planner import PlannerInput, PlannerOutput, TaskPlanner
from app.services.agent.progress import ProgressManager
from app.services.agent.prompts import (
    FINAL_ANSWER_PROMPT,
    REACT_SYSTEM_PROMPT,
    build_project_context,
    is_simple_question,
)
from app.services.agent.ratelimit import RateLimiter
from app.services.agent.reflection import (
    RecoveryStrategy,
    ReflectionResult,
    Reflector,
)
from app.services.agent.session import SessionManager
from app.services.agent.tool_quality import ToolQualityTracker, get_tool_quality_tracker
from app.services.llm.guardrail import Guardrail, get_guardrail
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class ReActStep:
    """单步 ReAct 输出"""
    thought: Optional[str] = None
    action: Optional[str] = None        # 工具名
    action_input: Optional[Dict] = None  # 工具参数
    final_answer: Optional[str] = None   # 最终答案
    raw: str = ""                        # 原始 LLM 输出


# ReAct 解析正则
# Thought / Action Input 可能跨行，用非贪婪 + 前瞻分隔到下一个字段或末尾。
# 前瞻模式 \n[A-Z][a-z]+(?:\s[A-Z][a-z]+)?: 匹配字段标记，支持单词字段（Thought/Action）
# 和双词字段（Action Input/Final Answer）——此前用 [A-Z][a-z]+: 无法匹配双词字段
# （"Final Answer:" 中 Final 后是空格非冒号），导致 Thought 贪婪吞掉 Final Answer 整段。
_THOUGHT_RE = re.compile(
    r"Thought:\s*(.*?)(?=\n[A-Z][a-z]+(?:\s[A-Z][a-z]+)?:|\Z)", re.DOTALL
)
_ACTION_INPUT_RE = re.compile(
    r"Action Input:\s*(.*?)(?=\n[A-Z][a-z]+(?:\s[A-Z][a-z]+)?:|\Z)", re.DOTALL
)
_FINAL_ANSWER_RE = re.compile(r"Final Answer:\s*(.*)", re.DOTALL)
# Action 行只有工具名（独占一行），直接匹配到行尾。
# 注意：不能用前瞻 \n[A-Z][a-z]+: 分隔，因为下一行 "Action Input:" 中的
# "Action" 后面是空格而非冒号，不匹配 [A-Z][a-z]+:，会导致 Action 贪婪吞掉
# "Action Input: {...}" 整段。改用 .+（不匹配换行）精确取行内工具名。
_ACTION_RE = re.compile(r"Action:\s*(.+)")


def parse_react_output(content: str) -> ReActStep:
    """解析 LLM 的 ReAct 格式输出

    支持两种结束方式：
    1. Action + Action Input：调用工具
    2. Final Answer：直接回答
    """
    step = ReActStep(raw=content)

    thought_m = _THOUGHT_RE.search(content)
    if thought_m:
        step.thought = thought_m.group(1).strip()

    final_m = _FINAL_ANSWER_RE.search(content)
    if final_m:
        step.final_answer = final_m.group(1).strip()
        return step  # Final Answer 优先级最高

    action_m = _ACTION_RE.search(content)
    action_input_m = _ACTION_INPUT_RE.search(content)
    if action_m:
        step.action = action_m.group(1).strip()
        if action_input_m:
            raw_input = action_input_m.group(1).strip()
            try:
                step.action_input = json.loads(raw_input)
            except json.JSONDecodeError:
                # 容错：将原始字符串作为单一参数
                step.action_input = {"_raw": raw_input}
    return step


class AgentEngine:
    """ReAct 引擎主类

    Usage:
        engine = AgentEngine(db, llm_router, registry, ...)
        result = await engine.run(task_id, query, session_id, user)
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_router: LLMRouter,
        registry,  # ToolRegistry（避免循环引用用 duck typing）
        planner: TaskPlanner,
        session_mgr: SessionManager,
        progress: ProgressManager,
        audit: AuditLogger,
        ratelimit: RateLimiter,
        guardrail: Optional[Guardrail] = None,
    ):
        self.db = db
        self.llm_router = llm_router
        self.registry = registry
        self.planner = planner
        self.session_mgr = session_mgr
        self.progress = progress
        self.audit = audit
        self.ratelimit = ratelimit
        self.guardrail = guardrail or get_guardrail()

        # ===== Agent 增强组件 =====
        # 1. 工具失败反思器（工具失败时分析原因 + 恢复建议）
        self.reflector: Optional[Reflector] = None
        if getattr(settings, "AGENT_USE_REFLECTION", True):
            self.reflector = Reflector(llm_router=llm_router)

        # 2. DAG 并行执行器（计划明确时按拓扑层并行执行工具）
        self.dag_executor: Optional[DagExecutor] = None
        if getattr(settings, "AGENT_USE_DAG_EXECUTOR", False):
            self.dag_executor = DagExecutor(registry=registry)

        # 3. 工具质量跟踪器（记录成功率/耗时，推荐最优工具）
        self.tool_quality: Optional[ToolQualityTracker] = None
        if getattr(settings, "AGENT_TOOL_QUALITY_TRACKING", True):
            self.tool_quality = get_tool_quality_tracker()

        # 4. 知识盲区检测器（连续空结果时自动触发网络搜索）
        self.gap_detector: Optional[KnowledgeGapDetector] = None
        if getattr(settings, "AGENT_USE_KNOWLEDGE_GAP_DETECTION", True):
            self.gap_detector = KnowledgeGapDetector(
                llm_router=llm_router,
            )

    async def run(
        self,
        task_id: UUID,
        query: str,
        session_id: UUID,
        user: User,
        project_id: Optional[UUID] = None,
        tier: str = "fast_screen",
        progress_tracker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """执行一次完整的 ReAct 推理

        Returns:
            {
                "answer": str,
                "plan": dict,
                "steps": [step_trace, ...],
                "token_usage": {...},
                "cost_usd": float,
                "duration_sec": float,
                "status": "completed" | "failed",
                "error": Optional[str],
            }
        """
        start_ts = time.time()
        max_steps = settings.AGENT_MAX_STEPS
        timeout_sec = settings.AGENT_TASK_TIMEOUT_SEC
        task_id_str = str(task_id)
        owner_id = str(user.id)
        role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        if progress_tracker is not None:
            self.progress_tracker = progress_tracker

        # 累计统计
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        step_traces: List[Dict[str, Any]] = []

        try:
            # 1. 输入 Guardrail 校验
            input_check = self.guardrail.check_input(query)
            if input_check.blocked:
                raise GuardrailBlockedError(
                    "输入被安全护栏拦截",
                    rule=",".join(input_check.reasons),
                )

            # 1.5 重置知识盲区检测器（新任务开始）
            if self.gap_detector:
                self.gap_detector.reset()

            # 2. 获取会话上下文
            ctx = await self.session_mgr.get_context(session_id)
            context_summary = ctx.get("summary") or ""

            # 3. 追加用户消息到上下文
            await self.session_mgr.append_message(
                session_id, role="user", content=query
            )

            # 3.5 加载项目上下文（让 Agent "看到" 项目数据，无需每次调用工具查询）
            project_context_str = await self._load_project_context(project_id)

            # 4. 任务状态 → planning
            await self._update_task_status(task_id, TaskStatus.PLANNING)

            # 4.5 简单问答跳过 Planner，直接进入 ReAct（节省一次 LLM 调用，加速响应）
            available_tools = self.registry.list_for_user(user)
            skip_planner = (
                getattr(settings, "AGENT_SKIP_PLANNER_FOR_SIMPLE_Q", True)
                and is_simple_question(query)
            )

            if skip_planner:
                logger.info(f"跳过 Planner（简单问答）：{query[:60]}")
                plan_output = PlannerOutput.empty(
                    reasoning="简单问答，直接进入 ReAct"
                )
            else:
                plan_output: PlannerOutput = await self.planner.plan(
                    PlannerInput(
                        query=query,
                        context_summary=context_summary,
                        available_tools=available_tools,
                    )
                )

            self.progress.push_task_started(
                task_id_str, plan_output.to_dict(), owner_id=owner_id
            )
            self.progress.push_plan(task_id_str, plan_output.to_dict())

            # 持久化 plan
            await self._update_task(task_id, plan=plan_output.to_dict())

            # 6. 任务状态 → running
            await self._update_task_status(task_id, TaskStatus.RUNNING)

            # 6.5 DAG 并行执行（若启用且计划有多个步骤）
            # DAG 模式：先并行执行计划中的工具，将结果作为 observation 注入 ReAct
            # ReAct 循环随后基于这些结果生成最终答案
            observation: str = ""  # 累积工具观察结果
            if (
                self.dag_executor is not None
                and plan_output.steps
                and len(plan_output.steps) > 1
            ):
                try:
                    dag_result = await self.dag_executor.execute(
                        plan=plan_output,
                        user=user,
                        task_id=task_id_str,
                        session_id=str(session_id),
                        project_id=str(project_id) if project_id else None,
                        db=self.db,
                        progress=self.progress,
                    )
                    observation = dag_result.to_observation(max_chars=4000)
                    logger.info(
                        f"DAG 执行完成: {len(dag_result.results)} 步, "
                        f"失败 {len(dag_result.failed_steps)} 步, "
                        f"耗时 {dag_result.total_duration_ms}ms"
                    )
                    # 记录 DAG 步骤的 step_traces
                    for r in dag_result.results:
                        step_traces.append({
                            "step": len(step_traces) + 1,
                            "thought": f"[DAG] {r.step_id}: {r.tool}",
                            "action": r.tool,
                            "action_input": r.args,
                            "final_answer": None,
                            "dag_result": r.to_dict(),
                        })
                        # 记录工具质量
                        if self.tool_quality:
                            await self.tool_quality.record(
                                tool_name=r.tool,
                                success=r.success,
                                duration_ms=r.duration_ms,
                                error=r.error,
                            )
                except Exception as e:
                    logger.warning(f"DAG 执行失败，降级到标准 ReAct: {e}")
                    observation = f"DAG 执行异常: {e}，降级到逐步推理。"

            # 7. ReAct 主循环
            final_answer: Optional[str] = None
            step = 0

            while step < max_steps:
                # 超时检查
                if time.time() - start_ts > timeout_sec:
                    raise TaskTimeoutError(
                        f"任务超时（>{timeout_sec}s），已完成 {step} 步"
                    )

                step += 1
                step_t0 = time.perf_counter()
                self.progress.push_thought(
                    task_id_str,
                    f"开始第 {step} 步推理",
                    step=step,
                    max_steps=max_steps,
                )

                # 7.1 构造 ReAct prompt
                prompt = self._build_react_prompt(
                    query=query,
                    context_summary=context_summary,
                    observation=observation,
                    available_tools=available_tools,
                    step=step,
                    max_steps=max_steps,
                )

                # 7.2 调用 LLM（流式 — 边生成边推送 token 到前端，降低首字延迟）
                try:
                    system_prompt = REACT_SYSTEM_PROMPT.format(
                        max_steps=max_steps,
                        project_context=project_context_str,
                    )
                    full_content_parts: List[str] = []
                    llm_result: Dict[str, Any] = {}
                    async for chunk in self.llm_router.stream_complete(
                        prompt,
                        tier=tier,
                        system=system_prompt,
                    ):
                        chunk_type = chunk.get("type")
                        if chunk_type == "token":
                            token_text = chunk.get("content", "")
                            if token_text:
                                full_content_parts.append(token_text)
                                # 推送流式 token 到前端
                                self.progress.push_token(
                                    task_id_str,
                                    token_text,
                                    step=step,
                                    owner_id=owner_id,
                                )
                        elif chunk_type == "done":
                            llm_result = chunk
                            # 若 LLM 返回的完整内容比累积的多/少，以 done 为准
                            done_content = chunk.get("content", "")
                            if done_content:
                                full_content_parts = [done_content]
                        elif chunk_type == "error":
                            err_msg = chunk.get("content", "LLM 调用失败")
                            raise AppException(err_msg)

                    content = "".join(full_content_parts) or llm_result.get("content", "")
                except AppException:
                    raise
                except Exception as e:
                    logger.error(f"LLM 调用失败 step={step}: {e}", exc_info=True)
                    raise AppException(f"LLM 调用失败: {e}")

                # 累计 token / 成本
                usage = llm_result.get("usage", {}) or {}
                total_prompt_tokens += usage.get("prompt_tokens", 0) or 0
                total_completion_tokens += usage.get("completion_tokens", 0) or 0
                total_cost += llm_result.get("cost_usd", 0) or 0
                step_tokens = int(usage.get("total", 0) or 0)
                step_cost = float(llm_result.get("cost_usd", 0) or 0)

                content = content or ""

                # 7.3 解析 ReAct 输出
                react_step = parse_react_output(content)
                step_traces.append(
                    {
                        "step": step,
                        "thought": react_step.thought,
                        "action": react_step.action,
                        "action_input": react_step.action_input,
                        "final_answer": react_step.final_answer,
                    }
                )

                # emit_step_trace (status=running) — parse 之后、工具执行之前
                if hasattr(self, "progress_tracker") and self.progress_tracker:
                    try:
                        await self.progress_tracker.emit_step_trace(
                            run_id=task_id_str,
                            step_index=step,
                            thought=react_step.thought or "",
                            action=react_step.action or "",
                            action_input=react_step.action_input,
                            status="running",
                        )
                    except Exception as _ste:
                        logger.debug(f"emit_step_trace(running) 失败（不影响主流程）: {_ste}")

                # 7.4 若是最终答案 → 跳出循环
                if react_step.final_answer:
                    final_answer = react_step.final_answer
                    # final_answer 场景：补 done 事件
                    if hasattr(self, "progress_tracker") and self.progress_tracker:
                        try:
                            step_duration = int((time.perf_counter() - step_t0) * 1000)
                            await self.progress_tracker.emit_step_trace(
                                run_id=task_id_str,
                                step_index=step,
                                thought=react_step.thought or "",
                                observation=(react_step.final_answer or "")[:600],
                                duration_ms=step_duration,
                                tokens=step_tokens,
                                cost_usd=step_cost,
                                status="done",
                            )
                        except Exception as _ste:
                            logger.debug(f"emit_step_trace(final_done) 失败: {_ste}")
                    self.progress.push_thought(
                        task_id_str,
                        react_step.thought or "已获得最终答案",
                        step=step,
                        max_steps=max_steps,
                    )
                    break

                # 7.5 若无 Action 也无 Final Answer → 解析失败，重试或降级
                if not react_step.action:
                    observation = (
                        f"上一步输出无法解析为 Action 或 Final Answer。"
                        f"请严格使用 'Thought: ...\\nAction: ...\\nAction Input: {{...}}' "
                        f"或 'Thought: ...\\nFinal Answer: ...' 格式。"
                    )
                    # 解析失败：补 done/error
                    if hasattr(self, "progress_tracker") and self.progress_tracker:
                        try:
                            step_duration = int((time.perf_counter() - step_t0) * 1000)
                            await self.progress_tracker.emit_step_trace(
                                run_id=task_id_str,
                                step_index=step,
                                thought=react_step.thought or "",
                                observation=observation[:600],
                                duration_ms=step_duration,
                                tokens=step_tokens,
                                cost_usd=step_cost,
                                status="done",
                            )
                        except Exception as _ste:
                            logger.debug(f"emit_step_trace(no_action) 失败: {_ste}")
                    continue

                # 7.6 工具调用
                self.progress.push_tool_call(
                    task_id_str,
                    react_step.action,
                    react_step.action_input or {},
                    step=step,
                )

                tool_start = time.time()
                tool_error: Optional[str] = None
                tool_ok = False
                tool_observation_text = ""
                try:
                    tool_result = await self.registry.execute_tool(
                        tool_name=react_step.action,
                        params=react_step.action_input or {},
                        user=user,
                        task_id=task_id_str,
                        session_id=str(session_id),
                        project_id=str(project_id) if project_id else None,
                        db=self.db,  # 关键修复：传递 db session，否则工具内 ctx.db 为 None
                        progress=self.progress,
                    )
                    tool_ok = bool(tool_result.success)
                    tool_error = tool_result.error
                    tool_observation_text = str(
                        tool_result.data if tool_result.success else tool_result.error
                    )
                except Exception as _te:
                    tool_result = None
                    tool_ok = False
                    tool_error = str(_te)
                    tool_observation_text = tool_error
                    raise
                finally:
                    tool_duration_ms = int((time.time() - tool_start) * 1000)
                    # emit_step_trace (status=done/error) — 工具执行之后
                    if hasattr(self, "progress_tracker") and self.progress_tracker:
                        try:
                            step_duration = int((time.perf_counter() - step_t0) * 1000)
                            await self.progress_tracker.emit_step_trace(
                                run_id=task_id_str,
                                step_index=step,
                                thought=react_step.thought or "",
                                action=react_step.action or "",
                                action_input=react_step.action_input,
                                observation=tool_observation_text[:600],
                                duration_ms=step_duration,
                                tokens=step_tokens,
                                cost_usd=step_cost,
                                status="error" if not tool_ok else "done",
                            )
                        except Exception as _ste:
                            logger.debug(f"emit_step_trace(after_tool) 失败: {_ste}")

                self.progress.push_tool_result(
                    task_id_str,
                    react_step.action,
                    success=tool_result.success,
                    data=tool_result.data,
                    error=tool_result.error,
                    step=step,
                    duration_ms=tool_duration_ms,
                )

                # 审计
                await self.audit.log_tool_call(
                    user_id=owner_id,
                    role=role_str,
                    task_id=task_id_str,
                    tool=react_step.action,
                    args=react_step.action_input or {},
                    success=tool_result.success,
                )

                # 追加 assistant + tool 消息到上下文
                await self.session_mgr.append_message(
                    session_id,
                    role="assistant",
                    content=react_step.thought or "",
                    tool_calls=[
                        {"tool": react_step.action, "args": react_step.action_input}
                    ],
                )
                await self.session_mgr.append_message(
                    session_id,
                    role="tool",
                    content=str(tool_result.data if tool_result.success else tool_result.error),
                    tool_results=[
                        {
                            "tool": react_step.action,
                            "success": tool_result.success,
                            "data": tool_result.data,
                            "error": tool_result.error,
                        }
                    ],
                )

                # 上下文压缩
                await self.session_mgr.maybe_compress(session_id, self.llm_router)

                # ===== Agent 增强：工具质量记录 =====
                if self.tool_quality:
                    try:
                        await self.tool_quality.record(
                            tool_name=react_step.action,
                            success=tool_result.success,
                            duration_ms=tool_duration_ms,
                            error=tool_result.error,
                        )
                    except Exception as qe:
                        logger.debug(f"工具质量记录失败（不影响主流程）: {qe}")

                # ===== Agent 增强：知识盲区检测 =====
                if self.gap_detector:
                    try:
                        self.gap_detector.observe(
                            step=step,
                            tool=react_step.action,
                            success=tool_result.success,
                            data=tool_result.data,
                            error=tool_result.error,
                        )
                    except Exception as ge:
                        logger.debug(f"盲区观察记录失败: {ge}")

                # ===== Agent 增强：工具失败反思 =====
                if not tool_result.success and self.reflector:
                    try:
                        reflection = await self.reflector.reflect(
                            query=query,
                            tool_name=react_step.action,
                            tool_args=react_step.action_input or {},
                            error=tool_result.error or "未知错误",
                            recent_steps=step_traces,
                            available_tools=available_tools,
                            retry_count=self._get_retry_count(
                                react_step.action, step_traces
                            ),
                        )
                        # 用反思结果替换 observation
                        observation = reflection.observation_for_llm or (
                            f"工具 {react_step.action} 失败: {tool_result.error}"
                        )
                        # 推送反思结果到前端
                        self.progress.push_thought(
                            task_id_str,
                            f"工具失败反思: {reflection.failure_analysis} | "
                            f"策略: {reflection.recovery_strategy.value}",
                            step=step,
                            max_steps=max_steps,
                        )
                    except Exception as re:
                        logger.warning(f"工具失败反思异常（降级原始错误）: {re}")
                        observation = f"工具 {react_step.action} 失败: {tool_result.error}"
                else:
                    # 更新 observation
                    if tool_result.success:
                        observation = f"工具 {react_step.action} 返回: {json.dumps(tool_result.data, ensure_ascii=False, default=str)[:2000]}"
                    else:
                        observation = f"工具 {react_step.action} 失败: {tool_result.error}"

                # ===== Agent 增强：知识盲区检测触发网络搜索建议 =====
                if self.gap_detector and step >= 2:
                    try:
                        gap_result = await self.gap_detector.detect(query=query)
                        if gap_result.is_knowledge_gap and gap_result.suggested_search_query:
                            observation += (
                                f"\n\n⚠️ 知识盲区检测: {gap_result.reasoning}\n"
                                f"💡 建议使用 web_search 工具搜索: "
                                f'"{gap_result.suggested_search_query}"'
                            )
                            self.progress.push_thought(
                                task_id_str,
                                f"知识盲区检测触发: {gap_result.gap_type.value} | "
                                f"建议搜索: {gap_result.suggested_search_query[:50]}",
                                step=step,
                                max_steps=max_steps,
                            )
                    except Exception as ge:
                        logger.debug(f"盲区检测失败（不影响主流程）: {ge}")

            # 8. 生成最终答案（若循环结束仍无 final_answer）
            if final_answer is None:
                final_answer = await self._generate_final_answer(
                    query=query,
                    step_traces=step_traces,
                    observation=observation,
                    tier=tier,
                )

            # 9. 输出 Guardrail 校验
            output_check = self.guardrail.check_output(final_answer)
            if output_check.blocked:
                # 输出被拦截：使用拦截原因作为答案
                final_answer = f"⚠️ 输出被安全护栏拦截：{', '.join(output_check.reasons)}"
                if output_check.annotations:
                    final_answer += "\n\n" + "\n".join(output_check.annotations)
            elif output_check.annotations:
                # 非拦截但有标注（如预后免责声明）→ 追加
                final_answer += "\n\n" + "\n".join(output_check.annotations)

            # 10. 追加最终 assistant 消息
            await self.session_mgr.append_message(
                session_id, role="assistant", content=final_answer
            )

            # 11. 任务完成
            duration_sec = round(time.time() - start_ts, 3)
            token_usage = {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_prompt_tokens + total_completion_tokens,
            }
            result = {
                "answer": final_answer,
                "plan": plan_output.to_dict(),
                "steps": step_traces,
                "token_usage": token_usage,
                "cost_usd": round(total_cost, 6),
                "duration_sec": duration_sec,
                "status": TaskStatus.COMPLETED,
                "error": None,
            }

            await self._update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=datetime.now(timezone.utc).isoformat(),
                token_usage=token_usage,
                cost_usd=round(total_cost, 6),
                duration_sec=duration_sec,
            )

            self.progress.push_final_response(
                task_id_str,
                final_answer,
                references=[],
                owner_id=owner_id,
            )
            self.progress.push_task_completed(task_id_str, result, owner_id=owner_id)

            return result

        except AppException as e:
            # 业务异常：记录并标记任务失败
            await self._fail_task(task_id, str(e), owner_id)
            self.progress.push_error(task_id_str, str(e), error_code=e.code, owner_id=owner_id)
            return {
                "answer": f"任务执行失败: {e.message}",
                "plan": None,
                "steps": step_traces,
                "token_usage": {
                    "prompt": total_prompt_tokens,
                    "completion": total_completion_tokens,
                    "total": total_prompt_tokens + total_completion_tokens,
                },
                "cost_usd": round(total_cost, 6),
                "duration_sec": round(time.time() - start_ts, 3),
                "status": TaskStatus.FAILED,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Agent 引擎未知异常: {e}", exc_info=True)
            await self._fail_task(task_id, str(e), owner_id)
            self.progress.push_error(task_id_str, str(e), owner_id=owner_id)
            return {
                "answer": f"任务执行失败: {e}",
                "plan": None,
                "steps": step_traces,
                "token_usage": {
                    "prompt": total_prompt_tokens,
                    "completion": total_completion_tokens,
                    "total": total_prompt_tokens + total_completion_tokens,
                },
                "cost_usd": round(total_cost, 6),
                "duration_sec": round(time.time() - start_ts, 3),
                "status": TaskStatus.FAILED,
                "error": str(e),
            }

    def _build_react_prompt(
        self,
        query: str,
        context_summary: str,
        observation: str,
        available_tools: List[Dict[str, Any]],
        step: int,
        max_steps: int,
    ) -> str:
        """构造 ReAct 主循环 prompt（含历史摘要 + 观察结果 + 工具清单）"""
        from app.services.agent.prompts import build_tools_description

        tools_desc = build_tools_description(available_tools)
        parts = [
            f"# 用户问题\n{query}",
        ]
        if context_summary:
            parts.append(f"\n# 历史摘要\n{context_summary}")
        if observation:
            parts.append(f"\n# 上一步观察\n{observation}")
        parts.append(f"\n# 可用工具\n{tools_desc}")
        parts.append(f"\n# 当前进度\n第 {step} / {max_steps} 步")
        parts.append(
            "\n# 请按格式输出\nThought: <思考>\nAction: <工具名>\nAction Input: <JSON 参数>\n"
            "（或）\nThought: <思考>\nFinal Answer: <最终答案>"
        )
        return "\n".join(parts)

    async def _load_project_context(self, project_id: Optional[UUID]) -> str:
        """加载项目上下文摘要，注入到系统提示词中

        目的：让 Agent 在回答用户问题时能"看到"当前项目的关键信息，
              无需每次都调用工具查询。解决"问的问题好像答不上来"的核心痛点。

        Returns:
            项目上下文字符串（项目信息 + Top 5 靶点 + Top 5 分子）
        """
        if not project_id:
            return ""
        try:
            from sqlalchemy import select
            from app.models.project import Project
            from app.models.target import Target
            from app.models.molecule import Molecule

            # 1. 项目基础信息
            project = await self.db.get(Project, project_id)
            if not project:
                return ""
            project_dict = {
                "name": project.name,
                "cancer_type": getattr(project, "cancer_type", None),
                "stage": getattr(project, "stage", None),
                "status": getattr(project, "status", None),
            }

            # 2. Top 5 靶点（按置信度降序）
            tgt_stmt = (
                select(Target)
                .where(Target.project_id == project_id)
                .order_by(Target.confidence_score.desc().nullslast())
                .limit(5)
            )
            tgt_result = await self.db.execute(tgt_stmt)
            targets = [
                {
                    "gene_symbol": t.gene_symbol,
                    "evidence_grade": t.evidence_grade,
                    "confidence_score": float(t.confidence_score) if t.confidence_score else None,
                    "approved_drugs": t.approved_drugs if isinstance(t.approved_drugs, list) else [],
                }
                for t in tgt_result.scalars().all()
            ]

            # 3. Top 5 分子（按创建时间降序）
            mol_stmt = (
                select(Molecule)
                .where(Molecule.project_id == project_id)
                .order_by(Molecule.created_at.desc().nullslast() if hasattr(Molecule, 'created_at') else Molecule.id.desc())
                .limit(5)
            )
            try:
                mol_result = await self.db.execute(mol_stmt)
                molecules = [
                    {
                        "name": getattr(m, "name", None),
                        "smiles": getattr(m, "smiles", None),
                        "molecular_weight": float(getattr(m, "molecular_weight", 0) or 0),
                        "logp": float(getattr(m, "logp", 0) or 0) if getattr(m, "logp", None) is not None else None,
                        "is_approved": bool(getattr(m, "is_approved", False)),
                    }
                    for m in mol_result.scalars().all()
                ]
            except Exception:
                molecules = []

            # 基础上下文：精简版（靶点、分子 Top 5）
            base_context = build_project_context(
                project=project_dict,
                targets=targets,
                molecules=molecules,
            )

            # 增强：合并 EvidenceCollector 完整证据包（三级输出+token预算裁剪，瓶颈 B）
            # （包含治疗方案/实验/基因组解读/验证/对接计算等模块级数据，
            #  避免 Agent 需要反复调工具才能获取本地已有知识）
            extra_lines: List[str] = []
            try:
                from app.services.intelligence.evidence_collector import (
                    get_evidence_collector,
                )
                from app.core.config import settings

                collector = get_evidence_collector()
                max_tokens = getattr(settings, "AGENT_MAX_TOKENS", None)
                if max_tokens is None:
                    max_tokens = 8000
                chars_budget = int(max_tokens) * 4
                if chars_budget >= 32000:
                    lvl = "full"
                elif chars_budget >= 12000:
                    lvl = "compact"
                else:
                    lvl = "summary"

                before_chars = 0
                try:
                    bundle = collector.collect_project_evidence_bundle(str(project_id))
                    import inspect as _inspect
                    if _inspect.isawaitable(bundle):
                        import asyncio as _aio
                        try:
                            bundle = await bundle
                        except Exception:
                            bundle = None
                    if bundle and getattr(bundle, "text", None):
                        before_chars = len(bundle.text)
                except Exception:
                    before_chars = 0

                trimmed_text = await collector.collect_project_evidence_with_budget(
                    str(project_id), level=lvl, token_budget_chars=chars_budget,
                )
                after_chars = len(trimmed_text) if trimmed_text else 0
                if trimmed_text:
                    extra_lines.append("")
                    extra_lines.append(trimmed_text)

                # emit_compression_stats (stage=evidence_preload)
                if hasattr(self, "progress_tracker") and self.progress_tracker:
                    try:
                        await self.progress_tracker.emit_compression_stats(
                            stage="evidence_preload",
                            before_chars=before_chars,
                            after_chars=after_chars,
                            details={"level": lvl, "budget_chars": chars_budget},
                        )
                    except Exception as _cse:
                        logger.debug(f"emit_compression_stats(evidence_preload) 失败: {_cse}")
            except Exception as e2:
                logger.info(
                    f"EvidenceCollector 未注入（非致命，继续）: {type(e2).__name__}: {e2}"
                )

            return base_context + "".join(extra_lines)
        except Exception as e:
            logger.warning(f"加载项目上下文失败（继续后续）: {e}")
            return ""

    async def _generate_final_answer(
        self,
        query: str,
        step_traces: List[Dict[str, Any]],
        observation: str,
        tier: str,
    ) -> str:
        """生成最终答案（循环结束时未得到 Final Answer 的兜底）"""
        reasoning_trace = json.dumps(step_traces, ensure_ascii=False, default=str)[:6000]
        prompt = FINAL_ANSWER_PROMPT.format(
            query=query,
            reasoning_trace=reasoning_trace,
        )
        try:
            # 流式生成：边生成边累积（兜底场景不推送 token，避免与 Final Answer 重复）
            parts: List[str] = []
            async for chunk in self.llm_router.stream_complete(prompt, tier=tier):
                if chunk.get("type") == "token":
                    parts.append(chunk.get("content", ""))
                elif chunk.get("type") == "done":
                    done_content = chunk.get("content", "")
                    if done_content:
                        return done_content
            return "".join(parts) or "（未能生成答案）"
        except Exception as e:
            logger.warning(f"最终答案生成失败: {e}")
            return f"基于已有信息无法生成完整答案。最后观察: {observation[:500]}"

    async def _update_task_status(self, task_id: UUID, status: str) -> None:
        """更新任务状态"""
        from sqlalchemy import update as sa_update

        stmt = (
            sa_update(AgentTask)
            .where(AgentTask.id == task_id)
            .values(status=status)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def _update_task(self, task_id: UUID, **values) -> None:
        """更新任务字段"""
        from sqlalchemy import update as sa_update

        if "status" in values and values["status"] == TaskStatus.RUNNING:
            values.setdefault(
                "started_at", datetime.now(timezone.utc).isoformat()
            )

        stmt = sa_update(AgentTask).where(AgentTask.id == task_id).values(**values)
        await self.db.execute(stmt)
        await self.db.flush()

    async def _fail_task(self, task_id: UUID, error: str, owner_id: str) -> None:
        """标记任务失败"""
        await self._update_task(
            task_id,
            status=TaskStatus.FAILED,
            error=error[:2000],
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _get_retry_count(
        tool_name: str,
        step_traces: List[Dict[str, Any]],
    ) -> int:
        """统计某工具在历史步骤中的调用次数（用于反思器的重试计数）

        统计所有调用（无论成功失败），因为反思器会基于调用次数判断是否
        应该继续重试。Reflector 内部有 max_retries 限制防止死循环。

        Args:
            tool_name: 工具名
            step_traces: 步骤轨迹

        Returns:
            该工具已被调用的次数 - 1（当前调用不算重试）
        """
        count = 0
        for trace in step_traces:
            if trace.get("action") == tool_name:
                count += 1
        # 当前这次调用不算重试，所以返回 count - 1
        return max(0, count - 1)
