"""干湿闭环验证任务模型 — 回应评委"抑制/过表达是否确实影响疾病需湿试验验证"

ValidationTask：把「AI 假设 → 验证任务 → 实验执行 → 结果回写 → 模型反馈」流程化，
与既有 Experiment（实验记录）和 FeedbackLoop（反馈引擎）打通，形成可追踪闭环。

设计要点：
- ValidationTask 与 Experiment 分层：本模型是「假设-预测-结论」语义层，
  Experiment 是「配置-结果-迭代」记录层，两者通过 experiment_id 关联。
- status 在记录结果后直接收敛为 conclusion（validated/refuted/inconclusive），
  减少冗余状态机。
- feedback_applied 提供幂等保护，避免重复调整 target.confidence_score。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ValidationTaskType:
    """验证任务类型 — 直接回应评委「抑制/过表达是否影响疾病」"""
    TARGET_KNOCKDOWN = "target_knockdown"          # 靶点敲降（siRNA/shRNA/CRISPR）
    TARGET_OVEREXPRESSION = "target_overexpression" # 靶点过表达
    BINDING_ASSAY = "binding_assay"                 # 结合实验（SPR/ITC）
    CELL_VIABILITY = "cell_viability"               # 细胞活力
    ANIMAL_STUDY = "animal_study"                   # 动物模型（PDX）
    TOXICITY_STUDY = "toxicity_study"               # 毒理实验


class ValidationTaskStatus:
    """验证任务状态 — 记录结果后收敛为 conclusion 值"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    AWAITING_RESULT = "awaiting_result"
    VALIDATED = "validated"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class ValidationConclusion:
    """验证结论 — 与 FeedbackLoop.apply_task_feedback 联动"""
    VALIDATED = "validated"        # 假设被湿实验证实 → target.confidence +0.1
    REFUTED = "refuted"            # 假设被证伪 → target.confidence -0.2
    INCONCLUSIVE = "inconclusive"  # 结论不明 → 不调整


class ValidationTask(Base, UUIDMixin, TimestampMixin):
    """验证任务 — 假设-预测-结论闭环"""
    __tablename__ = "validation_tasks"

    project_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    target_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("targets.id"), index=True
    )
    molecule_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("molecules.id"), index=True
    )
    treatment_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("treatments.id"), index=True
    )

    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)   # 要验证的假设（自然语言）
    prediction: Mapped[Optional[str]] = mapped_column(Text)         # AI 预期结果（如"细胞活力下降 30%"）
    status: Mapped[str] = mapped_column(String(20), default=ValidationTaskStatus.DRAFT)

    experiment_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("experiments.id"))
    partner_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("partners.id"))  # 委托合作方
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result_received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_result: Mapped[Optional[str]] = mapped_column(Text)
    conclusion: Mapped[Optional[str]] = mapped_column(String(20))   # validated/refuted/inconclusive
    feedback_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    next_action: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    experiment = relationship("Experiment", backref="validation_task")
    partner = relationship("Partner", backref="validation_tasks")
    target = relationship("Target", backref="validation_tasks")
    molecule = relationship("Molecule", backref="validation_tasks")

    def __repr__(self) -> str:
        return f"<ValidationTask {self.task_type} ({self.status})>"
