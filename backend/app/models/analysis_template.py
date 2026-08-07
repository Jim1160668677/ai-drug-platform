"""分析模板模型 — 报告模板系统（CDISC SDTM / FHIR / 自定义）

设计来源：用户需求「提供开放的规则引擎与模板系统，支持用户根据特定研究需求
自定义推理规则、分析流程与报告模板」。

与 ReasoningRule 的关系：
- ReasoningRule（rule_type=report）定义「何时生成报告」
- AnalysisTemplate 定义「报告的结构与渲染逻辑」

支持行业标准：
- CDISC SDTM：临床试验数据标准化提交
- FHIR：医疗数据互操作
- 自定义：用户自定义报告结构
"""
from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TemplateFormat:
    """模板格式枚举"""
    MARKDOWN = "markdown"          # Markdown 报告（默认）
    HTML = "html"                  # HTML 报告
    JSON = "json"                  # JSON 结构化报告
    CDISC_SDTM = "cdisc_sdtm"     # CDISC SDTM 标准格式
    FHIR = "fhir"                  # FHIR 医疗数据标准
    PDF = "pdf"                    # PDF 报告（渲染后）


class TemplateCategory:
    """模板类别枚举"""
    TARGET_REPORT = "target_report"            # 靶点发现报告
    MOLECULE_REPORT = "molecule_report"        # 分子设计报告
    TREATMENT_PLAN = "treatment_plan"          # 治疗方案报告
    DATA_ANALYSIS = "data_analysis"            # 数据分析报告
    HYPOTHESIS_REVIEW = "hypothesis_review"    # 假设评审报告
    RESEARCH_SUMMARY = "research_summary"      # 研究总结报告
    CUSTOM = "custom"                          # 自定义


class AnalysisTemplate(Base, UUIDMixin, TimestampMixin):
    """分析报告模板 — 定义报告结构与渲染逻辑

    sections JSON 结构：
    [
        {
            "id": "summary",
            "title": "研究概要",
            "type": "text|table|chart|code",
            "data_source": "run.meta_review|dataset.parsed_summary|hypothesis.text",
            "render_hint": {"chart_type": "bar|scatter|heatmap", "x": "...", "y": "..."},
            "required": true
        },
        ...
    ]

    render_config JSON 结构：
    {
        "style": "default|academic|clinical",
        "locale": "zh-CN|en-US",
        "include_trace": false,
        "include_cost": true
    }

    模板渲染流程：
    1. RuleEngine 匹配 report 规则 → 选择模板
    2. EvidenceCollector 收集模板所需数据源
    3. AnalysisService.render_template(template_id, context) 渲染
    4. 输出 Markdown / HTML / JSON / CDISC SDTM / FHIR
    """

    __tablename__ = "analysis_templates"
    __table_args__ = (
        # 模板类别过滤：按类别列出模板
        Index("ix_analysis_templates_category", "category"),
        # 用户模板查询：列出某用户的自定义模板
        Index("ix_analysis_templates_user", "user_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), default=TemplateCategory.CUSTOM, nullable=False
    )
    format: Mapped[str] = mapped_column(
        String(30), default=TemplateFormat.MARKDOWN, nullable=False
    )

    # 模板内容（Markdown/HTML 模板字符串，或 JSON 结构定义）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 章节定义（结构化报告的章节列表，见上方 JSON 结构）
    sections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 渲染配置（样式 / 语言 / 是否包含 trace 等）
    render_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 来源（预置 / 用户自定义 / 插件）
    source: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0", nullable=False)

    # 用户归属（预置模板 user_id 为 NULL，全局可见）
    user_id: Mapped[Optional[UUIDType]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # 是否为默认模板（每个 category 只能有一个默认）
    is_default: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisTemplate {self.id} name={self.name} "
            f"category={self.category} format={self.format}>"
        )
