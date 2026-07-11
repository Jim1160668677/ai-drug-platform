"""工作流服务 — 反馈闭环 + 流水线管理 + Nextflow 调度

设计来源：repowiki/zh/content/数据平台/数据处理流水线/
"""
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "FeedbackLoop", "ExperimentTracker", "LimsImporter",
    "PipelineManager", "NextflowRunner",
]

try:
    from app.services.workflow.feedback_loop import (
        FeedbackLoop, ExperimentTracker, LimsImporter,
    )
except ImportError as e:
    logger.warning(f"feedback_loop 导入失败: {e}")
    FeedbackLoop = ExperimentTracker = LimsImporter = None  # type: ignore

try:
    from app.services.workflow.pipeline_manager import PipelineManager
except ImportError as e:
    logger.warning(f"pipeline_manager 导入失败: {e}")
    PipelineManager = None  # type: ignore

try:
    from app.services.workflow.nextflow_runner import NextflowRunner
except ImportError as e:
    logger.warning(f"nextflow_runner 导入失败: {e}")
    NextflowRunner = None  # type: ignore
