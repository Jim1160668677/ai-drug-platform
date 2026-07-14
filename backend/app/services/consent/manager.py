"""知情同意管理服务 — 授权、撤回、校验"""
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import ConsentRecord, ConsentStatus

logger = logging.getLogger(__name__)


class ConsentManager:
    """知情同意管理器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def grant(
        self,
        project_id: str,
        patient_pseudonym: str,
        consent_type: str,
        purpose: str,
        expires_at: Optional[datetime] = None,
        constraints: Optional[dict] = None,
        granted_by: Optional[str] = None,
    ) -> ConsentRecord:
        """授予知情同意"""
        consent = ConsentRecord(
            project_id=project_id,
            patient_pseudonym=patient_pseudonym,
            consent_type=consent_type,
            status=ConsentStatus.GRANTED,
            purpose=purpose,
            expires_at=expires_at,
            constraints=constraints,
            granted_by=granted_by,
        )
        self.db.add(consent)
        await self.db.flush()
        return consent

    async def revoke(self, consent_id: str, reason: Optional[str] = None) -> ConsentRecord:
        """撤回知情同意"""
        consent = await self.db.get(ConsentRecord, UUID(consent_id))
        if not consent:
            raise ValueError(f"同意记录 {consent_id} 不存在")
        consent.status = ConsentStatus.WITHDRAWN
        consent.revoked_at = datetime.utcnow()
        consent.revoke_reason = reason
        await self.db.flush()
        return consent

    async def check(
        self,
        project_id: str,
        patient_pseudonym: str,
        consent_type: str,
    ) -> bool:
        """校验同意状态：必须存在 status=granted 且未过期的记录"""
        stmt = select(ConsentRecord).where(
            ConsentRecord.project_id == project_id,
            ConsentRecord.patient_pseudonym == patient_pseudonym,
            ConsentRecord.consent_type == consent_type,
            ConsentRecord.status == ConsentStatus.GRANTED,
        )
        result = (await self.db.execute(stmt)).scalars().all()

        for consent in result:
            # 检查是否过期
            if consent.expires_at and consent.expires_at < datetime.utcnow():
                # 标记为过期
                consent.status = ConsentStatus.EXPIRED
                continue
            return True

        await self.db.flush()
        return False

    async def list_consents(
        self,
        project_id: str,
        patient_pseudonym: Optional[str] = None,
    ) -> List[ConsentRecord]:
        """查询同意列表"""
        stmt = select(ConsentRecord).where(
            ConsentRecord.project_id == project_id,
        ).order_by(ConsentRecord.created_at.desc())

        if patient_pseudonym:
            stmt = stmt.where(ConsentRecord.patient_pseudonym == patient_pseudonym)

        return list((await self.db.execute(stmt)).scalars().all())

    async def get_consent(self, consent_id: str) -> Optional[ConsentRecord]:
        """获取同意详情"""
        return await self.db.get(ConsentRecord, UUID(consent_id))
