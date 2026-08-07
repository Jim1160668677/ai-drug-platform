"""DAG 并行执行器 — 按 PlannerOutput.parallel_layers 并行执行工具

设计来源：2026-07-28 Agent 增强（多步骤问题解决能力提升）

核心职责：
1. 接收 PlannerOutput（DAG 计划 + parallel_layers）
2. 按拓扑层级执行：同层工具并发（asyncio.gather），层间串行
3. 支持参数模板：后续步骤可引用前序步骤的结果（${step_id.field}）
4. 聚合所有步骤结果，返回给 AgentEngine

集成点：
- AgentEngine.run() 在 AGENT_USE_DAG_EXECUTOR=True 时调用 DagExecutor.execute()
- 执行完成后，将聚合结果作为 observation 传给 ReAct 循环（用于最终答案生成）

注意：DAG 执行模式适用于"计划明确"的任务（如批量分析多个靶点）。
      对于需要 LLM 动态决策的任务，仍使用标准 ReAct 循环。
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.models.user import User
from app.services.agent.planner import PlannerOutput, PlanStep
from app.services.agent.tools.base import ToolResult
from app.services.agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# 参数模板变量匹配：${step_1.project_id}
_TEMPLATE_RE = re.compile(r"\$\{(?P<step_id>[a-zA-Z0-9_]+)\.(?P<field>[a-zA-Z0-9_.]+)\}")


@dataclass
class StepExecutionResult:
    """单个步骤的执行结果"""

    step_id: str
    tool: str
    args: Dict[str, Any]
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "args": self.args,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DagExecutionResult:
    """DAG 执行聚合结果"""

    success: bool
    results: List[StepExecutionResult] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    total_duration_ms: int = 0

    def get_step_result(self, step_id: str) -> Optional[StepExecutionResult]:
        for r in self.results:
            if r.step_id == step_id:
                return r
        return None

    def to_observation(self, max_chars: int = 4000) -> str:
        """生成传给 ReAct 的 observation 文本"""
        parts = ["# DAG 执行结果"]
        for r in self.results:
            status = "✓" if r.success else "✗"
            line = f"\n## [{status}] {r.step_id}: {r.tool}"
            if r.success:
                data_str = str(r.data)[:500]
                line += f"\n结果: {data_str}"
            else:
                line += f"\n错误: {r.error}"
            parts.append(line)

        if self.failed_steps:
            parts.append(
                f"\n\n注意：以下步骤失败: {', '.join(self.failed_steps)}"
            )

        observation = "\n".join(parts)
        return observation[:max_chars]


class DagExecutor:
    """DAG 并行执行器

    Usage:
        executor = DagExecutor(registry)
        result = await executor.execute(
            plan=plan_output,
            user=user,
            task_id="...",
            session_id="...",
            project_id="...",
            db=db,
            progress=progress_manager,
        )
        observation = result.to_observation()
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.max_concurrency = 5  # 同层最大并发数

    async def execute(
        self,
        plan: PlannerOutput,
        user: User,
        task_id: str,
        session_id: str,
        project_id: Optional[str] = None,
        db: Optional[Any] = None,
        progress: Optional[Any] = None,
    ) -> DagExecutionResult:
        """执行 DAG 计划

        Args:
            plan: PlannerOutput（含 steps 和 parallel_layers）
            user: 用户对象
            task_id: 任务 ID
            session_id: 会话 ID
            project_id: 项目 ID
            db: 数据库会话
            progress: 进度管理器

        Returns:
            DagExecutionResult
        """
        if not plan.steps:
            return DagExecutionResult(success=True)

        start_ts = time.time()
        step_map: Dict[str, PlanStep] = {s.id: s for s in plan.steps}
        results: List[StepExecutionResult] = []
        # 已完成步骤的结果（用于参数模板替换）
        completed: Dict[str, StepExecutionResult] = {}

        for layer_idx, layer in enumerate(plan.parallel_layers):
            # 过滤出当前层中存在的步骤
            layer_steps = [step_map[sid] for sid in layer if sid in step_map]
            if not layer_steps:
                continue

            logger.info(
                f"DAG 层 {layer_idx}: {len(layer_steps)} 个步骤并发执行 — "
                f"{[s.id for s in layer_steps]}"
            )

            # 并发执行同层步骤
            layer_results = await self._execute_layer(
                layer_steps=layer_steps,
                completed=completed,
                user=user,
                task_id=task_id,
                session_id=session_id,
                project_id=project_id,
                db=db,
                progress=progress,
                layer_idx=layer_idx,
            )

            for r in layer_results:
                results.append(r)
                completed[r.step_id] = r

        total_ms = int((time.time() - start_ts) * 1000)
        failed = [r.step_id for r in results if not r.success]

        return DagExecutionResult(
            success=len(failed) == 0,
            results=results,
            failed_steps=failed,
            total_duration_ms=total_ms,
        )

    async def _execute_layer(
        self,
        layer_steps: List[PlanStep],
        completed: Dict[str, StepExecutionResult],
        user: User,
        task_id: str,
        session_id: str,
        project_id: Optional[str],
        db: Optional[Any],
        progress: Optional[Any],
        layer_idx: int,
    ) -> List[StepExecutionResult]:
        """执行单层步骤（并发）"""
        # 用信号量限制并发数
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run_step(step: PlanStep) -> StepExecutionResult:
            async with semaphore:
                return await self._execute_step(
                    step=step,
                    completed=completed,
                    user=user,
                    task_id=task_id,
                    session_id=session_id,
                    project_id=project_id,
                    db=db,
                    progress=progress,
                    layer_idx=layer_idx,
                )

        tasks = [_run_step(step) for step in layer_steps]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        final_results: List[StepExecutionResult] = []
        for step, result in zip(layer_steps, results):
            if isinstance(result, Exception):
                logger.error(
                    f"DAG 步骤 {step.id}({step.tool}) 异常: {result}",
                    exc_info=result,
                )
                final_results.append(
                    StepExecutionResult(
                        step_id=step.id,
                        tool=step.tool,
                        args=step.args,
                        success=False,
                        error=f"执行异常: {type(result).__name__}: {result}",
                    )
                )
            else:
                final_results.append(result)

        return final_results

    async def _execute_step(
        self,
        step: PlanStep,
        completed: Dict[str, StepExecutionResult],
        user: User,
        task_id: str,
        session_id: str,
        project_id: Optional[str],
        db: Optional[Any],
        progress: Optional[Any],
        layer_idx: int,
    ) -> StepExecutionResult:
        """执行单个 DAG 步骤"""
        # 参数模板替换（引用前序步骤的结果）
        resolved_args = self._resolve_args(step.args, completed)

        # 推送进度
        if progress and hasattr(progress, "push_tool_call"):
            try:
                progress.push_tool_call(
                    task_id,
                    step.tool,
                    resolved_args,
                    step=f"DAG-L{layer_idx}-{step.id}",
                )
            except Exception:
                pass

        logger.info(
            f"DAG 执行 {step.id}: {step.tool} args={resolved_args}"
        )

        start_ts = time.time()
        try:
            tool_result: ToolResult = await self.registry.execute_tool(
                tool_name=step.tool,
                params=resolved_args,
                user=user,
                task_id=task_id,
                session_id=session_id,
                project_id=project_id,
                db=db,
                progress=progress,
            )
            duration_ms = int((time.time() - start_ts) * 1000)

            # 推送结果
            if progress and hasattr(progress, "push_tool_result"):
                try:
                    progress.push_tool_result(
                        task_id,
                        step.tool,
                        success=tool_result.success,
                        data=tool_result.data,
                        error=tool_result.error,
                        step=f"DAG-L{layer_idx}-{step.id}",
                        duration_ms=duration_ms,
                    )
                except Exception:
                    pass

            return StepExecutionResult(
                step_id=step.id,
                tool=step.tool,
                args=resolved_args,
                success=tool_result.success,
                data=tool_result.data,
                error=tool_result.error,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_ts) * 1000)
            logger.error(
                f"DAG 步骤 {step.id}({step.tool}) 执行异常: {e}",
                exc_info=True,
            )
            return StepExecutionResult(
                step_id=step.id,
                tool=step.tool,
                args=resolved_args,
                success=False,
                error=f"执行异常: {type(e).__name__}: {e}",
                duration_ms=duration_ms,
            )

    def _resolve_args(
        self,
        args: Dict[str, Any],
        completed: Dict[str, StepExecutionResult],
    ) -> Dict[str, Any]:
        """参数模板替换

        支持 ${step_id.field} 模板，引用前序步骤的返回数据。

        示例：
            args = {"target_gene": "${step_1.gene_symbol}"}
            若 step_1 的 data = {"gene_symbol": "EGFR", ...}
            则替换后 args = {"target_gene": "EGFR"}
        """
        if not args:
            return args or {}

        resolved: Dict[str, Any] = {}
        for key, value in args.items():
            resolved[key] = self._resolve_value(value, completed)
        return resolved

    def _resolve_value(
        self,
        value: Any,
        completed: Dict[str, StepExecutionResult],
    ) -> Any:
        """递归解析值中的模板变量"""
        if isinstance(value, str):
            return self._resolve_template(value, completed)
        elif isinstance(value, dict):
            return {
                k: self._resolve_value(v, completed) for k, v in value.items()
            }
        elif isinstance(value, list):
            return [self._resolve_value(v, completed) for v in value]
        return value

    def _resolve_template(
        self,
        text: str,
        completed: Dict[str, StepExecutionResult],
    ) -> Any:
        """解析字符串中的 ${step_id.field} 模板

        若整个字符串就是一个模板变量，返回原始类型（而非字符串）。
        若模板变量无法解析（步骤不存在），返回空字符串。
        """
        match = _TEMPLATE_RE.fullmatch(text.strip())
        if match:
            # 整个字符串是单个模板变量 → 返回原始类型
            val = self._lookup_value(
                match.group("step_id"),
                match.group("field"),
                completed,
                default=None,
            )
            return val if val is not None else ""

        # 字符串中包含模板变量 → 替换为字符串
        def replacer(m: re.Match) -> str:
            val = self._lookup_value(
                m.group("step_id"),
                m.group("field"),
                completed,
                default="",
            )
            return str(val) if val is not None else ""

        return _TEMPLATE_RE.sub(replacer, text)

    def _lookup_value(
        self,
        step_id: str,
        field_path: str,
        completed: Dict[str, StepExecutionResult],
        default: Any = None,
    ) -> Any:
        """从已完成步骤的结果中查找字段值

        Args:
            step_id: 步骤 ID
            field_path: 字段路径（支持点号嵌套，如 "data.gene_symbol"）
            completed: 已完成步骤结果字典
            default: 未找到时的默认值
        """
        step_result = completed.get(step_id)
        if not step_result or not step_result.success:
            return default

        # 支持点号路径（如 data.gene_symbol）
        parts = field_path.split(".")
        current: Any = step_result.data

        for part in parts:
            if current is None:
                return default
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return default

        return current if current is not None else default


__all__ = [
    "DagExecutor",
    "DagExecutionResult",
    "StepExecutionResult",
]
