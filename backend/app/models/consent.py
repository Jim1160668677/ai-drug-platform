"""知情同意记录模型 — GDPR/HIPAA 合规"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ConsentStatus:
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class ConsentType:
    DATA_USE = "data_use"
    SHARING = "sharing"
    PUBLICATION = "publication"


class ConsentRecord(Base, UUIDMixin, TimestampMixin):
    """知情同意记录 — 管理患者对数据使用/共享/发表的授权

    支持授予、撤回、过期三种状态，支持设置过期时间和约束条件。
    """
    __tablename__ = "consent_records"

    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    patient_pseudonym: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ConsentStatus.GRANTED)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[Optional[dict]] = mapped_column(JSON)
    granted_by: Mapped[Optional[str]] = mapped_column(String(36))

    def __repr__(self) -> str:
        return f"<ConsentRecord {self.patient_pseudonym} {self.consent_type}={self.status}>"
