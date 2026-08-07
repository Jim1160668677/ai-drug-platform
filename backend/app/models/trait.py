"""性状模型 — 个人基因组解读模块的顶层分类实体

设计来源：参照 Trae 论坛「个人基因组定制解密」方案，
性状（Trait）是 SNP 位点知识库的顶层分类，例如「过敏易感」「乳糖不耐受」。
SnpLocus 通过 trait_id 外键关联到 Trait。

一对多关系：一个 Trait → 多个 SnpLocus（一位点可能在多性状下重复出现）
"""
from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TraitCategory:
    """性状分类常量 — 便于前端筛选与统计

    分类非强制约束（DB 层存字符串），用户可自定义新分类。
    常量名与 recommendation_engine.py 中的推荐矩阵键严格对齐。
    """

    ALLERGY = "allergy"              # 过敏易感
    METABOLISM = "metabolism"        # 代谢能力（酒精/乳糖/叶酸等）
    CARDIO = "cardio"                # 心血管
    ATHLETIC = "athletic"            # 运动表现
    SLEEP = "sleep"                  # 睡眠节律
    SKIN_HAIR = "skin_hair"          # 皮肤毛发
    COGNITION = "cognition"          # 认知/神经
    ALTITUDE = "altitude"            # 高原适应
    DRUG_RESPONSE = "drug_response"  # 药物反应（药物基因组学）
    OTHER = "other"


class Trait(Base, UUIDMixin, TimestampMixin):
    """性状 — 个人基因组解读的顶层分类

    表名：traits
    被引用：SnpLocus.trait_id → traits.id
    """

    __tablename__ = "traits"

    name: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="性状名，如 过敏易感"
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="性状分类"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), comment="性状描述"
    )
    icon: Mapped[Optional[str]] = mapped_column(
        String(64), comment="前端图标标识（可选）"
    )

    def __repr__(self) -> str:
        return f"<Trait {self.name} ({self.category})>"


__all__ = ["Trait", "TraitCategory"]
