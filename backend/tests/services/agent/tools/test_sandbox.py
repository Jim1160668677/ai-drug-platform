"""sandbox 工具测试 — execute_code + 静态黑名单"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.security import UserRole
from app.services.agent.tools.base import ToolContext
from app.services.agent.tools.sandbox import (
    ExecuteCodeTool,
    _check_code_safety,
    _CODE_BLACKLIST,
)


def _make_ctx():
    return ToolContext(
        db=MagicMock(),
        user=MagicMock(),
        task_id="task-sb",
        session_id="session-sb",
    )


# ========== _check_code_safety 静态黑名单 ==========


def test_check_code_safety_clean():
    """纯净代码通过"""
    safe, reason = _check_code_safety("print(1+1)\nresult = [x*2 for x in range(10)]")
    assert safe is True
    assert reason == ""


@pytest.mark.parametrize("pattern,code", [
    ("os.system", "import os\nos.system('ls')"),
    ("subprocess.", "import subprocess\nsubprocess.run(['ls'])"),
    ("os.popen", "os.popen('whoami')"),
    ("os.exec", "os.execv('/bin/sh', ['sh'])"),
    ("os.spawn", "os.spawnl(os.P_NOWAIT, 'x')"),
    ("eval(", "eval('1+1')"),
    ("exec(", "exec('x=1')"),
    ("__import__", "__import__('os')"),
    ("importlib.import_module", "import importlib\nimportlib.import_module('os')"),
    ("open('/etc", "open('/etc/passwd')"),
    ('open("/etc', 'open("/etc/passwd")'),
    ("shutil.rmtree", "import shutil\nshutil.rmtree('/x')"),
    ("os.remove", "os.remove('/x')"),
    ("os.unlink", "os.unlink('/x')"),
])
def test_check_code_safety_blacklist_patterns(pattern, code):
    """13 个黑名单模式均被拦截"""
    safe, reason = _check_code_safety(code)
    assert safe is False
    assert pattern in reason


def test_code_blacklist_has_13_patterns():
    """断言黑名单规模"""
    assert len(_CODE_BLACKLIST) >= 13


# ========== ExecuteCodeTool 元数据 ==========


def test_execute_code_metadata():
    tool = ExecuteCodeTool()
    assert tool.name == "execute_code"
    assert tool.side_effects is True
    assert tool.required_role == UserRole.CHIEF_RESEARCHER


def test_execute_code_parameters():
    """参数定义：code 必填，language/stdin 可选"""
    tool = ExecuteCodeTool()
    schema = tool.to_schema()
    assert "code" in schema["required"]
    assert "language" not in schema["required"]
    assert "stdin" not in schema["required"]
    assert schema["properties"]["language"]["default"] == "python"


# ========== execute 分支测试 ==========


@pytest.mark.asyncio
async def test_execute_code_unsupported_language():
    """不支持的语言 → fail"""
    tool = ExecuteCodeTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"code": "puts 1", "language": "ruby"}, ctx
    )
    assert result.success is False
    assert "ruby" in result.error
    assert result.data["supported"] == ["python"]


@pytest.mark.asyncio
async def test_execute_code_blacklisted_pattern():
    """代码含黑名单 → fail（在沙箱开关前拦截）"""
    tool = ExecuteCodeTool()
    ctx = _make_ctx()
    result = await tool.execute(
        {"code": "import os\nos.system('ls')"}, ctx
    )
    assert result.success is False
    assert "代码安全检查未通过" in result.error


@pytest.mark.asyncio
async def test_execute_code_sandbox_disabled(monkeypatch):
    """默认沙箱关闭 → fail + hint"""
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", False)

    tool = ExecuteCodeTool()
    ctx = _make_ctx()
    result = await tool.execute({"code": "print(1+1)"}, ctx)

    assert result.success is False
    assert "沙箱功能未启用" in result.error
    assert result.data["hint"] is not None
    assert result.data["code_preview"] == "print(1+1)"


@pytest.mark.asyncio
async def test_execute_code_docker_sdk_missing(monkeypatch):
    """启用沙箱 + ImportError → fail"""
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    # 模拟 sandbox_runner 模块导入失败
    import sys
    original = sys.modules.get("app.services.agent.sandbox_runner")
    sys.modules["app.services.agent.sandbox_runner"] = None  # 触发 ImportError

    try:
        tool = ExecuteCodeTool()
        ctx = _make_ctx()
        result = await tool.execute({"code": "print(1+1)"}, ctx)
        assert result.success is False
        assert "沙箱运行时未安装" in result.error
    finally:
        # 恢复
        if original is not None:
            sys.modules["app.services.agent.sandbox_runner"] = original
        else:
            sys.modules.pop("app.services.agent.sandbox_runner", None)


@pytest.mark.asyncio
async def test_execute_code_success_via_mock_runner(monkeypatch):
    """启用沙箱 + mock SandboxRunner → ok"""
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner_instance = MagicMock()
    mock_runner_instance.run = AsyncMock(
        return_value={"stdout": "2\n", "exit_code": 0}
    )

    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner_instance,
    ):
        tool = ExecuteCodeTool()
        ctx = _make_ctx()
        result = await tool.execute({"code": "print(1+1)"}, ctx)

    assert result.success is True
    assert result.data["stdout"] == "2\n"
    assert result.display["type"] == "code_output"


@pytest.mark.asyncio
async def test_execute_code_runner_raises(monkeypatch):
    """沙箱运行时抛异常 → fail"""
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner_instance = MagicMock()
    mock_runner_instance.run = AsyncMock(side_effect=RuntimeError("docker daemon down"))

    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner_instance,
    ):
        tool = ExecuteCodeTool()
        ctx = _make_ctx()
        result = await tool.execute({"code": "print(1+1)"}, ctx)

    assert result.success is False
    assert "docker daemon down" in result.error


@pytest.mark.asyncio
async def test_execute_code_passes_stdin(monkeypatch):
    """stdin 参数透传给 runner"""
    monkeypatch.setattr(settings, "AGENT_SANDBOX_ENABLED", True)

    mock_runner_instance = MagicMock()
    mock_runner_instance.run = AsyncMock(return_value={"stdout": "ok"})

    with patch(
        "app.services.agent.sandbox_runner.SandboxRunner",
        return_value=mock_runner_instance,
    ):
        tool = ExecuteCodeTool()
        ctx = _make_ctx()
        await tool.execute(
            {"code": "x=input()", "stdin": "hello"}, ctx
        )

    # 验证 stdin 被透传
    assert mock_runner_instance.run.call_args.kwargs["stdin"] == "hello"
