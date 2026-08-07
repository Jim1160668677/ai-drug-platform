"""模型性能监控 — 滚动窗口指标驱动降级触发条件优化

设计要点：
- 单例模式（get_performance_monitor），全进程共享同一份指标
- 每个模型维护独立的滚动窗口（collections.deque(maxlen=window_size)）
- 指标：成功率、P95 延迟、样本数、最近一次错误
- is_healthy() 综合判断：成功率 >= 阈值 且 P95 延迟 <= 阈值
"""
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """单个模型的滚动窗口指标"""

    model_name: str
    successes: int = 0
    failures: int = 0
    latencies: Deque[float] = field(default_factory=deque)
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        """成功率（0.0-1.0）；无样本时返回 1.0（乐观默认，避免冷启动误降级）"""
        if self.total == 0:
            return 1.0
        return self.successes / self.total

    @property
    def p95_latency_sec(self) -> float:
        """P95 延迟（秒）；无样本时返回 0.0"""
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = max(0, int(0.95 * len(sorted_lat)) - 1)
        return sorted_lat[idx]

    def to_dict(self) -> dict:
        """序列化为可 JSON 持久化的字典"""
        return {
            "model_name": self.model_name,
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 4),
            "p95_latency_sec": round(self.p95_latency_sec, 3),
            "avg_latency_sec": round(
                sum(self.latencies) / len(self.latencies), 3
            ) if self.latencies else 0.0,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
        }


class ModelPerformanceMonitor:
    """模型性能监控器 — 滚动窗口指标追踪（线程安全）"""

    def __init__(self, window_size=None, success_rate_threshold=None, p95_latency_threshold_sec=None):
        self.window_size = window_size or settings.LLM_HEALTH_ROLLING_WINDOW
        self.success_rate_threshold = (
            success_rate_threshold if success_rate_threshold is not None
            else settings.LLM_HEALTH_SUCCESS_RATE_THRESHOLD
        )
        self.p95_latency_threshold_sec = (
            p95_latency_threshold_sec if p95_latency_threshold_sec is not None
            else settings.LLM_HEALTH_LATENCY_P95_THRESHOLD_SEC
        )
        self._metrics: Dict[str, ModelMetrics] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, model_name: str) -> ModelMetrics:
        with self._lock:
            if model_name not in self._metrics:
                self._metrics[model_name] = ModelMetrics(
                    model_name=model_name,
                    latencies=deque(maxlen=self.window_size),
                )
            return self._metrics[model_name]

    def record(self, model_name, success, latency_sec, error=None):
        """记录一次模型调用的结果"""
        metrics = self._get_or_create(model_name)
        with self._lock:
            if success:
                metrics.successes += 1
            else:
                metrics.failures += 1
                if error:
                    metrics.last_error = error
                    metrics.last_error_time = time.time()
            metrics.latencies.append(latency_sec)
            if metrics.total > self.window_size * 2:
                ratio = self.window_size / metrics.total
                metrics.successes = int(metrics.successes * ratio)
                metrics.failures = int(metrics.failures * ratio)

    def is_healthy(self, model_name: str) -> bool:
        """判断模型是否健康（样本数<5时视为健康，避免冷启动误判）"""
        metrics = self._metrics.get(model_name)
        if metrics is None or metrics.total < 5:
            return True
        if metrics.success_rate < self.success_rate_threshold:
            return False
        if metrics.p95_latency_sec > self.p95_latency_threshold_sec:
            return False
        return True

    def get_metrics(self, model_name: str) -> Optional[dict]:
        metrics = self._metrics.get(model_name)
        if metrics is None:
            return None
        return metrics.to_dict()

    def get_all_metrics(self) -> Dict[str, dict]:
        with self._lock:
            return {name: m.to_dict() for name, m in self._metrics.items()}

    def get_health_snapshot(self) -> dict:
        """获取健康度总览（供 API 端点返回）"""
        all_metrics = self.get_all_metrics()
        return {
            "window_size": self.window_size,
            "success_rate_threshold": self.success_rate_threshold,
            "p95_latency_threshold_sec": self.p95_latency_threshold_sec,
            "models": all_metrics,
            "healthy_models": [n for n in all_metrics if self.is_healthy(n)],
            "unhealthy_models": [n for n in all_metrics if not self.is_healthy(n)],
        }

    def reset(self, model_name: Optional[str] = None) -> None:
        """重置指标（供测试使用）"""
        with self._lock:
            if model_name:
                self._metrics.pop(model_name, None)
            else:
                self._metrics.clear()


_monitor_instance: Optional[ModelPerformanceMonitor] = None
_monitor_lock = threading.Lock()


def get_performance_monitor() -> ModelPerformanceMonitor:
    """获取全局 ModelPerformanceMonitor 单例"""
    global _monitor_instance
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = ModelPerformanceMonitor()
    return _monitor_instance
