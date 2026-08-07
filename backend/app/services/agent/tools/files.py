"""文件操作工具组 — 2 个工具

工具列表：
- read_file    读取文件（沙箱白名单内）
- write_file   写入文件（副作用，需确认）
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings
from app.core.security import UserRole
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


# 允许访问的根目录白名单（绝对路径）
_ALLOWED_ROOTS = [
    str(Path.cwd() / "workspace"),
    str(Path.cwd() / "data"),
    "/tmp/agent_workspace",
]


def _is_path_allowed(path: str) -> bool:
    """路径白名单校验：防止目录穿越攻击"""
    try:
        abs_path = os.path.abspath(path)
        # 对白名单根目录也做 abspath 归一化，避免跨平台路径分隔符差异
        # （_ALLOWED_ROOTS 中的 "/tmp/agent_workspace" 在 Windows 上需转为 "C:\\tmp\\..."）
        abs_roots = [os.path.abspath(r) for r in _ALLOWED_ROOTS]
        return any(abs_path.startswith(root) for root in abs_roots)
    except Exception:
        return False


class ReadFileTool(AgentTool):
    """读取文件 — 沙箱白名单内"""

    name = "read_file"
    description = (
        "读取工作目录内文件内容。"
        "仅允许访问 workspace/ 和 data/ 目录下的文件。"
        "返回文件内容（文本）或 base64 编码（二进制）。"
    )
    parameters = [
        ToolParameter("path", "string", "文件路径（相对 workspace/ 或 data/）", required=True),
        ToolParameter("max_size_kb", "integer", "最大读取大小（KB）", required=False, default=100),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        import asyncio

        path = params["path"]
        max_size_kb = min(max(params.get("max_size_kb", 100), 1), 1024)

        if not _is_path_allowed(path):
            return ToolResult.fail(
                error=f"路径不在允许范围内: {path}",
                data={"allowed_roots": _ALLOWED_ROOTS},
            )

        try:
            def _read():
                file_size = os.path.getsize(path)
                if file_size > max_size_kb * 1024:
                    raise ValueError(f"文件过大: {file_size} bytes > {max_size_kb}KB")
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read(), file_size

            content, size = await asyncio.to_thread(_read)
            return ToolResult.ok(
                data={
                    "path": path,
                    "content": content,
                    "size_bytes": size,
                },
                display={"type": "text", "payload": {"content": content[:5000]}},
            )
        except FileNotFoundError:
            return ToolResult.fail(error=f"文件不存在: {path}")
        except Exception as e:
            logger.error(f"read_file 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class WriteFileTool(AgentTool):
    """写入文件 — 副作用，需用户确认"""

    name = "write_file"
    description = (
        "写入内容到工作目录内文件。"
        "仅允许写入 workspace/ 目录。"
        "会覆盖已存在的文件，执行前需用户确认。"
    )
    parameters = [
        ToolParameter("path", "string", "文件路径（相对 workspace/）", required=True),
        ToolParameter("content", "string", "文件内容", required=True),
        ToolParameter("append", "boolean", "是否追加（默认覆盖）", required=False, default=False),
    ]
    side_effects = True  # 写文件有副作用，需用户确认
    required_role = UserRole.CHIEF_RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        import asyncio

        path = params["path"]
        content = params["content"]
        append = params.get("append", False)

        if not _is_path_allowed(path):
            return ToolResult.fail(
                error=f"路径不在允许范围内: {path}",
                data={"allowed_roots": _ALLOWED_ROOTS},
            )

        try:
            def _write():
                # 确保目录存在
                os.makedirs(os.path.dirname(path), exist_ok=True)
                mode = "a" if append else "w"
                with open(path, mode, encoding="utf-8") as f:
                    f.write(content)
                return os.path.getsize(path)

            size = await asyncio.to_thread(_write)
            return ToolResult.ok(
                data={
                    "path": path,
                    "size_bytes": size,
                    "mode": "append" if append else "overwrite",
                },
            )
        except Exception as e:
            logger.error(f"write_file 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
