"""规则引擎包 — 基于 YAML 的灵活业务规则配置与执行

设计来源：方向 C（多模态+规则引擎）。
两层架构：
- YAML 配置层：presets/*.yaml 定义推理规则、分析流程、报告模板
- Python 执行层：engine.py 求值条件并执行动作，plugins.py 提供可扩展插件

公共 API：
- RuleEngine：规则引擎核心（加载/求值/执行）
- RuleLoader：规则加载器（文件/目录/preset）
- PluginRegistry：插件注册表
- schemas：Rule/RuleSet/Condition/Action 数据模型
"""
from app.services.intelligence.rule_engine.engine import RuleEngine
from app.services.intelligence.rule_engine.loader import RuleLoader
from app.services.intelligence.rule_engine.plugins import PluginRegistry, get_default_registry
from app.services.intelligence.rule_engine.schemas import (
    Action, Condition, Rule, RuleEngineReport, RuleExecutionResult, RuleSet,
)

__all__ = [
    "RuleEngine",
    "RuleLoader",
    "PluginRegistry",
    "get_default_registry",
    "Action",
    "Condition",
    "Rule",
    "RuleSet",
    "RuleEngineReport",
    "RuleExecutionResult",
]
