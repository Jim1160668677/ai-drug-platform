"""实验模型 — 干湿闭环（Dry-Wet Loop）"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ExperimentType:
    CYTOTOXICITY = "cytotoxicity"  # 细胞毒性测试 MTT/CCK-8
    APOPTOSIS = "apoptosis"        # 流式细胞凋亡
    PDX = "pdx"                    # PDX 动物模型
    PD = "pharmacodynamics"        # 药效学
    PK = "pharmacokinetics"        # 药代动力学
    IN_VITRO = "in_vitro"          # 体外实验
    IN_VIVO = "in_vivo"            # 体内实验


class ExperimentStatus:
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    exp_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ExperimentType
    status: Mapped[str] = mapped_column(String(20), default=ExperimentStatus.PLANNED)
    target_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("targets.id"))
    molecule_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("molecules.id"))
    treatment_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("treatments.id"))
    # Phase B4 反馈闭环：关联 Co-Scientist 假设，将湿实验结果反馈到假设评估
    hypothesis_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("hypotheses.id"), nullable=True, index=True
    )
    config: Mapped[Optional[dict]] = mapped_column(JSON)  # 实验配置
    result: Mapped[Optional[dict]] = mapped_column(JSON)  # 实验结果（IC50/存活率/肿瘤体积等）
    success: Mapped[Optional[bool]] = mapped_column()  # 实验是否验证成功
    feedback_applied: Mapped[Optional[bool]] = mapped_column(default=False)  # 模型权重是否已更新
    iteration: Mapped[Optional[int]] = mapped_column(default=1)  # 迭代轮次
    lab_source: Mapped[Optional[str]] = mapped_column(String(200))  # 实验室来源
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # 失败数据价值化：失败原因沉淀
    failure_reason: Mapped[Optional[dict]] = mapped_column(JSON)
    failure_params: Mapped[Optional[dict]] = mapped_column(JSON)
    wrong_path_proof: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    project = relationship("Project", back_populates="experiments")
    target = relationship("Target", back_populates="experiments")
    molecule = relationship("Molecule", back_populates="experiments")
    treatment = relationship("Treatment", back_populates="experiments")
    # Phase B4：假设关联（单向，不强制 back_populates 以避免侵入 Hypothesis 模型）
    hypothesis = relationship("Hypothesis", foreign_keys=[hypothesis_id])
    failure_knowledge: Mapped[List["FailureKnowledge"]] = relationship("FailureKnowledge", back_populates="experiment")

    def __repr__(self) -> str:
        return f"<Experiment {self.name} ({self.exp_type})>"