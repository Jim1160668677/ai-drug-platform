"""Co-Scientist 多智能体科学推理引擎

基于 Nature 论文 Co-Scientist 的多智能体架构，模拟科学研究流程：
- 多智能体协作（Generation/Reflection/Ranking/Proximity/Evolution/MetaReview）
- 科学辩论机制（自博弈正反方辩论）
- Elo 锦标赛排名
- 假设进化策略（Enhancement/Combination/Simplification）
- 专家反馈循环
- 测试时计算缩放
"""
from app.services.coscientist.feedback import FeedbackProcessor
from app.services.coscientist.progress import ProgressTracker
from app.services.coscientist.supervisor import CoScientistResult, Supervisor

__all__ = [
    "Supervisor",
    "CoScientistResult",
    "ProgressTracker",
    "FeedbackProcessor",
]