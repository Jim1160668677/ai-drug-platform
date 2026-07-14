"""治疗方案模型 — 并行治疗方案设计"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class TreatmentType:
    TARGETED = "targeted"        # 靶向治疗
    IMMUNO = "immuno"            # 免疫治疗
    CHEMO = "chemo"              # 化疗
    RADIO = "radio"              # 放疗
    COMBINATION = "combination"  # 组合疗法
    VACCINE = "vaccine"          # mRNA 肿瘤疫苗


class TreatmentStatus:
    PROPOSED = "proposed"        # 已提出
    TESTING = "testing"          # 测试中
    EFFECTIVE = "effective"      # 有效
    INEFFECTIVE = "ineffective"  # 无效
    DEPRECATED = "deprecated"    # 已废弃


class Treatment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "treatments"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    therapy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=TreatmentStatus.PROPOSED)
    target_ids: Mapped[Optional[list]] = mapped_column(JSON)  # 关联的靶点 ID 列表
    molecule_ids: Mapped[Optional[list]] = mapped_column(JSON)  # 关联的分子 ID 列表
    efficacy_score: Mapped[Optional[float]] = mapped_column(Float)  # 疗效评分 0-1
    risk_score: Mapped[Optional[float]] = mapped_column(Float)  # 风险评分 0-1
    confidence: Mapped[Optional[float]] = mapped_column(Float)  # 置信度
    config: Mapped[Optional[dict]] = mapped_column(JSON)  # 方案配置
    monitoring_data: Mapped[Optional[dict]] = mapped_column(JSON)  # 疗效监测数据
    hypothesis_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("hypotheses.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    project = relationship("Project", back_populates="treatments")
    experiments: Mapped[List["Experiment"]] = relationship("Experiment", back_populates="treatment")

    def __repr__(self) -> str:
        return f"<Treatment {self.name} ({self.therapy_type})>"


class ClinicalFeedback(Base, UUIDMixin, TimestampMixin):
    """临床反馈数据 — 患者用药结果"""
    __tablename__ = "clinical_feedbacks"

    treatment_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    patient_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    dosage: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    efficacy: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    adverse_reactions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    biomarker_changes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ClinicalFeedback {self.patient_code} ({self.efficacy})>"
