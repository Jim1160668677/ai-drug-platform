"""合成模块 — 集成 AiZynthFinder + RDKit SAscore + SCScore

任务 3：药物合成能力扩展。
- route_generator: AiZynthFinder MCTS 合成路线搜索
- feasibility_predictor: SAscore + SCScore 双指标可行性评估
- cost_estimator: 基于步数/规模/难度的成本估算
- synthesis_planner: 编排三者并持久化 SynthesisPlan

所有计算引擎遵循 settings.AIZYNTH_USE_MOCK 开关，测试默认 Mock。
"""
try:
    from .route_generator import SynthesisRouteGenerator
    from .feasibility_predictor import FeasibilityPredictor
    from .cost_estimator import SynthesisCostEstimator
    from .synthesis_planner import SynthesisPlanner
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"部分合成模块导入失败（已降级）: {e}")

__all__ = [
    "SynthesisRouteGenerator",
    "FeasibilityPredictor",
    "SynthesisCostEstimator",
    "SynthesisPlanner",
]
