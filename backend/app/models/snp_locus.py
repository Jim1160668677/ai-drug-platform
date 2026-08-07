"""SNP 位点知识库模型 — 单条位点信息 + 证据等级 + PRS 权重

设计来源：参照 Trae 论坛方案，知识库以 rsid 为核心，
关联性状、基因、风险等位、效应量、人群、证据来源。
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class LocusTier:
    """位点分级 — PRS 评分用"""

    CORE = "core"              # 核心主效位点（权重 0.7）
    AUXILIARY = "auxiliary"    # 辅助叠加位点（权重 0.3）


class Population:
    """人群标签 — 优先收录东亚人群验证位点"""

    EAST_ASIAN = "east_asian"
    HAN_CHINESE = "han_chinese"
    CHINESE = "chinese"
    ASIAN = "asian"
    EUROPEAN = "european"
    AFRICAN = "african"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class EvidenceSource:
    """证据来源"""

    GWAS_CATALOG = "gwas_catalog"
    CLINVAR = "clinvar"
    OMIM = "omim"
    LLM = "llm"               # AI 检索生成
    MANUAL = "manual"          # 人工录入


class EvidenceLevel:
    """证据等级 — I 最强、IV 最弱"""

    LEVEL_I = "I"        # 大样本东亚队列验证 + 功能学证据
    LEVEL_II = "II"      # 东亚队列验证
    LEVEL_III = "III"    # 欧美队列验证 + 东亚复制
    LEVEL_IV = "IV"      # 仅欧美队列


class SnpLocus(Base, UUIDMixin, TimestampMixin):
    """SNP 位点知识库条目

    一条记录 = 一个 rsid 在一个性状下的注释。
    同一 rsid 可关联多个性状（多效性）。
    """

    __tablename__ = "snp_loci"

    rsid: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="dbSNP 编号，如 rs1234")
    chromosome: Mapped[str] = mapped_column(String(8), nullable=False, comment="染色体 1-22/X/Y/MT")
    position_grch37: Mapped[Optional[int]] = mapped_column(BigInteger, comment="GRCh37/hg19 坐标")
    position_grch38: Mapped[Optional[int]] = mapped_column(BigInteger, comment="GRCh38/hg38 坐标")
    ref_allele: Mapped[Optional[str]] = mapped_column(String(8), comment="参考等位")
    alt_allele: Mapped[Optional[str]] = mapped_column(String(8), comment="替代等位")

    gene_symbol: Mapped[Optional[str]] = mapped_column(String(64), index=True, comment="关联基因符号，如 IL13")

    trait_id: Mapped[UUIDType] = mapped_column(ForeignKey("traits.id"), nullable=False, index=True, comment="关联性状")

    effect_allele: Mapped[Optional[str]] = mapped_column(String(8), comment="风险等位基因")
    risk_genotype: Mapped[Optional[str]] = mapped_column(String(16), comment="风险基因型，如 AA/AG/GG")
    effect_size: Mapped[Optional[float]] = mapped_column(Float, comment="效应量（OR 或 β 值）")
    weight: Mapped[float] = mapped_column(Float, default=0.5, nullable=False, comment="PRS 权重 0-1")

    locus_tier: Mapped[str] = mapped_column(String(16), default=LocusTier.CORE, nullable=False, comment="位点分级 core/auxiliary")
    population: Mapped[str] = mapped_column(String(32), default=Population.EAST_ASIAN, nullable=False, comment="验证人群")

    evidence_source: Mapped[str] = mapped_column(String(32), default=EvidenceSource.LLM, nullable=False, comment="证据来源")
    evidence_level: Mapped[str] = mapped_column(String(16), default=EvidenceLevel.LEVEL_IV, nullable=False, comment="证据等级 I-IV")
    pmid: Mapped[Optional[str]] = mapped_column(String(32), comment="PubMed 文献 ID")

    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True, comment="是否经创始人审核通过")

    trait = relationship("Trait")

    def __repr__(self) -> str:
        return f"<SnpLocus {self.rsid} trait={self.trait_id} approved={self.is_approved}>"


__all__ = [
    "SnpLocus",
    "LocusTier",
    "Population",
    "EvidenceSource",
    "EvidenceLevel",
]
