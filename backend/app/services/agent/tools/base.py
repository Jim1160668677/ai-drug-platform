"""Agent 工具基类 — Protocol + 通用数据类

设计来源：2026-07-18-agent-functional-design.md §3.1
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UserRole
from app.models.user import User


@dataclass
class ToolContext:
    """工具执行上下文

    工具执行时所需的环境信息。所有工具通过此上下文访问数据库、用户信息等。
    """
    db: AsyncSession
    user: User
    task_id: str
    session_id: str
    project_id: Optional[str] = None
    # 副作用确认回调：返回 True 表示用户同意，False 表示拒绝
    confirm_callback: Optional[Callable[[Dict[str, Any]], Awaitable[bool]]] = None
    # 进度推送器（可选，工具内可推送子进度）
    progress: Optional[Any] = None


@dataclass
class ToolResult:
    """工具执行结果

    Attributes:
        success: 是否成功
        data: 返回数据（成功时）
        error: 错误信息（失败时）
        display: 前端展示提示（如 {type: "table"|"chart"|"molecule", payload: ...}）
    """
    success: bool
    data: Any = None
    error: Optional[str] = None
    display: Optional[Dict[str, Any]] = None

    @classmethod
    def ok(cls, data: Any, display: Optional[Dict[str, Any]] = None) -> "ToolResult":
        return cls(success=True, data=data, display=display)

    @classmethod
    def fail(cls, error: str, data: Any = None) -> "ToolResult":
        return cls(success=False, data=data, error=error)


@dataclass
class ToolParameter:
    """工具参数定义（用于生成 JSON Schema）"""
    name: str
    type: str  # string / integer / number / boolean / array / object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[list] = None


class AgentTool:
    """Agent 工具基类

    子类需设置：
    - name: 工具唯一标识（如 discover_targets）
    - description: 工具描述（供 LLM 选择工具）
    - parameters: 参数列表（用于 JSON Schema 生成）
    - side_effects: 是否有副作用（True 则执行前需用户确认）
    - required_role: 最低权限角色

    子类需实现：
    - execute(params, ctx) -> ToolResult
    """

    name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = []
    side_effects: bool = False
    required_role: UserRole = UserRole.RESEARCHER

    def to_schema(self) -> Dict[str, Any]:
        """生成 JSON Schema（供 LLM 与前端使用）"""
        properties = {}
        required = []
        for p in self.parameters:
            prop: Dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.default is not None:
                prop["default"] = p.default
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def to_info(self) -> Dict[str, Any]:
        """工具信息（供 GET /tools 端点）"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.to_schema(),
            "side_effects": self.side_effects,
            "required_role": self.required_role.value
            if isinstance(self.required_role, UserRole)
            else str(self.required_role),
        }

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """子类必须实现"""
        raise NotImplementedError

    async def execute_safely(
        self, params: Dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        """带统一异常捕获的执行入口

        - 同步阻塞调用自动用 asyncio.to_thread 包装（防止事件循环阻塞）
        - 异常统一转为 ToolResult.fail
        """
        try:
            result = self.execute(params, ctx)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            return ToolResult.fail(error=f"工具执行异常: {type(e).__name__}: {e}")
