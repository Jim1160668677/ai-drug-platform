"""职能×机构矩阵单元测试"""
from app.services.org.function_matrix import (
    FUNCTION_ORG_MATRIX,
    FUNCTION_WORKSPACE,
    FUNCTION_DEFAULT_PERMISSIONS,
    is_valid_function_org_pair,
    get_default_permissions,
    get_workspace_entry,
    list_function_roles,
    list_org_types,
)


class TestFunctionOrgMatrix:
    """职能×机构合法性矩阵"""

    def test_target_discovery_valid_in_research_institute(self):
        assert is_valid_function_org_pair("target_discovery", "research_institute")

    def test_target_discovery_valid_in_pharma(self):
        assert is_valid_function_org_pair("target_discovery", "pharma")

    def test_clinical_guidance_only_in_hospital(self):
        """用药指导职能仅在医院合法"""
        assert is_valid_function_org_pair("clinical_guidance", "hospital")
        assert not is_valid_function_org_pair("clinical_guidance", "pharma")
        assert not is_valid_function_org_pair("clinical_guidance", "cro")

    def test_experiment_validation_in_cro_cdmo(self):
        """实验验证职能在 CRO/CDMO/检测机构合法"""
        assert is_valid_function_org_pair("experiment_validation", "cro")
        assert is_valid_function_org_pair("experiment_validation", "cdmo")
        assert is_valid_function_org_pair("experiment_validation", "testing_lab")

    def test_molecule_design_in_pharma_and_cro(self):
        assert is_valid_function_org_pair("molecule_design", "pharma")
        assert is_valid_function_org_pair("molecule_design", "cro")

    def test_invalid_function_returns_false(self):
        assert not is_valid_function_org_pair("nonexistent_role", "pharma")

    def test_invalid_org_returns_false(self):
        assert not is_valid_function_org_pair("target_discovery", "nonexistent_org")

    def test_all_function_roles_have_workspace(self):
        """每个职能角色都有默认工作台"""
        for role in list_function_roles():
            assert role in FUNCTION_WORKSPACE, f"{role} 缺少默认工作台"
            assert get_workspace_entry(role).startswith("/workbench")

    def test_all_function_roles_have_default_permissions(self):
        """每个职能角色都有默认权限列表"""
        for role in list_function_roles():
            perms = get_default_permissions(role)
            assert isinstance(perms, list)
            assert len(perms) > 0, f"{role} 缺少默认权限"

    def test_list_org_types_covers_all_matrix_values(self):
        """list_org_types 覆盖矩阵中所有机构类型"""
        org_types = set(list_org_types())
        for orgs in FUNCTION_ORG_MATRIX.values():
            for org in orgs:
                assert org in org_types

    def test_unknown_function_gets_default_workspace(self):
        """未知职能返回默认工作台"""
        assert get_workspace_entry("unknown_role") == "/workbench"

    def test_unknown_function_gets_empty_permissions(self):
        """未知职能返回空权限列表"""
        assert get_default_permissions("unknown_role") == []

    def test_seven_function_roles_defined(self):
        """共 7 个职能角色"""
        roles = list_function_roles()
        assert len(roles) == 7
        assert "target_discovery" in roles
        assert "molecule_design" in roles
        assert "clinical_guidance" in roles
        assert "experiment_validation" in roles
        assert "project_pi" in roles
        assert "regulatory" in roles
        assert "data_engineering" in roles

    def test_six_org_types_defined(self):
        """共 6 个机构类型"""
        org_types = list_org_types()
        assert len(org_types) == 6
        assert "research_institute" in org_types
        assert "pharma" in org_types
        assert "hospital" in org_types
        assert "cro" in org_types
        assert "cdmo" in org_types
        assert "testing_lab" in org_types
