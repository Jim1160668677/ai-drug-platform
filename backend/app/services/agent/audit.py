"""Agent 审计日志器 — 异步写入 AuditLog 表

设计来源：2026-07-18-agent-functional-design.md §8

复用现有 app.models.audit.AuditLog（不可篡改 append-only 表）。
所有 Agent 相关动作（任务创建、工具调用、沙箱执行、确认操作）均记录。
"""
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UserRole
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


# 需要脱敏的字段名（任意层级出现都打码）
_SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "auth", "credentials", "private_key",
}


def _mask_sensitive(params: Any) -> Any:
    """递归脱敏：将敏感字段的值替换为 ***REDACTED***"""
    if isinstance(params, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else _mask_sensitive(v))
            for k, v in params.items()
        }
    if isinstance(params, list):
        return [_mask_sensitive(x) for x in params]
    return params


class AuditLogger:
    """审计日志写入器

    设计原则：
    - 异步写入，失败不阻塞主流程（仅记录日志告警）
    - 自动脱敏敏感字段
    - 复用 AuditLog 表的 actor/role/action/entity 字段约定
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_action(
        self,
        *,
        actor: str,
        role: Optional[str],
        action: str,
        entity: Optional[str] = None,
        entity_id: Optional[str] = None,
        before_val: Optional[dict] = None,
        after_val: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """写入一条审计日志

        Args:
            actor: 操作者标识（user_id 或 username）
            role: 操作者角色
            action: 动作类型（如 agent.task.created / agent.tool.called）
            entity: 实体类型（如 agent_task / agent_session）
            entity_id: 实体 ID
            before_val: 修改前值（脱敏后）
            after_val: 修改后值（脱敏后）
            ip_address: 请求方 IP
            user_agent: UA
            detail: 自由文本详情
        """
        try:
            record = AuditLog(
                actor=actor,
                role=role,
                action=action,
                entity=entity,
                entity_id=str(entity_id) if entity_id else None,
                before_val=_mask_sensitive(before_val) if before_val else None,
                after_val=_mask_sensitive(after_val) if after_val else None,
                ip_address=ip_address,
                user_agent=user_agent,
                detail=detail,
            )
            self.db.add(record)
            await self.db.flush()  # 仅 flush，由调用方决定 commit
        except Exception as e:
            # 审计失败不阻塞主流程
            logger.error(f"审计日志写入失败: {e}", exc_info=True)

    async def log_task_created(
        self,
        user_id: str,
        role: Optional[str],
        task_id: str,
        session_id: str,
        query: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """记录任务创建"""
        await self.log_action(
            actor=user_id,
            role=role,
            action="agent.task.created",
            entity="agent_task",
            entity_id=task_id,
            after_val={"session_id": session_id, "query": query[:500]},
            ip_address=ip_address,
        )

    async def log_tool_call(
        self,
        user_id: str,
        role: Optional[str],
        task_id: str,
        tool: str,
        args: dict,
        success: bool,
        ip_address: Optional[str] = None,
    ) -> None:
        """记录工具调用"""
        await self.log_action(
            actor=user_id,
            role=role,
            action=f"agent.tool.{'success' if success else 'failed'}",
            entity="agent_tool_call",
            entity_id=task_id,
            after_val={"tool": tool, "args": args, "success": success},
            ip_address=ip_address,
        )

    async def log_sandbox_exec(
        self,
        user_id: str,
        role: Optional[str],
        task_id: Optional[str],
        sandbox_id: str,
        code: str,
        exit_code: Optional[int],
        success: bool,
    ) -> None:
        """记录沙箱执行（code 不完整记录，仅前 200 字符用于审计）"""
        await self.log_action(
            actor=user_id,
            role=role,
            action=f"agent.sandbox.{'success' if success else 'failed'}",
            entity="sandbox_execution",
            entity_id=sandbox_id,
            after_val={
                "task_id": task_id,
                "code_preview": code[:200],
                "exit_code": exit_code,
            },
        )

    async def log_confirmation(
        self,
        user_id: str,
        role: Optional[str],
        task_id: str,
        tool: str,
        approved: bool,
    ) -> None:
        """记录副作用确认结果"""
        await self.log_action(
            actor=user_id,
            role=role,
            action=f"agent.confirm.{'approved' if approved else 'rejected'}",
            entity="agent_confirmation",
            entity_id=task_id,
            after_val={"tool": tool, "approved": approved},
        )
