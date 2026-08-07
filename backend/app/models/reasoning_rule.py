"""推理规则模型 — 开放规则引擎（YAML 配置层 + Python 插件层）

设计来源：用户需求「提供开放的规则引擎与模板系统，支持用户根据特定研究需求
自定义推理规则、分析流程与报告模板」。

两层扩展机制：
1. YAML 配置层（rules/presets/*.yaml）：主流用户无代码自定义
   - reasoning_rules.yaml：触发条件 → 研究目标模板（替代 auto_trigger.py 硬编码）
   - analysis_flows.yaml：分析流程模板
   - report_templates.yaml：CDISC SDTM / FHIR / 自定义报告模板
   - case_templates/*.yaml：案例模板（升级 cases/base.py）
2. Python 插件层（rules/plugins.py）：高级用户代码扩展
   - register_agent / register_strategy / register_data_source / register_action

本表持久化用户自定义规则，YAML 预置规则通过 RuleEngine 启动时加载到内存。
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class RuleType:
    """规则类型枚举

    - trigger: 触发规则（事件 → 条件匹配 → 启动推理，替代 auto_trigger.py）
    - analysis_flow: 分析流程规则（定义多步骤分析管道）
    - report: 报告模板规则（定义报告结构与渲染逻辑）
    - guardrail: 守卫规则（成本/时长/轮数限制，超限降级）
    - custom: 自定义规则（Python 插件扩展）
    """
    TRIGGER = "trigger"
    ANALYSIS_FLOW = "analysis_flow"
    REPORT = "report"
    GUARDRAIL = "guardrail"
    CUSTOM = "custom"


class RuleSource:
    """规则来源枚举"""
    PRESET = "preset"        # YAML 预置（rules/presets/*.yaml）
    USER = "user"            # 用户自定义（通过 API 创建）
    PLUGIN = "plugin"        # Python 插件（entry_points 加载）


class ReasoningRule(Base, UUIDMixin, TimestampMixin):
    """推理规则定义 — 一条可配置的规则

    trigger JSON 结构（RuleType.TRIGGER）：
    {
        "event": "data_parsed|target_discovered|hypothesis_generated|...",
        "conditions": [
            {"field": "dataset.data_type", "op": "eq", "value": "rna_seq"},
            {"field": "dataset.sample_count", "op": "gte", "value": 10}
        ],
        "match_mode": "all|any"
    }

    action JSON 结构：
    {
        "type": "start_reasoning|suggest_analysis|generate_report|call_agent",
        "params": {"research_goal_template": "...", "max_rounds": 5, ...},
        "target_mode": "chat|reasoning|agent"
    }

    优先级：priority 越高越先匹配（同事件多规则时按 priority 降序执行）。
    """

    __tablename__ = "reasoning_rules"
    __table_args__ = (
        # 规则类型过滤：按类型列出规则
        Index("ix_reasoning_rules_type_enabled", "rule_type", "enabled"),
        # 用户规则查询：列出某用户的自定义规则
        Index("ix_reasoning_rules_user", "user_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), default=RuleSource.USER, nullable=False
    )

    # 触发条件（RuleType.TRIGGER 时填写）
    trigger: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 执行动作（所有类型填写）
    action: Mapped[dict] = mapped_column(JSON, nullable=False)

    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # 用户归属（preset 规则 user_id 为 NULL，全局可见）
    user_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )  # 项目级规则（仅对该项目生效）

    # 版本与标签（便于管理与检索）
    version: Mapped[str] = mapped_column(String(20), default="1.0.0", nullable=False)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # ["aml", "drug_repurpose", ...]

    def __repr__(self) -> str:
        return (
            f"<ReasoningRule {self.id} name={self.name} "
            f"type={self.rule_type} enabled={self.enabled} priority={self.priority}>"
        )
