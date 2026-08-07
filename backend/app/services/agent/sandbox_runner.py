"""Docker 沙箱代码执行器

设计来源：2026-07-18-agent-functional-design.md §8（Docker 隔离）

延迟 import docker，避免在未启用沙箱时强制依赖。
所有同步 docker SDK 调用用 asyncio.to_thread 包装，避免阻塞事件循环
（项目硬约束：CPU 密集操作不得阻塞事件循环）。

兼容两个调用点：
- endpoints/sandbox.py：传入 record（SandboxExecution 实例）持久化字段
- tools/sandbox.py：不传 record，仅返回 dict 结果
"""
import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sandbox_execution import SandboxExecution, SandboxStatus

logger = logging.getLogger(__name__)


class SandboxRunner:
    """Docker 容器代码执行器

    安全策略：
    - network_disabled=True：无网络访问
    - read_only=True：只读文件系统（仅 /tmp 可写）
    - tmpfs={"/tmp": "size=512m"}：tmpfs 内存盘
    - mem_limit="512m"：内存上限
    - cpu_quota=100000 / cpu_period=100000：1 核 CPU
    - timeout=30s：执行超时
    """

    IMAGE_NAME = "ai-drug-sandbox:latest"
    STDOUT_TRUNCATE = 50000
    STDERR_TRUNCATE = 50000

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def run(
        self,
        *,
        code: str,
        stdin: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: str,
        db: AsyncSession,
        record: Optional[SandboxExecution] = None,
    ) -> Dict[str, Any]:
        """执行代码

        Args:
            code: Python 代码
            stdin: 标准输入
            task_id: 关联任务 ID（用于日志）
            user_id: 用户 ID
            db: 数据库会话
            record: 沙箱执行记录（可选，端点调用时传入，工具调用时不传）

        Returns:
            执行结果 dict（含 stdout/stderr/exit_code/duration_ms/status 等字段）
        """
        started_at = datetime.now(timezone.utc)
        start_ts = time.monotonic()

        try:
            result = await asyncio.to_thread(
                self._run_container, code, stdin
            )
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            completed_at = datetime.now(timezone.utc)

            exit_code = result.get("exit_code", -1)
            status = (
                SandboxStatus.COMPLETED if exit_code == 0 else SandboxStatus.FAILED
            )
            result.update(
                {
                    "duration_ms": duration_ms,
                    "started_at": started_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "status": status,
                }
            )

            # 如有 record，持久化字段
            if record is not None:
                record.stdout = result.get("stdout", "")
                record.stderr = result.get("stderr", "")
                record.exit_code = exit_code
                record.duration_ms = duration_ms
                record.started_at = started_at
                record.completed_at = completed_at
                record.status = status
                record.memory_kb = result.get("memory_kb")
                await db.flush()

            return result

        except Exception as e:
            logger.error(f"沙箱执行异常: {e}", exc_info=True)
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            completed_at = datetime.now(timezone.utc)

            error_result = {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -2,
                "duration_ms": duration_ms,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "status": SandboxStatus.FAILED,
                "memory_kb": 0,
            }

            if record is not None:
                record.stderr = str(e)
                record.exit_code = -2
                record.duration_ms = duration_ms
                record.started_at = started_at
                record.completed_at = completed_at
                record.status = SandboxStatus.FAILED
                await db.flush()

            return error_result

    def _run_container(
        self, code: str, stdin: Optional[str]
    ) -> Dict[str, Any]:
        """同步执行 docker 容器（在线程池中调用）"""
        import docker  # 延迟导入：未装 docker 包时仍可 import 本模块

        client = docker.from_env()

        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        container = None
        try:
            container = client.containers.run(
                image=self.IMAGE_NAME,
                command=["python", "/sandbox/code.py"],
                volumes={tmp_path: {"bind": "/sandbox/code.py", "mode": "ro"}},
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "size=512m"},
                mem_limit="512m",
                cpu_quota=100000,
                cpu_period=100000,
                stdin_open=stdin is not None,
                detach=True,
            )

            if stdin:
                # 通过 attach 传入 stdin
                socket = container.attach(stdin=True, stream=False)
                try:
                    socket.send(stdin.encode("utf-8"))
                finally:
                    socket.close()

            # 等待容器完成（带超时）
            exit_info = container.wait(timeout=self.timeout)
            exit_code = exit_info.get("StatusCode", -1)

            # 获取日志
            stdout = container.logs(stdout=True, stderr=False).decode(
                "utf-8", errors="replace"
            )
            stderr = container.logs(stdout=False, stderr=True).decode(
                "utf-8", errors="replace"
            )

            # 截断
            stdout = stdout[: self.STDOUT_TRUNCATE]
            stderr = stderr[: self.STDERR_TRUNCATE]

            # 内存使用（best effort）
            memory_kb = 0
            try:
                stats = container.stats(stream=False)
                memory_kb = stats.get("memory_stats", {}).get("usage", 0) // 1024
            except Exception:
                pass

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "memory_kb": memory_kb,
            }

        except Exception:
            # 超时或异常 → 强制 kill 容器
            if container is not None:
                try:
                    container.kill()
                except Exception:
                    pass
            raise

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
