"""职能×机构矩阵 — 定义各职能角色的合法机构类型、默认工作台与默认权限

回应评委意见①：靶点发现/分子设计/用药指导/实验验证面向不同机构，
本矩阵明确"谁在什么机构做什么"，用于用户分配校验与工作台路由。
"""


# 职能×机构合法性矩阵：每个职能在哪些机构类型下合法
FUNCTION_ORG_MATRIX = {
    "target_discovery": ["research_institute", "pharma", "hospital"],
    "molecule_design": ["pharma", "cro", "research_institute"],
    "clinical_guidance": ["hospital"],
    "experiment_validation": ["research_institute", "cro", "cdmo", "testing_lab"],
    "project_pi": ["research_institute", "pharma", "hospital"],
    "regulatory": ["pharma", "cro"],
    "data_engineering": ["research_institute", "pharma", "hospital"],
}

# 职能 → 默认工作台路由
FUNCTION_WORKSPACE = {
    "target_discovery": "/workbench/targets",
    "molecule_design": "/workbench/molecules",
    "clinical_guidance": "/workbench/treatments",
    "experiment_validation": "/workbench/experiments",
    "project_pi": "/workbench/projects",
    "regulatory": "/workbench/projects",
    "data_engineering": "/workbench/dashboard",
}

# 职能 → 默认权限（叠加在 UserRole 职级之上，不替代）
FUNCTION_DEFAULT_PERMISSIONS = {
    "target_discovery": ["target:read", "analysis:run:standard"],
    "molecule_design": ["molecule:write", "analysis:run:standard"],
    "clinical_guidance": ["clinical:advise", "target:read"],
    "experiment_validation": ["experiment:write", "data:read:assigned"],
    "project_pi": ["data:read", "analysis:read", "decision:advise"],
    "regulatory": ["report:read", "audit:read"],
    "data_engineering": ["system:logs", "quality:read"],
}


def is_valid_function_org_pair(function_role: str, org_type: str) -> bool:
    """检查职能与机构类型是否为合法组合"""
    valid_orgs = FUNCTION_ORG_MATRIX.get(function_role)
    if valid_orgs is None:
        return False
    return org_type in valid_orgs


def get_default_permissions(function_role: str) -> list:
    """获取职能的默认权限列表"""
    return FUNCTION_DEFAULT_PERMISSIONS.get(function_role, [])


def get_workspace_entry(function_role: str) -> str:
    """获取职能的默认工作台路由"""
    return FUNCTION_WORKSPACE.get(function_role, "/workbench")


def list_function_roles() -> list:
    """列出所有职能角色"""
    return list(FUNCTION_ORG_MATRIX.keys())


def list_org_types() -> list:
    """列出所有机构类型（去重）"""
    seen = set()
    for orgs in FUNCTION_ORG_MATRIX.values():
        seen.update(orgs)
    return sorted(seen)
