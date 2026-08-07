"""Prometheus 指标定义 — Phase F

使用 prometheus_client 定义全局指标，支持：
- HTTP 请求计数/延迟/并发（http_requests_total / http_request_duration_seconds / http_requests_in_progress）
- LLM 调用计数/延迟/成本（llm_calls_total / llm_call_duration_seconds / llm_cost_usd_total）
- LLM 缓存命中/未命中（llm_cache_hits_total / llm_cache_misses_total）
- WebSocket 活跃连接（ws_connections_active）
- 数据库活跃连接（db_connections_active）
- 应用运行时长（app_uptime_seconds）

设计原则：
- 指标全局单例（模块级定义），prometheus_client 自动注册到默认 REGISTRY
- 标签 cardinality 可控：路径归一化（/runs/{id} → /runs/:id），避免爆炸
- 线程安全：prometheus_client 内部已实现原子操作
- 可降级：prometheus_client 不可用时所有 record_* 函数降级为 no-op

使用方式：
    from app.core.observability.metrics import record_http_request
    record_http_request(method="GET", path="/health", status=200, duration_sec=0.012)
"""
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 启动时间（用于 uptime 指标）
_START_TIME = time.time()

# 尝试导入 prometheus_client，失败时降级为 no-op
try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — 依赖已存在于 requirements
    _PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client 未安装，指标采集降级为 no-op")

    # 占位类型，避免 NameError
    class _Stub:  # type: ignore
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kw): return self
        def inc(self, *a, **kw): pass
        def observe(self, *a, **kw): pass
        def set(self, *a, **kw): pass

    Counter = Gauge = Histogram = _Stub  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest():  # type: ignore
        return b""


# ========== HTTP 指标 ==========

# 请求总数（按 方法/路径/状态码 标签）
HTTP_REQUESTS_TOTAL: Counter = Counter(
    "precision_drug_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

# 请求延迟分布（秒）
HTTP_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "precision_drug_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 当前进行中的请求数
HTTP_REQUESTS_IN_PROGRESS: Gauge = Gauge(
    "precision_drug_http_requests_in_progress",
    "Current HTTP requests in progress",
)


# ========== LLM 指标 ==========

# LLM 调用总数（按 模型/tier/状态 标签）
LLM_CALLS_TOTAL: Counter = Counter(
    "precision_drug_llm_calls_total",
    "Total LLM API calls",
    ["model", "tier", "status"],
)

# LLM 调用延迟（秒）
LLM_CALL_DURATION_SECONDS: Histogram = Histogram(
    "precision_drug_llm_call_duration_seconds",
    "LLM call duration in seconds",
    ["model", "tier"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# LLM 累计成本（美元）
LLM_COST_USD_TOTAL: Counter = Counter(
    "precision_drug_llm_cost_usd_total",
    "Total LLM cost in USD",
    ["model"],
)

# 缓存命中/未命中
LLM_CACHE_HITS_TOTAL: Counter = Counter(
    "precision_drug_llm_cache_hits_total",
    "LLM response cache hits",
    ["tier"],
)

LLM_CACHE_MISSES_TOTAL: Counter = Counter(
    "precision_drug_llm_cache_misses_total",
    "LLM response cache misses",
    ["tier"],
)


# ========== 系统指标 ==========

# WebSocket 活跃连接数
WS_CONNECTIONS_ACTIVE: Gauge = Gauge(
    "precision_drug_ws_connections_active",
    "Active WebSocket connections",
)

# 数据库活跃连接数
DB_CONNECTIONS_ACTIVE: Gauge = Gauge(
    "precision_drug_db_connections_active",
    "Active database connections",
)

# 应用运行时长（秒）
APP_UPTIME_SECONDS: Gauge = Gauge(
    "precision_drug_app_uptime_seconds",
    "Application uptime in seconds",
)


# ========== 便捷记录函数 ==========

# 需要归一化的路径前缀（避免 cardinality 爆炸）
# 将 /runs/550e8400-... → /runs/:id
_PATH_ID_PATTERNS = (
    "/runs/",
    "/projects/",
    "/datasets/",
    "/targets/",
    "/molecules/",
    "/hypotheses/",
    "/experiments/",
    "/treatments/",
    "/jobs/",
    "/tasks/",
    "/sessions/",
)


# UUID 正则：8-4-4-4-12 hex 格式
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
# 长 hex 串（32+ 字符，如 MongoDB ObjectId 或 session ID）
_LONG_HEX_RE = re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE)
# 短 hex 串（16-31 字符，可能是 nanoid 或短 UUID）
_SHORT_HEX_RE = re.compile(r"^[0-9a-f]{16,31}$", re.IGNORECASE)


def _normalize_path(path: str) -> str:
    """归一化路径 — 将 UUID/数字 ID 替换为 :id

    避免高基数路径导致 Prometheus 标签 cardinality 爆炸。

    判定规则（保守，避免误判静态路径段）：
    1. 纯数字 → :id
    2. 标准 UUID 格式（8-4-4-4-12）→ :id
    3. 32+ 字符的纯 hex 串 → :id
    4. 16-31 字符的纯 hex 串 → :id（可能是短 UUID）
    5. 其他（含字母/连字符的语义路径段）→ 保留原样
    """
    if not path:
        return "/"
    parts = path.split("/")
    normalized = []
    for part in parts:
        if not part:
            continue
        # 纯数字 ID
        if part.isdigit():
            normalized.append(":id")
            continue
        # 标准 UUID
        if _UUID_RE.match(part):
            normalized.append(":id")
            continue
        # 长 hex 串（32+）
        if _LONG_HEX_RE.match(part):
            normalized.append(":id")
            continue
        # 短 hex 串（16-31）
        if _SHORT_HEX_RE.match(part):
            normalized.append(":id")
            continue
        # 其他保留原样（包括 test-endpoint 这种语义路径）
        normalized.append(part)
    return "/" + "/".join(normalized)


def record_http_request(
    method: str,
    path: str,
    status: int,
    duration_sec: float,
) -> None:
    """记录一次 HTTP 请求

    Args:
        method: HTTP 方法（GET/POST/...）
        path: 请求路径（会自动归一化）
        status: HTTP 状态码
        duration_sec: 请求耗时（秒）
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        norm_path = _normalize_path(path)
        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            path=norm_path,
            status=str(status),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            path=norm_path,
        ).observe(duration_sec)
    except Exception as e:
        logger.debug(f"record_http_request 失败（不影响主流程）: {e}")


def record_llm_call(
    model: str,
    tier: str,
    status: str,
    duration_sec: float,
    cost_usd: float = 0.0,
) -> None:
    """记录一次 LLM 调用

    Args:
        model: 模型名（如 agnes-2.0-flash）
        tier: 模型层级（fast_screen / deep_insight / router）
        status: 调用状态（success / failed / timeout / fallback）
        duration_sec: 调用耗时（秒）
        cost_usd: 本次成本（美元）
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        LLM_CALLS_TOTAL.labels(model=model, tier=tier, status=status).inc()
        LLM_CALL_DURATION_SECONDS.labels(model=model, tier=tier).observe(duration_sec)
        if cost_usd > 0:
            LLM_COST_USD_TOTAL.labels(model=model).inc(cost_usd)
    except Exception as e:
        logger.debug(f"record_llm_call 失败（不影响主流程）: {e}")


def record_cache_hit(tier: str) -> None:
    """记录缓存命中"""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        LLM_CACHE_HITS_TOTAL.labels(tier=tier).inc()
    except Exception as e:
        logger.debug(f"record_cache_hit 失败: {e}")


def record_cache_miss(tier: str) -> None:
    """记录缓存未命中"""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        LLM_CACHE_MISSES_TOTAL.labels(tier=tier).inc()
    except Exception as e:
        logger.debug(f"record_cache_miss 失败: {e}")


def set_active_connections(ws: Optional[int] = None, db: Optional[int] = None) -> None:
    """设置活跃连接数

    Args:
        ws: WebSocket 连接数（None 表示不更新）
        db: 数据库连接数（None 表示不更新）
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        if ws is not None:
            WS_CONNECTIONS_ACTIVE.set(ws)
        if db is not None:
            DB_CONNECTIONS_ACTIVE.set(db)
    except Exception as e:
        logger.debug(f"set_active_connections 失败: {e}")


def refresh_uptime() -> None:
    """刷新 uptime 指标"""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        APP_UPTIME_SECONDS.set(time.time() - _START_TIME)
    except Exception:
        pass


def generate_metrics() -> tuple:
    """生成 Prometheus 文本格式指标

    Returns:
        (content_bytes, content_type)
    """
    refresh_uptime()
    content = generate_latest()
    return content, CONTENT_TYPE_LATEST
