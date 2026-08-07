"""系统可观测性模块 — Phase F

提供 Prometheus 指标采集、结构化日志增强、请求追踪能力。

子模块：
- metrics: Prometheus 指标定义（Counter/Histogram/Gauge）
- middleware: 指标采集中间件（HTTP 请求计数/延迟）
- logging_ext: 结构化 JSON 日志（可选，通过 LOG_JSON_FORMAT 启用）

设计原则：
- 零侵入：通过中间件自动采集，业务代码无需修改
- 可降级：prometheus_client 不可用时降级为空操作
- 低开销：指标采集 < 1ms/请求，异步日志不阻塞主流程
- 安全：敏感信息（API Key/密码/token）自动脱敏

参考：
- 现有中间件：app/core/middleware.py（EnvelopeMiddleware）
- 现有日志：app/core/logging.py（loguru）
- 现有指标端点：app/api/v1/endpoints/system.py（/metrics，原为静态 mock）
"""
from app.core.observability.metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    LLM_CALLS_TOTAL,
    LLM_CALL_DURATION_SECONDS,
    LLM_COST_USD_TOTAL,
    LLM_CACHE_HITS_TOTAL,
    LLM_CACHE_MISSES_TOTAL,
    WS_CONNECTIONS_ACTIVE,
    DB_CONNECTIONS_ACTIVE,
    APP_UPTIME_SECONDS,
    record_http_request,
    record_llm_call,
    record_cache_hit,
    record_cache_miss,
    set_active_connections,
    generate_metrics,
)

__all__ = [
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "HTTP_REQUESTS_IN_PROGRESS",
    "LLM_CALLS_TOTAL",
    "LLM_CALL_DURATION_SECONDS",
    "LLM_COST_USD_TOTAL",
    "LLM_CACHE_HITS_TOTAL",
    "LLM_CACHE_MISSES_TOTAL",
    "WS_CONNECTIONS_ACTIVE",
    "DB_CONNECTIONS_ACTIVE",
    "APP_UPTIME_SECONDS",
    "record_http_request",
    "record_llm_call",
    "record_cache_hit",
    "record_cache_miss",
    "set_active_connections",
    "generate_metrics",
]
