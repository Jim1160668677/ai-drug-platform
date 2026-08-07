"""系统端点 — 健康检查 + Prometheus 指标

设计来源：repowiki/zh/content/API参考文档/API概览与规范.md
           repowiki/zh/content/系统架构/后端架构设计/FastAPI应用工厂.md

路径规范（D1）：
- GET /api/v1/health   — 信封格式健康检查
- GET /api/v1/metrics  — Prometheus 文本格式监控指标
- GET /health          — 根路径无信封健康检查（K8s 探针，定义在 main.py）

注意：spec 强制 /api/v1/metrics 无 system 前缀（v1.x 修正了 main.py 内联的 /api/v1/system/metrics）
"""
import time
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.schemas.common import ApiResponse, success_response

router = APIRouter(tags=["系统"])

# 启动时间（用于 uptime 计算）
_START_TIME = time.time()


@router.get("/health", response_model=ApiResponse[Dict[str, Any]], summary="健康检查（信封格式）")
async def api_health_check():
    """健康检查（信封格式）— 供前端/网关消费

    返回 ApiResponse 信封：
    - status: healthy
    - app: precision-drug-design
    - version: 1.0.0
    - mock_mode: Mock 模式开关
    - env: 环境
    - guardrail_enabled: 安全护栏开关
    - uptime_sec: 启动后秒数
    """
    uptime = round(time.time() - _START_TIME, 1)
    return success_response({
        "status": "healthy",
        "app": "precision-drug-design",
        "version": "1.0.0",
        "mock_mode": settings.USE_MOCK,
        "env": settings.APP_ENV,
        "guardrail_enabled": settings.GUARDRAIL_ENABLED,
        "uptime_sec": uptime,
    })


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus 监控指标")
async def metrics():
    """Prometheus 格式监控指标 — Phase F

    暴露指标（由 app/core/observability/metrics.py 自动采集）：
    - precision_drug_http_requests_total{method,path,status}
    - precision_drug_http_request_duration_seconds_bucket{method,path,le}
    - precision_drug_http_requests_in_progress
    - precision_drug_llm_calls_total{model,tier,status}
    - precision_drug_llm_call_duration_seconds_bucket{model,tier,le}
    - precision_drug_llm_cost_usd_total{model}
    - precision_drug_llm_cache_hits_total{tier}
    - precision_drug_llm_cache_misses_total{tier}
    - precision_drug_ws_connections_active
    - precision_drug_db_connections_active
    - precision_drug_app_uptime_seconds

    实现说明：
    - 通过 prometheus_client.generate_latest() 输出真实指标
    - MetricsMiddleware 自动采集 HTTP 请求指标
    - LLM 指标通过 record_llm_call() 在服务层采集
    """
    from app.core.config import settings

    if not getattr(settings, "METRICS_ENABLED", True):
        return PlainTextResponse(
            "# Metrics disabled by configuration\n",
            media_type="text/plain; version=0.0.4",
        )

    # 同步 CostTracker 数据到 Prometheus 指标
    try:
        from app.services.llm.cost_tracker import get_cost_tracker
        from app.core.observability.metrics import LLM_COST_USD_TOTAL, LLM_CALLS_TOTAL
        tracker = get_cost_tracker()
        if tracker:
            summary = tracker.today_summary()
            # 注意：CostTracker 是累计当日花费，这里通过 gauge 模拟
            # 真实场景应改为在 record() 时直接 inc 到 Counter
            for model, cost in summary.get("by_model", {}).items():
                try:
                    # 直接设置到 counter 的底层值（仅用于展示）
                    # 生产环境应通过 record_llm_call() 在每次调用时 inc
                    pass  # 避免重复计数：record_llm_call 已在调用时记录
                except Exception:
                    pass
    except Exception:
        pass

    # 同步 LLM 缓存统计
    try:
        from app.services.llm.cache import get_cache
        from app.core.observability.metrics import record_cache_hit, record_cache_miss
        cache = get_cache()
        stats = cache.stats()
        # 缓存统计是累计值，这里不重复记录（已在 get/set 时记录）
        _ = stats  # 预留用于 debug
    except Exception:
        pass

    from app.core.observability.metrics import generate_metrics
    content, content_type = generate_metrics()
    return PlainTextResponse(content, media_type=content_type)
