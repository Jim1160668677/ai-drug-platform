"""知识查询工具组 — 2 个工具

工具列表：
- search_literature      文献检索（委托 RAGEngine.retrieve）
- query_knowledge_base   知识库问答（委托 RAGEngine.build_context + LLM）
"""
import logging
from typing import Any, Dict

from app.core.security import UserRole
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


class SearchLiteratureTool(AgentTool):
    """文献检索 — 委托 RAGEngine.retrieve"""

    name = "search_literature"
    description = (
        "从本地知识库检索相关文献。"
        "支持向量检索（ChromaDB）与关键词检索（Jaccard）两种模式。"
        "返回相关文档列表（含相似度评分、元数据）。"
    )
    parameters = [
        ToolParameter("query", "string", "检索查询", required=True),
        ToolParameter("top_k", "integer", "返回结果数（1-20）", required=False, default=5),
        ToolParameter(
            "mode",
            "string",
            "检索模式",
            required=False,
            default="auto",
            enum=["auto", "vector", "jaccard"],
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.llm.rag import RAGEngine

        query = params["query"]
        top_k = min(max(params.get("top_k", 5), 1), 20)
        # mode 参数保留用于 LLM 工具描述兼容；retrieve() 内部自动先向量检索，
        # 失败则降级 Jaccard，不接受 mode 参数。

        try:
            engine = RAGEngine(ctx.db)
            # retrieve() 实际返回 List[Dict]，兼容 namedtuple/dict 形式
            result = await engine.retrieve(query=query, top_k=top_k)

            # 兼容三种返回形式：
            # 1. List[Dict]（实际实现）→ 直接用，retrieval_mode 自动
            # 2. namedtuple(documents, retrieval_mode)（测试 mock）→ 取属性
            # 3. dict(documents, retrieval_mode)（兼容旧 mock）→ 取键
            if isinstance(result, list):
                docs = result
                retrieval_mode = "auto"
            elif hasattr(result, "documents"):
                docs = result.documents or []
                retrieval_mode = getattr(result, "retrieval_mode", "auto")
            elif isinstance(result, dict):
                docs = result.get("documents", [])
                retrieval_mode = result.get("retrieval_mode", "auto")
            else:
                docs = []
                retrieval_mode = "auto"

            return ToolResult.ok(
                data={
                    "query": query,
                    "documents": docs,
                    "total": len(docs),
                    "retrieval_mode": retrieval_mode,
                },
                display={
                    "type": "literature_list",
                    "payload": {"documents": docs[:top_k]},
                },
            )
        except Exception as e:
            logger.error(f"search_literature 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class QueryKnowledgeBaseTool(AgentTool):
    """知识库问答 — 委托 RAGEngine.build_context"""

    name = "query_knowledge_base"
    description = (
        "对知识库进行问答。"
        "先检索相关文献，再用 LLM 基于检索结果生成答案。"
        "适用于医学/药学/生物知识类问题。"
    )
    parameters = [
        ToolParameter("question", "string", "问题", required=True),
        ToolParameter("top_k", "integer", "检索文献数", required=False, default=5),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """知识库问答 — 检索 + LLM 生成答案

        修复说明：
        - retrieve() 返回 List[Dict]（不是带 .documents 属性的对象）
        - build_context() 返回 str（augmented prompt，不是带 answer 的 dict）
        - 需要额外调用 LLM 基于上下文生成答案
        """
        from app.services.llm.rag import RAGEngine
        from app.core.deps import get_llm_client_with_config

        question = params["question"]
        top_k = min(max(params.get("top_k", 5), 1), 20)

        try:
            # 获取 LLM 客户端（用于生成答案）
            llm_client = await get_llm_client_with_config(ctx.db)
            engine = RAGEngine(ctx.db, llm_client=llm_client)

            # 1. 检索：retrieve 返回 List[Dict]，直接使用
            docs = await engine.retrieve(query=question, top_k=top_k)
            # 兼容：如果返回了带 .documents 的对象，取 .documents
            if hasattr(docs, "documents"):
                docs = docs.documents
            if not isinstance(docs, list):
                docs = []

            # 2. 构造增强 prompt / 获取答案
            # build_context 实际返回 str（augmented prompt），但兼容旧契约/测试
            # mock 返回 dict(answer=...) 的情况
            augmented = await engine.build_context(question, docs)

            if isinstance(augmented, dict) and "answer" in augmented:
                # 旧契约 / 测试 mock：build_context 直接返回答案 dict
                answer = augmented["answer"]
            elif isinstance(augmented, str):
                # 实际行为：返回 augmented prompt，需调用 LLM 生成答案
                if docs:
                    try:
                        response = await llm_client.chat(
                            messages=[{"role": "user", "content": augmented}]
                        )
                        answer = response.get("content", "") if isinstance(response, dict) else str(response)
                        if not answer:
                            answer = f"检索到 {len(docs)} 篇相关文献，但 LLM 未返回内容。"
                    except Exception as e:
                        logger.warning(f"LLM 生成答案失败，降级为上下文摘要: {e}")
                        answer = f"检索到 {len(docs)} 篇相关文献，但 LLM 生成答案失败：{e}"
                else:
                    answer = (
                        f"知识库中未检索到与「{question}」相关的文献。"
                        "可能是知识库尚未导入相关文档。"
                    )
            else:
                answer = str(augmented) if augmented else (
                    f"知识库中未检索到与「{question}」相关的文献。"
                    "可能是知识库尚未导入相关文档。"
                )

            return ToolResult.ok(
                data={
                    "question": question,
                    "answer": answer,
                    "references": docs[:top_k],
                    "retrieval_mode": "vector_or_jaccard",
                    "total_docs": len(docs),
                },
                display={
                    "type": "knowledge_answer",
                    "payload": {
                        "answer": answer,
                        "references": docs[:3],
                    },
                },
            )
        except Exception as e:
            logger.error(f"query_knowledge_base 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
