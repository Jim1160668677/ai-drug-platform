"""靶点模型 — AI 辅助靶点发现"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class EvidenceGrade:
    """证据分级标准 I-IV"""
    LEVEL_I = "I"      # 已获批靶向药/标准治疗方案
    LEVEL_II = "II"    # 指南推荐但未获批
    LEVEL_III = "III"  # 临床试验阶段
    LEVEL_IV = "IV"    # 临床前研究/个案报道/理论推测


class Target(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "targets"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    gene_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # 如 EGFR, B7H3, FAP
    gene_name: Mapped[Optional[str]] = mapped_column(String(200))  # 全名
    evidence_grade: Mapped[str] = mapped_column(String(10), default=EvidenceGrade.LEVEL_IV)  # I-IV
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-1 置信度
    source: Mapped[Optional[str]] = mapped_column(String(200))  # 发现来源
    variant_info: Mapped[Optional[dict]] = mapped_column(JSON)  # 变异信息
    annotation: Mapped[Optional[dict]] = mapped_column(JSON)  # ClinVar/COSMIC/MyGene 注释
    pathway: Mapped[Optional[dict]] = mapped_column(JSON)  # KEGG/Reactome 通路
    approved_drugs: Mapped[Optional[list]] = mapped_column(JSON)  # 已匹配的获批药物
    evidence_chain: Mapped[Optional[dict]] = mapped_column(JSON)  # 证据链
    analysis_tier: Mapped[Optional[str]] = mapped_column(String(20))  # fast_screen / deep_insight
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    project = relationship("Project", back_populates="targets")
    molecules: Mapped[List["Molecule"]] = relationship("Molecule", back_populates="target")
    experiments: Mapped[List["Experiment"]] = relationship("Experiment", back_populates="target")

    def __repr__(self) -> str:
        return f"<Target {self.gene_symbol} (Grade {self.evidence_grade})>"
