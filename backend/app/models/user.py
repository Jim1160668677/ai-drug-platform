"""用户模型 — 5角色 RBAC + 机构/职能维度

向后兼容：原有 role（职级）枚举不变；新增 org_id/function_role/title 为正交维度，
全部 nullable，既有用户 function_role=NULL 时按既有逻辑工作。
"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import UserRole
from app.models.base import Base, TimestampMixin, UUIDMixin


class FunctionRole:
    """职能角色 — 正交于 UserRole（职级），标识用户在机构内做什么

    回应评委意见①：靶点发现/分子设计/用药指导/实验验证面向不同机构。
    """

    TARGET_DISCOVERY = "target_discovery"          # 靶点发现（生信）
    MOLECULE_DESIGN = "molecule_design"            # 分子设计（药物化学）
    CLINICAL_GUIDANCE = "clinical_guidance"       # 用药指导（临床医生）
    EXPERIMENT_VALIDATION = "experiment_validation"  # 实验验证（湿实验）
    PROJECT_PI = "project_pi"                      # 项目 PI
    REGULATORY = "regulatory"                      # 注册申报
    DATA_ENGINEERING = "data_engineering"           # 数据工程


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.RESEARCHER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    organization: Mapped[Optional[str]] = mapped_column(String(200))  # 冗余显示名（向后兼容）
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    bio: Mapped[Optional[str]] = mapped_column(Text)

    # 机构/职能维度（新增，全部 nullable，向后兼容）
    org_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    function_role: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(100))  # 职称

    # 反向关系
    projects_owned: Mapped[List["Project"]] = relationship(
        "Project", back_populates="owner", foreign_keys="Project.owner_id"
    )
    organization_ref = relationship("Organization", back_populates="users")

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
