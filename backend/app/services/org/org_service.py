"""机构服务 — 机构 CRUD + 用户职能分配"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.organization import Organization
from app.models.user import User
from app.services.org.function_matrix import (
    is_valid_function_org_pair,
    get_workspace_entry,
)


class OrgService:
    """机构与职能管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_org(self, payload: dict) -> Organization:
        """创建机构"""
        name = payload.get("name")
        if not name:
            raise ValidationError("机构名称不能为空")
        org_type = payload.get("org_type")
        if not org_type:
            raise ValidationError("机构类型不能为空")

        # 检查名称唯一
        existing = await self.db.execute(
            select(Organization).where(Organization.name == name)
        )
        if existing.scalar_one_or_none():
            raise ValidationError(f"机构名称已存在: {name}")

        org = Organization(
            name=name,
            org_type=org_type,
            license_no=payload.get("license_no"),
            contact_email=payload.get("contact_email"),
            address=payload.get("address"),
            capabilities=payload.get("capabilities"),
            extra_metadata=payload.get("metadata") or payload.get("extra_metadata"),
            is_active=payload.get("is_active", True),
        )
        self.db.add(org)
        await self.db.flush()
        return org

    async def list_orgs(
        self, org_type: Optional[str] = None, page: int = 1, page_size: int = 50
    ) -> dict:
        """机构列表（分页）"""
        stmt = select(Organization)
        count_stmt = select(func.count()).select_from(Organization)
        if org_type:
            stmt = stmt.where(Organization.org_type == org_type)
            count_stmt = count_stmt.where(Organization.org_type == org_type)

        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(Organization.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await self.db.execute(stmt)).scalars().all()
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_org(self, org_id: UUID) -> Organization:
        """获取机构详情"""
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise NotFoundError("机构不存在")
        return org

    async def update_org(self, org_id: UUID, payload: dict) -> Organization:
        """更新机构"""
        org = await self.get_org(org_id)
        for key in (
            "name", "org_type", "license_no", "contact_email",
            "address", "capabilities", "is_active",
        ):
            if key in payload and payload[key] is not None:
                setattr(org, key, payload[key])
        if "metadata" in payload or "extra_metadata" in payload:
            org.extra_metadata = payload.get("metadata") or payload.get("extra_metadata")
        await self.db.flush()
        return org

    async def assign_user_to_org(
        self,
        user_id: UUID,
        org_id: UUID,
        function_role: Optional[str] = None,
        title: Optional[str] = None,
    ) -> User:
        """分配用户到机构 + 设置职能（校验职能×机构合法性）"""
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("用户不存在")

        org = await self.get_org(org_id)

        if function_role:
            if not is_valid_function_org_pair(function_role, org.org_type):
                raise ValidationError(
                    f"职能 {function_role} 与机构类型 {org.org_type} 不匹配"
                )
            user.function_role = function_role

        user.org_id = org.id
        if title is not None:
            user.title = title
        await self.db.flush()
        return user

    async def list_users_by_function(
        self, function_role: str, org_id: Optional[UUID] = None
    ) -> List[User]:
        """按职能查询用户"""
        stmt = select(User).where(User.function_role == function_role)
        if org_id:
            stmt = stmt.where(User.org_id == org_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def get_workspace_for_function(self, function_role: str) -> str:
        """职能 → 默认工作台路由"""
        return get_workspace_entry(function_role)
