"""异步任务进度推送端点 — WebSocket 实时进度 + HTTP 状态查询

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/异步任务管理.md

实现要点：
- 内存态 TaskProgressManager（dict[task_id] -> 进度信息），跨请求持久化
- update_progress(task_id, percent, message, status) helper 供服务层调用
- WebSocket 端点：连接时推送当前进度，每 1 秒检查并推送更新，
  直到 status 为 completed/failed 后关闭
- WebSocket 握手阶段校验 JWT token（query 参数 ?token=xxx）；HTTP 端点用 get_current_user
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError, UpstreamError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import success_response

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 内存态任务进度管理器 ==========


class TaskProgressManager:
    """内存态任务进度管理器

    存储结构：{task_id: {percent, message, status, owner_id, updated_at, completed_at}}

    status 取值：pending / running / completed / failed

    安全与稳定性：
    - owner_id 用于越权校验，防止任意用户订阅他人任务进度
    - 终态任务保留 1 小时后自动清理，防止内存泄漏
    """

    # 终态任务保留时长（秒）—— 超时后惰性清理
    _TERMINAL_RETENTION_SEC = 3600
    _TERMINAL_STATUSES = {"completed", "failed"}

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def update_progress(
        self,
        task_id: str,
        percent: float,
        message: str,
        status: str = "running",
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新任务进度（供服务层调用）

        Args:
            task_id: 任务 ID
            percent: 进度百分比 0-100
            message: 进度描述
            status: 任务状态（pending/running/completed/failed）
            owner_id: 任务所属用户 ID（用于越权校验，首次设置后不可变更）

        Returns:
            更新后的任务进度信息
        """
        if percent < 0:
            percent = 0.0
        elif percent > 100:
            percent = 100.0

        now = datetime.now(timezone.utc)
        # 保留已存在的 owner_id（防止后续更新覆盖）
        existing = self._tasks.get(task_id, {})
        effective_owner = owner_id or existing.get("owner_id")

        record = {
            "task_id": task_id,
            "percent": percent,
            "message": message,
            "status": status,
            "owner_id": effective_owner,
            "updated_at": now.isoformat(),
        }
        # 终态任务记录完成时间，用于 TTL 清理
        if status in self._TERMINAL_STATUSES:
            record["completed_at"] = now.isoformat()
        else:
            # 保留历史 completed_at（若存在）
            if "completed_at" in existing:
                record["completed_at"] = existing["completed_at"]
        self._tasks[task_id] = record
        logger.info(
            "任务进度更新: %s %.1f%% %s [%s]",
            task_id,
            percent,
            message,
            status,
        )
        return record

    def get_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务进度（不存在返回 None）

        惰性清理：终态任务超过 _TERMINAL_RETENTION_SEC 自动删除，防止内存泄漏。
        """
        record = self._tasks.get(task_id)
        if record is None:
            return None
        # 惰性 TTL 清理
        if record.get("status") in self._TERMINAL_STATUSES:
            completed_at = record.get("completed_at")
            if completed_at:
                try:
                    completed_dt = datetime.fromisoformat(completed_at)
                    if (datetime.now(timezone.utc) - completed_dt).total_seconds() > self._TERMINAL_RETENTION_SEC:
                        self._tasks.pop(task_id, None)
                        logger.info("任务记录 TTL 清理: %s", task_id)
                        return None
                except (ValueError, TypeError):
                    pass
        return record

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        """列出所有任务进度"""
        return dict(self._tasks)

    def delete_task(self, task_id: str) -> bool:
        """删除任务记录，返回是否删除成功"""
        return self._tasks.pop(task_id, None) is not None


# 模块级单例 — 跨请求持久化任务进度
_progress_manager = TaskProgressManager()


def get_progress_manager() -> TaskProgressManager:
    """获取全局 TaskProgressManager 单例（供服务层 import 调用）"""
    return _progress_manager


# WebSocket 推送的终态集合
_TERMINAL_STATUSES = {"completed", "failed"}

# 推送间隔（秒）
_PUSH_INTERVAL_SEC = 1.0

# ========== WebSocket 端点 ==========


@router.websocket("/tasks/{task_id}")
async def task_progress_ws(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str] = Query(None, description="JWT access token（握手阶段校验）"),
):
    """异步任务进度推送（WebSocket）

    连接时立即推送当前进度（不存在则推送 pending 占位），
    随后每 1 秒检查并推送更新，直到 status 为 completed/failed 后关闭连接。

    认证：握手阶段从 query 参数 ?token=xxx 获取 JWT，校验签名后才 accept。
    校验失败：close(code=4401) 拒绝连接。
    """
    # 握手阶段校验 token
    if not token:
        logger.warning("WebSocket 拒绝连接（缺少 token）: task_id=%s", task_id)
        await websocket.close(code=4401)
        return
    try:
        payload = decode_token(token)
        # 安全修复：只允许 access token，拒绝 refresh token（refresh token 生命周期长，
        # 泄露后可长期订阅他人任务进度）
        if payload.get("type") != "access":
            logger.warning("WebSocket 拒绝连接（非 access token）: task_id=%s", task_id)
            await websocket.close(code=4401)
            return
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4401)
            return
    except Exception as e:
        logger.warning("WebSocket 拒绝连接（token 无效）: task_id=%s err=%s", task_id, e)
        await websocket.close(code=4401)
        return

    await websocket.accept()
    logger.info("WebSocket 连接建立: task_id=%s user=%s", task_id, user_id)

    # 越权校验：若任务已有 owner 且非当前用户，拒绝订阅（防止水平越权）
    existing = _progress_manager.get_progress(task_id)
    if existing and existing.get("owner_id") and existing["owner_id"] != str(user_id):
        logger.warning(
            "WebSocket 拒绝连接（越权访问）: task_id=%s user=%s owner=%s",
            task_id, user_id, existing["owner_id"],
        )
        await websocket.close(code=4403)
        return

    # 上次推送的内容指纹，用于检测变化
    last_signature: Optional[str] = None
    # 连接开始时间，用于最大连接时长保护（防止僵尸连接占用资源）
    conn_start = datetime.now(timezone.utc)
    max_conn_sec = 1800  # 30 分钟上限

    try:
        # 首次推送当前进度
        progress = _progress_manager.get_progress(task_id)
        if progress is None:
            # 任务不存在，推送 pending 占位（任务可能尚未注册）
            # 由当前用户"认领"该 task_id 的 owner
            progress = _progress_manager.update_progress(
                task_id=task_id,
                percent=0.0,
                message="等待任务启动",
                status="pending",
                owner_id=str(user_id),
            )

        await websocket.send_json(progress)
        last_signature = f"{progress['percent']}|{progress['status']}|{progress['message']}"

        # 终态直接关闭
        if progress["status"] in _TERMINAL_STATUSES:
            logger.info("任务已终态，关闭 WebSocket: task_id=%s", task_id)
            await websocket.close()
            return

        # 轮询推送更新
        while True:
            # 最大连接时长保护，防止僵尸连接长期占用资源
            if (datetime.now(timezone.utc) - conn_start).total_seconds() > max_conn_sec:
                logger.info(
                    "WebSocket 连接超时关闭（>%ss）: task_id=%s",
                    max_conn_sec, task_id,
                )
                try:
                    cur = _progress_manager.get_progress(task_id)
                    await websocket.send_json(
                        {
                            "task_id": task_id,
                            "status": cur["status"] if cur else "running",
                            "percent": cur["percent"] if cur else 0.0,
                            "message": f"连接已达最大时长 {max_conn_sec}s，请重新连接继续订阅",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "force_close": True,
                        }
                    )
                except Exception:
                    pass
                await websocket.close()
                return
            await asyncio.sleep(_PUSH_INTERVAL_SEC)
            current = _progress_manager.get_progress(task_id)
            if current is None:
                # 任务记录被删除，通知客户端后关闭
                await websocket.send_json(
                    {
                        "task_id": task_id,
                        "status": "failed",
                        "percent": 0.0,
                        "message": "任务记录已删除",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                await websocket.close()
                return

            signature = f"{current['percent']}|{current['status']}|{current['message']}"
            if signature != last_signature:
                await websocket.send_json(current)
                last_signature = signature

            if current["status"] in _TERMINAL_STATUSES:
                logger.info("任务终态，关闭 WebSocket: task_id=%s status=%s", task_id, current["status"])
                # 给客户端一点时间接收最后一条消息
                await asyncio.sleep(0.1)
                await websocket.close()
                return
    except WebSocketDisconnect:
        logger.info("WebSocket 客户端断开: task_id=%s", task_id)
    except Exception as e:
        logger.error("WebSocket 异常: task_id=%s %s", task_id, e, exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


# ========== HTTP 辅助端点 ==========


@router.get("/tasks/{task_id}/status", summary="查询任务进度")
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询异步任务进度（HTTP 轮询回退方案）

    适用于不便使用 WebSocket 的客户端，或需要鉴权查询的场景。
    """
    progress = _progress_manager.get_progress(task_id)
    if progress is None:
        raise NotFoundError(
            f"任务不存在或尚未启动: {task_id}",
            details={"task_id": task_id},
        )

    # 越权校验：任务拥有者非当前用户时拒绝（与 WebSocket 端点保持一致）
    owner_id = progress.get("owner_id")
    if owner_id and owner_id != str(current_user.id):
        logger.warning(
            "HTTP 任务进度查询越权拒绝: task_id=%s user=%s owner=%s",
            task_id, current_user.id, owner_id,
        )
        # 出于安全考虑，越权时返回 404 而非 403，避免泄漏任务存在性
        raise NotFoundError(
            f"任务不存在或尚未启动: {task_id}",
            details={"task_id": task_id},
        )

    return success_response(data=progress)