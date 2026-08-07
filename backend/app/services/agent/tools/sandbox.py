"""沙箱代码执行工具 — 1 个工具

工具列表：
- execute_code   在 Docker 沙箱内执行代码（副作用，需确认）

设计来源：2026-07-18-agent-react-design.md §8（Docker 隔离）
"""
import logging
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


# 危险代码静态黑名单（基础拦截，主要靠 Docker 隔离）
_CODE_BLACKLIST = [
    "os.system",
    "subprocess.",
    "os.popen",
    "os.exec",
    "os.spawn",
    "eval(",
    "exec(",
    "__import__",
    "importlib.import_module",
    "open('/etc",
    "open(\"/etc",
    "shutil.rmtree",
    "os.remove",
    "os.unlink",
]


def _check_code_safety(code: str) -> tuple[bool, str]:
    """代码静态安全检查

    Returns:
        (是否通过, 拦截原因)
    """
    for pattern in _CODE_BLACKLIST:
        if pattern in code:
            return False, f"代码包含禁用模式: {pattern}"
    return True, ""


class ExecuteCodeTool(AgentTool):
    """代码执行 — Docker 沙箱内执行（副作用，需确认）"""

    name = "execute_code"
    description = (
        "在隔离的 Docker 沙箱内执行 Python 代码。"
        "沙箱限制：无网络、只读文件系统、内存上限 512MB、CPU 1 核、超时 30 秒。"
        "适用于数据分析、可视化、数值计算场景。"
        "执行前需用户确认。"
    )
    parameters = [
        ToolParameter("code", "string", "待执行的 Python 代码", required=True),
        ToolParameter("language", "string", "编程语言（默认 python）", required=False, default="python"),
        ToolParameter("stdin", "string", "标准输入", required=False),
    ]
    side_effects = True  # 代码执行有副作用
    required_role = UserRole.CHIEF_RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        code = params["code"]
        language = params.get("language", "python")
        stdin = params.get("stdin")

        if language != "python":
            return ToolResult.fail(
                error=f"暂不支持的语言: {language}",
                data={"supported": ["python"]},
            )

        # 静态黑名单检查
        safe, reason = _check_code_safety(code)
        if not safe:
            return ToolResult.fail(error=f"代码安全检查未通过: {reason}")

        # 沙箱开关
        if not settings.AGENT_SANDBOX_ENABLED:
            return ToolResult.fail(
                error="沙箱功能未启用（设置 AGENT_SANDBOX_ENABLED=true 开启）",
                data={
                    "code_preview": code[:200],
                    "hint": "生产环境请联系管理员开启沙箱",
                },
            )

        try:
            from app.services.agent.sandbox_runner import SandboxRunner

            runner = SandboxRunner()
            result = await runner.run(
                code=code,
                stdin=stdin,
                task_id=ctx.task_id,
                user_id=str(ctx.user.id),
                db=ctx.db,
            )
            return ToolResult.ok(
                data=result,
                display={"type": "code_output", "payload": result},
            )
        except ImportError:
            # Docker SDK 不可用
            return ToolResult.fail(
                error="沙箱运行时未安装（需要 docker 包）",
                data={"code_preview": code[:200]},
            )
        except Exception as e:
            logger.error(f"execute_code 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
