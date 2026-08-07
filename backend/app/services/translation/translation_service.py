"""合作方与转化路径服务 — 资源池化 + 时间线汇总

PartnerService：CRO/CDMO/医院/检测机构 CRUD
TranslationStageService：9 阶段转化路径 CRUD + 时间线汇总（累计成本/时长/完成度）

注意：SQLAlchemy Uuid(as_uuid=True) 列的绑定处理器要求 uuid.UUID 对象，
      传入字符串会抛 'str' object has no attribute 'hex'。
      因此所有外部传入的 ID（来自端点 path 参数或测试）都先用 _to_uuid 归一化。
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.models.translation import (
    Partner,
    TranslationStage,
    TranslationStageStatus,
)

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """把 str/UUID 统一转为 UUID（SQLAlchemy Uuid 列要求 UUID 对象）

    None 透传，非法格式抛 ValueError（调用方应确保合法）。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class PartnerService:
    """合作方 CRUD"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_partner(self, data: Dict[str, Any]) -> Partner:
        if not data.get("name"):
            raise ValidationError("合作方名称不能为空")
        if not data.get("partner_type"):
            raise ValidationError("合作方类型不能为空")

        # 检查重名
        existing = await self.db.execute(
            select(Partner).where(Partner.name == data["name"])
        )
        if existing.scalar_one_or_none():
            raise ValidationError("合作方名称已存在")

        partner = Partner(
            name=data["name"],
            partner_type=data["partner_type"],
            org_id=_to_uuid(data.get("org_id")),
            capabilities=data.get("capabilities"),
            contact_name=data.get("contact_name"),
            contact_email=data.get("contact_email"),
            contact_phone=data.get("contact_phone"),
            lead_time_days=data.get("lead_time_days"),
            cost_per_unit_usd=data.get("cost_per_unit_usd"),
            quality_rating=data.get("quality_rating"),
            is_active=data.get("is_active", True),
            notes=data.get("notes"),
        )
        self.db.add(partner)
        await self.db.commit()
        await self.db.refresh(partner)
        return partner

    async def list_partners(
        self,
        partner_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[Partner], int]:
        stmt = select(Partner)
        if partner_type:
            stmt = stmt.where(Partner.partner_type == partner_type)
        stmt = stmt.order_by(Partner.created_at.desc())

        count_stmt = select(func.count()).select_from(Partner)
        if partner_type:
            count_stmt = count_stmt.where(Partner.partner_type == partner_type)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.offset((page - 1) * size).limit(size)
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def get_partner(self, partner_id: Any) -> Partner:
        partner = await self.db.get(Partner, _to_uuid(partner_id))
        if not partner:
            raise NotFoundError("合作方不存在")
        return partner

    async def update_partner(self, partner_id: Any, data: Dict[str, Any]) -> Partner:
        partner = await self.get_partner(partner_id)
        for field in (
            "name", "partner_type", "capabilities", "contact_name",
            "contact_email", "contact_phone", "lead_time_days", "cost_per_unit_usd",
            "quality_rating", "is_active", "notes",
        ):
            if field in data:
                setattr(partner, field, data[field])
        # org_id 单独处理（需转 UUID）
        if "org_id" in data:
            partner.org_id = _to_uuid(data["org_id"])
        await self.db.commit()
        await self.db.refresh(partner)
        return partner


class TranslationStageService:
    """转化阶段 CRUD + 时间线汇总"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_stage(self, data: Dict[str, Any]) -> TranslationStage:
        if not data.get("project_id"):
            raise ValidationError("项目 ID 不能为空")
        if not data.get("stage_type"):
            raise ValidationError("阶段类型不能为空")
        if not data.get("stage_name"):
            raise ValidationError("阶段名称不能为空")

        stage = TranslationStage(
            project_id=_to_uuid(data["project_id"]),
            molecule_id=_to_uuid(data.get("molecule_id")),
            stage_type=data["stage_type"],
            stage_name=data["stage_name"],
            description=data.get("description"),
            status=data.get("status", TranslationStageStatus.NOT_STARTED),
            partner_id=_to_uuid(data.get("partner_id")),
            start_date=data.get("start_date"),
            estimated_end_date=data.get("estimated_end_date"),
            actual_end_date=data.get("actual_end_date"),
            cost_usd=data.get("cost_usd"),
            duration_days=data.get("duration_days"),
            exit_criteria=data.get("exit_criteria"),
            exit_criteria_met=data.get("exit_criteria_met", False),
            findings=data.get("findings"),
            go_no_go=data.get("go_no_go"),
            order_index=data.get("order_index", 0),
        )
        self.db.add(stage)
        await self.db.commit()
        await self.db.refresh(stage)
        return stage

    async def list_stages(
        self,
        project_id: Any,
        molecule_id: Optional[Any] = None,
    ) -> List[TranslationStage]:
        stmt = (
            select(TranslationStage)
            .options(selectinload(TranslationStage.partner))
            .where(TranslationStage.project_id == _to_uuid(project_id))
            .order_by(TranslationStage.order_index.asc())
        )
        if molecule_id:
            stmt = stmt.where(TranslationStage.molecule_id == _to_uuid(molecule_id))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_stage(self, stage_id: Any) -> TranslationStage:
        stage = await self.db.get(TranslationStage, _to_uuid(stage_id))
        if not stage:
            raise NotFoundError("转化阶段不存在")
        return stage

    async def update_stage(self, stage_id: Any, data: Dict[str, Any]) -> TranslationStage:
        stage = await self.get_stage(stage_id)
        for field in (
            "stage_name", "description", "status", "start_date",
            "estimated_end_date", "actual_end_date", "cost_usd", "duration_days",
            "exit_criteria", "exit_criteria_met", "findings", "go_no_go", "order_index",
        ):
            if field in data:
                setattr(stage, field, data[field])
        # partner_id 单独处理（需转 UUID）
        if "partner_id" in data:
            stage.partner_id = _to_uuid(data["partner_id"])
        await self.db.commit()
        await self.db.refresh(stage)
        return stage

    async def assign_partner(self, stage_id: Any, partner_id: Any) -> TranslationStage:
        stage = await self.get_stage(stage_id)
        # 验证 partner 存在
        partner = await self.db.get(Partner, _to_uuid(partner_id))
        if not partner:
            raise NotFoundError("合作方不存在")
        stage.partner_id = partner.id
        await self.db.commit()
        # 重新查询以急加载 partner（async 下 refresh 不支持 relationship，序列化需访问 partner.name）
        stmt = (
            select(TranslationStage)
            .options(selectinload(TranslationStage.partner))
            .where(TranslationStage.id == stage.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_timeline(self, project_id: Any) -> Dict[str, Any]:
        """时间线汇总 — 累计成本/时长/完成百分比"""
        stages = await self.list_stages(project_id)

        total_cost = sum(s.cost_usd or 0 for s in stages)
        total_duration = sum(s.duration_days or 0 for s in stages)
        completed = sum(1 for s in stages if s.status == TranslationStageStatus.COMPLETED)
        total = len(stages)
        completion_pct = round(completed / total * 100, 1) if total > 0 else 0.0

        return {
            "project_id": str(project_id),
            "stages": [
                {
                    "id": str(s.id),
                    "stage_type": s.stage_type,
                    "stage_name": s.stage_name,
                    "status": s.status,
                    "partner_id": str(s.partner_id) if s.partner_id else None,
                    "partner_name": (s.partner.name if s.partner and s.partner.name else None),
                    "cost_usd": s.cost_usd,
                    "duration_days": s.duration_days,
                    "start_date": s.start_date.isoformat() if s.start_date else None,
                    "estimated_end_date": s.estimated_end_date.isoformat() if s.estimated_end_date else None,
                    "actual_end_date": s.actual_end_date.isoformat() if s.actual_end_date else None,
                    "exit_criteria_met": s.exit_criteria_met,
                    "go_no_go": s.go_no_go,
                    "order_index": s.order_index,
                    "findings": s.findings,
                }
                for s in stages
            ],
            "total_cost_usd": round(total_cost, 2),
            "total_duration_days": total_duration,
            "completion_pct": completion_pct,
            "total_stages": total,
            "completed_stages": completed,
        }
