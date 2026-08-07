"""失败知识库模型 — 沉淀负结果、规避此路不通"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class FailureReason:
    CONTAMINATION = "contamination"
    CONCENTRATION = "concentration"
    PROTOCOL_DEGRADATION = "protocol_degradation"
    EQUIPMENT_MALFUNCTION = "equipment_malfunction"
    HUMAN_ERROR = "human_error"
    BIOLOGICAL_VARIABILITY = "biological_variability"
    UNKNOWN = "unknown"


class FailureKnowledge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "failure_knowledge"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    failure_reason: Mapped[str] = mapped_column(String(50), nullable=False)
    failure_params: Mapped[Optional[dict]] = mapped_column(JSON)
    wrong_path_proof: Mapped[Optional[str]] = mapped_column(Text)
    target_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("targets.id"))
    molecule_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("molecules.id"))
    hypothesis_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("hypotheses.id"))
    experiment_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("experiments.id"))
    is_high_confidence: Mapped[Optional[bool]] = mapped_column(default=False)
    failure_count: Mapped[Optional[int]] = mapped_column(default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    project = relationship("Project", back_populates="failure_knowledge")
    target = relationship("Target", back_populates="failure_knowledge")
    molecule = relationship("Molecule", back_populates="failure_knowledge")
    hypothesis = relationship("Hypothesis", back_populates="failure_knowledge")
    experiment = relationship("Experiment", back_populates="failure_knowledge")

    def __repr__(self) -> str:
        return f"<FailureKnowledge reason={self.failure_reason} project={self.project_id}>"