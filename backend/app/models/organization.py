"""机构模型 — 机构与职能维度

回应评委意见①：项目面向科研院所（靶点发现）、药企（分子设计）、医院（用药指导）、
CRO/CDMO/检测机构（实验验证），但原角色体系按职级划分无机构维度。
本模型新增机构实体，User 通过 org_id + function_role 关联，保留既有 UserRole 职级不变。
"""
from typing import List, Optional

from sqlalchemy import Boolean, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class OrgType:
    """机构类型"""

    RESEARCH_INSTITUTE = "research_institute"  # 科研院所
    PHARMA = "pharma"                          # 药企
    HOSPITAL = "hospital"                      # 医院
    CRO = "cro"                                # 合同研究组织
    CDMO = "cdmo"                              # 合同研发生产
    TESTING_LAB = "testing_lab"                # 检测机构


class Organization(Base, UUIDMixin, TimestampMixin):
    """机构 — 用户所属的组织实体

    与 User 是多对一关系（User.org_id → Organization.id）。
    capabilities 标记机构能力（如 target_validation/synthesis/clinical），
    用于职能×机构合法性校验与合作方匹配。
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    org_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # OrgType
    license_no: Mapped[Optional[str]] = mapped_column(String(100))  # 资质编号
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    capabilities: Mapped[Optional[list]] = mapped_column(JSON)  # ["target_validation","synthesis","clinical"]
    # 注意：属性名不能用 metadata（与 DeclarativeBase.metadata 冲突），DB 列名映射为 metadata
    extra_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 关联
    users: Mapped[List["User"]] = relationship("User", back_populates="organization_ref")

    def __repr__(self) -> str:
        return f"<Organization {self.name} ({self.org_type})>"
