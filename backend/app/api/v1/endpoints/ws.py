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

    存储结构：{task_id: {percent, message, status, updated_at}}

    status 取值：pending / running / completed / failed
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def update_progress(
        self,
        task_id: str,
        percent: float,
        message: str,
        status: str = "running",
    ) -> Dict[str, Any]:
        """更新任务进度（供服务层调用）

        Args:
            task_id: 任务 ID
            percent: 进度百分比 0-100
            message: 进度描述
            status: 任务状态（pending/running/completed/failed）

        Returns:
            更新后的任务进度信息
        """
        if percent < 0:
            percent = 0.0
        elif percent > 100:
            percent = 100.0

        record = {
            "task_id": task_id,
            "percent": percent,
            "message": message,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
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
        """获取任务进度（不存在返回 None）"""
        return self._tasks.get(task_id)

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

    # 上次推送的内容指纹，用于检测变化
    last_signature: Optional[str] = None

    try:
        # 首次推送当前进度
        progress = _progress_manager.get_progress(task_id)
        if progress is None:
            # 任务不存在，推送 pending 占位（任务可能尚未注册）
            progress = _progress_manager.update_progress(
                task_id=task_id,
                percent=0.0,
                message="等待任务启动",
                status="pending",
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

    return success_response(data=progress)