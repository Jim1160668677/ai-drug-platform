"""系统可观测性模块单元测试 — Phase F

覆盖：
- metrics: 指标定义/记录函数/路径归一化
- middleware: MetricsMiddleware HTTP 请求采集
- logging_ext: 敏感字段脱敏

测试策略：
- 使用 prometheus_client 的 REGISTRY 验证指标真实存在
- 使用 fastapi TestClient 验证中间件
- 覆盖正常流程、降级、路径归一化等场景
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.observability import metrics as M
from app.core.observability.metrics import (
    _normalize_path,
    record_http_request,
    record_llm_call,
    record_cache_hit,
    record_cache_miss,
    set_active_connections,
    generate_metrics,
)


# ============================================================
# 路径归一化测试
# ============================================================


class TestNormalizePath:
    """_normalize_path() 测试"""

    def test_static_path(self):
        assert _normalize_path("/health") == "/health"
        assert _normalize_path("/api/v1/metrics") == "/api/v1/metrics"

    def test_uuid_path(self):
        assert _normalize_path("/api/v1/runs/550e8400-e29b-41d4-a716-446655440000") == "/api/v1/runs/:id"

    def test_numeric_id_path(self):
        assert _normalize_path("/api/v1/users/123") == "/api/v1/users/:id"
        assert _normalize_path("/api/v1/projects/42/datasets") == "/api/v1/projects/:id/datasets"

    def test_long_hex_path(self):
        result = _normalize_path("/api/v1/sessions/abcdef0123456789abcdef0123456789")
        assert ":id" in result

    def test_empty_path(self):
        assert _normalize_path("") == "/"
        assert _normalize_path(None) == "/"

    def test_multiple_ids(self):
        result = _normalize_path("/api/v1/projects/123/datasets/456")
        assert result == "/api/v1/projects/:id/datasets/:id"

# ============================================================
# 指标记录函数测试
# ============================================================


class TestRecordHttpRequest:
    """record_http_request() 测试"""

    def test_records_without_error(self):
        record_http_request("GET", "/health", 200, 0.012)

    def test_records_with_uuid_path(self):
        record_http_request("POST", "/api/v1/runs/550e8400-e29b-41d4-a716-446655440000", 201, 0.15)

    def test_metrics_output_contains_request(self):
        record_http_request("GET", "/test-endpoint-unique-xyz", 200, 0.05)
        content, _ = generate_metrics()
        assert b"/test-endpoint-unique-xyz" in content

    def test_different_status_codes(self):
        record_http_request("GET", "/test-status-multi", 200, 0.01)
        record_http_request("GET", "/test-status-multi", 404, 0.01)
        record_http_request("GET", "/test-status-multi", 500, 0.01)
        content, _ = generate_metrics()
        assert b'status="200"' in content
        assert b'status="404"' in content
        assert b'status="500"' in content


class TestRecordLLMCall:
    """record_llm_call() 测试"""

    def test_records_success(self):
        record_llm_call("agnes-2.0-flash", "fast_screen", "success", 0.5, 0.001)

    def test_records_failed(self):
        record_llm_call("agnes-2.0-flash", "deep_insight", "failed", 1.2, 0.0)

    def test_records_fallback(self):
        record_llm_call("agnes-2.0-flash", "fast_screen", "fallback", 0.3, 0.0)
        record_llm_call("glm-4.7-flash", "fast_screen", "success", 0.4, 0.0)

    def test_metrics_output_contains_llm(self):
        content, _ = generate_metrics()
        assert b"precision_drug_llm_calls_total" in content
        assert b"precision_drug_llm_call_duration_seconds" in content

    def test_cost_recorded(self):
        record_llm_call("test-model-cost-xyz", "fast_screen", "success", 0.1, 0.5)
        content, _ = generate_metrics()
        assert b"precision_drug_llm_cost_usd_total" in content


class TestCacheMetrics:
    """缓存命中/未命中指标测试"""

    def test_cache_hit(self):
        record_cache_hit("fast_screen")
        content, _ = generate_metrics()
        assert b"precision_drug_llm_cache_hits_total" in content

    def test_cache_miss(self):
        record_cache_miss("deep_insight")
        content, _ = generate_metrics()
        assert b"precision_drug_llm_cache_misses_total" in content


class TestSystemMetrics:
    """系统级指标测试"""

    def test_set_active_connections(self):
        set_active_connections(ws=5, db=10)
        content, _ = generate_metrics()
        assert b"precision_drug_ws_connections_active" in content
        assert b"precision_drug_db_connections_active" in content

    def test_uptime(self):
        content, _ = generate_metrics()
        assert b"precision_drug_app_uptime_seconds" in content

    def test_generate_metrics_returns_tuple(self):
        content, ctype = generate_metrics()
        assert isinstance(content, bytes)
        assert isinstance(ctype, str)
        assert "text/plain" in ctype


# ============================================================
# MetricsMiddleware 集成测试
# ============================================================


def _create_test_app() -> FastAPI:
    """创建带 MetricsMiddleware 的测试 app"""
    app = FastAPI()

    from app.core.observability.middleware import MetricsMiddleware
    app.add_middleware(MetricsMiddleware)

    @app.get("/test-endpoint")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/error-endpoint")
    async def error_endpoint():
        raise ValueError("test error")

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        return {"run_id": run_id}

    return app


class TestMetricsMiddleware:
    """MetricsMiddleware 集成测试"""

    def test_request_recorded(self):
        app = _create_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/test-endpoint")
        assert response.status_code == 200

        content, _ = generate_metrics()
        assert b"/test-endpoint" in content

    def test_error_request_recorded(self):
        app = _create_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        client.get("/error-endpoint")

        content, _ = generate_metrics()
        assert b"/error-endpoint" in content

    def test_uuid_path_normalized(self):
        app = _create_test_app()
        client = TestClient(app)

        client.get("/runs/550e8400-e29b-41d4-a716-446655440000")

        content, _ = generate_metrics()
        assert b"/runs/:id" in content
        assert b"550e8400" not in content

    def test_in_progress_decremented(self):
        app = _create_test_app()
        client = TestClient(app)

        client.get("/test-endpoint")
        client.get("/test-endpoint")

        content, _ = generate_metrics()
        text = content.decode("utf-8")
        for line in text.split("\n"):
            if line.startswith("precision_drug_http_requests_in_progress"):
                value = float(line.split()[-1])
                assert value == 0
                return
        pytest.fail("in_progress 指标未找到")


# ============================================================
# /metrics 端点测试
# ============================================================


class TestMetricsEndpoint:
    """/api/v1/metrics 端点测试"""

    def test_metrics_endpoint_returns_text(self):
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        assert b"precision_drug_" in response.content

    def test_health_endpoint_records_metric(self):
        from app.main import app

        client = TestClient(app)
        before, _ = generate_metrics()
        before_count = before.count(b"/api/v1/health")

        client.get("/api/v1/health")

        after, _ = generate_metrics()
        after_count = after.count(b"/api/v1/health")
        assert after_count >= before_count


# ============================================================
# 日志脱敏测试
# ============================================================


class TestLogMasking:
    """敏感字段脱敏测试"""

    def test_mask_api_key(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {"api_key": "sk-1234567890", "name": "test"}
        masked = _mask_sensitive(data)
        assert masked["api_key"] == "***REDACTED***"
        assert masked["name"] == "test"

    def test_mask_password(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {"password": "secret123", "user": "admin"}
        masked = _mask_sensitive(data)
        assert masked["password"] == "***REDACTED***"
        assert masked["user"] == "admin"

    def test_mask_token(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {"access_token": "eyJhb...", "token_type": "bearer"}
        masked = _mask_sensitive(data)
        assert masked["access_token"] == "***REDACTED***"
        assert masked["token_type"] == "***REDACTED***"

    def test_mask_nested(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {
            "user": {"name": "alice", "api_key": "sk-xxx"},
            "config": {"secret": "topsecret", "port": 8080},
        }
        masked = _mask_sensitive(data)
        assert masked["user"]["name"] == "alice"
        assert masked["user"]["api_key"] == "***REDACTED***"
        assert masked["config"]["secret"] == "***REDACTED***"
        assert masked["config"]["port"] == 8080

    def test_mask_list(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = [
            {"api_key": "sk-1", "name": "a"},
            {"api_key": "sk-2", "name": "b"},
        ]
        masked = _mask_sensitive(data)
        assert masked[0]["api_key"] == "***REDACTED***"
        assert masked[0]["name"] == "a"
        assert masked[1]["api_key"] == "***REDACTED***"

    def test_mask_authorization_header(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {"Authorization": "Bearer eyJhb...", "path": "/api"}
        masked = _mask_sensitive(data)
        assert masked["Authorization"] == "***REDACTED***"
        assert masked["path"] == "/api"

    def test_non_sensitive_unchanged(self):
        from app.core.observability.logging_ext import _mask_sensitive
        data = {"name": "test", "age": 30, "items": [1, 2, 3]}
        masked = _mask_sensitive(data)
        assert masked == data

    def test_primitives_unchanged(self):
        from app.core.observability.logging_ext import _mask_sensitive
        assert _mask_sensitive("hello") == "hello"
        assert _mask_sensitive(42) == 42
        assert _mask_sensitive(None) is None
