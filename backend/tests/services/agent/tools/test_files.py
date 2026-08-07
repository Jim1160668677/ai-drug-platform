"""files 工具组测试 — 2 个工具 + _is_path_allowed"""
import os
from unittest.mock import MagicMock

import pytest

from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.files import (
    ReadFileTool,
    WriteFileTool,
    _ALLOWED_ROOTS,
    _is_path_allowed,
)


def _make_ctx(db=None, user=None):
    return ToolContext(
        db=db or MagicMock(),
        user=user or MagicMock(),
        task_id="task-f",
        session_id="session-f",
    )


# ========== _is_path_allowed 路径白名单 ==========


def test_is_path_allowed_workspace(monkeypatch, tmp_path):
    """workspace/ 下的路径 → True"""
    # 用 tmp_path 模拟 workspace 目录
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )
    target = workspace / "test.txt"
    assert _is_path_allowed(str(target)) is True


def test_is_path_allowed_data(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(data_dir)],
    )
    target = data_dir / "sub" / "file.csv"
    assert _is_path_allowed(str(target)) is True


def test_is_path_allowed_tmp(monkeypatch):
    """/tmp/agent_workspace/ 下 → True（Unix 路径，Windows 下可能 False）"""
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        ["/tmp/agent_workspace"],
    )
    # 在 Windows 上 /tmp 会被解析为当前盘符的 \tmp
    result = _is_path_allowed("/tmp/agent_workspace/file.txt")
    assert result is True


def test_is_path_allowed_blocked_etc(monkeypatch):
    """/etc/passwd → False"""
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        ["/tmp/agent_workspace"],
    )
    assert _is_path_allowed("/etc/passwd") is False


def test_is_path_allowed_blocked_traversal(monkeypatch, tmp_path):
    """workspace/../etc → 解析后不在白名单 → False"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )
    # workspace/../other 解析后是 tmp_path/other，不在白名单
    traversal = str(workspace / ".." / "other" / "file.txt")
    assert _is_path_allowed(traversal) is False


# ========== ReadFileTool ==========


@pytest.mark.asyncio
async def test_read_file_success(monkeypatch, tmp_path):
    """成功读取白名单内文件"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "hello.txt"
    test_file.write_text("hello world", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = ReadFileTool()
    ctx = _make_ctx()
    result = await tool.execute({"path": str(test_file)}, ctx)

    assert result.success is True
    assert result.data["content"] == "hello world"
    assert result.display["type"] == "text"


@pytest.mark.asyncio
async def test_read_file_too_large(monkeypatch, tmp_path):
    """文件大小 > max_size_kb → fail"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "big.txt"
    test_file.write_text("x" * 2048, encoding="utf-8")  # 2KB

    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = ReadFileTool()
    ctx = _make_ctx()
    result = await tool.execute({"path": str(test_file), "max_size_kb": 1}, ctx)

    assert result.success is False
    assert "文件过大" in result.error


@pytest.mark.asyncio
async def test_read_file_blocked_path(monkeypatch, tmp_path):
    """路径不在白名单 → fail"""
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(tmp_path / "workspace")],  # 不存在的目录
    )

    tool = ReadFileTool()
    ctx = _make_ctx()
    result = await tool.execute({"path": "/etc/passwd"}, ctx)

    assert result.success is False
    assert "路径不在允许范围内" in result.error


@pytest.mark.asyncio
async def test_read_file_not_found(monkeypatch, tmp_path):
    """白名单内但文件不存在 → fail"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = ReadFileTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"path": str(workspace / "nonexistent.txt")}, ctx
    )

    assert result.success is False
    assert "文件不存在" in result.error


# ========== WriteFileTool ==========


def test_write_file_metadata():
    """元数据：side_effects=True, required_role=CHIEF_RESEARCHER"""
    tool = WriteFileTool()
    assert tool.name == "write_file"
    assert tool.side_effects is True
    assert tool.required_role == UserRole.CHIEF_RESEARCHER


@pytest.mark.asyncio
async def test_write_file_success(monkeypatch, tmp_path):
    """成功写入文件"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "out.txt"

    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = WriteFileTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"path": str(target), "content": "new content"}, ctx
    )

    assert result.success is True
    assert result.data["mode"] == "overwrite"
    assert target.read_text(encoding="utf-8") == "new content"


@pytest.mark.asyncio
async def test_write_file_append_mode(monkeypatch, tmp_path):
    """append=True 时追加而非覆盖"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "log.txt"
    target.write_text("line1\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = WriteFileTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"path": str(target), "content": "line2\n", "append": True}, ctx
    )

    assert result.success is True
    assert result.data["mode"] == "append"
    assert target.read_text(encoding="utf-8") == "line1\nline2\n"


@pytest.mark.asyncio
async def test_write_file_blocked_path(monkeypatch, tmp_path):
    """路径不在白名单 → fail"""
    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(tmp_path / "workspace")],
    )

    tool = WriteFileTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"path": "/etc/evil.txt", "content": "x"}, ctx
    )

    assert result.success is False
    assert "路径不在允许范围内" in result.error


@pytest.mark.asyncio
async def test_write_file_creates_parent_dirs(monkeypatch, tmp_path):
    """写入时自动创建父目录"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "sub" / "deep" / "file.txt"

    monkeypatch.setattr(
        "app.services.agent.tools.files._ALLOWED_ROOTS",
        [str(workspace)],
    )

    tool = WriteFileTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"path": str(target), "content": "nested"}, ctx
    )

    assert result.success is True
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "nested"
