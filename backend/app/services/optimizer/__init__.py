"""优化器服务 — 治疗方案优化 + 疗效监测 + 动态调整 + 联邦学习

设计来源：repowiki/zh/content/AI引擎与算法/治疗方案优化/
"""
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "TreatmentPlanner", "TreatmentOptimizer", "EfficacyMonitor", "DynamicAdjuster",
    "FederatedLearningService", "FederatedLearner",
]

# 分段导入 — 失败不中断整个包
try:
    from app.services.optimizer.treatment_planner import (
        TreatmentPlanner, TreatmentOptimizer,
    )
except ImportError as e:
    logger.warning(f"treatment_planner 导入失败: {e}")
    TreatmentPlanner = TreatmentOptimizer = None  # type: ignore

try:
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor
except ImportError as e:
    logger.warning(f"efficacy_monitor 导入失败: {e}")
    EfficacyMonitor = None  # type: ignore

try:
    from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
except ImportError as e:
    logger.warning(f"dynamic_adjuster 导入失败: {e}")
    DynamicAdjuster = None  # type: ignore

try:
    from app.services.optimizer.federated_learning import (
        FederatedLearningService, FederatedLearner,
    )
except ImportError as e:
    logger.warning(f"federated_learning 导入失败: {e}")
    FederatedLearningService = FederatedLearner = None  # type: ignore
