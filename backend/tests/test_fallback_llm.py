"""智谱 GLM 降级链路单元测试

覆盖范围：
- QualityAssessor: 质量评估（空内容/HTTP错误/超时/网络异常/内容过短/健康响应）
- ModelPerformanceMonitor: 滚动窗口指标（记录/健康判断/快照/重置）
- FallbackLLMClient: 降级包装器（主模型成功/主模型失败→备用成功/双失败/降级关闭/流式）
- SwitchLogger: 日志持久化（成功写入/DB失败优雅降级）
- ModelSwitchLog: ORM 模型验证
"""
import asyncio
import uuid
from datetime import datetime
from typing import AsyncIterator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.base import LLMClient
from app.core.llm.fallback import (
    AssessmentResult,
    FallbackLLMClient,
    QualityAssessor,
)
from app.core.llm.performance import ModelPerformanceMonitor
from app.core.llm.switch_logger import SwitchLogger
from app.models.model_switch_log import ModelSwitchLog, SwitchTriggerType


# ========== 测试用 Mock 客户端 ==========

class FakeLLMClient(LLMClient):
    """可控的 LLM 客户端 — 返回预设响应"""

    def __init__(self, response: dict, model_name: str = "test-model", raise_exc=None):
        self.response = response
        self.default_model = model_name
        self.raise_exc = raise_exc
        self.call_count = 0

    async def chat(self, messages: List[dict], model: str = None, **kwargs) -> dict:
        self.call_count += 1
        if self.raise_exc:
            raise self.raise_exc
        return self.response.copy()

    async def stream_chat(self, messages, model=None, **kwargs) -> AsyncIterator[Dict]:
        self.call_count += 1
        if self.raise_exc:
            raise self.raise_exc
        content = self.response.get("content", "")
        if content.startswith("[LLM"):
            yield {"type": "error", "content": content}
        else:
            yield {"type": "token", "content": content}
            yield {"type": "done", "content": content, "usage": {}, "model": self.default_model}

    async def embed(self, text: str) -> List[float]:
        self.call_count += 1
        return [0.1, 0.2, 0.3]


def _healthy_response(content="这是一段足够长的健康响应内容，用于测试正常场景。"):
    return {
        "content": content,
        "model": "agnes-2.0-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "duration_sec": 1.0,
        "references": [],
        "code": None,
    }


def _empty_response():
    return {"content": "", "model": "agnes-2.0-flash", "usage": {}, "duration_sec": 0.5}


def _http_error_response(status=500):
    return {"content": f"[LLM HTTP {status}] Internal Server Error", "model": "agnes-2.0-flash", "usage": {}, "duration_sec": 0.5}


def _timeout_response():
    return {"content": "[LLM 调用超时] TimeoutException: timed out", "model": "agnes-2.0-flash", "usage": {}, "duration_sec": 60.0}


def _network_error_response():
    return {"content": "[LLM 调用失败] ConnectionError: connection refused", "model": "agnes-2.0-flash", "usage": {}, "duration_sec": 0.3}


def _short_response():
    return {"content": "短", "model": "agnes-2.0-flash", "usage": {}, "duration_sec": 0.5}


def _zhipu_response():
    return {
        "content": "智谱GLM-4.7-Flash的备用响应内容，足够长以通过质量检查。",
        "model": "glm-4.7-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 25, "total_tokens": 35},
        "duration_sec": 0.8,
    }


# ========== QualityAssessor 测试 ==========

class TestQualityAssessor:
    """质量评估器测试"""

    def test_empty_content_triggers_fallback(self):
        a = QualityAssessor()
        r = a.assess(_empty_response())
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.EMPTY_CONTENT

    def test_http_error_triggers_fallback(self):
        a = QualityAssessor()
        r = a.assess(_http_error_response(500))
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.HTTP_ERROR
        assert r.http_status == 500

    def test_http_4xx_triggers_fallback(self):
        a = QualityAssessor()
        r = a.assess(_http_error_response(429))
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.HTTP_ERROR
        assert r.http_status == 429

    def test_timeout_triggers_fallback(self):
        a = QualityAssessor()
        r = a.assess(_timeout_response())
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.TIMEOUT

    def test_network_error_triggers_fallback(self):
        a = QualityAssessor()
        r = a.assess(_network_error_response())
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.NETWORK_ERROR

    def test_short_content_triggers_fallback(self):
        a = QualityAssessor(min_content_chars=20)
        r = a.assess(_short_response())
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.QUALITY_LOW

    def test_healthy_response_no_fallback(self):
        a = QualityAssessor()
        r = a.assess(_healthy_response())
        assert r.is_low_quality is False
        assert r.reason == ""

    def test_empty_retry_disabled(self):
        a = QualityAssessor(retry_on_empty=False)
        r = a.assess(_empty_response())
        assert r.is_low_quality is False

    def test_http_retry_disabled(self):
        a = QualityAssessor(retry_on_http_error=False)
        r = a.assess(_http_error_response(500))
        assert r.is_low_quality is False

    def test_timeout_retry_disabled(self):
        a = QualityAssessor(retry_on_timeout=False)
        r = a.assess(_timeout_response())
        assert r.is_low_quality is False

    def test_none_content_treated_as_empty(self):
        a = QualityAssessor()
        r = a.assess({"content": None, "model": "test"})
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.EMPTY_CONTENT

    def test_whitespace_only_content_triggers_empty(self):
        a = QualityAssessor()
        r = a.assess({"content": "   \n  \t  ", "model": "test"})
        assert r.is_low_quality is True
        assert r.trigger_type == SwitchTriggerType.EMPTY_CONTENT


# ========== ModelPerformanceMonitor 测试 ==========

class TestModelPerformanceMonitor:
    """性能监控器测试"""

    def test_record_success(self):
        m = ModelPerformanceMonitor(window_size=10)
        m.record("model-a", success=True, latency_sec=1.0)
        m.record("model-a", success=True, latency_sec=2.0)
        metrics = m.get_metrics("model-a")
        assert metrics["total"] == 2
        assert metrics["successes"] == 2
        assert metrics["failures"] == 0
        assert metrics["success_rate"] == 1.0

    def test_record_failure(self):
        m = ModelPerformanceMonitor(window_size=10)
        m.record("model-a", success=False, latency_sec=0.5, error="timeout")
        metrics = m.get_metrics("model-a")
        assert metrics["failures"] == 1
        assert metrics["success_rate"] == 0.0
        assert metrics["last_error"] == "timeout"

    def test_is_healthy_cold_start(self):
        m = ModelPerformanceMonitor()
        # 样本数 < 5 时视为健康
        for _ in range(3):
            m.record("cold-model", success=False, latency_sec=0.1)
        assert m.is_healthy("cold-model") is True

    def test_is_healthy_low_success_rate(self):
        m = ModelPerformanceMonitor(window_size=100, success_rate_threshold=0.7)
        for _ in range(4):
            m.record("bad-model", success=False, latency_sec=0.1)
        m.record("bad-model", success=True, latency_sec=0.1)
        # 5 samples, 1 success = 0.2 < 0.7
        assert m.is_healthy("bad-model") is False

    def test_is_healthy_high_latency(self):
        m = ModelPerformanceMonitor(
            window_size=100, p95_latency_threshold_sec=1.0
        )
        for _ in range(5):
            m.record("slow-model", success=True, latency_sec=5.0)
        assert m.is_healthy("slow-model") is False

    def test_is_healthy_all_good(self):
        m = ModelPerformanceMonitor()
        for _ in range(5):
            m.record("good-model", success=True, latency_sec=0.5)
        assert m.is_healthy("good-model") is True

    def test_get_metrics_none_for_unknown(self):
        m = ModelPerformanceMonitor()
        assert m.get_metrics("unknown") is None

    def test_get_health_snapshot(self):
        m = ModelPerformanceMonitor()
        for _ in range(5):
            m.record("good", success=True, latency_sec=0.3)
        snap = m.get_health_snapshot()
        assert "models" in snap
        assert "healthy_models" in snap
        assert "unhealthy_models" in snap
        assert "good" in snap["healthy_models"]

    def test_reset_single_model(self):
        m = ModelPerformanceMonitor()
        m.record("a", success=True, latency_sec=0.1)
        m.record("b", success=True, latency_sec=0.1)
        m.reset("a")
        assert m.get_metrics("a") is None
        assert m.get_metrics("b") is not None

    def test_reset_all(self):
        m = ModelPerformanceMonitor()
        m.record("a", success=True, latency_sec=0.1)
        m.record("b", success=True, latency_sec=0.1)
        m.reset()
        assert m.get_metrics("a") is None
        assert m.get_metrics("b") is None

    def test_window_size_limits_latencies(self):
        m = ModelPerformanceMonitor(window_size=5)
        for i in range(20):
            m.record("m", success=True, latency_sec=float(i))
        metrics = m.get_metrics("m")
        # latencies deque maxlen=5, but successes accumulate
        assert len(m._metrics["m"].latencies) == 5

    def test_success_rate_no_samples(self):
        m = ModelPerformanceMonitor()
        # 无样本时成功率为 1.0（乐观默认）
        m._get_or_create("empty")
        metrics = m.get_metrics("empty")
        assert metrics["success_rate"] == 1.0


# ========== FallbackLLMClient 测试 ==========

class TestFallbackLLMClient:
    """降级客户端测试"""

    def _make_client(self, primary_response, fallback_response=None,
                     fallback_enabled=True, primary_exc=None):
        primary = FakeLLMClient(primary_response, "agnes-2.0-flash", raise_exc=primary_exc)
        fallback = FakeLLMClient(
            fallback_response or _zhipu_response(), "glm-4.7-flash"
        )
        monitor = ModelPerformanceMonitor()
        switch_logger = SwitchLogger()
        switch_logger.disable()  # 测试中不写 DB
        client = FallbackLLMClient(
            primary_client=primary,
            fallback_client=fallback,
            performance_monitor=monitor,
            switch_logger=switch_logger,
            fallback_enabled=fallback_enabled,
        )
        return client, primary, fallback, monitor

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self):
        client, primary, fallback, _ = self._make_client(_healthy_response())
        result = await client.chat([{"role": "user", "content": "test"}])
        assert result["content"] == _healthy_response()["content"]
        assert primary.call_count == 1
        assert fallback.call_count == 0  # 备用未被调用

    @pytest.mark.asyncio
    async def test_primary_empty_fallback_succeeds(self):
        client, primary, fallback, _ = self._make_client(_empty_response())
        result = await client.chat([{"role": "user", "content": "test"}])
        assert "glm-4.7-flash" in result.get("model", "")
        # 空内容触发重试机制：primary 被调用 2 次（初次 + 重试）
        assert primary.call_count == 2
        assert fallback.call_count == 1

    @pytest.mark.asyncio
    async def test_primary_http_error_fallback_succeeds(self):
        client, primary, fallback, _ = self._make_client(_http_error_response(500))
        result = await client.chat([{"role": "user", "content": "test"}])
        assert "智谱" in result["content"]

    @pytest.mark.asyncio
    async def test_primary_timeout_fallback_succeeds(self):
        client, primary, fallback, _ = self._make_client(_timeout_response())
        result = await client.chat([{"role": "user", "content": "test"}])
        assert "智谱" in result["content"]

    @pytest.mark.asyncio
    async def test_primary_short_content_fallback(self):
        client, primary, fallback, _ = self._make_client(_short_response())
        result = await client.chat([{"role": "user", "content": "test"}])
        assert "智谱" in result["content"]

    @pytest.mark.asyncio
    async def test_primary_network_error_fallback(self):
        client, primary, fallback, _ = self._make_client(_network_error_response())
        result = await client.chat([{"role": "user", "content": "test"}])
        assert "智谱" in result["content"]

    @pytest.mark.asyncio
    async def test_both_fail_returns_primary(self):
        # 主模型和备用模型都返回低质量 → 返回主模型的原始响应
        client, primary, fallback, _ = self._make_client(
            _empty_response(), fallback_response=_empty_response()
        )
        result = await client.chat([{"role": "user", "content": "test"}])
        # 备用也失败时返回主模型响应
        assert result["content"] == "" or "智谱" not in result.get("content", "")

    @pytest.mark.asyncio
    async def test_fallback_disabled_returns_primary(self):
        client, primary, fallback, _ = self._make_client(
            _empty_response(), fallback_enabled=False
        )
        result = await client.chat([{"role": "user", "content": "test"}])
        assert result["content"] == ""  # 主模型空响应，未降级
        assert fallback.call_count == 0

    @pytest.mark.asyncio
    async def test_performance_monitor_records_success(self):
        client, primary, fallback, monitor = self._make_client(_healthy_response())
        await client.chat([{"role": "user", "content": "test"}])
        metrics = monitor.get_metrics("agnes-2.0-flash")
        assert metrics["successes"] == 1
        assert metrics["failures"] == 0

    @pytest.mark.asyncio
    async def test_performance_monitor_records_failure_and_fallback(self):
        client, primary, fallback, monitor = self._make_client(_empty_response())
        await client.chat([{"role": "user", "content": "test"}])
        primary_metrics = monitor.get_metrics("agnes-2.0-flash")
        fallback_metrics = monitor.get_metrics("glm-4.7-flash")
        assert primary_metrics["failures"] == 1
        assert fallback_metrics["successes"] == 1

    @pytest.mark.asyncio
    async def test_stream_chat_primary_success(self):
        client, primary, fallback, _ = self._make_client(_healthy_response())
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "test"}]):
            chunks.append(chunk)
        # 应有 token 和 done
        types = [c["type"] for c in chunks]
        assert "token" in types or "done" in types
        assert fallback.call_count == 0

    @pytest.mark.asyncio
    async def test_stream_chat_primary_error_fallback(self):
        client, primary, fallback, _ = self._make_client(_http_error_response(500))
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "test"}]):
            chunks.append(chunk)
        # 主模型流式出错 → 降级到备用
        types = [c["type"] for c in chunks]
        assert "token" in types or "done" in types
        assert fallback.call_count == 1

    @pytest.mark.asyncio
    async def test_embed_delegates_to_primary(self):
        client, primary, fallback, _ = self._make_client(_healthy_response())
        vec = await client.embed("test text")
        assert vec == [0.1, 0.2, 0.3]
        assert primary.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_exception_returns_primary(self):
        # 备用模型抛异常 → 返回主模型响应
        client, primary, fallback, _ = self._make_client(
            _empty_response(),
            fallback_response=_zhipu_response(),
        )
        # 让 fallback.chat 抛异常
        fallback.raise_exc = RuntimeError("Zhipu API down")
        result = await client.chat([{"role": "user", "content": "test"}])
        # 返回主模型的空响应（备用也失败）
        assert result["content"] == ""


# ========== SwitchLogger 测试 ==========

class TestSwitchLogger:
    """切换日志记录器测试"""

    @pytest.mark.asyncio
    async def test_log_switch_disabled_no_op(self):
        sl = SwitchLogger()
        sl.disable()
        # 不应抛异常
        await sl.log_switch(
            from_model="agnes",
            to_model="glm",
            trigger_type=SwitchTriggerType.TIMEOUT,
            reason="test",
        )
        assert sl._enabled is False

    @pytest.mark.asyncio
    async def test_log_switch_db_failure_graceful(self):
        """DB 写入失败时优雅降级，不抛异常"""
        sl = SwitchLogger()
        with patch("app.db.session.async_session_factory") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock(side_effect=Exception("DB down"))
            mock_maker.return_value = mock_session
            # 不应抛异常
            await sl.log_switch(
                from_model="agnes-2.0-flash",
                to_model="glm-4.7-flash",
                trigger_type=SwitchTriggerType.HTTP_ERROR,
                reason="HTTP 500",
                latency_ms=500,
                fallback_succeeded=True,
            )

    @pytest.mark.asyncio
    async def test_log_switch_success(self):
        """成功写入 DB"""
        sl = SwitchLogger()
        mock_log = MagicMock()
        with patch("app.db.session.async_session_factory") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()
            mock_maker.return_value = mock_session
            await sl.log_switch(
                from_model="agnes-2.0-flash",
                to_model="glm-4.7-flash",
                trigger_type=SwitchTriggerType.QUALITY_LOW,
                reason="内容过短",
                latency_ms=300,
                content_length=5,
                fallback_succeeded=True,
                fallback_latency_ms=200,
                performance_metrics={"window_size": 50},
            )
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_switch_string_trigger_type(self):
        """字符串 trigger_type 正确转换"""
        sl = SwitchLogger()
        with patch("app.db.session.async_session_factory") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()
            mock_maker.return_value = mock_session
            await sl.log_switch(
                from_model="a",
                to_model="b",
                trigger_type="timeout",
                reason="test",
            )
            added_obj = mock_session.add.call_args[0][0]
            assert added_obj.trigger_type == SwitchTriggerType.TIMEOUT

    @pytest.mark.asyncio
    async def test_log_switch_invalid_string_trigger_falls_back(self):
        """无效字符串 trigger_type 回退到 MANUAL"""
        sl = SwitchLogger()
        with patch("app.db.session.async_session_factory") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()
            mock_maker.return_value = mock_session
            await sl.log_switch(
                from_model="a",
                to_model="b",
                trigger_type="invalid_type",
                reason="test",
            )
            added_obj = mock_session.add.call_args[0][0]
            assert added_obj.trigger_type == SwitchTriggerType.MANUAL


# ========== ModelSwitchLog 模型测试 ==========

class TestModelSwitchLogModel:
    """ORM 模型验证"""

    def test_switch_trigger_type_enum_values(self):
        assert SwitchTriggerType.QUALITY_LOW.value == "quality_low"
        assert SwitchTriggerType.HTTP_ERROR.value == "http_error"
        assert SwitchTriggerType.TIMEOUT.value == "timeout"
        assert SwitchTriggerType.EMPTY_CONTENT.value == "empty_content"
        assert SwitchTriggerType.NETWORK_ERROR.value == "network_error"
        assert SwitchTriggerType.HEALTH_CHECK.value == "health_check"
        assert SwitchTriggerType.MANUAL.value == "manual"

    def test_model_table_name(self):
        assert ModelSwitchLog.__tablename__ == "model_switch_logs"

    def test_model_creation(self):
        log = ModelSwitchLog(
            from_model="agnes-2.0-flash",
            to_model="glm-4.7-flash",
            trigger_type=SwitchTriggerType.HTTP_ERROR,
            reason="HTTP 500",
            latency_ms=500,
            content_length=0,
            fallback_succeeded=True,
            fallback_latency_ms=300,
        )
        assert log.from_model == "agnes-2.0-flash"
        assert log.to_model == "glm-4.7-flash"
        assert log.trigger_type == SwitchTriggerType.HTTP_ERROR
        assert log.fallback_succeeded is True

    def test_model_repr(self):
        log = ModelSwitchLog(
            from_model="a",
            to_model="b",
            trigger_type=SwitchTriggerType.TIMEOUT,
            reason="test",
        )
        r = repr(log)
        assert "a" in r and "b" in r and "TIMEOUT" in r


# ========== 集成路径测试 ==========

class TestFallbackIntegration:
    """降级链路集成测试 — 验证完整流程"""

    @pytest.mark.asyncio
    async def test_full_fallback_flow_with_logging(self):
        """完整降级流程：主模型失败 → 备用成功 → 日志记录"""
        primary = FakeLLMClient(_http_error_response(503), "agnes-2.0-flash")
        fallback = FakeLLMClient(_zhipu_response(), "glm-4.7-flash")
        monitor = ModelPerformanceMonitor()
        switch_logger = SwitchLogger()

        # Mock DB session
        with patch("app.db.session.async_session_factory") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()
            mock_maker.return_value = mock_session

            client = FallbackLLMClient(
                primary_client=primary,
                fallback_client=fallback,
                performance_monitor=monitor,
                switch_logger=switch_logger,
                fallback_enabled=True,
            )
            result = await client.chat([{"role": "user", "content": "test"}])

            # 验证返回备用模型响应
            assert "智谱" in result["content"]
            # 验证日志被写入
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()
            # 验证性能指标
            assert monitor.get_metrics("agnes-2.0-flash")["failures"] == 1
            assert monitor.get_metrics("glm-4.7-flash")["successes"] == 1

    @pytest.mark.asyncio
    async def test_consecutive_failures_monitored(self):
        """连续失败 → 性能监控记录所有失败"""
        primary = FakeLLMClient(_empty_response(), "agnes-2.0-flash")
        fallback = FakeLLMClient(_zhipu_response(), "glm-4.7-flash")
        monitor = ModelPerformanceMonitor()
        switch_logger = SwitchLogger()
        switch_logger.disable()

        client = FallbackLLMClient(
            primary_client=primary,
            fallback_client=fallback,
            performance_monitor=monitor,
            switch_logger=switch_logger,
        )
        # 连续 3 次调用
        for _ in range(3):
            await client.chat([{"role": "user", "content": "test"}])

        metrics = monitor.get_metrics("agnes-2.0-flash")
        assert metrics["failures"] == 3
        assert metrics["success_rate"] == 0.0
        # 3 次失败后模型不健康（但需要 >= 5 样本，所以还是健康）
        assert monitor.is_healthy("agnes-2.0-flash") is True  # 冷启动保护
