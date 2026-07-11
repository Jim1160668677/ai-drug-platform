"""向量存储服务 — ChromaDB 封装"""
import logging
from typing import Any, Dict, List

from app.core.config import settings
from app.core.deps import get_llm_client

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB 向量存储封装

    Mock 模式下不实际连接 ChromaDB，search 返回空列表。
    """

    def __init__(self):
        self._client = None
        self._collections: Dict[str, Any] = {}

    def _get_client(self):
        if self._client is not None:
            return self._client

        if settings.is_mock:
            return None

        try:
            import chromadb
            self._client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT,
            )
            return self._client
        except Exception as e:
            logger.warning(f"ChromaDB 连接失败，降级为空检索: {e}")
            return None

    def _get_collection(self, name: str):
        client = self._get_client()
        if client is None:
            return None
        if name not in self._collections:
            try:
                self._collections[name] = client.get_or_create_collection(
                    name=name, metadata={"hnsw:space": "cosine"}
                )
            except Exception as e:
                logger.warning(f"获取 ChromaDB 集合 {name} 失败: {e}")
                return None
        return self._collections[name]

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

        coll = self._get_collection(collection)
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
            coll.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
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
        coll = self._get_collection(collection)
        if coll is None:
            return []

        llm_client = get_llm_client()
        try:
            query_emb = await llm_client.embed(query)
        except Exception as e:
            logger.warning(f"查询嵌入失败: {e}")
            return []

        try:
            results = coll.query(query_embeddings=[query_emb], n_results=top_k)
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


_vector_store_singleton: VectorStore = None


def get_vector_store() -> VectorStore:
    global _vector_store_singleton
    if _vector_store_singleton is None:
        _vector_store_singleton = VectorStore()
    return _vector_store_singleton
