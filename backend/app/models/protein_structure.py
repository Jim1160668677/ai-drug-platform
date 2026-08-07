"""蛋白结构预测模型 — 集成 ESMFold/AlphaFold 的结构预测结果

回应新闻洞察：Google C2S-Scale 模型 + 程序员用 ChatGPT+AlphaFold 救狗案例均依赖
蛋白结构预测。本模型持久化 ESMFold（单序列，~2s/蛋白）预测结果，供下游对接与
新抗原识别使用。

设计要点：
- target_id 可空：支持未注册为 Target 的裸序列预测（如突变蛋白快速验证）
- storage_path 指向 PDB 文件路径（本地或对象存储）
- plddt_mean 是 ESMFold 置信度均值（>70 视为可信）
- prediction_source 标识引擎：esmfold / alphafold / experimental / mock
- status 串联异步预测生命周期：pending → running → completed/failed
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ProteinStructureSource:
    """结构来源标识"""
    ESMFOLD = "esmfold"            # fair-esm 单序列预测
    ALPHAFOLD = "alphafold"       # AlphaFold2/3（未来集成）
    EXPERIMENTAL = "experimental" # 实验解析（X-ray/CryoEM）
    MOCK = "mock"                  # Mock 模式


class ProteinStructureStatus:
    """异步预测生命周期"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProteinStructure(Base, UUIDMixin, TimestampMixin):
    """蛋白结构预测记录 — ESMFold 等引擎的预测结果

    与 Target 关联（可选），存储序列、PDB 文件路径、plDDT 置信度等。
    """
    __tablename__ = "protein_structures"

    target_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("targets.id"), index=True
    )  # 可空：支持裸序列预测
    owner_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    sequence: Mapped[str] = mapped_column(Text, nullable=False)  # 氨基酸序列
    sequence_md5: Mapped[Optional[str]] = mapped_column(String(32), index=True)  # 去重索引
    storage_path: Mapped[Optional[str]] = mapped_column(String(500))  # PDB 文件路径
    plddt_mean: Mapped[Optional[float]] = mapped_column(Float)  # 置信度均值 0-100
    plddt_per_residue: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # JSON: 每残基 plDDT 列表
    prediction_source: Mapped[str] = mapped_column(
        String(20), default=ProteinStructureSource.ESMFOLD
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ProteinStructureStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    model_name: Mapped[Optional[str]] = mapped_column(String(100))  # 如 "esm2_t36_3B_UR50D"
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)  # 预测耗时（秒）
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)

    # 关联
    target = relationship("Target", backref="protein_structures")

    def __repr__(self) -> str:
        return f"<ProteinStructure {self.prediction_source} {self.status} plddt={self.plddt_mean}>"
