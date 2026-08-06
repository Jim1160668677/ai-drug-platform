"""Agent 工具注册中心

设计来源：2026-07-18-agent-functional-design.md §1.1 / §7

职责：
- 启动时注册所有 22 个工具（含 Phase B6 新增 3 个 Co-Scientist 工具）
- 按用户角色过滤可用工具（list_for_user）
- 参数校验（JSON Schema + Pydantic）
- 工具执行（含权限校验、副作用确认、异常捕获）
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.exceptions import ForbiddenError, ValidationError
from app.core.security import UserRole
from app.models.user import User
from app.services.agent.tools.base import AgentTool, ToolContext, ToolResult
from app.services.agent.tools.permissions import has_tool_permission

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册中心

    Usage:
        registry = ToolRegistry()
        registry.register_all()  # 启动时注册所有工具

        # 列出用户可用工具
        tools = registry.list_for_user(user)

        # 执行工具
        result = await registry.execute_tool(
            tool_name="discover_targets",
            params={"project_id": "..."},
            user=user,
            task_id="...",
            session_id="...",
            project_id="...",
            progress=progress_manager,
        )
    """

    def __init__(self):
        self._tools: Dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """注册单个工具"""
        if not tool.name:
            raise ValueError(f"工具 name 不能为空: {tool}")
        if tool.name in self._tools:
            logger.warning(f"工具 {tool.name} 已注册，覆盖")
        self._tools[tool.name] = tool
        logger.debug(f"注册工具: {tool.name}")

    def register_all(self) -> None:
        """注册全部 19 个工具（按工具组导入）"""
        # 延迟导入避免循环依赖
        from app.services.agent.tools.data_analysis import (
            AnalyzeDatasetTool,
            QueryDataTool,
            ComputeStatisticsTool,
            VisualizeDataTool,
        )
        from app.services.agent.tools.targets import (
            DiscoverTargetsTool,
            BuildEvidenceChainTool,
            PredictSynergyTool,
        )
        from app.services.agent.tools.molecules import (
            DesignMoleculesTool,
            DesignMultiTargetTool,
            AssessDruglikenessTool,
            DockMoleculeTool,
        )
        from app.services.agent.tools.knowledge import (
            SearchLiteratureTool,
            QueryKnowledgeBaseTool,
        )
        from app.services.agent.tools.ncbi import SearchNcbiTool
        from app.services.agent.tools.academic_search import SearchAcademicTool
        from app.services.agent.tools.web_search import (
            WebSearchTool,
            FetchWebPageTool,
        )
        from app.services.agent.tools.files import ReadFileTool, WriteFileTool
        from app.services.agent.tools.sandbox import ExecuteCodeTool
        from app.services.agent.tools.coscientist import (
            GenerateHypothesisTool,
            QueryRunTool,
            ScientificDebateTool,
        )
        from app.services.agent.tools.experiment_design import (
            ExperimentDesignTool,
        )

        tool_classes = [
            # 数据分析
            AnalyzeDatasetTool, QueryDataTool, ComputeStatisticsTool, VisualizeDataTool,
            # 靶点
            DiscoverTargetsTool, BuildEvidenceChainTool, PredictSynergyTool,
            # 分子
            DesignMoleculesTool, DesignMultiTargetTool, AssessDruglikenessTool, DockMoleculeTool,
            # 知识（本地 RAG + NCBI + 网络搜索）
            SearchLiteratureTool, QueryKnowledgeBaseTool,
            SearchNcbiTool,
            SearchAcademicTool,
            WebSearchTool, FetchWebPageTool,
            # 文件
            ReadFileTool, WriteFileTool,
            # 沙箱
            ExecuteCodeTool,
            # Co-Scientist（Phase B6 新增）
            GenerateHypothesisTool, QueryRunTool, ScientificDebateTool,
            # 实验设计（建议七新增）
            ExperimentDesignTool,
        ]
        for cls in tool_classes:
            try:
                self.register(cls())
            except Exception as e:
                logger.error(f"注册工具 {cls.__name__} 失败: {e}", exc_info=True)

        logger.info(f"工具注册完成，共 {len(self._tools)} 个")

    def get_tool(self, name: str) -> Optional[AgentTool]:
        """获取工具实例"""
        return self._tools.get(name)

    def list_all(self) -> List[AgentTool]:
        """列出全部工具"""
        return list(self._tools.values())

    def list_for_user(self, user: User) -> List[Dict[str, Any]]:
        """列出用户可用工具（按角色过滤），返回工具信息字典"""
        role = user.role if isinstance(user.role, UserRole) else UserRole(user.role)
        result = []
        for tool in self._tools.values():
            if has_tool_permission(tool.name, role):
                result.append(tool.to_info())
        return result

    def validate_params(self, tool_name: str, params: Dict[str, Any]) -> None:
        """参数校验（基础校验：必填字段 + 类型检查）

        复杂校验由工具自身在 execute 内完成。
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            raise ValidationError(f"未知工具: {tool_name}")

        for p in tool.parameters:
            if p.required and p.name not in params:
                raise ValidationError(
                    f"缺少必填参数: {p.name}",
                    details={"parameter": p.name, "tool": tool_name},
                )
            if p.name in params and params[p.name] is not None:
                # 简单类型检查
                value = params[p.name]
                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                }
                expected = type_map.get(p.type)
                if expected and not isinstance(value, expected):
                    raise ValidationError(
                        f"参数 {p.name} 类型错误，期望 {p.type}",
                        details={
                            "parameter": p.name,
                            "expected": p.type,
                            "actual": type(value).__name__,
                        },
                    )

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user: User,
        task_id: str,
        session_id: str,
        project_id: Optional[str] = None,
        db: Optional[Any] = None,
        progress: Optional[Any] = None,
        confirm_callback: Optional[Any] = None,
    ) -> ToolResult:
        """执行工具

        流程：
        1. 工具存在性校验
        2. 权限校验（RBAC）
        3. 参数校验
        4. 副作用确认（如需）
        5. 执行（带异常捕获）
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            return ToolResult.fail(error=f"未知工具: {tool_name}")

        # 权限校验
        role = user.role if isinstance(user.role, UserRole) else UserRole(user.role)
        if not has_tool_permission(tool_name, role):
            logger.warning(
                f"工具权限拒绝: user={user.id} role={role} tool={tool_name}"
            )
            return ToolResult.fail(error=f"无权使用工具: {tool_name}")

        # 参数校验
        try:
            self.validate_params(tool_name, params)
        except ValidationError as e:
            return ToolResult.fail(error=str(e))

        # 副作用确认
        if tool.side_effects and confirm_callback is not None:
            try:
                approved = await confirm_callback({
                    "tool": tool_name,
                    "args": params,
                    "description": tool.description,
                    "risk_level": "high" if tool_name == "execute_code" else "medium",
                })
                if not approved:
                    return ToolResult.fail(error="用户拒绝执行该操作")
            except Exception as e:
                logger.warning(f"副作用确认回调异常: {e}")
                return ToolResult.fail(error=f"确认流程异常: {e}")

        # 执行
        ctx = ToolContext(
            db=db,
            user=user,
            task_id=task_id,
            session_id=session_id,
            project_id=project_id,
            confirm_callback=confirm_callback,
            progress=progress,
        )

        return await tool.execute_safely(params, ctx)


# 模块级单例
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册中心单例"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.register_all()
    return _registry
