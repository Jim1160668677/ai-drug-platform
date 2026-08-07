"""沙箱代码执行端点 — REST 接口

设计来源：2026-07-18-agent-functional-design.md §6

提供 REST 接口直接执行代码（绕过 Agent 引擎，用于调试与一次性脚本）。
权限严格：仅 FOUNDER / CHIEF_RESEARCHER / DATA_ENGINEER 可用。
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.core.exceptions import ForbiddenError, NotFoundError, UpstreamError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.sandbox_execution import SandboxExecution, SandboxStatus
from app.models.user import User
from app.schemas.agent import SandboxExecuteRequest, SandboxExecuteResponse
from app.schemas.common import success_response
from app.services.agent.audit import AuditLogger

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/execute", response_model=dict, summary="代码执行（沙箱）")
async def execute_code(
    payload: SandboxExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER, UserRole.DATA_ENGINEER)
    ),
):
    """在隔离的 Docker 沙箱内执行代码

    权限：仅 FOUNDER / CHIEF_RESEARCHER / DATA_ENGINEER
    限制：无网络、只读文件系统、内存 512MB、CPU 1 核、超时 30 秒
    """
    if not settings.AGENT_SANDBOX_ENABLED:
        raise ForbiddenError(
            "沙箱功能未启用（设置 AGENT_SANDBOX_ENABLED=true 开启）"
        )

    # 创建执行记录
    record = SandboxExecution(
        task_id=payload.task_id,
        user_id=current_user.id,
        code=payload.code,
        language=payload.language,
        stdin=payload.stdin,
        status=SandboxStatus.QUEUED,
    )
    db.add(record)
    await db.flush()

    # 审计
    audit = AuditLogger(db)
    role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    await audit.log_sandbox_exec(
        user_id=str(current_user.id),
        role=role_str,
        task_id=str(payload.task_id) if payload.task_id else None,
        sandbox_id=str(record.id),
        code=payload.code,
        exit_code=None,
        success=False,
    )

    try:
        from app.services.agent.sandbox_runner import SandboxRunner

        runner = SandboxRunner()
        result = await runner.run(
            code=payload.code,
            stdin=payload.stdin,
            task_id=str(record.id),
            user_id=str(current_user.id),
            db=db,
            record=record,
        )
        await db.commit()
        return success_response(
            data=SandboxExecuteResponse.model_validate(record).model_dump()
        )
    except ImportError:
        await db.rollback()
        raise UpstreamError(
            "沙箱运行时未安装（需要 docker Python 包）",
            service="sandbox",
        )
    except Exception as e:
        logger.error(f"沙箱执行失败: {e}", exc_info=True)
        record.status = SandboxStatus.FAILED
        record.stderr = str(e)
        await db.commit()
        raise UpstreamError(f"沙箱执行失败: {e}", service="sandbox")


@router.get("/{execution_id}", response_model=dict, summary="查询执行结果")
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询沙箱执行记录"""
    record = await db.get(SandboxExecution, execution_id)
    if record is None:
        raise NotFoundError("执行记录不存在")
    if record.user_id != current_user.id and current_user.role != UserRole.FOUNDER:
        raise ForbiddenError("无权访问此执行记录")
    return success_response(
        data=SandboxExecuteResponse.model_validate(record).model_dump()
    )
