"""Agent REST + WebSocket 端点

设计来源：2026-07-18-agent-functional-design.md §6

REST 端点：
- POST   /agent/sessions                 创建会话
- GET    /agent/sessions                 会话列表
- GET    /agent/sessions/{session_id}    会话详情
- DELETE /agent/sessions/{session_id}    归档会话
- POST   /agent/chat                     发起对话（异步执行，返回 task_id）
- GET    /agent/tasks/{task_id}          查询任务状态
- POST   /agent/tasks/{task_id}/cancel   取消任务
- GET    /agent/tools                    列出当前用户可用工具

WebSocket 端点：
- WS /agent/ws/{session_id}?token=xxx    订阅会话内任务进度
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_llm_client_with_config, get_active_llm_config
from app.core.exceptions import (
    NotFoundError,
    ForbiddenError,
    ValidationError,
    RateLimitedError,
)
from app.db.session import get_db
from app.models.agent_session import AgentSession, SessionStatus
from app.models.agent_task import AgentTask, TaskStatus, TERMINAL_STATUSES
from app.models.user import User
from app.schemas.agent import (
    ChatRequest,
    ChatResponse,
    ConfirmationResponse,
    SessionCreate,
    SessionResponse,
    TaskResponse,
    ToolInfo,
    WSEvent,
)
from app.schemas.common import paged_response, success_response
from app.services.agent.audit import AuditLogger
from app.services.agent.engine import AgentEngine
from app.services.agent.planner import TaskPlanner
from app.services.agent.progress import ProgressManager
from app.services.agent.ratelimit import get_rate_limiter
from app.services.agent.session import SessionManager
from app.services.agent.tools.registry import get_tool_registry
from app.services.agent.ws_handler import (
    WS_CODE_AUTH_FAILED,
    WS_CODE_FORBIDDEN,
    authenticate_ws_token,
    make_event,
    reject_ws,
)
from app.services.llm.guardrail import get_guardrail
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 工具函数 ==========


def _check_session_owner(session: AgentSession, user: User) -> None:
    """会话归属校验"""
    if session.user_id != user.id:
        # 越权返回 404 避免泄漏存在性
        raise NotFoundError("会话不存在")


def _check_task_owner(task: AgentTask, user: User) -> None:
    """任务归属校验"""
    if task.user_id != user.id:
        raise NotFoundError("任务不存在")


async def _build_engine(db: AsyncSession, user: User) -> AgentEngine:
    """构造 AgentEngine 实例（每次请求新建）"""
    # 注意：get_llm_client_with_config 只返回 client（不是 tuple）。
    # 如需数据库激活的 LLMConfig，用 get_active_llm_config 单独取。
    llm_client = await get_llm_client_with_config(db)
    llm_config = await get_active_llm_config(db)
    llm_router = LLMRouter(llm_client, llm_config)

    registry = get_tool_registry()
    planner = TaskPlanner(llm_router)
    session_mgr = SessionManager(db)
    progress = ProgressManager()
    audit = AuditLogger(db)
    ratelimit = get_rate_limiter()

    return AgentEngine(
        db=db,
        llm_router=llm_router,
        registry=registry,
        planner=planner,
        session_mgr=session_mgr,
        progress=progress,
        audit=audit,
        ratelimit=ratelimit,
        guardrail=get_guardrail(),
    )


# ========== 会话端点 ==========


@router.post("/sessions", response_model=dict, summary="创建会话")
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新 Agent 会话"""
    session_mgr = SessionManager(db)
    session = await session_mgr.create(
        user_id=current_user.id,
        title=payload.title,
        project_id=payload.project_id,
    )
    await db.commit()
    return success_response(
        data=SessionResponse.model_validate(session).model_dump(exclude={"context"})
    )


@router.get("/sessions", response_model=dict, summary="会话列表")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的会话"""
    session_mgr = SessionManager(db)
    items, total = await session_mgr.list_sessions(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        include_archived=include_archived,
    )
    data = [
        SessionResponse.model_validate(s).model_dump(exclude={"context"})
        for s in items
    ]
    return paged_response(data=data, page=page, page_size=page_size, total=total)


@router.get("/sessions/{session_id}", response_model=dict, summary="会话详情")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话详情（含上下文）"""
    session = await db.get(AgentSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _check_session_owner(session, current_user)
    return success_response(
        data=SessionResponse.model_validate(session).model_dump()
    )


@router.delete("/sessions/{session_id}", response_model=dict, summary="归档会话")
async def archive_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """归档会话（软删除，可恢复）"""
    session_mgr = SessionManager(db)
    ok = await session_mgr.archive(session_id, current_user.id)
    if not ok:
        raise NotFoundError("会话不存在")
    await db.commit()
    return success_response(data={"archived": True, "session_id": str(session_id)})


# ========== 对话端点 ==========


@router.post("/chat", response_model=dict, summary="发起 Agent 对话")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发起对话 — 异步执行

    同步返回 task_id，客户端通过 WebSocket 订阅 /agent/ws/{session_id} 接收实时进度。
    """
    # 1. 校验会话归属
    session = await db.get(AgentSession, payload.session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    _check_session_owner(session, current_user)

    # 2. 限流：RPM
    ratelimit = get_rate_limiter()
    ok, retry_after = await ratelimit.check_rpm(str(current_user.id))
    if not ok:
        raise RateLimitedError(
            "请求过于频繁，请稍后重试",
            retry_after=retry_after,
        )

    # 3. 并发任务数限制
    ok, _ = await ratelimit.acquire_concurrency(str(current_user.id))
    if not ok:
        raise RateLimitedError("并发任务数已达上限")

    # 4. 创建任务记录
    task = AgentTask(
        session_id=session.id,
        user_id=current_user.id,
        project_id=payload.project_id or session.project_id,
        query=payload.message,
        status=TaskStatus.PENDING,
    )
    db.add(task)

    # 5. 审计
    audit = AuditLogger(db)
    role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    await audit.log_task_created(
        user_id=str(current_user.id),
        role=role_str,
        task_id=str(task.id),
        session_id=str(session.id),
        query=payload.message,
    )

    await db.commit()
    await db.refresh(task)

    # 6. 异步启动引擎（不阻塞响应）
    # 注意：闭包内不能直接使用 current_user —— 请求返回后外层 db session 关闭，
    # user 实例将变 detached，访问 user.role 等属性会抛 DetachedInstanceError。
    # 因此在闭包外提取 user_id，闭包内重新加载 user 实例。
    task_id_str = str(task.id)
    session_id_str = str(session.id)
    project_id_str = str(payload.project_id or session.project_id) if (payload.project_id or session.project_id) else None
    tier = payload.tier
    user_id = current_user.id
    user_role_str = role_str

    async def _run_in_background():
        # 后台运行：使用新的 db session 避免生命周期问题
        from app.db.session import async_session_factory
        from sqlalchemy import select
        from app.models.user import User

        async with async_session_factory() as bg_db:
            try:
                # 重新加载 user 实例，避免 detached state
                result = await bg_db.execute(select(User).where(User.id == user_id))
                bg_user = result.scalar_one_or_none()
                if bg_user is None:
                    logger.error(f"Agent 后台任务：用户 {user_id} 不存在")
                    return

                engine = await _build_engine(bg_db, bg_user)
                await engine.run(
                    task_id=task.id,
                    query=payload.message,
                    session_id=session.id,
                    user=bg_user,
                    project_id=payload.project_id or session.project_id,
                    tier=tier,
                )
                await bg_db.commit()
            except Exception as e:
                logger.error(f"Agent 后台任务失败: {e}", exc_info=True)
                await bg_db.rollback()
            finally:
                # 释放并发槽位
                await ratelimit.release_concurrency(str(user_id))

    # 使用 asyncio.create_task 启动后台执行
    asyncio.create_task(_run_in_background())

    return success_response(
        data=ChatResponse(
            task_id=task.id,
            session_id=session.id,
            status=TaskStatus.PENDING,
        ).model_dump()
    )


# ========== 任务端点 ==========


@router.get("/tasks/{task_id}", response_model=dict, summary="查询任务状态")
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询任务状态与结果"""
    task = await db.get(AgentTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    _check_task_owner(task, current_user)
    return success_response(data=TaskResponse.model_validate(task).model_dump())


@router.post("/tasks/{task_id}/cancel", response_model=dict, summary="取消任务")
async def cancel_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消未完成的任务"""
    task = await db.get(AgentTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    _check_task_owner(task, current_user)

    if task.status in TERMINAL_STATUSES:
        raise ValidationError(f"任务已处于终态: {task.status}，无法取消")

    task.status = TaskStatus.CANCELLED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.error = "用户主动取消"
    await db.commit()

    # 推送取消事件
    progress = ProgressManager()
    progress.push_task_cancelled(str(task_id), owner_id=str(current_user.id))

    return success_response(data={"cancelled": True, "task_id": str(task_id)})


# ========== 工具列表端点 ==========


@router.get("/tools", response_model=dict, summary="列出当前用户可用工具")
async def list_tools(
    current_user: User = Depends(get_current_user),
):
    """列出当前用户角色可使用的所有工具"""
    registry = get_tool_registry()
    tools = registry.list_for_user(current_user)
    return success_response(data={"tools": tools, "total": len(tools)})


# ========== WebSocket 端点 ==========


@router.websocket("/ws/{session_id}")
async def agent_ws(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None, description="JWT access token"),
):
    """Agent 会话 WebSocket — 推送任务进度事件

    连接后订阅该会话内所有任务的进度更新。
    事件类型：task_started / plan / thought / tool_call / tool_result /
    final_response / error / confirmation_required / task_completed
    """
    # 鉴权
    user_id = await authenticate_ws_token(token)
    if user_id is None:
        await reject_ws(websocket, WS_CODE_AUTH_FAILED, "鉴权失败")
        return

    await websocket.accept()
    logger.info(f"Agent WS 连接建立: session={session_id} user={user_id}")

    # 校验会话归属
    from app.db.session import async_session_factory
    from sqlalchemy import select

    async with async_session_factory() as db:
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            await websocket.close(code=4400, reason="无效的 session_id")
            return

        session = await db.get(AgentSession, session_uuid)
        if session is None or str(session.user_id) != user_id:
            logger.warning(
                f"Agent WS 越权拒绝: session={session_id} user={user_id}"
            )
            await websocket.close(code=WS_CODE_FORBIDDEN, reason="无权访问此会话")
            return

    # 进入消息循环
    conn_start = datetime.now(timezone.utc)
    max_conn_sec = 1800  # 30 分钟

    try:
        # 发送连接成功事件
        await websocket.send_json(
            make_event(
                "connected",
                task_id="",
                payload={"session_id": session_id, "user_id": user_id},
            )
        )

        while True:
            # 超时保护
            if (datetime.now(timezone.utc) - conn_start).total_seconds() > max_conn_sec:
                await websocket.send_json(
                    make_event(
                        "force_close",
                        "",
                        {"reason": f"连接已达最大时长 {max_conn_sec}s"},
                    )
                )
                await websocket.close()
                return

            # 接收客户端消息（带超时）
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json(
                    make_event("ping", "", {"ts": datetime.now(timezone.utc).isoformat()})
                )
                continue

            # 解析客户端消息
            try:
                import json
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    make_event("error", "", {"error": "消息格式错误，需 JSON"})
                )
                continue

            msg_type = msg.get("type", "")
            task_id = msg.get("task_id", "")

            if msg_type == "ping":
                await websocket.send_json(
                    make_event("pong", task_id, {"ts": datetime.now(timezone.utc).isoformat()})
                )
            elif msg_type == "subscribe":
                # 订阅任务进度（用 TaskProgressManager 查询当前状态）
                from app.api.v1.endpoints.ws import get_progress_manager
                pm = get_progress_manager()
                progress = pm.get_progress(task_id)
                if progress:
                    # 越权校验
                    owner_id = progress.get("owner_id")
                    if owner_id and owner_id != user_id:
                        await websocket.send_json(
                            make_event(
                                "error",
                                task_id,
                                {"error": "无权订阅此任务"},
                            )
                        )
                        continue
                    await websocket.send_json(
                        {
                            "type": "progress_snapshot",
                            "task_id": task_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "payload": progress,
                        }
                    )
                else:
                    await websocket.send_json(
                        make_event(
                            "not_found",
                            task_id,
                            {"error": "任务不存在或尚未启动"},
                        )
                    )
            elif msg_type == "cancel":
                # 取消任务
                async with async_session_factory() as cancel_db:
                    from sqlalchemy import select
                    try:
                        task_uuid = UUID(task_id)
                    except ValueError:
                        continue
                    task = await cancel_db.get(AgentTask, task_uuid)
                    if task and str(task.user_id) == user_id:
                        if task.status not in TERMINAL_STATUSES:
                            task.status = TaskStatus.CANCELLED
                            task.completed_at = datetime.now(timezone.utc).isoformat()
                            task.error = "用户主动取消（WS）"
                            await cancel_db.commit()
                            await websocket.send_json(
                                make_event("task_cancelled", task_id, {"reason": "user_cancelled"})
                            )
            elif msg_type == "unsubscribe":
                # 客户端主动取消订阅（无服务端状态，仅确认）
                await websocket.send_json(
                    make_event("unsubscribed", task_id, {})
                )

    except WebSocketDisconnect:
        logger.info(f"Agent WS 客户端断开: session={session_id}")
    except Exception as e:
        logger.error(f"Agent WS 异常: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass
