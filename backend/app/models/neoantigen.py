"""新抗原与 mRNA 疫苗模型 — 复现「程序员用 ChatGPT+AlphaFold 救狗」案例

新闻洞察：程序员为爱犬定制癌症疫苗的完整流程为：
诊断 → 全基因组测序 → ChatGPT 找靶点 → AlphaFold 预测突变蛋白结构
→ 识别新抗原 → 设计个性化 mRNA 疫苗。

本模型持久化新抗原识别结果（突变肽段 + MHC 结合亲和力 + 疫苗序列），
支持个性化肿瘤疫苗研发场景。

设计要点：
- mutant_peptide / wildtype_peptide 配对存储，便于免疫原性比较
- mhc_alleles 是 JSON 数组，支持泛等位基因预测（MHCflurry）
- binding_affinity_nM < 500nM 且 mutant != wildtype 视为新抗原（is_neoantigen=True）
- vaccine_sequence 存储 LLM 设计的 mRNA 序列（可选，未设计时为空）
- owner_id 强制多租户隔离
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class NeoantigenStatus:
    """新抗原状态"""
    PENDING = "pending"          # 待识别
    IDENTIFIED = "identified"    # 已识别为新抗原
    REJECTED = "rejected"        # 不构成新抗原
    VACCINE_DESIGNED = "vaccine_designed"  # 已设计 mRNA 疫苗序列


class Neoantigen(Base, UUIDMixin, TimestampMixin):
    """新抗原记录 — 突变肽段 + MHC 结合 + mRNA 疫苗序列

    每条记录代表一个突变肽段在特定 MHC 等位基因下的结合预测结果，
    可选包含 LLM 设计的 mRNA 疫苗序列。
    """
    __tablename__ = "neoantigens"

    owner_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    target_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("targets.id"), index=True
    )  # 关联靶点（突变蛋白对应的基因）

    # 肽段信息
    mutant_peptide: Mapped[str] = mapped_column(String(50), nullable=False)  # 8-11 mer
    wildtype_peptide: Mapped[Optional[str]] = mapped_column(String(50))  # 野生型对照
    mutation_position: Mapped[Optional[int]] = mapped_column(Integer)  # 突变位置
    protein_context: Mapped[Optional[str]] = mapped_column(Text)  # 蛋白上下文序列

    # MHC 结合预测
    mhc_alleles: Mapped[Optional[list]] = mapped_column(JSON)  # JSON 数组：["HLA-A*02:01", ...]
    binding_affinity_nM: Mapped[float] = mapped_column(Float)  # IC50，<500nM 为强结合
    binding_rank: Mapped[Optional[float]] = mapped_column(Float)  # %rank，<2% 为新抗原
    is_neoantigen: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # binding<500nM && mutant!=wildtype
    status: Mapped[str] = mapped_column(
        String(30), default=NeoantigenStatus.PENDING
    )

    # mRNA 疫苗设计（LLM 生成，可选）
    vaccine_sequence: Mapped[Optional[str]] = mapped_column(Text)  # mRNA 序列
    vaccine_design_rationale: Mapped[Optional[str]] = mapped_column(Text)  # 设计理由
    gc_content: Mapped[Optional[float]] = mapped_column(Float)  # GC 含量（30-70% 为佳）
    predicted_stability: Mapped[Optional[float]] = mapped_column(Float)  # 预测稳定性 0-1

    # 结构信息（来自 ESMFold 预测）
    structure_plddt: Mapped[Optional[float]] = mapped_column(Float)  # 突变蛋白 plDDT
    mutation_effect: Mapped[Optional[str]] = mapped_column(Text)  # LLM 分析的突变功能影响

    def __repr__(self) -> str:
        return f"<Neoantigen {self.mutant_peptide[:10]}... binding={self.binding_affinity_nM}nM>"
