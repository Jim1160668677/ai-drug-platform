"""Agent 任务规划器 — LLM 生成计划 + DAG 拓扑排序

设计来源：2026-07-18-agent-functional-design.md §3
"""
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.agent.prompts import PLANNER_PROMPT, build_tools_description

logger = logging.getLogger(__name__)


@dataclass
class PlannerInput:
    """规划器输入"""
    query: str
    context_summary: Optional[str] = None
    available_tools: List[Dict[str, Any]] = field(default_factory=list)
    max_steps: int = 8


@dataclass
class PlanStep:
    """规划步骤"""
    id: str
    tool: str
    args: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    description: Optional[str] = None


@dataclass
class PlannerOutput:
    """规划器输出"""
    steps: List[PlanStep]
    parallel_layers: List[List[str]]  # 可并行执行的层
    reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps": [
                {
                    "id": s.id,
                    "tool": s.tool,
                    "args": s.args,
                    "depends_on": s.depends_on,
                    "description": s.description,
                }
                for s in self.steps
            ],
            "parallel_layers": self.parallel_layers,
            "reasoning": self.reasoning,
        }

    @classmethod
    def empty(cls, reasoning: str = "") -> "PlannerOutput":
        """空计划（可直接回答）"""
        return cls(steps=[], parallel_layers=[], reasoning=reasoning)


class TaskPlanner:
    """任务规划器

    Usage:
        planner = TaskPlanner(llm_router)
        output = await planner.plan(PlannerInput(...))
    """

    def __init__(self, llm_router=None):
        """
        Args:
            llm_router: LLMRouter 实例（可选）；为 None 时退化为单步直答
        """
        self.llm_router = llm_router

    async def plan(self, inp: PlannerInput) -> PlannerOutput:
        """生成执行计划

        流程：
        1. 用 PLANNER_PROMPT 调 LLM
        2. 解析 JSON，校验工具/参数
        3. 拓扑排序分层
        4. 失败时降级为单步直答（空计划）
        """
        if self.llm_router is None or not inp.available_tools:
            return PlannerOutput.empty(reasoning="无 LLM 或无可用工具，直接回答")

        tools_desc = build_tools_description(inp.available_tools)
        prompt = PLANNER_PROMPT.format(
            query=inp.query,
            tools_description=tools_desc,
            context_summary=inp.context_summary or "（无历史上下文）",
        )

        try:
            result = await self.llm_router.quick(prompt, system="你是任务规划器。")
            content = result.get("content", "")
            plan_dict = self._parse_json(content)
        except Exception as e:
            logger.warning(f"Planner LLM 调用失败，降级单步直答: {e}")
            return PlannerOutput.empty(reasoning=f"规划失败: {e}")

        if plan_dict is None:
            logger.warning(f"Planner 输出解析失败，降级单步直答。原始输出: {content[:200]}")
            return PlannerOutput.empty(reasoning="LLM 输出非合法 JSON")

        # 校验与构建步骤
        valid_tool_names = {t["name"] for t in inp.available_tools}
        steps: List[PlanStep] = []
        for raw in plan_dict.get("steps", [])[:inp.max_steps]:
            step_id = raw.get("id", f"step_{len(steps) + 1}")
            tool_name = raw.get("tool", "")
            if tool_name not in valid_tool_names:
                logger.warning(f"跳过未知工具步骤: {tool_name}")
                continue
            steps.append(
                PlanStep(
                    id=step_id,
                    tool=tool_name,
                    args=raw.get("args", {}) or {},
                    depends_on=raw.get("depends_on", []) or [],
                    description=raw.get("description"),
                )
            )

        # 拓扑排序分层
        parallel_layers = self._topological_layers(steps)

        return PlannerOutput(
            steps=steps,
            parallel_layers=parallel_layers,
            reasoning=plan_dict.get("reasoning"),
        )

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        """从 LLM 输出中解析 JSON（容错：提取 ``` 代码块或第一个 {...} 段）"""
        # 优先尝试代码块
        if "```" in content:
            parts = content.split("```")
            for i, p in enumerate(parts):
                if i % 2 == 1:  # 奇数索引是代码块内容
                    p = p.strip()
                    if p.startswith("json"):
                        p = p[4:].strip()
                    try:
                        return json.loads(p)
                    except json.JSONDecodeError:
                        continue
        # 否则尝试直接解析
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass
        # 最后尝试提取第一个 {...} 段
        start = content.find("{")
        end = content.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _topological_layers(steps: List[PlanStep]) -> List[List[str]]:
        """Kahn 拓扑排序 — 分层返回可并行执行的步骤 ID

        Returns:
            [[step_1, step_2], [step_3], ...]  每层内可并行，层间串行
        """
        if not steps:
            return []

        # 构建邻接表与入度
        step_map = {s.id: s for s in steps}
        in_degree: Dict[str, int] = {s.id: 0 for s in steps}
        dependents: Dict[str, List[str]] = {s.id: [] for s in steps}

        for s in steps:
            for dep in s.depends_on:
                if dep in step_map:  # 忽略不存在的依赖
                    in_degree[s.id] += 1
                    dependents[dep].append(s.id)

        # BFS 分层
        layers: List[List[str]] = []
        queue = deque([sid for sid, d in in_degree.items() if d == 0])

        while queue:
            layer = list(queue)
            layers.append(layer)
            next_queue: deque[str] = deque()
            for sid in layer:
                for child in dependents[sid]:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_queue.append(child)
            queue = next_queue

        # 检测环：若仍有节点未处理，说明存在循环依赖
        processed = sum(len(layer) for layer in layers)
        if processed < len(steps):
            logger.warning(
                f"检测到循环依赖，未处理步骤: {set(step_map) - set(sum(layers, []))}"
            )
            # 降级：将剩余步骤平铺到最后一层
            remaining = [sid for sid in step_map if sid not in sum(layers, [])]
            layers.append(remaining)

        return layers
