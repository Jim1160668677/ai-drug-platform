"""计算任务模型 — 统一记录所有计算引擎（对接/结构预测/单细胞/新抗原/筛选）的执行

回应新闻洞察：Google C2S-Scale 论文强调「LLM + 计算」混合架构的成本/能耗可追踪。
本模型统一记录每项计算任务的引擎、模式（mock/real/hybrid）、成本、耗时、能耗，
供 BenchmarkRunner 跨模式对比使用。

设计要点：
- job_type 覆盖所有计算类型：docking/structure_prediction/perturbation/neoantigen/screening
- engine 标识具体工具：unimol/vina/esmfold/scgpt/mhcflurry/hybrid
- mode 区分运行模式：mock/real/hybrid — 用于基准评测分组
- energy_kwh 记录能耗（基于 BENCHMARK_*_WATTS 与 duration_sec 估算）— 回应"成本-精度"对比需求
- owner_id 强制多租户隔离
"""
from typing import Any, Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ComputeJobType:
    """计算任务类型"""
    DOCKING = "docking"                        # 分子对接
    STRUCTURE_PREDICTION = "structure_prediction"  # 蛋白结构预测
    PERTURBATION = "perturbation"              # 单细胞扰动预测
    CELL_ANNOTATION = "cell_annotation"        # 细胞类型注释
    NEOANTIGEN = "neoantigen"                  # 新抗原识别
    VACCINE_DESIGN = "vaccine_design"          # mRNA 疫苗设计
    DUAL_CONTEXT_SCREEN = "dual_context_screen"  # 双上下文筛选
    BENCHMARK = "benchmark"                    # 基准评测


class ComputeEngine:
    """计算引擎标识"""
    UNIMOL = "unimol"        # Uni-Mol AI 对接
    VINA = "vina"            # AutoDock Vina 物理对接
    ESMFOLD = "esmfold"      # ESMFold 蛋白结构预测
    SCGPT = "scgpt"          # scGPT 单细胞基础模型
    MHCFLURRY = "mhcflurry"  # MHCflurry MHC-I 结合预测
    HYBRID = "hybrid"        # LLM+计算混合
    LLM_ONLY = "llm_only"    # 纯 LLM（无计算引擎）
    SUPERCOMPUTE = "supercompute"  # 传统超算基准


class ComputeMode:
    """运行模式 — 用于基准评测分组"""
    MOCK = "mock"            # Mock 模式（无 GPU）
    REAL = "real"            # 真实模式（调用实际引擎）
    HYBRID = "hybrid"        # 混合模式（LLM + 计算）


class ComputeJobStatus:
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComputeJob(Base, UUIDMixin, TimestampMixin):
    """计算任务记录 — 统一追踪所有计算引擎的执行

    每次调用计算引擎（对接/结构预测/单细胞等）都会创建一条记录，
    包含输入参数、结果、成本、耗时、能耗，用于基准评测与成本分析。
    """
    __tablename__ = "compute_jobs"

    owner_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), index=True
    )  # 可空：支持无项目上下文的快速计算

    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    engine: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), default=ComputeMode.MOCK)
    status: Mapped[str] = mapped_column(
        String(20), default=ComputeJobStatus.PENDING, index=True
    )

    # 输入输出
    input_params: Mapped[Optional[dict]] = mapped_column(JSON)  # JSON: 输入参数
    result: Mapped[Optional[dict]] = mapped_column(JSON)  # JSON: 计算结果

    # 成本与性能指标
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)  # 总成本（LLM + 计算）
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)  # 耗时（秒）
    energy_kwh: Mapped[Optional[float]] = mapped_column(Float)  # 能耗（千瓦时）
    token_count: Mapped[Optional[int]] = mapped_column(Integer)  # LLM token 用量

    # 错误信息
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<ComputeJob {self.job_type}/{self.engine} {self.status}>"
