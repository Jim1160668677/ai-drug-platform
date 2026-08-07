"""Agent 服务层 — 自研 ReAct 引擎

模块结构（见 2026-07-18-agent-functional-design.md §1）：
- engine.py        ReAct 主循环
- planner.py       任务规划 + DAG 调度
- dag_executor.py  DAG 并行执行器（按拓扑层并行调用工具）
- reflection.py    工具失败反思器（分析失败原因 + 恢复建议）
- tool_quality.py  工具质量跟踪器（成功率/耗时统计 + 推荐）
- knowledge_gap.py 知识盲区检测器（连续空结果 → 触发网络搜索）
- session.py       会话/上下文管理
- progress.py      WebSocket 事件分发（委托 TaskProgressManager）
- ratelimit.py     Redis 令牌桶限流
- audit.py         审计日志（委托 AuditLog 模型）
- prompts.py       ReAct/Planner prompt 模板
- tools/           工具层
"""
from app.services.agent.engine import AgentEngine
from app.services.agent.planner import TaskPlanner, PlannerInput, PlannerOutput
from app.services.agent.dag_executor import DagExecutor, DagExecutionResult
from app.services.agent.reflection import Reflector, ReflectionResult, ErrorCategory, RecoveryStrategy
from app.services.agent.tool_quality import ToolQualityTracker, ToolMetrics, get_tool_quality_tracker
from app.services.agent.knowledge_gap import KnowledgeGapDetector, GapDetectionResult, GapType
from app.services.agent.session import SessionManager
from app.services.agent.progress import ProgressManager
from app.services.agent.ratelimit import RateLimiter
from app.services.agent.audit import AuditLogger

__all__ = [
    "AgentEngine",
    "TaskPlanner",
    "PlannerInput",
    "PlannerOutput",
    "DagExecutor",
    "DagExecutionResult",
    "Reflector",
    "ReflectionResult",
    "ErrorCategory",
    "RecoveryStrategy",
    "ToolQualityTracker",
    "ToolMetrics",
    "get_tool_quality_tracker",
    "KnowledgeGapDetector",
    "GapDetectionResult",
    "GapType",
    "SessionManager",
    "ProgressManager",
    "RateLimiter",
    "AuditLogger",
]
