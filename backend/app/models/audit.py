"""审计日志模型 — 不可篡改的 append-only 日志"""
from typing import Optional

from sqlalchemy import BigInteger, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """审计日志 — 所有数据访问和操作不可篡改记录

    注：数据库层面通过触发器防止 UPDATE/DELETE（见 postgres/init.sql）
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # 操作者
    role: Mapped[Optional[str]] = mapped_column(String(50))  # 操作者角色
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # 动作类型
    entity: Mapped[Optional[str]] = mapped_column(String(100), index=True)  # 实体类型
    entity_id: Mapped[Optional[str]] = mapped_column(String(100))  # 实体 ID
    before_val: Mapped[Optional[dict]] = mapped_column(JSON)  # 修改前值
    after_val: Mapped[Optional[dict]] = mapped_column(JSON)  # 修改后值
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    detail: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<AuditLog {self.actor} {self.action} {self.entity}>"
