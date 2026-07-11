"""项目模型 — 患者/研究项目"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Enum, ForeignKey, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ProjectStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    patient_pseudonym: Mapped[Optional[str]] = mapped_column(String(100))  # 患者假名（脱敏）
    cancer_type: Mapped[Optional[str]] = mapped_column(String(100))  # 癌种
    stage: Mapped[Optional[str]] = mapped_column(String(50))  # 分期
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.ACTIVE)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    owner_id: Mapped[UUIDType] = mapped_column(ForeignKey("users.id"), nullable=False)

    # 关联
    owner = relationship("User", back_populates="projects_owned", foreign_keys=[owner_id])
    datasets: Mapped[List["Dataset"]] = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")
    targets: Mapped[List["Target"]] = relationship("Target", back_populates="project", cascade="all, delete-orphan")
    hypotheses: Mapped[List["Hypothesis"]] = relationship("Hypothesis", back_populates="project", cascade="all, delete-orphan")
    treatments: Mapped[List["Treatment"]] = relationship("Treatment", back_populates="project", cascade="all, delete-orphan")
    experiments: Mapped[List["Experiment"]] = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project {self.name}>"
