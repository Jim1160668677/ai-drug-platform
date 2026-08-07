"""个人基因组解读模型 — 用户基因文件 + 基因型匹配 + 风险评估 + 生活建议

设计来源：参照 Trae 论坛「个人基因组定制解密」方案核心闭环：
上传 SNP 文件 → 匹配位点库 → 风险评分 → 个性化建议
"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class GenomeBuild:
    """基因组版本"""

    GRCH37 = "GRCh37"      # hg19
    GRCH38 = "GRCh38"      # hg38
    UNKNOWN = "unknown"   # 通用模板（无坐标版本）


class SourceFormat:
    """SNP 芯片文件来源格式"""

    TWENTY_THREE_AND_ME = "23andme"
    ANCESTRY = "ancestry"
    WECHAT_GENE = "wechat_gene"
    GENERIC = "generic"


class RiskLevel:
    """风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationCategory:
    """生活建议分类"""

    DIET = "diet"                # 饮食
    EXERCISE = "exercise"        # 运动
    SLEEP = "sleep"              # 睡眠
    MEDICAL = "medical"          # 医疗随访
    LIFESTYLE = "lifestyle"      # 生活方式


class PersonalGenome(Base, UUIDMixin, TimestampMixin):
    """个人基因组文件 — 用户上传的 SNP 芯片数据

    一个用户可上传多份文件（不同检测机构）。
    """

    __tablename__ = "personal_genomes"

    owner_id: Mapped[UUIDType] = mapped_column(ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    project_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("projects.id"), index=True, comment="关联项目（可选）")

    file_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="原始文件名")
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="存储路径")

    genome_build: Mapped[str] = mapped_column(String(16), default=GenomeBuild.GRCH37, nullable=False, comment="基因组版本 GRCh37/GRCh38/unknown")
    source_format: Mapped[str] = mapped_column(String(32), default=SourceFormat.GENERIC, nullable=False, comment="来源格式")

    total_variants: Mapped[Optional[int]] = mapped_column(Integer, comment="总变异数")
    parsed_summary: Mapped[Optional[dict]] = mapped_column(JSON, comment="解析摘要")
    quality_metrics: Mapped[Optional[dict]] = mapped_column(JSON, comment="质量指标")

    # 关联
    genotype_matches: Mapped[List["GenotypeMatch"]] = relationship(
        "GenotypeMatch", back_populates="personal_genome", cascade="all, delete-orphan"
    )
    risk_assessments: Mapped[List["RiskAssessment"]] = relationship(
        "RiskAssessment", back_populates="personal_genome", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PersonalGenome {self.file_name} build={self.genome_build}>"


class GenotypeMatch(Base, UUIDMixin, TimestampMixin):
    """个体基因型与位点库匹配结果

    一条记录 = 一个 PersonalGenome × 一个 SnpLocus 的匹配结果。
    """

    __tablename__ = "genotype_matches"

    personal_genome_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("personal_genomes.id"), nullable=False, index=True
    )
    snp_locus_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("snp_loci.id"), nullable=False, index=True
    )

    user_genotype: Mapped[str] = mapped_column(String(16), nullable=False, comment="用户基因型 AA/AG/GG/--")
    is_risk: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否风险基因型")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, comment="该位点风险评分")
    note: Mapped[Optional[str]] = mapped_column(Text, comment="备注（如链翻转说明）")

    personal_genome = relationship("PersonalGenome", back_populates="genotype_matches")
    snp_locus = relationship("SnpLocus")

    def __repr__(self) -> str:
        return f"<GenotypeMatch genotype={self.user_genotype} risk={self.is_risk}>"


class RiskAssessment(Base, UUIDMixin, TimestampMixin):
    """风险评估 — 针对一个性状的整体风险评分

    一个 PersonalGenome × 一个 Trait = 一份评估。
    """

    __tablename__ = "risk_assessments"

    personal_genome_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("personal_genomes.id"), nullable=False, index=True
    )
    trait_id: Mapped[UUIDType] = mapped_column(ForeignKey("traits.id"), nullable=False, index=True, comment="关联性状")

    overall_risk_score: Mapped[float] = mapped_column(Float, nullable=False, comment="整体风险评分 0-1")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, comment="风险等级 low/medium/high")

    core_loci_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="核心主效位点命中数")
    auxiliary_loci_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="辅助位点命中数")
    matched_loci_ids: Mapped[Optional[list]] = mapped_column(JSON, comment="命中的位点 ID 列表")

    interpretation: Mapped[Optional[dict]] = mapped_column(JSON, comment="LLM 解读结果")
    llm_model: Mapped[Optional[str]] = mapped_column(String(128), comment="使用的 LLM 模型")

    # 关联
    personal_genome = relationship("PersonalGenome", back_populates="risk_assessments")
    recommendations: Mapped[List["LifestyleRecommendation"]] = relationship(
        "LifestyleRecommendation", back_populates="risk_assessment", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RiskAssessment score={self.overall_risk_score} level={self.risk_level}>"


class LifestyleRecommendation(Base, UUIDMixin, TimestampMixin):
    """个性化生活建议 — LLM 按风险等级生成"""

    __tablename__ = "lifestyle_recommendations"

    risk_assessment_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("risk_assessments.id"), nullable=False, index=True
    )

    category: Mapped[str] = mapped_column(String(32), nullable=False, comment="建议分类 diet/exercise/sleep/medical/lifestyle")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="建议内容")
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False, comment="优先级 high/medium/low")
    evidence: Mapped[Optional[str]] = mapped_column(Text, comment="证据依据")

    risk_assessment = relationship("RiskAssessment", back_populates="recommendations")

    def __repr__(self) -> str:
        return f"<LifestyleRecommendation [{self.category}] {self.content[:30]}...>"


__all__ = [
    "PersonalGenome",
    "GenotypeMatch",
    "RiskAssessment",
    "LifestyleRecommendation",
    "GenomeBuild",
    "SourceFormat",
    "RiskLevel",
    "RecommendationCategory",
]
