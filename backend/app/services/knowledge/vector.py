"""向量存储服务 — ChromaDB 封装

注意：ChromaDB 的 HttpClient、get_or_create_collection、coll.add、coll.query
均为同步阻塞调用。在 asyncio 事件循环中直接调用会卡死整个后端
（health check 超时、其他请求无响应）。

所有同步操作必须用 asyncio.to_thread() 包裹，避免阻塞事件循环。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.deps import get_llm_client

logger = logging.getLogger(__name__)


def _connect_chromadb():
    """同步：连接 ChromaDB（在 to_thread 中调用）"""
    import chromadb
    return chromadb.HttpClient(
        host=settings.CHROMA_HOST,
        port=settings.CHROMA_PORT,
    )


def _get_or_create_collection(client, name: str):
    """同步：获取或创建集合（在 to_thread 中调用）"""
    return client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )


def _coll_add(coll, ids, texts, metadatas, embeddings):
    """同步：批量入库（在 to_thread 中调用）"""
    coll.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)


def _coll_query(coll, query_emb, top_k):
    """同步：向量检索（在 to_thread 中调用）"""
    return coll.query(query_embeddings=[query_emb], n_results=top_k)


class VectorStore:
    """ChromaDB 向量存储封装

    Mock 模式下不实际连接 ChromaDB，search 返回空列表。
    """

    def __init__(self):
        self._client: Optional[Any] = None
        self._collections: Dict[str, Any] = {}

    def _get_client_sync(self):
        """同步获取客户端（仅用于已缓存场景的快速路径）"""
        if self._client is not None:
            return self._client
        return None  # 未初始化，需要异步初始化

    async def _get_collection(self, name: str):
        """异步获取集合（包裹同步 ChromaDB 调用，避免阻塞事件循环）"""
        # 快速路径：集合已缓存
        if name in self._collections:
            return self._collections[name]

        # 需要客户端：首次连接或已连接
        if self._client is None and not settings.is_mock:
            try:
                self._client = await asyncio.to_thread(_connect_chromadb)
            except Exception as e:
                logger.warning(f"ChromaDB 连接失败，降级为空检索: {e}")
                self._client = None
                return None

        if settings.is_mock or self._client is None:
            return None

        try:
            coll = await asyncio.to_thread(_get_or_create_collection, self._client, name)
            self._collections[name] = coll
            return coll
        except Exception as e:
            logger.warning(f"获取 ChromaDB 集合 {name} 失败: {e}")
            return None

    async def add_documents(self, documents: List[Dict[str, Any]], collection: str = "default") -> int:
        """文档向量化入库

        Args:
            documents: [{"id": str, "text": str, "metadata": {...}}, ...]
            collection: 集合名称
        Returns:
            新增文档数
        """
        if not documents:
            return 0

        coll = await self._get_collection(collection)
        if coll is None:
            logger.info(f"[Mock] 向量存储跳过 {len(documents)} 文档")
            return 0

        llm_client = get_llm_client()
        ids = []
        texts = []
        metadatas = []
        embeddings = []

        for doc in documents:
            ids.append(doc.get("id") or str(hash(doc.get("text", ""))))
            texts.append(doc.get("text", ""))
            metadatas.append(doc.get("metadata", {}))
            try:
                emb = await llm_client.embed(doc.get("text", ""))
                embeddings.append(emb)
            except Exception as e:
                logger.warning(f"嵌入生成失败: {e}")
                return 0

        try:
            await asyncio.to_thread(_coll_add, coll, ids, texts, metadatas, embeddings)
            return len(ids)
        except Exception as e:
            logger.error(f"向量入库失败: {e}")
            return 0

    async def search(
        self,
        query: str,
        collection: str = "default",
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """相似度检索"""
        coll = await self._get_collection(collection)
        if coll is None:
            return []

        llm_client = get_llm_client()
        try:
            query_emb = await llm_client.embed(query)
        except Exception as e:
            logger.warning(f"查询嵌入失败: {e}")
            return []

        try:
            # 关键修复：coll.query 是同步阻塞调用，必须用 to_thread 包裹
            # 否则会卡死 asyncio 事件循环，导致后端 health check 超时
            results = await asyncio.to_thread(_coll_query, coll, query_emb, top_k)
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

        out = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, _id in enumerate(ids):
            out.append({
                "id": _id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distances[i] if i < len(distances) else 0,
                "similarity": 1 - (distances[i] if i < len(distances) else 0),
            })
        return out


_vector_store_singleton: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _vector_store_singleton
    if _vector_store_singleton is None:
        _vector_store_singleton = VectorStore()
    return _vector_store_singleton
