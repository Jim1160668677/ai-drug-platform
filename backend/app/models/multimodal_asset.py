"""多模态资产模型 — 多模态数据整合引擎

设计来源：用户需求「构建多模态数据整合分析引擎，支持对用户全量数据
（结构化实验数据、非结构化文献数据、数值型计算结果、图像数据等多类型数据）
进行统一处理、关联分析与智能推理」。

分层多模态架构：
1. 基础层（multimodal/normalizer.py）：统一文本化
   - DICOM 元数据 / PDF(PyPDF2) / OCR(Tesseract) / 结构化数据序列化 → RAG 索引
   - 覆盖 90% 数据类型，确保所有数据可被检索
2. 关键场景（multimodal/vision_llm.py）：原生多模态 LLM
   - 病理图像 / 蛋白结构图 → agnes-2.0-vision（settings.LLM_MODEL_VISION 注入）
   - 降级链：vision LLM 失败 → OCR+文本 LLM → 元数据摘要

本表持久化多模态资产的文本化结果与结构化数据，供 RAG 索引与推理引用。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AssetType:
    """多模态资产类型枚举

    覆盖论文与用户需求的全量数据类型：
    - 文本类：文献 / 报告 / 笔记
    - 结构化：实验数据 / 计算结果
    - 图像类：病理图像 / 蛋白结构图 / 影像
    - 医学格式：DICOM / FHIR
    """
    LITERATURE = "literature"          # 文献（PDF / HTML / 文本）
    REPORT = "report"                  # 报告（Markdown / Word / PDF）
    EXPERIMENT_DATA = "experiment_data"  # 结构化实验数据（CSV / Excel）
    COMPUTE_RESULT = "compute_result"  # 数值型计算结果（对接 / folding）
    PATHOLOGY_IMAGE = "pathology_image"  # 病理图像（H&E / IHC 切片）
    PROTEIN_STRUCTURE = "protein_structure"  # 蛋白结构图（PDB / cartoon）
    MEDICAL_IMAGE = "medical_image"    # 医学影像（DICOM / CT / MRI）
    GENE_REPORT_PDF = "gene_report_pdf"  # 基因检测报告 PDF
    CLINICAL_RECORD = "clinical_record"  # 临床记录（FHIR / 病历）
    CUSTOM = "custom"                  # 自定义


class ProcessingStatus:
    """资产处理状态枚举"""
    PENDING = "pending"            # 待处理
    NORMALIZING = "normalizing"    # 基础层文本化中
    VISION_ANALYZING = "vision_analyzing"  # 原生多模态 LLM 分析中
    COMPLETED = "completed"        # 处理完成
    FAILED = "failed"              # 处理失败
    SKIPPED = "skipped"            # 跳过（不支持的数据类型）


class MultimodalAsset(Base, UUIDMixin, TimestampMixin):
    """多模态资产 — 一个已处理的可检索资产

    处理流程：
    1. 用户上传文件 / 引用数据集 → 创建 MultimodalAsset（status=pending）
    2. MultimodalNormalizer 基础层处理 → text_summary + structured_data（status=completed）
    3. 若为关键场景（病理/结构图）→ VisionLLMClient 原生多模态分析 → 更新 text_summary
    4. text_summary 注入 RAG 索引（CoScientistIndexer）供检索
    5. structured_data 供 EvidenceCollector 引用构建数据知识图谱

    降级链：
    - vision LLM 失败 → 保留 OCR + 元数据文本化结果（status=completed, vision_skipped=true）
    - 基础层失败 → status=failed，error 记录原因

    storage_path 指向 MinIO 对象路径（与 Dataset.storage_path 复用存储层）。
    """

    __tablename__ = "multimodal_assets"
    __table_args__ = (
        # 项目级资产查询：列出某项目的多模态资产
        Index("ix_multimodal_assets_project_type", "project_id", "asset_type"),
        # 数据集关联查询：获取某数据集的资产
        Index("ix_multimodal_assets_dataset", "dataset_id"),
        # 处理状态过滤：查找待处理 / 失败的资产
        Index("ix_multimodal_assets_status", "processing_status"),
    )

    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    dataset_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )  # 关联源数据集（若资产由数据集派生）
    session_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("unified_sessions.id", ondelete="SET NULL"), nullable=True
    )  # 关联会话（若资产由对话上传）

    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # MinIO 对象路径（与 Dataset.storage_path 复用存储层）
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # 原始文件格式（pdf/png/dcm/csv/pdb/...）
    file_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 基础层文本化结果（所有资产类型均有，供 RAG 索引）
    text_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 结构化数据（供 EvidenceCollector 引用，JSON 结构因 asset_type 而异）
    # - pathology_image: {"findings": [...], "regions": [...], "diagnosis": "..."}
    # - protein_structure: {"pdb_id": "...", "chains": [...], "binding_sites": [...]}
    # - medical_image: {"modality": "CT|MRI", "body_part": "...", "findings": [...]}
    # - literature: {"title": "...", "abstract": "...", "entities": [...], "doi": "..."}
    structured_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    processing_status: Mapped[str] = mapped_column(
        String(30), default=ProcessingStatus.PENDING, nullable=False
    )
    # 是否跳过原生多模态 LLM（降级到 OCR + 文本 LLM）
    vision_skipped: Mapped[Optional[bool]] = mapped_column(nullable=True, default=False)
    # 处理耗时（秒）
    processing_duration_sec: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 关联实体（构建数据知识图谱，可选）
    # 如 pathology_image 关联到某靶点 / 假设
    linked_entity_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # target|molecule|hypothesis|experiment
    linked_entity_id: Mapped[Optional[UUIDType]] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MultimodalAsset {self.id} type={self.asset_type} "
            f"name={self.name} status={self.processing_status}>"
        )
