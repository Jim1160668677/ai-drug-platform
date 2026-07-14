"""数据血缘模型 — 数据流转追溯"""
from typing import Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DataLineage(Base, UUIDMixin, TimestampMixin):
    """数据血缘记录 — 追踪数据从 source 到 target 的转换关系

    典型链路：dataset → target → molecule → treatment
    """
    __tablename__ = "data_lineage"

    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transformation: Mapped[str] = mapped_column(String(100), nullable=False)
    transformation_meta: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[Optional[str]] = mapped_column(String(36))

    def __repr__(self) -> str:
        return f"<DataLineage {self.source_type}:{self.source_id} → {self.target_type}:{self.target_id}>"
