"""合作方与转化路径模型 — 回应评委"不知道临床转化需集成哪些资源"

Partner：CRO/CDMO/医院/检测机构/登记机构
TranslationStage：9 阶段转化时间线（靶点验证 → 临床前 → IND → I/II/III 期 → NDA）
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class PartnerType:
    """合作方类型"""
    CRO = "cro"                    # 合同研究组织（毒理/药效/动物实验）
    CDMO = "cdmo"                  # 合同开发生产组织（合成/制剂/生产）
    HOSPITAL = "hospital"          # 临床医院（I/II/III 期）
    TESTING_LAB = "testing_lab"    # 检测机构（生物标志物/基因检测）
    REGISTRY = "registry"          # 登记机构（NMPA/FDA）


class Partner(Base, UUIDMixin, TimestampMixin):
    """合作方 — CRO/CDMO/医院/检测机构/登记机构"""
    __tablename__ = "partners"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    partner_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    org_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("organizations.id"))
    capabilities: Mapped[Optional[list]] = mapped_column(JSON)  # ['toxicity_study','api_synthesis','phase1_trial',...]
    contact_name: Mapped[Optional[str]] = mapped_column(String(100))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)  # 平均交付周期
    cost_per_unit_usd: Mapped[Optional[float]] = mapped_column(Float)
    quality_rating: Mapped[Optional[float]] = mapped_column(Float)  # 1-5
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    organization = relationship("Organization", backref="partners")

    def __repr__(self) -> str:
        return f"<Partner {self.name} ({self.partner_type})>"


class TranslationStageType:
    """转化阶段类型 — 9 个固定阶段"""
    TARGET_VALIDATION = "target_validation"   # 靶点验证（敲降/过表达）
    PRECLINICAL_ADME = "preclinical_adme"     # 临床前 ADME
    PRECLINICAL_TOX = "preclinical_tox"       # 临床前毒理
    IND_FILING = "ind_filing"                  # IND 申请
    PHASE1 = "phase1"
    PHASE2 = "phase2"
    PHASE3 = "phase3"
    NDA_FILING = "nda_filing"


class TranslationStageStatus:
    """转化阶段状态"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class TranslationStage(Base, UUIDMixin, TimestampMixin):
    """转化阶段 — 项目/分子的临床转化路径节点"""
    __tablename__ = "translation_stages"

    project_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    molecule_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("molecules.id"), index=True
    )
    stage_type: Mapped[str] = mapped_column(String(40), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default=TranslationStageStatus.NOT_STARTED
    )
    partner_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("partners.id"))
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    estimated_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    duration_days: Mapped[Optional[int]] = mapped_column(Integer)
    exit_criteria: Mapped[Optional[list]] = mapped_column(JSON)  # 通过条件清单
    exit_criteria_met: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    findings: Mapped[Optional[str]] = mapped_column(Text)
    go_no_go: Mapped[Optional[str]] = mapped_column(String(10))  # go/no_go
    order_index: Mapped[int] = mapped_column(Integer, default=0)  # 时间线排序

    project = relationship("Project", backref="translation_stages")
    molecule = relationship("Molecule", backref="translation_stages")
    partner = relationship("Partner", backref="stages")

    def __repr__(self) -> str:
        return f"<TranslationStage {self.stage_name} ({self.status})>"
