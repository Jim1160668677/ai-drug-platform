"""分子模型 — 分子设计与对接 + 对接结果"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Molecule(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "molecules"

    target_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("targets.id"), index=True)
    smiles: Mapped[str] = mapped_column(Text, nullable=False)  # SMILES 字符串
    name: Mapped[Optional[str]] = mapped_column(String(200))
    chembl_id: Mapped[Optional[str]] = mapped_column(String(50))  # ChEMBL ID（老药新用时）
    inchi_key: Mapped[Optional[str]] = mapped_column(String(50))
    molecular_weight: Mapped[Optional[float]] = mapped_column(Float)
    logp: Mapped[Optional[float]] = mapped_column(Float)
    properties: Mapped[Optional[dict]] = mapped_column(JSON)  # 类药性、ADMET 等
    docking_result: Mapped[Optional[dict]] = mapped_column(JSON)  # DiffDock 对接结果（旧字段，保留兼容）
    designed_by: Mapped[Optional[str]] = mapped_column(String(50))  # deepchem/repurpose/manual
    is_approved: Mapped[Optional[bool]] = mapped_column(default=False)  # 是否已获批药物
    source: Mapped[Optional[str]] = mapped_column(String(200))

    # 关联
    target = relationship("Target", back_populates="molecules")
    experiments: Mapped[List["Experiment"]] = relationship("Experiment", back_populates="molecule")
    docking_results: Mapped[List["DockingResult"]] = relationship(
        "DockingResult", back_populates="molecule", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Molecule {self.name or self.smiles[:20]}>"


class DockingResult(Base, UUIDMixin, TimestampMixin):
    """分子对接结果 — DiffDock/其他对接工具的输出

    设计来源：repowiki/zh/content/数据库设计/数据库Schema设计/分析结果模型/分子结构模型.md
    """
    __tablename__ = "docking_results"

    molecule_id: Mapped[UUIDType] = mapped_column(ForeignKey("molecules.id"), nullable=False, index=True)
    protein_pdb_id: Mapped[Optional[str]] = mapped_column(String(20))  # 蛋白 PDB ID
    protein_pdb_path: Mapped[Optional[str]] = mapped_column(String(500))  # 蛋白 PDB 文件路径
    poses: Mapped[Optional[list]] = mapped_column(JSON)  # 对接 pose 列表（坐标 + 置信度）
    top_confidence: Mapped[Optional[float]] = mapped_column(Float)  # 最高置信度
    docked_by: Mapped[Optional[str]] = mapped_column(String(50))  # diffdock/autodock/vina

    # 关联
    molecule = relationship("Molecule", back_populates="docking_results")

    def __repr__(self) -> str:
        return f"<DockingResult {self.molecule_id} (conf={self.top_confidence})>"
