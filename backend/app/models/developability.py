"""药物可开发性评估模型 — 5 维度干实验预筛选

回应评委意见：药物分子是否容易合成、毒理、制剂递送、生产成本如何，
在送入湿实验前先用算法做预筛选，节省湿实验成本。
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DevelopabilityAssessment(Base, UUIDMixin, TimestampMixin):
    """药物可开发性评估记录 — 一次评估的持久化结果

    5 个维度：
    1. 合成可及性 SA Score（1-10，越低越易合成）
    2. 毒理风险（low/moderate/high）
    3. 制剂递送评分（0-1，越高越适合口服）
    4. 生产成本估算（USD/克）
    5. 综合评分 + go/revise/no_go 决策
    """
    __tablename__ = "developability_assessments"

    molecule_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("molecules.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)  # 同分子可多次评估
    created_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))

    # 5 维度评分
    sa_score: Mapped[Optional[float]] = mapped_column(Float)  # 1-10，越低越易合成
    sa_ease_label: Mapped[Optional[str]] = mapped_column(String(20))  # easy/medium/hard
    toxicity_risk: Mapped[Optional[str]] = mapped_column(String(20))  # low/moderate/high
    toxicity_alerts: Mapped[Optional[list]] = mapped_column(JSON)  # [{name, smarts, severity}]
    formulation_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-1
    formulation_notes: Mapped[Optional[str]] = mapped_column(Text)
    cost_estimate_usd: Mapped[Optional[float]] = mapped_column(Float)  # USD/克
    cost_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)  # {materials, labor, overhead}

    # 综合
    overall_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-1
    recommendation: Mapped[Optional[str]] = mapped_column(String(20))  # go/revise/no_go
    rationale: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    molecule = relationship("Molecule", backref="developability_assessments")

    def __repr__(self) -> str:
        return f"<DevelopabilityAssessment mol={self.molecule_id} v{self.version} {self.recommendation}>"
