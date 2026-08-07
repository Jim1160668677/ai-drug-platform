"""Agent 相关 Pydantic 模型 — 请求/响应/事件

设计来源：2026-07-18-agent-functional-design.md §6
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent_session import SessionStatus
from app.models.agent_task import TaskStatus
from app.models.sandbox_execution import SandboxStatus


# ========== 会话 ==========

class SessionCreate(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, max_length=200, description="会话标题，默认'新会话'")
    project_id: Optional[UUID] = Field(None, description="关联项目 ID")


class SessionResponse(BaseModel):
    """会话响应"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    title: str
    status: str = SessionStatus.ACTIVE
    message_count: int = 0
    last_message_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    context: Optional[Dict[str, Any]] = None  # 仅详情接口返回


# ========== 任务 ==========

class ChatRequest(BaseModel):
    """发起 Agent 对话"""
    session_id: UUID = Field(..., description="会话 ID")
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    project_id: Optional[UUID] = Field(None, description="项目 ID（覆盖会话默认）")
    tier: str = Field("fast_screen", description="分析层级: fast_screen / deep_insight")


class PlanStepView(BaseModel):
    """规划步骤视图"""
    id: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class PlanView(BaseModel):
    """任务规划视图"""
    steps: List[PlanStepView] = Field(default_factory=list)
    parallel_layers: List[List[str]] = Field(default_factory=list)
    reasoning: Optional[str] = None


class ToolCallView(BaseModel):
    """工具调用视图（推送给前端）"""
    step: int
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    thought: Optional[str] = None


class ToolResultView(BaseModel):
    """工具结果视图"""
    step: int
    tool: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    display: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None


class TokenUsageView(BaseModel):
    """Token 用量"""
    prompt: int = 0
    completion: int = 0
    total: int = 0


class TaskResponse(BaseModel):
    """任务响应"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    user_id: UUID
    project_id: Optional[UUID] = None
    query: str
    status: str = TaskStatus.PENDING
    current_step: Optional[int] = None
    plan: Optional[PlanView] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    token_usage: Optional[TokenUsageView] = None
    cost_usd: Optional[float] = None
    duration_sec: Optional[float] = None
    created_at: datetime


class ChatResponse(BaseModel):
    """发起对话后的同步响应（任务异步执行）"""
    task_id: UUID
    session_id: UUID
    status: str = TaskStatus.PENDING
    message: str = "任务已创建，请通过 WebSocket 订阅进度"


# ========== 工具 ==========

class ToolInfo(BaseModel):
    """工具信息（用于 GET /tools 列表）"""
    name: str
    description: str
    parameters: Dict[str, Any]
    side_effects: bool
    required_role: str


# ========== 副作用确认 ==========

class ConfirmationRequest(BaseModel):
    """需要用户确认的副作用操作"""
    task_id: UUID
    step: int
    tool: str
    args: Dict[str, Any]
    description: str
    risk_level: str = "medium"  # low / medium / high


class ConfirmationResponse(BaseModel):
    """用户确认结果"""
    approved: bool = Field(..., description="是否同意执行")
    reason: Optional[str] = Field(None, description="拒绝原因（可选）")


# ========== WebSocket 事件 ==========

class WSEvent(BaseModel):
    """WebSocket 推送事件信封

    type 取值：
    - task_started: 任务开始执行
    - plan: 规划完成，推送 DAG
    - thought: LLM 思考过程
    - tool_call: 工具调用开始
    - tool_result: 工具执行结果
    - final_response: 最终答案
    - error: 错误
    - confirmation_required: 需要用户确认副作用
    - task_completed: 任务完成
    """
    type: str
    task_id: str
    timestamp: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class WSClientMessage(BaseModel):
    """WebSocket 客户端消息

    type 取值：
    - subscribe: 订阅任务进度
    - unsubscribe: 取消订阅
    - confirm: 副作用确认
    - cancel: 取消任务
    - ping: 心跳
    """
    type: str
    task_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


# ========== 沙箱 ==========

class SandboxExecuteRequest(BaseModel):
    """代码执行请求"""
    code: str = Field(..., min_length=1, max_length=50000, description="待执行代码")
    language: str = Field("python", description="编程语言")
    stdin: Optional[str] = Field(None, max_length=10000, description="标准输入")
    task_id: Optional[UUID] = Field(None, description="关联任务 ID")


class SandboxExecuteResponse(BaseModel):
    """代码执行响应"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str = SandboxStatus.QUEUED
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    memory_kb: Optional[int] = None
