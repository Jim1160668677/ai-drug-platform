"""统一智能系统服务层 — 融合 AI 问答 / 科学推理 / Agent 工作台

架构来源：Nature Co-Scientist 论文（s41586-026-10644-y）+ karpathy/autoresearch 自主实验循环理念

6 层架构：
- L2 意图路由层：IntentRouter（keyword + LLM 二级）
- L3 统一编排层：UnifiedOrchestrator（融合 LLMOrchestrator + Supervisor + AgentEngine）
- L5 数据/记忆层：ContextMemoryStore / ReasoningTraceStore

参考资源：
- https://www.nature.com/articles/s41586-026-10644-y （Co-Scientist 论文）
- https://github.com/karpathy/autoresearch （自主实验循环理念，见 REFERENCES.md）
"""
from app.services.intelligence.context_store import ContextMemoryStore
from app.services.intelligence.trace_store import ReasoningTraceStore
from app.services.intelligence.intent_router import IntentRouter, IntentResult
from app.services.intelligence.orchestrator import UnifiedOrchestrator
from app.services.intelligence.channels.chat import ChatChannel
from app.services.intelligence.channels.reasoning import ReasoningChannel
from app.services.intelligence.channels.agent import AgentChannel
from app.services.intelligence.evidence_collector import EvidenceCollector, EvidenceBundle
from app.services.intelligence.reasoning_runner import ReasoningRunner
from app.services.intelligence.analysis_service import AnalysisService
from app.services.intelligence.multimodal_normalizer import MultimodalNormalizer, MultimodalContent
from app.services.intelligence.vision_llm_client import VisionLLMClient

__all__ = [
    "ContextMemoryStore",
    "ReasoningTraceStore",
    "IntentRouter",
    "IntentResult",
    "UnifiedOrchestrator",
    "ChatChannel",
    "ReasoningChannel",
    "AgentChannel",
    # 方向 A：管道嵌入+追溯
    "EvidenceCollector",
    "EvidenceBundle",
    "ReasoningRunner",
    "AnalysisService",
    # 方向 C：多模态+规则引擎
    "MultimodalNormalizer",
    "MultimodalContent",
    "VisionLLMClient",
]
