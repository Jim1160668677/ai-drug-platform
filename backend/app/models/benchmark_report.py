"""基准评测报告模型 — 持久化混合架构 vs 传统超算的成本/精度对比结果

回应评委意见：「LLM 在靶点识别中相比超算模拟的局限性」需要数据支撑。
本模型记录每个案例（如阿司匹林、伊马替尼）在 3 种模式（hybrid/supercompute/llm_only）
下的 7 个指标（RMSD/affinity_error/cost/duration/energy/cost_per_hit/top_k_enrichment），
用于生成跨模式对比报告，证明混合架构的成本优势。

设计要点：
- case_id 关联 BenchmarkRunner.BENCHMARK_CASES（如 "aspirin" / "imatinib"）
- mode 区分 3 种模式：hybrid（LLM+计算）/ traditional_supercompute（传统超算）/ llm_only（纯 LLM）
- metrics 是 JSON 字段，存储 7 个指标的完整快照
- summary 是 LLM 生成的自然语言总结
- 同一 case_id + mode 可有多条记录（多次运行），按 created_at 取最新
"""
from typing import Any, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BenchmarkMode:
    """基准模式 — 3 种对比维度"""
    HYBRID = "hybrid"                          # LLM + 计算（混合架构）
    TRADITIONAL_SUPERCOMPUTE = "traditional_supercompute"  # 传统超算（GPU 集群）
    LLM_ONLY = "llm_only"                     # 纯 LLM（无计算引擎）


class BenchmarkReport(Base, UUIDMixin, TimestampMixin):
    """基准评测报告 — 单次案例 × 模式的指标快照

    每次运行 BenchmarkRunner.run_benchmark(case_id, mode) 都会创建一条记录，
    包含 7 个指标的完整数据，用于跨模式对比与历史趋势分析。
    """
    __tablename__ = "benchmark_reports"

    case_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_id: Mapped[Optional[UUIDType]] = mapped_column(ForeignKey("users.id"), index=True)

    # 7 个核心指标（JSON 快照）
    # {
    #   "rmsd_Å": float,              # RMSD 精度（越低越好）
    #   "affinity_error": float,      # 亲和力预测误差（越低越好）
    #   "cost_usd": float,           # 总成本（LLM API + 计算资源）
    #   "duration_sec": int,          # 总耗时
    #   "cost_per_correct_hit": float, # 单位有效命中成本
    #   "energy_kwh": float,          # 能耗（千瓦时）
    #   "top_k_enrichment": float,    # Top-K 富集因子（越高越好）
    # }
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    summary: Mapped[Optional[str]] = mapped_column(Text)  # LLM 生成的自然语言总结
    input_smiles: Mapped[Optional[str]] = mapped_column(String(500))  # 案例分子 SMILES
    input_target: Mapped[Optional[str]] = mapped_column(String(200))  # 案例靶点

    # 成本节省百分比（hybrid 模式相对 traditional_supercompute）
    cost_saving_pct: Mapped[Optional[float]] = mapped_column(Float)
    # 精度变化百分比（hybrid 相对 traditional_supercompute，负值表示精度提升）
    accuracy_change_pct: Mapped[Optional[float]] = mapped_column(Float)

    def __repr__(self) -> str:
        return f"<BenchmarkReport {self.case_id}/{self.mode}>"
