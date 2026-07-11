"""水平越权校验（Row-Level Security）— 按角色过滤数据可见范围

设计依据：app/core/security.py 的 ROLE_PERMISSIONS 矩阵
- FOUNDER (admin:all / data:read)：全组织可见
- CHIEF_RESEARCHER (data:read / analysis:read)：全组织可见（研究领导层）
- RESEARCHER (data:read:assigned)：仅可见自己拥有的项目及其关联资源
- DOCTOR (data:read:clinical)：仅可见自己拥有的项目（临床上下文）
- DATA_ENGINEER (system:logs / quality:read)：仅可见自己拥有的项目

资源归属链：
- Project → owner_id（直接归属）
- Dataset / Target / Hypothesis / Treatment / Experiment → project_id → Project.owner_id
- Molecule → target_id → Target.project_id → Project.owner_id
"""
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import Select

from app.core.security import UserRole
from app.models.project import Project
from app.models.target import Target
from app.models.user import User


def is_leadership_role(role: UserRole) -> bool:
    """领导角色（FOUNDER / CHIEF_RESEARCHER）拥有全组织数据可见性"""
    return role in (UserRole.FOUNDER, UserRole.CHIEF_RESEARCHER)


def apply_project_visibility(
    stmt: Select,
    current_user: User,
    project_fk_column: InstrumentedAttribute,
) -> Select:
    """对 project_id 直接关联的资源应用可见性过滤

    适用于 Dataset / Target / Hypothesis / Treatment / Experiment。
    领导角色（FOUNDER / CHIEF_RESEARCHER）不过滤，其余角色仅可见自己拥有的项目下的资源。

    Args:
        stmt: 原始 select 语句
        current_user: 当前登录用户
        project_fk_column: 资源上的 project_id 外键列（如 Dataset.project_id）

    Returns:
        过滤后的 select 语句
    """
    if is_leadership_role(current_user.role):
        return stmt
    visible_project_ids = select(Project.id).where(Project.owner_id == current_user.id)
    return stmt.where(project_fk_column.in_(visible_project_ids))


def apply_molecule_visibility(
    stmt: Select,
    current_user: User,
    target_fk_column: InstrumentedAttribute,
) -> Select:
    """对 Molecule 应用可见性过滤（通过 target_id → project_id → owner_id）

    孤立分子（target_id 为空）对非领导角色不可见，因为无法确定归属。

    Args:
        stmt: 原始 select 语句
        current_user: 当前登录用户
        target_fk_column: Molecule.target_id 列

    Returns:
        过滤后的 select 语句
    """
    if is_leadership_role(current_user.role):
        return stmt
    visible_project_ids = select(Project.id).where(Project.owner_id == current_user.id)
    visible_target_ids = select(Target.id).where(Target.project_id.in_(visible_project_ids))
    return stmt.where(target_fk_column.in_(visible_target_ids))


__all__ = [
    "is_leadership_role",
    "apply_project_visibility",
    "apply_molecule_visibility",
]
