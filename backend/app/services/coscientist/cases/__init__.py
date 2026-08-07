"""Co-Scientist 案例注册表

提供案例适配器的工厂方法，支持按 case_type 获取适配器实例。
三个验证案例（AML/肝纤维化/AMR）已按用户要求永久删除。
保留基础设施以支持自定义案例和未来扩展。

历史兼容：数据库中已有的 case_type='aml'/'liver_fibrosis'/'amr' 记录仍可正常查询，
get_case_adapter 对已删除的类型返回 None（调用方已处理此情况）。
"""
from typing import Dict, List, Optional

from .base import BaseCaseAdapter

# 案例注册表 — case_type -> adapter class
# 已清空：三个验证案例（AML/肝纤维化/AMR）已删除
_CASE_REGISTRY: Dict[str, type] = {}


def get_case_adapter(case_type: str) -> Optional[BaseCaseAdapter]:
    """获取案例适配器实例

    Args:
        case_type: 案例类型

    Returns:
        BaseCaseAdapter 实例，未知/已删除类型返回 None
    """
    cls = _CASE_REGISTRY.get(case_type)
    if cls is None:
        return None
    return cls()


def get_all_cases() -> List[BaseCaseAdapter]:
    """获取所有已注册的案例适配器实例列表"""
    return [cls() for cls in _CASE_REGISTRY.values()]


def get_all_case_info() -> List[Dict]:
    """获取所有案例的信息（CaseInfo 格式）"""
    return [adapter.get_case_info() for adapter in get_all_cases()]


def list_case_types() -> List[str]:
    """获取所有可用的案例类型"""
    return list(_CASE_REGISTRY.keys())


__all__ = [
    "BaseCaseAdapter",
    "get_case_adapter",
    "get_all_cases",
    "get_all_case_info",
    "list_case_types",
]