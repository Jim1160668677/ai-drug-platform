"""报告与审计模型 — 靶点报告 + 证据项

设计来源：repowiki/zh/content/数据库设计/数据库Schema设计/报告与审计模型.md
           repowiki/zh/content/数据库设计/数据库Schema设计/分析结果模型/靶点发现模型.md
"""
from decimal import Decimal
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class TargetReport(Base, UUIDMixin, TimestampMixin):
    """靶点发现报告 — 一次完整靶点发现的输出

    每次执行 discover（quick/deep）后生成一份报告，包含：
    - 命中的靶点列表
    - 分析层级（quick/deep）
    - LLM 成本与耗时
    - Markdown/JSON 双格式内容
    - CDISC SDTM 导出路径
    """
    __tablename__ = "target_reports"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    target_ids: Mapped[Optional[list]] = mapped_column(JSON)  # 命中的靶点 ID 列表
    analysis_tier: Mapped[str] = mapped_column(String(20), nullable=False)  # quick / deep
    llm_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    content_md: Mapped[Optional[str]] = mapped_column(Text)  # Markdown 报告内容
    content_json: Mapped[Optional[dict]] = mapped_column(JSON)  # 结构化报告内容
    cdisc_sdtm_path: Mapped[Optional[str]] = mapped_column(String(500))  # CDISC SDTM 导出路径
    created_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))

    # 关联
    evidence_items: Mapped[List["EvidenceItem"]] = relationship(
        "EvidenceItem", back_populates="report", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TargetReport {self.id} (tier={self.analysis_tier})>"


class EvidenceItem(Base, UUIDMixin, TimestampMixin):
    """证据项 — 支撑靶点发现的单条证据

    证据分级（规范要求 I/II/III/IV）：
    - I：随机对照试验（RCT）或 Meta 分析
    - II：队列研究或病例对照研究
    - III：病例报告或病例系列
    - IV：专家意见或机制推理
    """
    __tablename__ = "evidence_items"

    report_id: Mapped[UUIDType] = mapped_column(ForeignKey("target_reports.id"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)  # clinical/literature/genomic/drug
    evidence_level: Mapped[str] = mapped_column(String(10), nullable=False)  # I/II/III/IV
    payload: Mapped[Optional[dict]] = mapped_column(JSON)  # 证据详情（来源、摘要、URL 等）

    # 关联
    report = relationship("TargetReport", back_populates="evidence_items")

    def __repr__(self) -> str:
        return f"<EvidenceItem {self.evidence_type} (level={self.evidence_level})>"
