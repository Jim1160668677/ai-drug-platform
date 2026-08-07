"""Prompt 模板模型 — 性状检索 / 基因组版本切换

设计来源：参照 Trae 论坛方案的两套基因组版本提示词模板
（GRCh37/hg19 默认 + GRCh38/hg38 切换），扩展为表化管理，
支持热更新与性状分类匹配。
"""
from typing import Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TemplateType:
    """模板类型"""

    TRAIT_SEARCH = "trait_search"          # 性状位点检索
    INTERPRETATION = "interpretation"      # 解读报告生成
    RECOMMENDATION = "recommendation"      # 生活建议生成
    GENERAL = "general"                    # 通用


class PromptTemplate(Base, UUIDMixin, TimestampMixin):
    """Prompt 模板 — 性状检索用

    一个模板可绑定到特定基因组版本和性状分类，便于差异化提示。
    """

    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="模板名")
    template_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="模板类型")
    genome_build: Mapped[Optional[str]] = mapped_column(String(16), index=True, comment="基因组版本 GRCh37/GRCh38/通用")
    trait_category: Mapped[Optional[str]] = mapped_column(String(32), index=True, comment="性状分类")

    content: Mapped[str] = mapped_column(Text, nullable=False, comment="模板内容（含 {trait} {genome_build} 占位符）")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="模板说明")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True, comment="是否启用")

    def __repr__(self) -> str:
        return f"<PromptTemplate {self.name} type={self.template_type} build={self.genome_build}>"


__all__ = ["PromptTemplate", "TemplateType"]
