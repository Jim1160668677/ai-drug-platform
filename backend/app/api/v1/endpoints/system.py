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
    """Prometheus 格式监控指标

    暴露指标：
    - precision_drug_http_requests_total{method,path,status}
    - precision_drug_http_request_duration_ms_bucket{le}
    - precision_drug_llm_cost_usd_total{model}
    - precision_drug_active_users_count
    - precision_drug_db_connections_active
    - precision_drug_uptime_seconds

    TODO: P2 集成 prometheus_client 真实指标收集器
    """
    uptime = int(time.time() - _START_TIME)

    # 尝试从 CostTracker 获取真实 LLM 成本
    llm_cost_lines = []
    try:
        from app.services.llm.cost_tracker import get_cost_tracker
        tracker = get_cost_tracker()
        if tracker:
            summary = tracker.today_summary()
            for model, cost in summary.get("by_model", {}).items():
                llm_cost_lines.append(
                    f'precision_drug_llm_cost_usd_total{{model="{model}"}} {cost:.6f}'
                )
    except Exception:
        pass

    if not llm_cost_lines:
        llm_cost_lines.append('precision_drug_llm_cost_usd_total{model="unknown"} 0.0')

    lines = [
        "# HELP precision_drug_http_requests_total Total HTTP requests",
        "# TYPE precision_drug_http_requests_total counter",
        'precision_drug_http_requests_total{method="GET",path="/health",status="200"} 1',
        "",
        "# HELP precision_drug_http_request_duration_ms_bucket HTTP request duration in ms",
        "# TYPE precision_drug_http_request_duration_ms_bucket histogram",
        'precision_drug_http_request_duration_ms_bucket{le="50"} 1',
        'precision_drug_http_request_duration_ms_bucket{le="100"} 1',
        'precision_drug_http_request_duration_ms_bucket{le="500"} 1',
        'precision_drug_http_request_duration_ms_bucket{le="+Inf"} 1',
        "",
        "# HELP precision_drug_llm_cost_usd_total Total LLM cost in USD",
        "# TYPE precision_drug_llm_cost_usd_total counter",
    ]
    lines.extend(llm_cost_lines)
    lines.extend([
        "",
        "# HELP precision_drug_active_users_count Current active users",
        "# TYPE precision_drug_active_users_count gauge",
        "precision_drug_active_users_count 0",
        "",
        "# HELP precision_drug_db_connections_active Active database connections",
        "# TYPE precision_drug_db_connections_active gauge",
        "precision_drug_db_connections_active 0",
        "",
        "# HELP precision_drug_uptime_seconds Uptime in seconds",
        "# TYPE precision_drug_uptime_seconds gauge",
        f"precision_drug_uptime_seconds {uptime}",
        "",
    ])
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")
