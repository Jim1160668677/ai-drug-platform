"""规则引擎核心 — 条件求值与动作执行

RuleEngine 加载规则集，对上下文求值条件，按优先级执行匹配规则的动作。
支持嵌套条件（all/any/not）、字段路径访问、多种操作符与动作类型。

执行流程：
1. 加载规则（按 priority 降序）
2. 对每条规则求值 when 条件
3. 匹配则执行 then 动作（set_field/call_plugin/trigger_reasoning/log/emit_event）
4. 收集执行报告（含上下文变更）
"""
import logging
import operator
import time
from typing import Any, Dict, List, Optional

from app.services.intelligence.rule_engine.loader import RuleLoader
from app.services.intelligence.rule_engine.plugins import PluginRegistry, get_default_registry
from app.services.intelligence.rule_engine.schemas import (
    Action, Condition, Rule, RuleExecutionResult, RuleEngineReport, RuleSet,
)

logger = logging.getLogger(__name__)

# 操作符映射
_OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in a if a is not None else False,
    "exists": lambda a, b: a is not None,
    "not_exists": lambda a, b: a is None,
}


class RuleEngine:
    """规则引擎 — 条件求值与动作执行

    用法：
        engine = RuleEngine()
        ruleset = RuleLoader().load_preset("target_discovery")
        engine.load_ruleset(ruleset)
        report = await engine.execute({"target": {"confidence_score": 0.85, "evidence_grade": "strong"}})
    """

    def __init__(self, plugin_registry: Optional[PluginRegistry] = None):
        self.rules: List[Rule] = []
        self.rulesets: List[RuleSet] = []
        self.plugin_registry = plugin_registry or get_default_registry()

    def load_ruleset(self, ruleset: RuleSet) -> None:
        """加载规则集（追加到已加载列表）"""
        self.rulesets.append(ruleset)
        self.rules = RuleLoader().flatten_rules(self.rulesets)
        logger.info("[RuleEngine] 加载规则集 %s，当前共 %d 条启用规则", ruleset.name, len(self.rules))

    def load_from_file(self, path: str) -> None:
        """从 YAML 文件加载规则集"""
        self.load_ruleset(RuleLoader().load_file(path))

    def load_preset(self, name: str) -> None:
        """加载内置 preset"""
        self.load_ruleset(RuleLoader().load_preset(name))

    def clear(self) -> None:
        """清空已加载规则"""
        self.rules = []
        self.rulesets = []

    # ========== 条件求值 ==========

    def evaluate(self, condition: Condition, ctx: Dict[str, Any]) -> bool:
        """求值条件"""
        # all 组合
        if condition.all is not None:
            return all(self.evaluate(c, ctx) for c in condition.all)
        # any 组合
        if condition.any is not None:
            return any(self.evaluate(c, ctx) for c in condition.any)
        # not 取反（字段名 not_，YAML 别名为 not）
        not_cond = condition.not_
        if not_cond is not None:
            return not self.evaluate(not_cond, ctx)
        # 叶子条件
        if condition.field is None:
            return True
        actual = self._get_field(ctx, condition.field)
        op_fn = _OPERATORS.get(condition.op or "==", operator.eq)
        try:
            return bool(op_fn(actual, condition.value))
        except TypeError:
            return False

    def _get_field(self, ctx: Dict[str, Any], path: str) -> Any:
        """按点分路径访问嵌套字段，如 target.confidence_score"""
        current: Any = ctx
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                return None
        return current

    def _set_field(self, ctx: Dict[str, Any], path: str, value: Any) -> None:
        """按点分路径设置嵌套字段"""
        parts = path.split(".")
        current = ctx
        for part in parts[:-1]:
            if part not in current or not isinstance(current.get(part), dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    # ========== 动作执行 ==========

    async def _execute_action(
        self, action: Action, ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行单个动作"""
        if action.action == "set_field":
            if action.target:
                self._set_field(ctx, action.target, action.value)
            return {"action": "set_field", "target": action.target, "value": action.value}

        elif action.action == "call_plugin":
            plugin_name = (action.params or {}).get("name", "")
            plugin_params = (action.params or {}).get("params", {})
            if self.plugin_registry.has(plugin_name):
                result = await self.plugin_registry.invoke(plugin_name, ctx, plugin_params)
                return {"action": "call_plugin", "plugin": plugin_name, "result": result}
            return {"action": "call_plugin", "plugin": plugin_name, "error": "插件未注册"}

        elif action.action == "trigger_reasoning":
            goal = (action.params or {}).get("goal", "规则触发推理")
            ctx.setdefault("_triggered_reasoning", []).append(goal)
            return {"action": "trigger_reasoning", "goal": goal}

        elif action.action == "emit_event":
            event_type = (action.params or {}).get("event_type", "custom")
            ctx.setdefault("_events", []).append({
                "type": event_type, "params": action.params, "source": "rule_engine",
            })
            return {"action": "emit_event", "event_type": event_type}

        elif action.action == "log":
            msg = action.message or (action.params or {}).get("message", "")
            logger.info("[规则引擎] %s", msg)
            return {"action": "log", "message": msg}

        else:
            logger.warning("[RuleEngine] 未知动作类型: %s", action.action)
            return {"action": action.action, "error": "未知动作"}

    # ========== 执行入口 ==========

    async def execute(self, ctx: Dict[str, Any], tags: Optional[List[str]] = None) -> RuleEngineReport:
        """对上下文执行所有已加载规则

        Args:
            ctx: 上下文数据（会被动作原地修改）
            tags: 仅执行含指定标签的规则（可选）

        Returns:
            RuleEngineReport 执行报告
        """
        start = time.time()
        results: List[RuleExecutionResult] = []
        matched_count = 0
        action_count = 0
        # 记录原始上下文快照（用于计算变更）
        ctx_before = dict(ctx)

        for rule in self.rules:
            # 标签过滤
            if tags and rule.tags:
                if not any(t in rule.tags for t in tags):
                    continue

            result = RuleExecutionResult(rule_id=rule.id, rule_name=rule.name, matched=False)
            try:
                matched = self.evaluate(rule.when, ctx)
                result.matched = matched
                if matched:
                    matched_count += 1
                    for action in rule.then:
                        output = await self._execute_action(action, ctx)
                        result.outputs.append(output)
                        result.actions_executed += 1
                        action_count += 1
            except Exception as e:
                result.error = str(e)
                logger.exception("[RuleEngine] 规则 %s 执行异常: %s", rule.id, e)
            results.append(result)

        duration_sec = round(time.time() - start, 3)
        # 计算上下文变更
        ctx_changes = {k: ctx.get(k) for k in set(ctx.keys()) - set(ctx_before.keys())}
        for k in ctx_before:
            if k in ctx and ctx[k] != ctx_before.get(k):
                ctx_changes[k] = ctx[k]

        return RuleEngineReport(
            ruleset_name=",".join(rs.name for rs in self.rulesets) or "empty",
            total_rules=len(self.rules),
            matched_rules=matched_count,
            executed_actions=action_count,
            results=results,
            context_changes=ctx_changes,
            duration_sec=duration_sec,
        )

    # ========== 单规则测试 ==========

    async def test_rule(self, rule: Rule, ctx: Dict[str, Any]) -> RuleExecutionResult:
        """测试单条规则（不影响已加载规则集）"""
        result = RuleExecutionResult(rule_id=rule.id, rule_name=rule.name, matched=False)
        try:
            matched = self.evaluate(rule.when, ctx)
            result.matched = matched
            if matched:
                for action in rule.then:
                    output = await self._execute_action(action, ctx)
                    result.outputs.append(output)
                    result.actions_executed += 1
        except Exception as e:
            result.error = str(e)
        return result


__all__ = ["RuleEngine"]
