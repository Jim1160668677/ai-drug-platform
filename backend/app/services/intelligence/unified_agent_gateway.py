"""UnifiedAgentGateway — 统一智能Agent网关

核心设计:
1. 单一入口: chat(session_id, message, user, project_id, capability_hint)
2. 意图路由: 根据用户输入自动判断走 QA/Reasoning/Agent
3. 主动引导: 每次响应后附带 suggested_next_actions
4. 会话连续: 跨模式共享上下文

能力类型 (CapabilityType):
- qa: 简单问答 (快速响应)
- reasoning: 科学推理 (深度分析) 
- agent: 工具执行 (Agent工作台)
- auto: 自动判断 (默认)
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


class CapabilityType(str, Enum):
    QA = "qa"
    REASONING = "reasoning"
    AGENT = "agent"
    AUTO = "auto"


class IntentClassifier:
    """轻量意图分类器 - 基于规则+LLM的二级分类
    
    第一级: 关键词匹配 (快速判断)
    第二级: LLM分类 (复杂场景)
    """
    
    AGENT_KEYWORDS = [
        "执行", "运行", "分析", "处理", "计算", "预测",
        "检索", "搜索", "查询", "下载", "提取",
        "docking", "分子对接", "分子设计", "靶点发现",
        "pipeline", "流水线", "任务", "步骤",
        "工具", "function", "action", "task", "run",
    ]
    
    REASONING_KEYWORDS = [
        "假设", "机制", "通路", "信号", "调控",
        "为什么", "如何", "原因", "原理", "理论",
        "比较", "对比", "分析", "评估", "预测",
        "clinical", "临床", "patient", "患者",
        "treatment", "治疗", "diagnosis", "诊断",
    ]
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    def classify(self, message: str) -> CapabilityType:
        msg_lower = message.lower()
        
        agent_score = sum(1 for kw in self.AGENT_KEYWORDS if kw.lower() in msg_lower)
        reasoning_score = sum(1 for kw in self.REASONING_KEYWORDS if kw.lower() in msg_lower)
        
        if agent_score >= 2 and agent_score > reasoning_score:
            return CapabilityType.AGENT
        
        if reasoning_score >= 2 and reasoning_score > agent_score:
            return CapabilityType.REASONING
        
        return CapabilityType.QA
    
    async def llm_classify(self, message: str, context: str = "") -> CapabilityType:
        if not self.llm_client:
            return self.classify(message)
        
        return self.classify(message)


class GuidanceGenerator:
    """主动引导生成器 - 基于对话历史建议下一步操作"""
    
    GUIDANCE_TEMPLATES = {
        CapabilityType.QA: [
            {"action": "deep_analysis", "label": "深入分析", "description": "对这个问题进行深度科学分析"},
            {"action": "run_pipeline", "label": "运行流水线", "description": "执行一键药物发现流水线"},
            {"action": "search_literature", "label": "检索文献", "description": "搜索相关科学文献"},
        ],
        CapabilityType.REASONING: [
            {"action": "generate_hypothesis", "label": "生成假设", "description": "基于分析生成科学假设"},
            {"action": "run_validation", "label": "运行验证", "description": "设计验证实验方案"},
            {"action": "find_targets", "label": "发现靶点", "description": "查找相关药物靶点"},
        ],
        CapabilityType.AGENT: [
            {"action": "view_results", "label": "查看结果", "description": "查看当前任务的执行结果"},
            {"action": "refine_query", "label": "优化查询", "description": "调整参数重新执行"},
            {"action": "save_session", "label": "保存会话", "description": "保存当前工作进展"},
        ],
    }
    
    def generate(self, capability: CapabilityType, message_count: int = 0) -> List[Dict[str, Any]]:
        templates = self.GUIDANCE_TEMPLATES.get(capability, self.GUIDANCE_TEMPLATES[CapabilityType.QA])
        
        suggestions = []
        for template in templates:
            suggestion = {
                **template,
                "capability": capability.value,
                "priority": "high" if message_count < 3 else "medium",
            }
            suggestions.append(suggestion)
        
        return suggestions


class UnifiedAgentGateway:
    """统一智能Agent网关
    
    用法:
        gateway = UnifiedAgentGateway(db, llm_client)
        result = await gateway.chat(
            session_id=session.id,
            message="帮我分析EGFR靶点并生成假设",
            user=user,
            project_id="...",
        )
        # result 包含: { response, capability, suggestions, session_id }
    """
    
    def __init__(self, db: AsyncSession, llm_client: Any = None, llm_config: Any = None):
        self.db = db
        self.llm_client = llm_client
        self.llm_config = llm_config
        
        self.intent_classifier = IntentClassifier(llm_client=llm_client)
        self.guidance_generator = GuidanceGenerator()
        
        self._orchestrator = None
        self._qa_orchestrator = None
        self._agent_engine = None
    
    def _get_orchestrator(self):
        if self._orchestrator is None:
            from app.services.intelligence.orchestrator import UnifiedOrchestrator
            self._orchestrator = UnifiedOrchestrator(
                db=self.db,
                llm_client=self.llm_client,
                llm_config=self.llm_config,
            )
        return self._orchestrator
    
    def _get_qa_orchestrator(self):
        if self._qa_orchestrator is None:
            from app.services.llm.orchestrator import LLMOrchestrator
            self._qa_orchestrator = LLMOrchestrator(
                self.db,
                self.llm_client,
                llm_config=self.llm_config,
            )
        return self._qa_orchestrator
    
    def _get_agent_engine(self):
        if self._agent_engine is None:
            from app.services.agent.engine import AgentEngine
            from app.services.agent.tools.registry import get_tool_registry
            from app.services.agent.planner import TaskPlanner
            from app.services.agent.session import SessionManager
            from app.services.agent.progress import ProgressManager
            from app.services.agent.audit import AuditLogger
            from app.services.agent.ratelimit import get_rate_limiter
            from app.services.llm.router import LLMRouter
            from app.services.llm.guardrail import get_guardrail
            
            llm_router = LLMRouter(self.llm_client, self.llm_config)
            registry = get_tool_registry()
            planner = TaskPlanner(llm_router)
            session_mgr = SessionManager(self.db)
            progress = ProgressManager()
            audit = AuditLogger(self.db)
            ratelimit = get_rate_limiter()
            
            self._agent_engine = AgentEngine(
                db=self.db,
                llm_router=llm_router,
                registry=registry,
                planner=planner,
                session_mgr=session_mgr,
                progress=progress,
                audit=audit,
                ratelimit=ratelimit,
                guardrail=get_guardrail(),
            )
        return self._agent_engine
    
    async def chat(
        self,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str] = None,
        capability_hint: Optional[str] = None,
        force_mode: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_time = datetime.now(timezone.utc)

        try:
            if settings.INTELLIGENCE_USE_UNIFIED_ORCHESTRATOR:
                return await self._chat_via_orchestrator(
                    session_id=session_id,
                    message=message,
                    user=user,
                    project_id=project_id,
                    capability_hint=capability_hint,
                    force_mode=force_mode,
                    tier=tier,
                    start_time=start_time,
                )
            
            effective_hint = force_mode or capability_hint
            if effective_hint and effective_hint != CapabilityType.AUTO:
                capability = CapabilityType(effective_hint)
            else:
                capability = self.intent_classifier.classify(message)
            
            logger.info(f"[UnifiedGateway] 意图路由: capability={capability}, message={message[:50]}...")
            
            response_data = await self._dispatch(
                capability=capability,
                session_id=session_id,
                message=message,
                user=user,
                project_id=project_id,
            )
            
            message_count = response_data.get("message_count", 0)
            suggestions = self.guidance_generator.generate(capability, message_count)
            
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = {
                "response": response_data.get("response", response_data),
                "capability": capability.value,
                "suggestions": suggestions,
                "session_id": str(session_id),
                "metadata": {
                    "elapsed_seconds": round(elapsed, 2),
                    "routed_by": capability_hint and "explicit" or "auto",
                    "original_intent": capability.value,
                },
            }
            
            if "references" in response_data:
                result["metadata"]["references"] = response_data["references"]
            if "sources" in response_data:
                result["metadata"]["sources"] = response_data["sources"]
            
            return result
            
        except Exception as e:
            logger.error(f"[UnifiedGateway] 对话失败: {e}", exc_info=True)
            if capability_hint != CapabilityType.QA:
                logger.info("[UnifiedGateway] 降级为QA模式")
                try:
                    qa_result = await self._dispatch(
                        capability=CapabilityType.QA,
                        session_id=session_id,
                        message=message,
                        user=user,
                        project_id=project_id,
                    )
                    return {
                        "response": qa_result.get("response", qa_result),
                        "capability": CapabilityType.QA.value,
                        "suggestions": self.guidance_generator.generate(CapabilityType.QA),
                        "session_id": str(session_id),
                        "metadata": {
                            "elapsed_seconds": round((datetime.now(timezone.utc) - start_time).total_seconds(), 2),
                            "routed_by": "fallback",
                            "original_intent": capability_hint or "auto",
                            "error_detail": str(e),
                        },
                    }
                except Exception as fallback_error:
                    logger.error(f"[UnifiedGateway] 降级也失败: {fallback_error}")
            
            raise
    
    async def _chat_via_orchestrator(
        self,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str],
        capability_hint: Optional[str],
        force_mode: Optional[str],
        tier: Optional[str],
        start_time: datetime,
    ) -> Dict[str, Any]:
        orchestrator = self._get_orchestrator()
        
        effective_force = force_mode or capability_hint
        if effective_force and effective_force in (c.value for c in CapabilityType):
            pass
        else:
            effective_force = None
        
        logger.info(
            "[UnifiedGateway] 委托Orchestrator: session=%s force_mode=%s hint=%s",
            session_id, effective_force, capability_hint,
        )
        
        result = await orchestrator.chat(
            session_id=session_id,
            message=message,
            user=user,
            project_id=project_id,
            force_mode=effective_force,
            tier=tier,
        )
        
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        mode = result.get("mode", "chat")
        capability = CapabilityType(mode) if mode in (c.value for c in CapabilityType) else CapabilityType.QA
        
        suggestions = self.guidance_generator.generate(capability)
        
        response_content = result.get("answer", result)
        
        gateway_result = {
            "response": response_content,
            "capability": capability.value,
            "suggestions": suggestions,
            "session_id": str(session_id),
            "metadata": {
                "elapsed_seconds": round(elapsed, 2),
                "routed_by": "orchestrator",
                "original_intent": capability.value,
                "mode": mode,
                "cost_usd": result.get("cost_usd", 0),
                "duration_sec": result.get("duration_sec", 0),
                "tier": result.get("tier", "standard"),
                "tier_reason": result.get("tier_reason", None),
            },
        }
        
        if "intent" in result:
            gateway_result["metadata"]["intent"] = result["intent"]
        if "references" in result:
            gateway_result["metadata"]["references"] = result["references"]
        if "sources" in result:
            gateway_result["metadata"]["sources"] = result["sources"]
        
        return gateway_result
    
    async def _dispatch(
        self,
        capability: CapabilityType,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        
        if capability == CapabilityType.QA:
            orchestrator = self._get_qa_orchestrator()
            result = await orchestrator.route(
                message=message,
                project_id=project_id,
                tier="fast_screen",
                user=user,
            )
            return {
                "response": result,
                "message_count": 1,
            }
        
        elif capability == CapabilityType.REASONING:
            orchestrator = self._get_orchestrator()
            result = await orchestrator.chat(
                session_id=session_id,
                message=message,
                user=user,
                project_id=project_id,
                force_mode=CapabilityType.REASONING.value,
            )
            return {
                "response": result,
                "message_count": result.get("message_count", 1) if isinstance(result, dict) else 1,
                "references": result.get("references", []) if isinstance(result, dict) else [],
                "sources": result.get("sources", []) if isinstance(result, dict) else [],
            }
        
        elif capability == CapabilityType.AGENT:
            engine = self._get_agent_engine()
            task = await engine.create_task(
                query=message,
                session_id=session_id,
                user=user,
                project_id=project_id,
            )
            return {
                "response": {
                    "type": "agent_task",
                    "task_id": str(task.id),
                    "status": task.status,
                    "message": "Agent任务已创建，请通过WebSocket订阅进度",
                },
                "message_count": 1,
            }
        
        else:
            orchestrator = self._get_qa_orchestrator()
            result = await orchestrator.route(
                message=message,
                project_id=project_id,
                tier="fast_screen",
                user=user,
            )
            return {"response": result, "message_count": 1}
    
    async def get_session_suggestions(self, session_id: UUID) -> List[Dict[str, Any]]:
        return self.guidance_generator.generate(CapabilityType.QA)
    
    async def get_capabilities(self) -> Dict[str, Any]:
        return {
            "capabilities": [
                {
                    "type": CapabilityType.QA.value,
                    "name": "AI问答",
                    "description": "快速回答问题，适合简单查询",
                    "latency_ms": 2000,
                    "cost_level": "low",
                },
                {
                    "type": CapabilityType.REASONING.value,
                    "name": "科学推理",
                    "description": "深度科学分析，多步骤推理",
                    "latency_ms": 10000,
                    "cost_level": "medium",
                },
                {
                    "type": CapabilityType.AGENT.value,
                    "name": "Agent工作台",
                    "description": "执行复杂任务，调用专业工具",
                    "latency_ms": 30000,
                    "cost_level": "high",
                },
            ],
            "auto_routing": True,
            "guidance_enabled": True,
        }
