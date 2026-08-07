"""规则引擎插件层 — Python 可调用动作注册

允许规则通过 call_plugin 动作调用注册的 Python 函数，实现复杂业务逻辑。
插件函数签名：async def fn(ctx: dict, params: dict) -> dict

内置插件：
- drug_repurposer.lookup：查询靶点的老药重定位候选
- evidence_collector.collect：触发证据收集
- analysis_service.interpret：触发 LLM 解读
- emit_event：发射业务事件（供 auto_trigger 监听）
"""
import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

# 插件函数类型：async def fn(ctx: dict, params: dict) -> dict
PluginFn = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


class PluginRegistry:
    """插件注册表 — 管理规则引擎可调用的 Python 函数

    用法：
        registry = PluginRegistry()
        registry.register("my_plugin", my_async_fn)
        result = await registry.invoke("my_plugin", ctx, {"key": "value"})
    """

    def __init__(self):
        self._plugins: Dict[str, PluginFn] = {}
        self._register_builtin()

    def register(self, name: str, fn: PluginFn) -> None:
        """注册插件函数"""
        if name in self._plugins:
            logger.warning("[PluginRegistry] 覆盖已注册的插件: %s", name)
        self._plugins[name] = fn
        logger.debug("[PluginRegistry] 注册插件: %s", name)

    def unregister(self, name: str) -> None:
        """注销插件函数"""
        self._plugins.pop(name, None)

    def list_plugins(self) -> Dict[str, str]:
        """列出所有已注册插件"""
        return {name: (fn.__doc__ or "").strip().split("\n")[0] for name, fn in self._plugins.items()}

    async def invoke(self, name: str, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """调用插件函数"""
        fn = self._plugins.get(name)
        if fn is None:
            raise KeyError(f"插件未注册: {name}")
        try:
            return await fn(ctx, params)
        except Exception as e:
            logger.error("[PluginRegistry] 插件 %s 执行失败: %s", name, e)
            return {"error": str(e), "plugin": name}

    def has(self, name: str) -> bool:
        return name in self._plugins

    def _register_builtin(self) -> None:
        """注册内置插件（延迟绑定，避免循环导入）"""

        async def _emit_event(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
            """发射业务事件（写入 ctx._events 供消费者读取）"""
            event_type = params.get("event_type", "custom")
            events = ctx.setdefault("_events", [])
            event = {"type": event_type, "params": params, "source": "rule_engine"}
            events.append(event)
            logger.info("[PluginRegistry] 发射事件: %s", event_type)
            return {"emitted": event_type}

        async def _collect_evidence(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
            """触发证据收集（调用 EvidenceCollector）"""
            from app.services.intelligence.evidence_collector import EvidenceCollector
            project_id = params.get("project_id") or ctx.get("project_id")
            if not project_id:
                return {"error": "缺少 project_id"}
            collector = EvidenceCollector()
            bundle = await collector.collect_evidence_bundle(
                project_id=project_id,
                trigger_event=params.get("trigger_event"),
                entity_id=params.get("entity_id"),
            )
            ctx["_evidence"] = bundle.text
            return bundle.to_dict()

        async def _log(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
            """记录日志"""
            msg = params.get("message", "")
            level = params.get("level", "info")
            getattr(logger, level, logger.info)("[规则引擎日志] %s", msg)
            return {"logged": msg}

        async def _set_context(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
            """设置上下文字段"""
            key = params.get("key")
            value = params.get("value")
            if key:
                ctx[key] = value
            return {"set": key}

        self.register("emit_event", _emit_event)
        self.register("collect_evidence", _collect_evidence)
        self.register("log", _log)
        self.register("set_context", _set_context)


# 全局默认注册表（便于规则引擎直接使用）
_default_registry: PluginRegistry = None  # type: ignore


def get_default_registry() -> PluginRegistry:
    """获取全局默认插件注册表（单例）"""
    global _default_registry
    if _default_registry is None:
        _default_registry = PluginRegistry()
    return _default_registry


__all__ = ["PluginRegistry", "PluginFn", "get_default_registry"]
