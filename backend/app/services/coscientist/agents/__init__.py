"""Co-Scientist 智能体模块

导出 6 个专用 Agent + BaseAgent。
每个 Agent 封装特定职责，通过 BaseAgent.quick() 调用 LLM。
"""
from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.evolution import EvolutionAgent
from app.services.coscientist.agents.generation import GenerationAgent
from app.services.coscientist.agents.meta_review import MetaReviewAgent
from app.services.coscientist.agents.proximity import ProximityAgent
from app.services.coscientist.agents.ranking import RankingAgent
from app.services.coscientist.agents.reflection import ReflectionAgent

__all__ = [
    "BaseAgent",
    "GenerationAgent",
    "ReflectionAgent",
    "RankingAgent",
    "ProximityAgent",
    "EvolutionAgent",
    "MetaReviewAgent",
]