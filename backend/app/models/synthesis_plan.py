"""合成规划模型 — 持久化 AiZynthFinder 路线 + SAscore + SCScore + 成本估算

回应评委意见：「药物分子是否容易合成、成本如何」需要量化评估。
本模型记录每个目标分子的完整合成规划：路线（步骤树）、SA 评分、SC 评分、
总成本、可行性标签，以及 LLM 生成的自然语言推荐。

设计要点：
- molecule_id 可空：支持裸 SMILES 输入（未注册为 Molecule 的候选分子）
- routes 是 JSON 数组，每条路线含 steps 列表（反应步骤树）
- sa_score（1-10）+ sc_score（1-5）双指标交叉验证可行性
- total_cost_usd 来自 CostEstimator 的分项汇总
- source_engine 标识路线生成器：aizynthfinder / rdkit_template
- owner_id 强制多租户隔离
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class SynthesisFeasibility:
    """合成可行性标签"""
    EASY = "easy"      # SA < 3，1-2 步
    MEDIUM = "medium"  # SA 3-6，3-5 步
    HARD = "hard"      # SA > 6 或 > 5 步


class SynthesisSource:
    """路线生成引擎"""
    AIZYNTHFINDER = "aizynthfinder"  # AiZynthFinder MCTS（真实模式）
    RDKIT_TEMPLATE = "rdkit_template"  # RDKit BRICS + Hartenfeller 模板（降级模式）
    LLM_ASSISTED = "llm_assisted"    # LLM 辅助生成


class SynthesisPlan(Base, UUIDMixin, TimestampMixin):
    """合成规划记录 — 目标分子的完整合成方案

    每条记录代表一次合成规划：包含路线列表、可行性评分、成本估算、
    LLM 推荐理由，以及来源引擎标识。
    """
    __tablename__ = "synthesis_plans"

    owner_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    molecule_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("molecules.id"), index=True
    )  # 可空：支持裸 SMILES 输入
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id"), index=True
    )

    # 目标分子
    smiles: Mapped[str] = mapped_column(Text, nullable=False)  # 目标分子 SMILES
    canonical_smiles: Mapped[Optional[str]] = mapped_column(Text)  # RDKit 规范化 SMILES
    molecule_name: Mapped[Optional[str]] = mapped_column(String(200))

    # 路线列表（JSON 数组）
    # [{
    #   "steps": [{"smiles": "...", "reagent": "...", "reaction_name": "...", "conditions": "..."}],
    #   "score": 0.85,
    #   "n_steps": 3,
    #   "source": "aizynthfinder"
    # }]
    routes: Mapped[Optional[list]] = mapped_column(JSON)
    n_routes: Mapped[int] = mapped_column(Integer, default=0)
    best_route_score: Mapped[Optional[float]] = mapped_column(Float)
    n_steps_best: Mapped[Optional[int]] = mapped_column(Integer)

    # 可行性评分
    sa_score: Mapped[Optional[float]] = mapped_column(Float)  # 1-10，越低越易合成
    sc_score: Mapped[Optional[float]] = mapped_column(Float)  # 1-5，越低越易合成
    feasibility_label: Mapped[Optional[str]] = mapped_column(
        String(20), default=SynthesisFeasibility.MEDIUM
    )
    challenges: Mapped[Optional[list]] = mapped_column(JSON)  # JSON: [{name, severity, mitigation}]

    # 成本估算（USD）
    total_cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    cost_breakdown: Mapped[Optional[dict]] = mapped_column(JSON)  # {materials, labor, equipment, overhead}
    cost_per_gram: Mapped[Optional[float]] = mapped_column(Float)

    # LLM 推荐与总结
    llm_recommendation: Mapped[Optional[str]] = mapped_column(Text)  # 自然语言推荐
    recommended_route_idx: Mapped[Optional[int]] = mapped_column(Integer)  # 推荐路线索引
    risk_assessment: Mapped[Optional[str]] = mapped_column(Text)  # 风险评估

    # 来源
    source_engine: Mapped[str] = mapped_column(
        String(30), default=SynthesisSource.RDKIT_TEMPLATE
    )

    # 关联
    molecule = relationship("Molecule", backref="synthesis_plans")

    def __repr__(self) -> str:
        return f"<SynthesisPlan {self.smiles[:20]}... {self.feasibility_label} ${self.total_cost_usd}>"
