"""ReasoningChannel — 科学推理通道

设计来源：Nature Co-Scientist 论文的 Supervisor 7 阶段流水线。

核心能力：
1. 复用 Supervisor.run 执行多智能体科学推理
2. 注入 ContextMemoryStore + ReasoningTraceStore（通过 Supervisor 构造函数）
3. 每轮写快照支持故障重启
4. 推理完成后保存假设状态到上下文记忆

autoresearch 整合：等价于 autoresearch 的自主实验循环——
modify（generation）→ train（debate）→ evaluate（ranking）→ keep/discard（evolution）。
"""
import logging
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from app.services.intelligence.context_store import ContextMemoryStore
from app.services.intelligence.trace_store import ReasoningTraceStore

logger = logging.getLogger(__name__)


class ReasoningChannel:
    """科学推理通道 — 调用 Supervisor 执行多智能体推理

    用法：
        channel = ReasoningChannel(llm_client, context_store, trace_store)
        result = await channel.reason(session_id, "发现某疾病的新靶点", user, project_id)
    """

    def __init__(
        self,
        llm_client: Any,
        context_store: ContextMemoryStore,
        trace_store: ReasoningTraceStore,
    ):
        self.llm_client = llm_client
        self.context_store = context_store
        self.trace_store = trace_store

    @staticmethod
    def _detect_mode(research_goal: str) -> str:
        """根据研究目标复杂度自动检测推理模式

        启发式规则：
        - 简短/具体问题（<30字，含关键词如"靶点"、"表达"）→ fast
        - 中等复杂问题（30-80字）→ standard
        - 长/复杂问题（>80字，含关键词如"机制"、"通路"、"网络"、"多组学"）→ deep
        """
        text = research_goal.strip()
        length = len(text)

        fast_keywords = ["靶点", "表达", "筛选", "找", "查询", "什么", "哪个", "列举"]
        deep_keywords = ["机制", "通路", "网络", "多组学", "整合", "系统", "因果",
                         "通路交叉", "下游", "上游", "调控", "级联"]

        if length < 20:
            return "fast"
        if length > 80 or any(kw in text for kw in deep_keywords):
            return "deep"
        if any(kw in text for kw in fast_keywords) and length < 40:
            return "fast"
        return "standard"

    async def reason(
        self,
        session_id: UUID,
        research_goal: str,
        user: Any,
        project_id: Optional[str] = None,
        max_rounds: int = 5,
        initial_count: int = 5,
        evidence: str = "",
        run_id: Optional[UUID] = None,
        reasoning_mode: str = "auto",
    ) -> Dict[str, Any]:
        """执行科学推理

        Args:
            session_id: 统一会话 ID
            research_goal: 研究目标（自然语言）
            user: 当前用户
            project_id: 项目 ID
            max_rounds: 最大迭代轮数
            initial_count: 初始假设数量
            evidence: 证据上下文
            run_id: 预设的运行 ID（可选）
            reasoning_mode: auto (自动判定) / fast / standard / deep

        Returns:
            {run_id, final_rankings, meta_review, total_cost, duration, mode}
        """
        # auto 模式：根据问题复杂度自动选择推理模式
        if reasoning_mode == "auto":
            reasoning_mode = self._detect_mode(research_goal)
            logger.info("[reasoning] auto 检测模式 -> %s", reasoning_mode)
        # 延迟导入避免循环依赖
        from app.services.coscientist.supervisor import Supervisor
        from app.services.coscientist.progress import ProgressTracker

        # 生成唯一 run_id（调用方未提供时自动生成，避免 "pending" 占位符）
        if run_id is None:
            run_id = uuid.uuid4()
        run_id_str = str(run_id)

        # 创建 ProgressTracker，注入 trace_callback
        tracker = ProgressTracker(run_id=run_id_str)
        trace_callback = self.trace_store.create_trace_callback(
            run_id=run_id, session_id=session_id
        )
        # 将 trace_callback 附加到 tracker（ProgressTracker 改造后支持）
        if hasattr(tracker, "trace_callback"):
            tracker.trace_callback = trace_callback

        # 创建 Supervisor，注入 context_store + trace_store
        supervisor = Supervisor(
            llm_client=self.llm_client,
            tracker=tracker,
            generation_context=evidence or None,
        )
        # 注入 stores（Supervisor 改造后支持）
        if hasattr(supervisor, "context_store"):
            supervisor.context_store = self.context_store
        if hasattr(supervisor, "trace_store"):
            supervisor.trace_store = self.trace_store

        # 保存研究目标到上下文记忆
        await self.context_store.save_research_goal(
            session_id=session_id,
            goal=research_goal,
            project_id=UUID(project_id) if project_id else None,
        )

        # 执行推理
        result = await supervisor.run(
            research_goal=research_goal,
            max_rounds=max_rounds,
            initial_count=initial_count,
            evidence=evidence,
            reasoning_mode=reasoning_mode,
        )

        # 保存假设状态到上下文记忆（仅推理成功时）
        if result.final_rankings and not result.error:
            try:
                await self.context_store.save_snapshot(
                    run_id=run_id,
                    round_num=result.total_rounds,
                    phase="completed",
                    hypotheses=result.final_rankings,
                    context_summary=result.meta_review.get("summary", "") if result.meta_review else "",
                    session_id=session_id,
                    project_id=UUID(project_id) if project_id else None,
                )
            except Exception as e:
                logger.warning("[reasoning] 保存快照失败（不影响主流程）: %s", e)

        return {
            "run_id": result.run_id,
            "final_rankings": result.final_rankings,
            "meta_review": result.meta_review,
            "total_cost": result.total_cost_usd,
            "duration": result.duration_sec,
            "total_rounds": result.total_rounds,
            "mode": "reasoning",
            "reasoning_mode": reasoning_mode,
            "converged": result.converged,
            "error": result.error,
        }
