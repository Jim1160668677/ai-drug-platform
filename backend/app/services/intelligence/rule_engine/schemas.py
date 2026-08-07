"""规则引擎数据模型 — Pydantic schemas

定义 YAML 规则文件的契约：RuleSet / Rule / Condition / Action。
支持嵌套条件（all/any/not）与多种动作类型（set_field/trigger_reasoning/call_plugin/log）。
"""
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Condition(BaseModel):
    """单个条件 — 字段比较

    三种模式：
    1. 叶子条件：field + op + value
    2. all：子条件全部满足
    3. any：子条件任一满足
    4. not：子条件取反（YAML 用 not，Python 属性为 not_）
    """
    model_config = ConfigDict(populate_by_name=True)

    field: Optional[str] = Field(None, description="上下文字段路径，如 target.confidence_score")
    op: Optional[str] = Field(None, description="操作符: ==/!=/>/>=/</<=/in/not_in/contains/exists")
    value: Optional[Any] = Field(None, description="比较值")
    all: Optional[List["Condition"]] = Field(None, description="AND 组合")
    any: Optional[List["Condition"]] = Field(None, description="OR 组合")
    not_: Optional["Condition"] = Field(None, alias="not", description="NOT 取反")

    @field_validator("op")
    @classmethod
    def validate_op(cls, v):
        if v is None:
            return v
        allowed = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "exists", "not_exists"}
        if v not in allowed:
            raise ValueError(f"不支持的操作符: {v}，允许: {allowed}")
        return v


Condition.model_rebuild()


class Action(BaseModel):
    """规则动作"""
    action: str = Field(..., description="动作类型: set_field/trigger_reasoning/call_plugin/log/emit_event")
    target: Optional[str] = Field(None, description="目标字段（set_field 时）")
    value: Optional[Any] = Field(None, description="设置值（set_field 时）")
    params: Optional[Dict[str, Any]] = Field(None, description="动作参数")
    message: Optional[str] = Field(None, description="日志/事件消息")


class Rule(BaseModel):
    """单条规则"""
    id: str = Field(..., description="规则唯一 ID")
    name: str = Field(..., description="规则名称")
    when: Condition = Field(..., description="触发条件")
    then: List[Action] = Field(..., description="执行动作列表")
    priority: int = Field(0, description="优先级（数值越大越先执行）")
    enabled: bool = Field(True, description="是否启用")
    description: Optional[str] = Field(None, description="规则描述")
    tags: Optional[List[str]] = Field(None, description="规则标签")


class RuleSet(BaseModel):
    """规则集 — 一个 YAML 文件的根"""
    ruleset: Dict[str, Any] = Field(..., description="ruleset 根节点")
    name: str = Field(..., description="规则集名称")
    version: str = Field("1.0", description="版本号")
    description: Optional[str] = Field(None, description="规则集描述")
    rules: List[Rule] = Field(default_factory=list, description="规则列表")

    @field_validator("ruleset")
    @classmethod
    def validate_ruleset(cls, v):
        if not isinstance(v, dict):
            raise ValueError("ruleset 必须是字典")
        return v


class RuleExecutionResult(BaseModel):
    """规则执行结果"""
    rule_id: str
    rule_name: str
    matched: bool
    actions_executed: int = 0
    outputs: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class RuleEngineReport(BaseModel):
    """规则引擎执行报告"""
    ruleset_name: str
    total_rules: int
    matched_rules: int
    executed_actions: int
    results: List[RuleExecutionResult]
    context_changes: Dict[str, Any] = Field(default_factory=dict)
    duration_sec: float


__all__ = ["Condition", "Action", "Rule", "RuleSet", "RuleExecutionResult", "RuleEngineReport"]
