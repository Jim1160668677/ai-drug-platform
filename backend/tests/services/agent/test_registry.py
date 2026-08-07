"""工具注册中心测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.security import UserRole
from app.services.agent.tools.base import AgentTool, ToolParameter, ToolResult
from app.services.agent.tools.registry import ToolRegistry


class DummyTool(AgentTool):
    """测试用工具"""
    name = "dummy_tool"
    description = "测试工具"
    parameters = [
        ToolParameter(name="x", type="string", description="参数 x", required=True),
        ToolParameter(name="y", type="integer", description="参数 y", required=False, default=0),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params, ctx):
        return ToolResult.ok(data={"echo": params})


class SideEffectTool(AgentTool):
    """副作用测试工具"""
    name = "side_effect_tool"
    description = "有副作用的工具"
    parameters = []
    side_effects = True
    required_role = UserRole.CHIEF_RESEARCHER

    async def execute(self, params, ctx):
        return ToolResult.ok(data="executed")


class TestToolRegistryRegistration:
    def test_register_single_tool(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        assert registry.get_tool("dummy_tool") is not None

    def test_register_overwrite_warning(self, caplog):
        """重复注册覆盖"""
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(DummyTool())
        assert registry.get_tool("dummy_tool") is not None

    def test_register_empty_name_raises(self):
        class NoName(AgentTool):
            name = ""
            description = "x"
            parameters = []
            async def execute(self, params, ctx):
                return ToolResult.ok()

        registry = ToolRegistry()
        with pytest.raises(ValueError):
            registry.register(NoName())

    def test_register_all_19_tools(self):
        """register_all 注册全部工具"""
        registry = ToolRegistry()
        registry.register_all()
        all_tools = registry.list_all()
        assert len(all_tools) == 24
        tool_names = {t.name for t in all_tools}
        assert "discover_targets" in tool_names
        assert "design_molecules" in tool_names
        assert "execute_code" in tool_names
        assert "search_literature" in tool_names
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        # 新增工具
        assert "search_ncbi" in tool_names
        assert "web_search" in tool_names
        assert "fetch_web_page" in tool_names
        assert "generate_hypothesis" in tool_names
        assert "query_coscientist_run" in tool_names
        assert "scientific_debate" in tool_names
        assert "experiment_design" in tool_names
        assert "search_academic" in tool_names


class TestListForUser:
    def test_founder_sees_all_tools(self, test_user):
        registry = ToolRegistry()
        registry.register_all()
        tools = registry.list_for_user(test_user)
        assert len(tools) == 24

    def test_doctor_sees_subset(self, doctor_user):
        registry = ToolRegistry()
        registry.register_all()
        tools = registry.list_for_user(doctor_user)
        tool_names = {t["name"] for t in tools}
        # DOCTOR 可见的工具
        assert "query_data" in tool_names
        assert "build_evidence_chain" in tool_names
        assert "assess_druglikeness" in tool_names
        assert "search_literature" in tool_names
        assert "read_file" in tool_names
        # DOCTOR 不可见的工具
        assert "discover_targets" not in tool_names
        assert "design_molecules" not in tool_names
        assert "write_file" not in tool_names
        assert "execute_code" not in tool_names

    def test_tool_info_has_required_fields(self, test_user):
        registry = ToolRegistry()
        registry.register_all()
        tools = registry.list_for_user(test_user)
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "parameters" in t
            assert "side_effects" in t
            assert "required_role" in t


class TestValidateParams:
    def test_missing_required_param(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            registry.validate_params("dummy_tool", {})

    def test_wrong_type(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            registry.validate_params("dummy_tool", {"x": "ok", "y": "not_int"})

    def test_valid_params(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        # 不抛异常即通过
        registry.validate_params("dummy_tool", {"x": "hello", "y": 42})

    def test_unknown_tool(self):
        registry = ToolRegistry()
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            registry.validate_params("nonexistent", {})


class TestExecuteTool:
    @pytest.fixture
    def bypass_permission(self, monkeypatch):
        """绕过工具权限校验。

        TestExecuteTool 用 DummyTool/SideEffectTool 测试 execute_tool 的非权限流程
        （成功/参数校验/副作用确认），这些测试工具不在 TOOL_PERMISSIONS 矩阵中，
        has_tool_permission 默认返回 False 会在权限阶段直接拒绝。
        需要验证权限拒绝的测试（test_execute_permission_denied）不引用此 fixture。
        """
        monkeypatch.setattr(
            "app.services.agent.tools.registry.has_tool_permission",
            lambda tool_name, role: True,
        )

    @pytest.mark.asyncio
    async def test_execute_success(self, test_user, bypass_permission):
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = await registry.execute_tool(
            tool_name="dummy_tool",
            params={"x": "hello"},
            user=test_user,
            task_id="t1",
            session_id="s1",
        )
        assert result.success is True
        assert result.data == {"echo": {"x": "hello"}}

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, test_user):
        registry = ToolRegistry()
        result = await registry.execute_tool(
            tool_name="nonexistent",
            params={},
            user=test_user,
            task_id="t1",
            session_id="s1",
        )
        assert result.success is False
        assert "未知工具" in result.error

    @pytest.mark.asyncio
    async def test_execute_permission_denied(self, doctor_user):
        """DOCTOR 不能使用 discover_targets"""
        registry = ToolRegistry()
        registry.register_all()
        result = await registry.execute_tool(
            tool_name="discover_targets",
            params={"project_id": "p1"},
            user=doctor_user,
            task_id="t1",
            session_id="s1",
        )
        assert result.success is False
        assert "无权" in result.error

    @pytest.mark.asyncio
    async def test_execute_validation_error(self, test_user, bypass_permission):
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = await registry.execute_tool(
            tool_name="dummy_tool",
            params={},  # 缺少必填参数 x
            user=test_user,
            task_id="t1",
            session_id="s1",
        )
        assert result.success is False
        assert "缺少必填参数" in result.error

    @pytest.mark.asyncio
    async def test_execute_side_effects_approved(self, test_user, bypass_permission):
        """副作用工具通过确认后执行"""
        registry = ToolRegistry()
        registry.register(SideEffectTool())
        confirm_cb = AsyncMock(return_value=True)
        result = await registry.execute_tool(
            tool_name="side_effect_tool",
            params={},
            user=test_user,
            task_id="t1",
            session_id="s1",
            confirm_callback=confirm_cb,
        )
        assert result.success is True
        confirm_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_side_effects_rejected(self, test_user, bypass_permission):
        """副作用工具被拒绝时不执行"""
        registry = ToolRegistry()
        registry.register(SideEffectTool())
        confirm_cb = AsyncMock(return_value=False)
        result = await registry.execute_tool(
            tool_name="side_effect_tool",
            params={},
            user=test_user,
            task_id="t1",
            session_id="s1",
            confirm_callback=confirm_cb,
        )
        assert result.success is False
        assert "拒绝" in result.error


def test_get_tool_registry_singleton():
    """get_tool_registry 单例"""
    from app.services.agent.tools.registry import get_tool_registry, _registry
    import app.services.agent.tools.registry as reg_module

    # 重置单例（测试隔离）
    reg_module._registry = None
    r1 = get_tool_registry()
    r2 = get_tool_registry()
    assert r1 is r2
    assert len(r1.list_all()) == 24
