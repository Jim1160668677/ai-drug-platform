"""权限矩阵测试 — 23 工具 × 5 角色"""
import pytest

from app.core.security import UserRole
from app.services.agent.tools.permissions import (
    TOOL_PERMISSIONS,
    has_tool_permission,
)


ALL_TOOLS = [
    "analyze_dataset",
    "query_data",
    "compute_statistics",
    "visualize_data",
    "discover_targets",
    "build_evidence_chain",
    "predict_synergy",
    "design_molecules",
    "design_multi_target",
    "assess_druglikeness",
    "dock_molecule",
    "search_literature",
    "query_knowledge_base",
    "search_ncbi",
    "web_search",
    "fetch_web_page",
    "read_file",
    "write_file",
    "execute_code",
    "experiment_design",
    "generate_hypothesis",
    "query_coscientist_run",
    "scientific_debate",
    "search_academic",
]


def test_all_19_tools_registered():
    """权限矩阵覆盖全部 24 工具"""
    assert len(TOOL_PERMISSIONS) == 24
    for tool in ALL_TOOLS:
        assert tool in TOOL_PERMISSIONS, f"工具 {tool} 未注册"


def test_all_5_roles_covered():
    """每个工具的权限矩阵覆盖全部 5 角色"""
    for tool, perms in TOOL_PERMISSIONS.items():
        for role in UserRole:
            assert role in perms, f"工具 {tool} 缺少角色 {role} 的权限定义"


class TestFOUNDER:
    """FOUNDER 角色应拥有全部工具权限"""

    def test_founder_all_tools(self):
        for tool in ALL_TOOLS:
            assert has_tool_permission(tool, UserRole.FOUNDER), f"FOUNDER 应可使用 {tool}"


class TestCHIEF_RESEARCHER:
    def test_chief_all_tools(self):
        """CHIEF_RESEARCHER 与 FOUNDER 工具权限一致"""
        for tool in ALL_TOOLS:
            assert has_tool_permission(tool, UserRole.CHIEF_RESEARCHER), (
                f"CHIEF_RESEARCHER 应可使用 {tool}"
            )


class TestRESEARCHER:
    def test_researcher_can_use_analysis_tools(self):
        assert has_tool_permission("analyze_dataset", UserRole.RESEARCHER)
        assert has_tool_permission("query_data", UserRole.RESEARCHER)
        assert has_tool_permission("compute_statistics", UserRole.RESEARCHER)
        assert has_tool_permission("visualize_data", UserRole.RESEARCHER)

    def test_researcher_can_use_target_tools(self):
        assert has_tool_permission("discover_targets", UserRole.RESEARCHER)
        assert has_tool_permission("build_evidence_chain", UserRole.RESEARCHER)
        assert has_tool_permission("predict_synergy", UserRole.RESEARCHER)

    def test_researcher_can_use_molecule_tools(self):
        assert has_tool_permission("design_molecules", UserRole.RESEARCHER)
        assert has_tool_permission("design_multi_target", UserRole.RESEARCHER)
        assert has_tool_permission("assess_druglikeness", UserRole.RESEARCHER)
        assert has_tool_permission("dock_molecule", UserRole.RESEARCHER)

    def test_researcher_cannot_use_high_risk_tools(self):
        """RESEARCHER 不能使用 write_file 和 execute_code"""
        assert not has_tool_permission("write_file", UserRole.RESEARCHER)
        assert not has_tool_permission("execute_code", UserRole.RESEARCHER)


class TestDOCTOR:
    def test_doctor_can_query_data(self):
        """DOCTOR 可查询临床数据"""
        assert has_tool_permission("query_data", UserRole.DOCTOR)
        assert has_tool_permission("compute_statistics", UserRole.DOCTOR)
        assert has_tool_permission("visualize_data", UserRole.DOCTOR)

    def test_doctor_can_view_evidence(self):
        """DOCTOR 可查看证据链与类药性"""
        assert has_tool_permission("build_evidence_chain", UserRole.DOCTOR)
        assert has_tool_permission("assess_druglikeness", UserRole.DOCTOR)

    def test_doctor_can_search_literature(self):
        assert has_tool_permission("search_literature", UserRole.DOCTOR)
        assert has_tool_permission("query_knowledge_base", UserRole.DOCTOR)
        assert has_tool_permission("read_file", UserRole.DOCTOR)

    def test_doctor_cannot_discover_or_design(self):
        """DOCTOR 不能使用靶点发现 / 分子设计工具"""
        assert not has_tool_permission("discover_targets", UserRole.DOCTOR)
        assert not has_tool_permission("predict_synergy", UserRole.DOCTOR)
        assert not has_tool_permission("design_molecules", UserRole.DOCTOR)
        assert not has_tool_permission("design_multi_target", UserRole.DOCTOR)
        assert not has_tool_permission("dock_molecule", UserRole.DOCTOR)

    def test_doctor_cannot_use_high_risk_tools(self):
        assert not has_tool_permission("analyze_dataset", UserRole.DOCTOR)
        assert not has_tool_permission("write_file", UserRole.DOCTOR)
        assert not has_tool_permission("execute_code", UserRole.DOCTOR)


class TestDATA_ENGINEER:
    def test_engineer_can_use_data_tools(self):
        """DATA_ENGINEER 可用数据分析 + 文件 + 沙箱工具"""
        assert has_tool_permission("analyze_dataset", UserRole.DATA_ENGINEER)
        assert has_tool_permission("query_data", UserRole.DATA_ENGINEER)
        assert has_tool_permission("compute_statistics", UserRole.DATA_ENGINEER)
        assert has_tool_permission("visualize_data", UserRole.DATA_ENGINEER)

    def test_engineer_can_use_files_and_sandbox(self):
        assert has_tool_permission("read_file", UserRole.DATA_ENGINEER)
        assert has_tool_permission("write_file", UserRole.DATA_ENGINEER)
        assert has_tool_permission("execute_code", UserRole.DATA_ENGINEER)

    def test_engineer_cannot_use_research_tools(self):
        """DATA_ENGINEER 不能用靶点 / 分子研究工具"""
        assert not has_tool_permission("discover_targets", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("build_evidence_chain", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("predict_synergy", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("design_molecules", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("design_multi_target", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("assess_druglikeness", UserRole.DATA_ENGINEER)
        assert not has_tool_permission("dock_molecule", UserRole.DATA_ENGINEER)


def test_unknown_tool_returns_false():
    """未注册的工具默认拒绝"""
    assert has_tool_permission("nonexistent_tool", UserRole.FOUNDER) is False
