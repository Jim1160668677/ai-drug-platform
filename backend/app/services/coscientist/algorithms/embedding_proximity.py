"""EmbeddingProximity — 语义嵌入邻近度算法

基于语义向量的假设相似度计算，作为 Jaccard 文本相似度的增强通道。

设计：
- 优先使用 LLM 的 embed 接口生成假设文本向量
- 若 LLM 不支持 embed（Mock 模式），降级为 TF-IDF 向量化
- 双通道融合：Embedding 分 + Jaccard 分加权融合
- 阈值策略：融合分 > 0.45 → 进 LLM 精判；纯语义分 > 0.75 → 直接建议 merge

参考论文：Section "Proximity agent" + Extended Data Fig. 2c（增强版）
"""
import logging
import math
import re
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmbeddingProximity:
    """语义嵌入邻近度计算器

    用法：
        ep = EmbeddingProximity(llm_client)
        similarity_matrix = await ep.compute_similarities(hypotheses)
        fused = ep.fuse_with_jaccard(embedding_score, jaccard_score)
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        fusion_weights: Tuple[float, float] = (0.6, 0.4),
        llm_refine_threshold: float = 0.45,
        direct_merge_threshold: float = 0.75,
    ):
        """初始化嵌入邻近度计算器

        Args:
            llm_client: LLM 客户端（需支持 embed 方法）。为 None 时仅用 TF-IDF 降级模式
            fusion_weights: (embedding_weight, jaccard_weight) 融合权重
            llm_refine_threshold: 融合分超过此阈值时建议进入 LLM 精判
            direct_merge_threshold: 纯语义分超过此阈值时直接建议 merge
        """
        self.llm_client = llm_client
        self.fusion_weights = fusion_weights
        self.llm_refine_threshold = llm_refine_threshold
        self.direct_merge_threshold = direct_merge_threshold
        self._embed_available: Optional[bool] = None

    @property
    def embed_available(self) -> bool:
        """检查 LLM 是否支持 embed 方法（懒加载）"""
        if self._embed_available is None:
            if self.llm_client is None:
                self._embed_available = False
            else:
                self._embed_available = hasattr(self.llm_client, 'embed') and callable(
                    getattr(self.llm_client, 'embed')
                )
        return self._embed_available

    async def compute_similarities(
        self,
        hypotheses: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """计算所有假设对的语义嵌入相似度矩阵

        Args:
            hypotheses: 假设列表 [{id, name, description, mechanism}, ...]

        Returns:
            {
                "matrix": {(id_a, id_b): {"embedding_score": float, "method": str}},
                "vectors": {id: List[float]},
                "method": "llm_embed" | "tfidf",
                "embed_available": bool,
            }
        """
        if len(hypotheses) < 2:
            return {
                "matrix": {},
                "vectors": {},
                "method": "none",
                "embed_available": self.embed_available,
            }

        texts = []
        ids = []
        for h in hypotheses:
            hid = str(h.get("id", h.get("name", "")))
            text = self._hypothesis_to_text(h)
            texts.append(text)
            ids.append(hid)

        if self.embed_available:
            vectors, actual_method = await self._llm_embed_batch(texts)
            method = actual_method
        else:
            vectors = self._tfidf_vectors(texts)
            method = "tfidf"

        vector_map = {ids[i]: vectors[i] for i in range(len(ids))}

        matrix: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for i, j in combinations(range(len(hypotheses)), 2):
            id_a, id_b = ids[i], ids[j]
            vec_a, vec_b = vectors[i], vectors[j]
            score = self._cosine_similarity(vec_a, vec_b)
            matrix[(id_a, id_b)] = {
                "embedding_score": score,
                "method": method,
            }

        logger.info(
            "[embedding_proximity] 计算 %d 条假设的嵌入相似度，方法=%s",
            len(hypotheses), method,
        )

        return {
            "matrix": matrix,
            "vectors": vector_map,
            "method": method,
            "embed_available": self.embed_available,
        }

    def fuse_with_jaccard(
        self,
        embedding_score: float,
        jaccard_score: float,
        weights: Optional[Tuple[float, float]] = None,
    ) -> Dict[str, Any]:
        """加权融合嵌入分与 Jaccard 分

        Args:
            embedding_score: 语义嵌入相似度 (0-1)
            jaccard_score: Jaccard 文本相似度 (0-1)
            weights: (embedding_weight, jaccard_weight)，None 则用初始化默认值

        Returns:
            {
                "fused_score": float,
                "embedding_score": float,
                "jaccard_score": float,
                "llm_refine": bool,      # 是否建议进 LLM 精判
                "direct_merge": bool,    # 是否直接建议 merge
            }
        """
        w_embed, w_jaccard = weights or self.fusion_weights

        fused = w_embed * embedding_score + w_jaccard * jaccard_score
        fused = max(0.0, min(1.0, fused))

        direct_merge = embedding_score >= self.direct_merge_threshold
        llm_refine = (not direct_merge) and (fused >= self.llm_refine_threshold)

        if direct_merge:
            recommendation = "direct_merge"
        elif llm_refine:
            recommendation = "llm_refine"
        else:
            recommendation = "keep_separate"

        return {
            "fused_score": round(fused, 4),
            "embedding_score": round(embedding_score, 4),
            "jaccard_score": round(jaccard_score, 4),
            "llm_refine": llm_refine,
            "direct_merge": direct_merge,
            "recommendation": recommendation,
        }

    async def compute_and_fuse(
        self,
        hypotheses: List[Dict[str, Any]],
        jaccard_scores: Dict[Tuple[str, str], float],
    ) -> Dict[str, Any]:
        """一键计算嵌入相似度并与 Jaccard 融合

        Args:
            hypotheses: 假设列表
            jaccard_scores: {(id_a, id_b): jaccard_score} 映射

        Returns:
            {
                "matrix": {(id_a, id_b): {"embedding_score", "fused_score", "recommendation", ...}},
                "vectors": {id: List[float]},
                "method": str,
                "stats": {"direct_merge": int, "llm_refine": int, "keep_separate": int},
            }
        """
        embedding_result = await self.compute_similarities(hypotheses)
        matrix = embedding_result["matrix"]

        fused_matrix: Dict[Tuple[str, str], Dict[str, Any]] = {}
        stats = {"direct_merge": 0, "llm_refine": 0, "keep_separate": 0}

        for pair_key, emb_data in matrix.items():
            jac = jaccard_scores.get(pair_key, 0.0)
            emb_score = emb_data["embedding_score"]
            fused = self.fuse_with_jaccard(emb_score, jac)

            if fused["direct_merge"]:
                stats["direct_merge"] += 1
            elif fused["llm_refine"]:
                stats["llm_refine"] += 1
            else:
                stats["keep_separate"] += 1

            fused_matrix[pair_key] = {
                **emb_data,
                **fused,
            }

        return {
            "matrix": fused_matrix,
            "vectors": embedding_result["vectors"],
            "method": embedding_result["method"],
            "stats": stats,
        }

    async def _llm_embed_batch(self, texts: List[str]) -> Tuple[List[List[float]], str]:
        """批量调用 LLM embed 接口

        Args:
            texts: 文本列表

        Returns:
            (向量列表, 实际使用的方法名)
        """
        vectors = []
        for text in texts:
            try:
                vec = await self.llm_client.embed(text)
                if vec and isinstance(vec, list):
                    vectors.append(vec)
                else:
                    logger.warning("[embedding_proximity] embed 返回无效，降级 TF-IDF")
                    return self._tfidf_vectors(texts), "tfidf"
            except Exception as e:
                logger.warning("[embedding_proximity] LLM embed 失败: %s，降级 TF-IDF", e)
                return self._tfidf_vectors(texts), "tfidf"

        if vectors and len(vectors) == len(texts):
            return vectors, "llm_embed"
        return self._tfidf_vectors(texts), "tfidf"

    def _tfidf_vectors(self, texts: List[str]) -> List[List[float]]:
        """TF-IDF 向量化（降级方案）

        使用简化的 TF-IDF：
        - 分词：英文单词 + 中文 2-gram
        - 计算词频 (TF)
        - 计算逆文档频率 (IDF)
        - 生成归一化向量

        Args:
            texts: 文本列表

        Returns:
            归一化 TF-IDF 向量列表
        """
        tokenized = [self._tokenize(t) for t in texts]

        vocab: Dict[str, int] = {}
        for doc_tokens in tokenized:
            for token in doc_tokens:
                if token not in vocab:
                    vocab[token] = len(vocab)

        vocab_size = len(vocab)
        if vocab_size == 0:
            return [[0.0] for _ in texts]

        df = [0] * vocab_size
        for doc_tokens in tokenized:
            seen = set()
            for token in doc_tokens:
                idx = vocab[token]
                if idx not in seen:
                    df[idx] += 1
                    seen.add(idx)

        n_docs = len(texts)
        vectors = []
        for doc_tokens in tokenized:
            tf = [0.0] * vocab_size
            for token in doc_tokens:
                tf[vocab[token]] += 1.0

            vec = []
            for i in range(vocab_size):
                if tf[i] > 0 and df[i] > 0:
                    idf = math.log((n_docs + 1.0) / (df[i] + 1.0)) + 1.0
                    vec.append(tf[i] * idf)
                else:
                    vec.append(0.0)

            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]

            vectors.append(vec)

        return vectors

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """计算余弦相似度

        Args:
            vec_a: 向量 A
            vec_b: 向量 B

        Returns:
            余弦相似度 (-1 到 1)，截断到 0-1
        """
        if not vec_a or not vec_b:
            return 0.0

        len_a, len_b = len(vec_a), len(vec_b)
        min_len = min(len_a, len_b)

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for i in range(min_len):
            a, b = vec_a[i], vec_b[i]
            dot += a * b
            norm_a += a * a
            norm_b += b * b

        if len_a > min_len:
            norm_a += sum(vec_a[i] * vec_a[i] for i in range(min_len, len_a))
        if len_b > min_len:
            norm_b += sum(vec_b[i] * vec_b[i] for i in range(min_len, len_b))

        denom = math.sqrt(norm_a) * math.sqrt(norm_b)
        if denom < 1e-10:
            return 0.0

        return max(0.0, min(1.0, dot / denom))

    @staticmethod
    def _hypothesis_to_text(h: Dict[str, Any]) -> str:
        """将假设对象转为文本"""
        parts = []
        if h.get("name"):
            parts.append(h["name"])
        if h.get("description"):
            parts.append(h["description"])
        if h.get("mechanism"):
            parts.append(h["mechanism"])
        return " ".join(parts)

    @staticmethod
    def _tokenize(text: str) -> set:
        """简单分词（中文按字，英文按词）"""
        if not text:
            return set()

        words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))

        chinese_chars = re.findall(r"[\u4e00-\u9fff]+", text)
        for seq in chinese_chars:
            for i in range(len(seq) - 1):
                words.add(seq[i:i + 2])

        return words