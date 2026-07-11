"""RAG 引擎 — 检索增强生成

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/LLM服务层.md

支持两种检索模式：
1. 向量检索（ChromaDB）— 优先使用
2. Jaccard 关键词检索 — ChromaDB 不可用时的降级方案

文档管理：
- add_documents() — 入库
- build_context() — 构建上下文 prompt
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果数据类"""
    query: str
    documents: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_mode: str = "vector"  # vector / jaccard / empty
    total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "documents": self.documents,
            "retrieval_mode": self.retrieval_mode,
            "total": self.total,
        }


# 内存态文档库（Jaccard 降级时使用）
_jaccard_store: Dict[str, List[Dict[str, Any]]] = {}


def _tokenize(text: str) -> set:
    """简单分词 — 中文按字 + 英文按词"""
    tokens = set()
    # 英文单词
    for w in re.findall(r"[a-zA-Z]{2,}", text.lower()):
        tokens.add(w)
    # 中文单字
    for c in re.findall(r"[\u4e00-\u9fff]", text):
        tokens.add(c)
    return tokens


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard 相似度"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


class RAGEngine:
    """检索增强生成引擎

    Mock 模式或 ChromaDB 不可用时降级为 Jaccard 关键词检索。
    """

    def __init__(self, db: AsyncSession, llm_client=None):
        self.db = db
        self.llm_client = llm_client

    async def add_documents(
        self,
        documents: List[Dict[str, Any]],
        collection: str = "default",
    ) -> int:
        """添加文档到知识库

        Args:
            documents: [{"id", "text", "metadata"}]
            collection: 集合名（项目隔离）
        Returns:
            成功添加的文档数
        """
        if not documents:
            return 0

        # 1. 尝试向量库
        try:
            from app.services.knowledge.vector import get_vector_store

            store = get_vector_store()
            count = 0
            for doc in documents:
                try:
                    await store.add(
                        texts=[doc.get("text", "")],
                        metadatas=[doc.get("metadata", {})],
                        collection=collection,
                        ids=[doc.get("id")] if doc.get("id") else None,
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"向量库添加单文档失败: {e}")
            logger.info(f"向量库添加 {count}/{len(documents)} 文档到 {collection}")
            return count
        except Exception as e:
            logger.warning(f"向量库不可用，降级到内存 Jaccard: {e}")

        # 2. 降级：内存 Jaccard
        if collection not in _jaccard_store:
            _jaccard_store[collection] = []
        for doc in documents:
            _jaccard_store[collection].append({
                "id": doc.get("id", f"doc_{len(_jaccard_store[collection])}"),
                "text": doc.get("text", ""),
                "metadata": doc.get("metadata", {}),
            })
        logger.info(f"内存库添加 {len(documents)} 文档到 {collection}")
        return len(documents)

    async def retrieve(
        self,
        query: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索相关文档片段

        Args:
            query: 用户查询
            project_id: 项目 ID（用于隔离 collection）
            top_k: 返回文档数
        Returns:
            [{"id", "text", "metadata", "similarity"}]
        """
        collection = f"project_{project_id}" if project_id else "default"

        # 1. 尝试向量检索
        try:
            from app.services.knowledge.vector import get_vector_store

            store = get_vector_store()
            results = await store.search(query, collection=collection, top_k=top_k)
            if results:
                return results
        except Exception as e:
            logger.warning(f"向量检索失败，降级到 Jaccard: {e}")

        # 2. 降级：Jaccard 关键词检索
        return self._jaccard_retrieve(query, collection, top_k)

    def _jaccard_retrieve(
        self,
        query: str,
        collection: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Jaccard 关键词检索（降级方案）"""
        docs = _jaccard_store.get(collection, [])
        if not docs:
            return []

        query_tokens = _tokenize(query)
        scored = []
        for doc in docs:
            doc_tokens = _tokenize(doc.get("text", ""))
            sim = _jaccard_similarity(query_tokens, doc_tokens)
            scored.append((doc, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for doc, sim in scored[:top_k]:
            if sim > 0:
                results.append({
                    "id": doc.get("id"),
                    "text": doc.get("text", ""),
                    "metadata": doc.get("metadata", {}),
                    "similarity": round(sim, 4),
                })
        return results

    async def build_context(
        self,
        query: str,
        retrieved: List[Dict[str, Any]],
    ) -> str:
        """构建上下文 prompt

        Args:
            query: 原始用户查询
            retrieved: retrieve() 返回的文档列表
        Returns:
            增强后的 prompt 字符串
        """
        if not retrieved:
            return query

        context_parts = []
        for i, doc in enumerate(retrieved, 1):
            text = doc.get("text", "")
            similarity = doc.get("similarity", 0)
            source = (doc.get("metadata") or {}).get("source", "unknown")
            context_parts.append(
                f"[文献 {i}] (相似度: {similarity:.2f}, 来源: {source})\n{text}"
            )

        context_str = "\n\n".join(context_parts)
        return (
            f"## 检索到的相关文献\n{context_str}\n\n"
            f"## 用户问题\n{query}\n\n"
            "请基于以上文献和你的知识回答用户问题，并在回答中引用相关文献编号。"
        )

    async def augment(
        self,
        query: str,
        retrieved: List[Dict[str, Any]],
    ) -> str:
        """将检索到的文档拼入增强 prompt（build_context 的别名，保兼容）"""
        return await self.build_context(query, retrieved)


# 别名 — spec 期望类名 RagEngine
RagEngine = RAGEngine
