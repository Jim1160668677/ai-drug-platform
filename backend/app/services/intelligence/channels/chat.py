"""ChatChannel — 单/多轮对话通道

设计来源：Nature Co-Scientist 论文的「自然语言接口」+ 现有 LLMOrchestrator 复用。

核心能力：
1. 复用 LLMRouter.complete/stream_complete 调用 LLM
2. 集成 ContextMemoryStore 加载历史上下文（消息历史 + 研究目标 + 数据特征）
3. 集成 ReasoningTraceStore 记录 LLM 调用
4. 可选加载用户基因组上下文（复用 LLMOrchestrator.load_user_genome_context 模式）

autoresearch 整合：类似 autoresearch 将 program.md + 历史实验结果注入 agent 上下文，
本 Channel 将 ContextMemoryStore 的历史记忆注入 LLM 上下文。
"""
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID

from app.core.config import settings
from app.services.intelligence.context_store import ContextMemoryStore
from app.services.intelligence.trace_store import ReasoningTraceStore
from app.models.context_memory import MemoryType

logger = logging.getLogger(__name__)


class ChatChannel:
    """对话通道 — 单/多轮自然语言问答

    用法：
        channel = ChatChannel(llm_client, context_store, trace_store)
        result = await channel.chat(session_id, "什么是 EGFR 靶点？", user)
    """

    def __init__(
        self,
        llm_client: Any,
        context_store: ContextMemoryStore,
        trace_store: ReasoningTraceStore,
        llm_config: Optional[Any] = None,
    ):
        """初始化对话通道

        Args:
            llm_client: LLM 客户端实例（FallbackLLMClient）
            context_store: 上下文记忆存储
            trace_store: 推理追溯存储
            llm_config: 数据库激活的 LLMConfig（可选，用于动态选择模型）
        """
        self.llm_client = llm_client
        self.context_store = context_store
        self.trace_store = trace_store
        self.llm_config = llm_config

    def _select_model(self) -> str:
        """选择模型 — 优先使用数据库配置，回退到 settings"""
        if self.llm_config is not None:
            model = getattr(self.llm_config, "fast_model", None) or getattr(self.llm_config, "test_model", None)
            if model:
                return model
        return settings.LLM_MODEL_FAST

    async def chat(
        self,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str] = None,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """执行对话

        Args:
            session_id: 统一会话 ID
            message: 用户消息
            user: 当前用户对象
            project_id: 项目 ID（可选）
            run_id: 关联的推理运行 ID（可选）

        Returns:
            {answer, mode, cost_usd, duration_sec, model, context_used}
        """
        start = time.time()
        model = self._select_model()

        # 1. 保存用户消息到上下文记忆
        await self.context_store.append_message(
            session_id=session_id,
            role="user",
            content=message,
            token_count=len(message) // 4,
            importance=0.6,
            run_id=run_id,
            project_id=UUID(project_id) if project_id else None,
            user_id=user.id if hasattr(user, "id") else None,
        )

        # 2. 构建上下文提示词（从 ContextMemoryStore 加载历史）
        context_prompt = await self.context_store.build_context_prompt(
            session_id=session_id,
            max_tokens=3000,
        )

        # 3. 构建 LLM 消息
        messages = []
        if context_prompt:
            messages.append({
                "role": "system",
                "content": f"你是 AI 模式精准药物设计系统的智能助手。以下是当前研究上下文：\n\n{context_prompt}",
            })
        else:
            messages.append({
                "role": "system",
                "content": "你是 AI 模式精准药物设计系统的智能助手，帮助用户进行药物研发相关的问答和分析。",
            })
        messages.append({"role": "user", "content": message})

        # 4. 调用 LLM
        usage = {}
        answer = ""
        try:
            from app.services.llm.router import LLMRouter
            router = LLMRouter(self.llm_client)
            response = await router.complete(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=2000,
            )
            answer = response.content if hasattr(response, "content") else str(response)
            usage = getattr(response, "usage", {}) or {}
        except Exception as e:
            logger.error("ChatChannel LLM 调用失败: %s", e)
            answer = f"抱歉，处理您的问题时出现错误：{str(e)}"
            usage = {}

        duration_sec = round(time.time() - start, 3)
        prompt_tokens = usage.get("prompt_tokens", len(message) // 4)
        completion_tokens = usage.get("completion_tokens", len(answer) // 4)

        # 5. 估算成本
        from app.services.llm.orchestrator import _estimate_cost
        from app.models.analysis_job import AnalysisTier
        cost_usd = _estimate_cost(usage, AnalysisTier.FAST_SCREEN, model)

        # 6. 保存助手回复到上下文记忆
        await self.context_store.append_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            token_count=completion_tokens,
            importance=0.5,
            run_id=run_id,
            project_id=UUID(project_id) if project_id else None,
            user_id=user.id if hasattr(user, "id") else None,
        )

        # 7. 写推理追溯
        await self.trace_store.append_llm_call(
            run_id=run_id,
            session_id=session_id,
            agent_name="chat_channel",
            phase=None,
            round_num=None,
            messages=messages,
            response_content=answer,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            duration_sec=duration_sec,
        )

        return {
            "answer": answer,
            "mode": "chat",
            "cost_usd": cost_usd,
            "duration_sec": duration_sec,
            "model": model,
            "context_used": bool(context_prompt),
        }

    async def stream_chat(
        self,
        session_id: UUID,
        message: str,
        user: Any,
        project_id: Optional[str] = None,
    ):
        """流式对话（SSE 生成器）

        Yields:
            str: 流式响应片段
        """
        model = self._select_model()

        # 构建上下文
        context_prompt = await self.context_store.build_context_prompt(
            session_id=session_id, max_tokens=3000
        )
        messages = []
        if context_prompt:
            messages.append({
                "role": "system",
                "content": f"你是 AI 模式精准药物设计系统的智能助手。以下是当前研究上下文：\n\n{context_prompt}",
            })
        else:
            messages.append({
                "role": "system",
                "content": "你是 AI 模式精准药物设计系统的智能助手。",
            })
        messages.append({"role": "user", "content": message})

        # 保存用户消息
        await self.context_store.append_message(
            session_id=session_id,
            role="user",
            content=message,
            token_count=len(message) // 4,
        )

        # 流式调用
        full_answer = ""
        try:
            from app.services.llm.router import LLMRouter
            router = LLMRouter(self.llm_client)
            async for chunk in router.stream_complete(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=2000,
            ):
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_answer += content
                yield content
        except Exception as e:
            logger.error("ChatChannel 流式调用失败: %s", e)
            yield f"错误：{str(e)}"

        # 保存完整回复
        await self.context_store.append_message(
            session_id=session_id,
            role="assistant",
            content=full_answer,
            token_count=len(full_answer) // 4,
        )
