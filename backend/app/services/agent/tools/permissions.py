"""Agent 工具权限矩阵 — 22 工具 × 5 角色

设计来源：2026-07-18-agent-functional-design.md §7

角色层级（高 → 低）：
- FOUNDER            创始人（全部权限）
- CHIEF_RESEARCHER   首席研究员（全部工具，无系统配置）
- RESEARCHER         研究员（项目内数据 + 分析工具）
- DOCTOR             医生（临床数据只读）
- DATA_ENGINEER      数据工程师（系统类工具）

工具集（22 个）：
- data_analysis: analyze_dataset, query_data, compute_statistics, visualize_data
- targets:      discover_targets, build_evidence_chain, predict_synergy
- molecules:    design_molecules, design_multi_target, assess_druglikeness, dock_molecule
- knowledge:    search_literature, query_knowledge_base, search_ncbi, web_search, fetch_web_page
- files:        read_file, write_file
- sandbox:      execute_code
- coscientist:  generate_hypothesis, query_coscientist_run, scientific_debate  (Phase B6 新增)
"""
from typing import Dict

from app.core.security import UserRole


# 权限矩阵：tool_name -> {role: bool}
# True 表示该角色可使用该工具；按角色层级向下继承（高角色默认拥有低角色权限）
TOOL_PERMISSIONS: Dict[str, Dict[UserRole, bool]] = {
    # ===== 数据分析工具组 =====
    "analyze_dataset": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: True,
    },
    "query_data": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,  # 医生可查询临床数据
        UserRole.DATA_ENGINEER: True,
    },
    "compute_statistics": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "visualize_data": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },

    # ===== 靶点工具组 =====
    "discover_targets": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },
    "build_evidence_chain": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,  # 医生可查看证据链
        UserRole.DATA_ENGINEER: False,
    },
    "predict_synergy": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },

    # ===== 分子工具组 =====
    "design_molecules": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },
    "design_multi_target": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },
    "assess_druglikeness": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,  # 医生可查看类药性
        UserRole.DATA_ENGINEER: False,
    },
    "dock_molecule": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },

    # ===== 知识工具组 =====
    "search_literature": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "query_knowledge_base": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "search_ncbi": {
        # NCBI 检索权限同 search_literature
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "web_search": {
        # 网络搜索权限同 search_literature
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "fetch_web_page": {
        # 网页抓取权限同 search_literature
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "search_academic": {
        # 学术检索权限同 search_literature
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },

    # ===== 文件工具组 =====
    "read_file": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "write_file": {
        # 写文件有副作用，仅高级角色
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: False,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: True,
    },

    # ===== 沙箱工具组 =====
    "execute_code": {
        # 代码执行风险高，仅创始人 + 首席 + 数据工程师
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: False,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: True,
    },

    # ===== 实验设计工具组（建议七新增）=====
    "experiment_design": {
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },

    # ===== Co-Scientist 工具组（Phase B6 新增）=====
    "generate_hypothesis": {
        # 假设生成有副作用（消耗 LLM tokens + 创建运行记录）
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: False,
        UserRole.DATA_ENGINEER: False,
    },
    "query_coscientist_run": {
        # 运行查询只读，同 search_literature 权限
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
    "scientific_debate": {
        # 辩论查询只读，同 query_coscientist_run 权限
        UserRole.FOUNDER: True,
        UserRole.CHIEF_RESEARCHER: True,
        UserRole.RESEARCHER: True,
        UserRole.DOCTOR: True,
        UserRole.DATA_ENGINEER: True,
    },
}


def has_tool_permission(tool_name: str, role: UserRole) -> bool:
    """检查角色是否可使用某工具

    Args:
        tool_name: 工具名
        role: 用户角色
    Returns:
        是否有权限
    """
    perms = TOOL_PERMISSIONS.get(tool_name)
    if perms is None:
        return False  # 未注册工具默认拒绝
    return perms.get(role, False)
