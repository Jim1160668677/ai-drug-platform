"""LLM 降级与性能监控模块

智谱 GLM-4.7-Flash 作为 Agnes 大模型的备用模型，实现：
- 自动模型切换（质量不达标/故障时无缝切换）
- 切换日志持久化（时间/原因/性能指标）
- 滚动窗口性能监控（驱动触发条件优化）
"""
from app.core.llm.fallback import FallbackLLMClient, QualityAssessor
from app.core.llm.performance import ModelPerformanceMonitor, get_performance_monitor
from app.core.llm.switch_logger import SwitchLogger

__all__ = [
    "FallbackLLMClient",
    "QualityAssessor",
    "ModelPerformanceMonitor",
    "get_performance_monitor",
    "SwitchLogger",
]
