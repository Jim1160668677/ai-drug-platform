"""数据集模型 — 多组学数据接入 + 质量报告"""
from typing import List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, JSON, String, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DataType:
    """支持的数据类型"""
    RNA_SEQ = "rna_seq"                # RNA 测序
    SCRNA_SEQ = "scrna_seq"            # 单细胞测序
    WES = "wes"                        # 全外显子测序
    WGS = "wgs"                        # 全基因组测序
    GENE_REPORT = "gene_report"        # 基因检测报告
    PROTEOMICS = "proteomics"          # 蛋白质组学
    METABOLOMICS = "metabolomics"      # 代谢组学
    CLINICAL_IMAGING = "imaging"       # 临床影像
    CLINICAL_LAB = "clinical_lab"      # 临床检验
    IHC = "ihc"                        # 免疫组化
    FASTA = "fasta"                    # FASTA 序列
    VCF = "vcf"                        # VCF 变异文件
    SNP_CHIP = "snp_chip"              # SNP 芯片基因型数据（23andMe/Ancestry/微信基因等）
    MULTIQC = "multiqc"               # MultiQC 质控聚合报告
    DICOM = "dicom"                   # DICOM 医学影像
    CNV = "cnv"                        # 拷贝数变异段（CNVkit/Tempus segments）
    XENIUM = "xenium"                  # Xenium 空间转录组聚类结果
    NEOANTIGEN = "neoantigen"          # 新抗原表位预测结果（HLA/肽段/IC50）


class ParseStatus:
    PENDING = "pending"
    PARSING = "parsing"
    COMPLETED = "completed"
    FAILED = "failed"


class Dataset(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "datasets"

    project_id: Mapped[UUIDType] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(200))  # 数据来源
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))  # MinIO 对象路径
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)  # 字节
    file_format: Mapped[Optional[str]] = mapped_column(String(20))  # csv/tsv/h5/mtx/vcf/fasta
    parse_status: Mapped[str] = mapped_column(String(20), default=ParseStatus.PENDING, index=True)
    quality_metrics: Mapped[Optional[dict]] = mapped_column(JSON)  # 质量指标
    parsed_summary: Mapped[Optional[dict]] = mapped_column(JSON)  # 解析结果摘要
    # 规范化分析结果（parse_dataset 末尾由 BioAnalyzer 自动填充）
    # 修复数据契约缺口 #2：下游 EvidenceCollector / AnalysisService 期望读取此字段，
    # 但管道从未写入。结构：{"diff_expression": {...}, "clustering": {...},
    # "enrichment": {...}, "statistics": {...}, "summary": "..."}
    analysis_results: Mapped[Optional[dict]] = mapped_column(JSON)
    uploaded_by: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # 关联
    project = relationship("Project", back_populates="datasets")
    quality_reports: Mapped[List["QualityReport"]] = relationship(
        "QualityReport", back_populates="dataset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Dataset {self.name} ({self.data_type})>"


class QualityReport(Base, UUIDMixin, TimestampMixin):
    """数据集质量报告 — 完整性/准确性/一致性评估

    设计来源：repowiki/zh/content/数据平台/质量控制与评估.md
    """
    __tablename__ = "quality_reports"

    dataset_id: Mapped[UUIDType] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    completeness: Mapped[Optional[float]] = mapped_column(Float)  # 完整性 0-1
    accuracy: Mapped[Optional[float]] = mapped_column(Float)  # 准确性 0-1
    consistency: Mapped[Optional[float]] = mapped_column(Float)  # 一致性 0-1
    issues: Mapped[Optional[dict]] = mapped_column(JSON)  # 发现的问题列表

    # 关联
    dataset = relationship("Dataset", back_populates="quality_reports")

    def __repr__(self) -> str:
        return f"<QualityReport completeness={self.completeness}>"
