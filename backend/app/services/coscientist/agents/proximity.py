"""Proximity Agent — 假设相似度分析智能体

职责：分析假设对之间的语义和机制相似度，给出合并建议。
供 EvolutionStrategist 决策 Combination 策略。

设计：
- 两阶段：先用轻量级文本相似度（Jaccard）初筛，高相似度对再用 LLM 精判
- 可选增强：EmbeddingProximity 语义嵌入邻近度，与 Jaccard 双通道融合
- LLM 精判返回 semantic_similarity + recommendation(merge/keep_separate/refine)
- 批量处理所有假设对

参考论文：Section "Proximity agent" + Extended Data Fig. 2c
"""
import asyncio
import logging
import re
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from app.services.coscientist.agents.base import BaseAgent
from app.services.coscientist.agents.prompts import PROXIMITY_SYSTEM, PROXIMITY_USER
from app.services.coscientist.algorithms.embedding_proximity import EmbeddingProximity

logger = logging.getLogger(__name__)


class ProximityAgent(BaseAgent):
    """假设相似度分析智能体

    用法：
        agent = ProximityAgent(llm_client)
        result = await agent.run(hypotheses)
        # result = {"pairs": [{"id_a", "id_b", "semantic_similarity", "recommendation", ...}], ...}
    """

    agent_name = "proximity"

    def __init__(
        self,
        llm_client: Any,
        jaccard_threshold: float = 0.3,
        semaphore: Optional[asyncio.Semaphore] = None,
        timeout: float = 60.0,
        embedding_proximity: Optional[EmbeddingProximity] = None,
    ):
        """
        Args:
            llm_client: LLM 客户端
            jaccard_threshold: Jaccard 初筛阈值（低于此值不调用 LLM）
            semaphore: 并发控制
            timeout: LLM 调用超时
            embedding_proximity: 语义嵌入邻近度计算器（可选增强）
        """
        super().__init__(llm_client, semaphore=semaphore, timeout=timeout)
        self.jaccard_threshold = jaccard_threshold
        self.embedding_proximity = embedding_proximity

    async def run(
        self,
        hypotheses: List[Dict[str, Any]],
        research_goal: str = "",
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """分析所有假设对的相似度

        Args:
            hypotheses: 假设列表
            research_goal: 研究目标
            use_llm: 是否使用 LLM 精判（False 则仅用 Jaccard）
        Returns:
            {"pairs": [{"id_a", "id_b", "semantic_similarity", "mechanism_overlap",
                        "recommendation", "shared_concepts", ...}],
             "total_pairs": int, "llm_calls": int,
             "token_usage": {...}, "cost_usd": ...}
        """
        if len(hypotheses) < 2:
            return {
                "pairs": [],
                "total_pairs": 0,
                "llm_calls": 0,
                "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                "cost_usd": 0.0,
            }

        # 1. 生成所有假设对
        all_pairs = list(combinations(range(len(hypotheses)), 2))
        total_pairs = len(all_pairs)

        # 2. Jaccard 初筛（基础通道）
        pair_jaccard: Dict[Tuple[str, str], float] = {}
        for i, j in all_pairs:
            hyp_a, hyp_b = hypotheses[i], hypotheses[j]
            id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
            id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
            jac = self._jaccard_similarity(hyp_a, hyp_b)
            pair_jaccard[(id_a, id_b)] = jac

        # 3. 语义嵌入增强（可选）
        embedding_scores: Dict[Tuple[str, str], float] = {}
        embedding_vectors: Dict[str, List[float]] = {}
        embedding_method = "none"
        use_embedding = self.embedding_proximity is not None

        if use_embedding:
            try:
                emb_result = await self.embedding_proximity.compute_similarities(hypotheses)
                embedding_vectors = emb_result.get("vectors", {})
                embedding_method = emb_result.get("method", "none")
                for pair_key, data in emb_result.get("matrix", {}).items():
                    embedding_scores[pair_key] = data.get("embedding_score", 0.0)
                logger.info(
                    "[proximity] 嵌入增强启用: method=%s, vectors=%d, score_pairs=%d",
                    embedding_method, len(embedding_vectors), len(embedding_scores),
                )
            except Exception as e:
                logger.warning("[proximity] 嵌入计算失败，降级纯 Jaccard: %s", e)
                use_embedding = False

        # 4. 构建候选对列表 + 融合评分
        candidates: List[Tuple[int, int, float, str, str, Dict[str, Any]]] = []
        pair_fused: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for i, j in all_pairs:
            hyp_a, hyp_b = hypotheses[i], hypotheses[j]
            id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
            id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
            pair_key = (id_a, id_b)
            jac = pair_jaccard.get(pair_key, 0.0)

            if use_embedding and pair_key in embedding_scores:
                emb_score = embedding_scores[pair_key]
                fused = self.embedding_proximity.fuse_with_jaccard(emb_score, jac)
                pair_fused[pair_key] = fused

                if fused["direct_merge"]:
                    candidates.append((i, j, jac, id_a, id_b, fused))
                    continue
                if fused["llm_refine"] or not use_llm:
                    candidates.append((i, j, jac, id_a, id_b, fused))
            else:
                if jac >= self.jaccard_threshold or not use_llm:
                    candidates.append((i, j, jac, id_a, id_b, {}))

        # 5. LLM 精判
        llm_calls = 0
        total_token = {"prompt": 0, "completion": 0, "total": 0}
        total_cost = 0.0

        if use_llm and candidates:
            sem = asyncio.Semaphore(3)

            async def _analyze_pair(i, j, jac, id_a, id_b, fused_info):
                nonlocal llm_calls
                async with sem:
                    if fused_info and fused_info.get("direct_merge"):
                        llm_calls += 1
                        return (id_a, id_b, jac, {
                            "parsed": {
                                "semantic_similarity": fused_info.get("embedding_score", jac),
                                "mechanism_overlap": jac,
                                "recommendation": "merge",
                                "shared_concepts": [],
                                "unique_to_a": [],
                                "unique_to_b": [],
                            },
                            "token_usage": {"prompt": 0, "completion": 0, "total": 0},
                            "cost_usd": 0.0,
                        })
                    result = await self._llm_proximity(
                        hypotheses[i], hypotheses[j], research_goal
                    )
                    llm_calls += 1
                    return (id_a, id_b, jac, result)

            tasks = [_analyze_pair(*c) for c in candidates]
            llm_results = await asyncio.gather(*tasks, return_exceptions=True)

            pairs = []
            for r in llm_results:
                if isinstance(r, Exception):
                    logger.warning("[proximity] LLM 分析失败: %s", r)
                    continue
                id_a, id_b, jac, llm_res = r
                total_token["total"] += llm_res.get("token_usage", {}).get("total", 0)
                total_cost += llm_res.get("cost_usd", 0.0)
                pair_key = (id_a, id_b)
                fused_info = pair_fused.get(pair_key, {})
                pairs.append(self._format_pair_with_fusion(id_a, id_b, llm_res, jac, fused_info))

            analyzed_ids = {(p["id_a"], p["id_b"]) for p in pairs}
            for i, j in all_pairs:
                hyp_a, hyp_b = hypotheses[i], hypotheses[j]
                id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
                id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
                if (id_a, id_b) not in analyzed_ids:
                    jac = pair_jaccard.get((id_a, id_b), 0.0)
                    pair_key = (id_a, id_b)
                    fused_info = pair_fused.get(pair_key, {})
                    emb_score = fused_info.get("embedding_score", jac)
                    pairs.append({
                        "id_a": id_a,
                        "id_b": id_b,
                        "semantic_similarity": emb_score if use_embedding else jac,
                        "mechanism_overlap": jac,
                        "recommendation": "keep_separate",
                        "shared_concepts": [],
                        "unique_to_a": [],
                        "unique_to_b": [],
                        "jaccard_baseline": jac,
                        "embedding_score": emb_score if use_embedding else None,
                        "fused_score": fused_info.get("fused_score") if use_embedding else None,
                        "method": "embedding_fused" if use_embedding else "jaccard_only",
                    })
        else:
            pairs = []
            for i, j in all_pairs:
                hyp_a, hyp_b = hypotheses[i], hypotheses[j]
                id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
                id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
                jac = pair_jaccard.get((id_a, id_b), 0.0)
                pair_key = (id_a, id_b)
                fused_info = pair_fused.get(pair_key, {})
                emb_score = fused_info.get("embedding_score", jac)

                if fused_info and fused_info.get("direct_merge"):
                    rec = "merge"
                elif fused_info:
                    rec = "merge" if fused_info.get("fused_score", 0) >= 0.7 else "keep_separate"
                else:
                    rec = "merge" if jac >= 0.7 else "keep_separate"

                pairs.append({
                    "id_a": id_a,
                    "id_b": id_b,
                    "semantic_similarity": emb_score if use_embedding else jac,
                    "mechanism_overlap": jac,
                    "recommendation": rec,
                    "shared_concepts": [],
                    "unique_to_a": [],
                    "unique_to_b": [],
                    "jaccard_baseline": jac,
                    "embedding_score": emb_score if use_embedding else None,
                    "fused_score": fused_info.get("fused_score") if use_embedding else None,
                    "method": "embedding_fused" if use_embedding else "jaccard_only",
                })

        logger.info(
            "[proximity] 分析 %d 对假设（%d 对 LLM 精判, embedding=%s, 模式=%s）(tokens=%d)",
            total_pairs, llm_calls, embedding_method,
            "融合" if use_embedding else "纯 Jaccard",
            total_token["total"],
        )

        return {
            "pairs": pairs,
            "total_pairs": total_pairs,
            "llm_calls": llm_calls,
            "token_usage": total_token,
            "cost_usd": total_cost,
            "embedding_enabled": use_embedding,
            "embedding_method": embedding_method,
        }

    async def _llm_proximity(
        self,
        hyp_a: Dict[str, Any],
        hyp_b: Dict[str, Any],
        research_goal: str,
    ) -> Dict[str, Any]:
        """LLM 精判单个假设对"""
        prompt = PROXIMITY_USER.format(
            a_name=hyp_a.get("name", "未命名"),
            a_description=hyp_a.get("description", ""),
            a_mechanism=hyp_a.get("mechanism", ""),
            b_name=hyp_b.get("name", "未命名"),
            b_description=hyp_b.get("description", ""),
            b_mechanism=hyp_b.get("mechanism", ""),
        )

        result = await self.quick(prompt, system=PROXIMITY_SYSTEM)
        parsed = self._parse_json(result["content"], default={})

        return {
            "parsed": parsed,
            "token_usage": result["token_usage"],
            "cost_usd": result["cost_usd"],
        }

    def _format_pair(
        self, id_a: str, id_b: str, llm_res: Dict[str, Any], jaccard: float
    ) -> Dict[str, Any]:
        """格式化 LLM 结果为 pair 记录"""
        parsed = llm_res.get("parsed", {})

        try:
            semantic_sim = float(parsed.get("semantic_similarity", jaccard))
        except (ValueError, TypeError):
            semantic_sim = jaccard

        try:
            mechanism_overlap = float(parsed.get("mechanism_overlap", jaccard))
        except (ValueError, TypeError):
            mechanism_overlap = jaccard

        recommendation = str(parsed.get("recommendation", "keep_separate"))
        if recommendation not in ("merge", "keep_separate", "refine"):
            recommendation = "keep_separate"

        shared = parsed.get("shared_concepts", [])
        if not isinstance(shared, list):
            shared = [str(shared)]

        unique_a = parsed.get("unique_to_a", [])
        if not isinstance(unique_a, list):
            unique_a = [str(unique_a)]

        unique_b = parsed.get("unique_to_b", [])
        if not isinstance(unique_b, list):
            unique_b = [str(unique_b)]

        return {
            "id_a": id_a,
            "id_b": id_b,
            "semantic_similarity": max(0.0, min(1.0, semantic_sim)),
            "mechanism_overlap": max(0.0, min(1.0, mechanism_overlap)),
            "recommendation": recommendation,
            "shared_concepts": shared,
            "unique_to_a": unique_a,
            "unique_to_b": unique_b,
            "jaccard_baseline": jaccard,
            "method": "llm",
        }

    def _format_pair_with_fusion(
        self,
        id_a: str,
        id_b: str,
        llm_res: Dict[str, Any],
        jaccard: float,
        fused_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """格式化 LLM 结果为 pair 记录（带嵌入融合信息）"""
        parsed = llm_res.get("parsed", {})

        try:
            semantic_sim = float(parsed.get("semantic_similarity", jaccard))
        except (ValueError, TypeError):
            semantic_sim = jaccard

        try:
            mechanism_overlap = float(parsed.get("mechanism_overlap", jaccard))
        except (ValueError, TypeError):
            mechanism_overlap = jaccard

        recommendation = str(parsed.get("recommendation", "keep_separate"))
        if recommendation not in ("merge", "keep_separate", "refine"):
            recommendation = "keep_separate"

        shared = parsed.get("shared_concepts", [])
        if not isinstance(shared, list):
            shared = [str(shared)]

        unique_a = parsed.get("unique_to_a", [])
        if not isinstance(unique_a, list):
            unique_a = [str(unique_a)]

        unique_b = parsed.get("unique_to_b", [])
        if not isinstance(unique_b, list):
            unique_b = [str(unique_b)]

        emb_score = fused_info.get("embedding_score")
        fused_score = fused_info.get("fused_score")

        method = "llm_embedding_fused" if fused_info else "llm"

        return {
            "id_a": id_a,
            "id_b": id_b,
            "semantic_similarity": max(0.0, min(1.0, semantic_sim)),
            "mechanism_overlap": max(0.0, min(1.0, mechanism_overlap)),
            "recommendation": recommendation,
            "shared_concepts": shared,
            "unique_to_a": unique_a,
            "unique_to_b": unique_b,
            "jaccard_baseline": jaccard,
            "embedding_score": emb_score,
            "fused_score": fused_score,
            "method": method,
        }

    def _jaccard_similarity(self, hyp_a: Dict[str, Any], hyp_b: Dict[str, Any]) -> float:
        """计算两个假设的 Jaccard 文本相似度

        基于 name + description + mechanism 的词集合。
        """
        text_a = self._tokenize(
            f"{hyp_a.get('name', '')} {hyp_a.get('description', '')} {hyp_a.get('mechanism', '')}"
        )
        text_b = self._tokenize(
            f"{hyp_b.get('name', '')} {hyp_b.get('description', '')} {hyp_b.get('mechanism', '')}"
        )

        if not text_a and not text_b:
            return 0.0

        intersection = text_a & text_b
        union = text_a | text_b

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _tokenize(self, text: str) -> set:
        """简单分词（中文按字，英文按词）"""
        if not text:
            return set()

        # 提取英文单词
        words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))

        # 提取中文字符序列（2-4字）
        chinese_chars = re.findall(r"[\u4e00-\u9fff]+", text)
        for seq in chinese_chars:
            # 2-gram
            for i in range(len(seq) - 1):
                words.add(seq[i:i+2])

        return words