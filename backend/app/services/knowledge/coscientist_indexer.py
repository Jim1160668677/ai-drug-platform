"""Co-Scientist 知识库索引器 — Phase B7

将 Co-Scientist 运行结果（假设 + 运行摘要）索引到向量存储，
支持相似度检索和知识关联发现。

功能：
- index_run(run_id): 索引运行的所有假设和运行摘要
- search_hypotheses(query, top_k): 搜索相似假设
- search_runs(query, top_k): 搜索相似运行
- auto_index_if_completed(run_id): 运行完成时自动索引（幂等）
- get_stats(): 获取索引统计

集合设计：
- coscientist_hypotheses: 假设向量集合（每个假设一条文档）
- coscientist_runs: 运行摘要向量集合（每个运行一条文档）

设计原则：
- 复用现有 VectorStore（ChromaDB 封装），不引入新依赖
- Mock 模式下自动降级（VectorStore 返回 0，不影响主流程）
- 索引操作幂等（重复索引同一运行不会产生重复文档）
- 索引失败不阻塞主流程（仅记录日志）

参考：
- 向量存储：app/services/knowledge/vector.py
- RAG 引擎：app/services/llm/rag.py
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.coscientist_run import CoScientistRun, RunStatus
from app.models.hypothesis import Hypothesis

logger = logging.getLogger(__name__)

# 集合名称常量
COLLECTION_HYPOTHESES = "coscientist_hypotheses"
COLLECTION_RUNS = "coscientist_runs"


class CoScientistIndexer:
    """Co-Scientist 知识库索引器

    将假设和运行摘要索引到 VectorStore，支持相似度检索。

    用法：
        indexer = CoScientistIndexer(db)
        await indexer.index_run(run_id)  # 手动索引
        results = await indexer.search_hypotheses("AML drug targets")  # 搜索
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== 索引方法 ==========

    async def index_run(self, run_id: UUID) -> Dict[str, Any]:
        """索引运行的所有假设和运行摘要

        Args:
            run_id: Co-Scientist 运行 ID
        Returns:
            {"run_id", "hypotheses_indexed", "run_indexed", "errors": [...]}
        Raises:
            NotFoundError: 运行不存在
        """
        run = await self.db.get(CoScientistRun, run_id)
        if not run:
            raise NotFoundError(
                f"Co-Scientist 运行不存在: {run_id}",
                details={"run_id": str(run_id)},
            )

        result: Dict[str, Any] = {
            "run_id": str(run_id),
            "hypotheses_indexed": 0,
            "run_indexed": False,
            "errors": [],
        }

        # 1. 索引假设
        try:
            hyp_count = await self._index_hypotheses(run_id)
            result["hypotheses_indexed"] = hyp_count
        except Exception as e:
            logger.error("索引假设失败 (run=%s): %s", run_id, e, exc_info=True)
            result["errors"].append(f"hypotheses: {type(e).__name__}: {e}")

        # 2. 索引运行摘要
        try:
            run_indexed = await self._index_run_summary(run)
            result["run_indexed"] = run_indexed
        except Exception as e:
            logger.error("索引运行摘要失败 (run=%s): %s", run_id, e, exc_info=True)
            result["errors"].append(f"run_summary: {type(e).__name__}: {e}")

        logger.info(
            "Co-Scientist 索引完成: run=%s hyps=%d run_indexed=%s errors=%d",
            run_id,
            result["hypotheses_indexed"],
            result["run_indexed"],
            len(result["errors"]),
        )
        return result

    async def auto_index_if_completed(self, run_id: UUID) -> Optional[Dict[str, Any]]:
        """运行完成时自动索引（幂等）

        仅当运行状态为 COMPLETED 时执行索引。
        其他状态返回 None，不执行任何操作。

        Args:
            run_id: Co-Scientist 运行 ID
        Returns:
            索引结果（同 index_run），或 None（运行未完成）
        """
        run = await self.db.get(CoScientistRun, run_id)
        if not run:
            logger.warning("自动索引跳过：运行不存在 %s", run_id)
            return None

        if run.status != RunStatus.COMPLETED:
            logger.debug(
                "自动索引跳过：运行未完成 %s (status=%s)",
                run_id,
                run.status,
            )
            return None

        return await self.index_run(run_id)

    async def _index_hypotheses(self, run_id: UUID) -> int:
        """索引运行的所有假设到 coscientist_hypotheses 集合"""
        from app.services.knowledge.vector import get_vector_store

        hypotheses = (
            await self.db.execute(
                select(Hypothesis)
                .where(Hypothesis.coscientist_run_id == run_id)
                .order_by(Hypothesis.rank.asc().nullslast())
            )
        ).scalars().all()

        if not hypotheses:
            logger.info("运行 %s 无假设可索引", run_id)
            return 0

        # 构建文档列表
        documents: List[Dict[str, Any]] = []
        for h in hypotheses:
            text = self._build_hypothesis_text(h)
            metadata = {
                "run_id": str(run_id),
                "hypothesis_id": str(h.id),
                "name": h.name or "",
                "rank": h.rank or 0,
                "elo_score": h.elo_score or 0.0,
                "evolution_strategy": h.evolution_strategy or "initial",
                "status": h.status or "draft",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }
            documents.append({
                "id": f"hyp-{h.id}",
                "text": text,
                "metadata": metadata,
            })

        store = get_vector_store()
        count = await store.add_documents(documents, collection=COLLECTION_HYPOTHESES)
        return count

    async def _index_run_summary(self, run: CoScientistRun) -> bool:
        """索引运行摘要到 coscientist_runs 集合"""
        from app.services.knowledge.vector import get_vector_store

        text = self._build_run_text(run)
        metadata = {
            "run_id": str(run.id),
            "case_type": run.case_type or "custom",
            "status": run.status,
            "current_round": run.current_round,
            "max_rounds": run.max_rounds,
            "total_cost_usd": run.total_cost_usd or 0.0,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        documents = [{
            "id": f"run-{run.id}",
            "text": text,
            "metadata": metadata,
        }]

        store = get_vector_store()
        count = await store.add_documents(documents, collection=COLLECTION_RUNS)
        return count > 0

    # ========== 搜索方法 ==========

    async def search_hypotheses(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索相似假设

        Args:
            query: 自然语言查询（如 "AML 药物靶点"）
            top_k: 返回前 K 个结果
        Returns:
            [{"id", "text", "metadata", "similarity"}, ...]
        """
        from app.services.knowledge.vector import get_vector_store

        store = get_vector_store()
        results = await store.search(
            query=query,
            collection=COLLECTION_HYPOTHESES,
            top_k=min(max(top_k, 1), 50),
        )
        return results

    async def search_runs(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索相似运行

        Args:
            query: 自然语言查询
            top_k: 返回前 K 个结果
        Returns:
            [{"id", "text", "metadata", "similarity"}, ...]
        """
        from app.services.knowledge.vector import get_vector_store

        store = get_vector_store()
        results = await store.search(
            query=query,
            collection=COLLECTION_RUNS,
            top_k=min(max(top_k, 1), 50),
        )
        return results

    async def search_all(
        self,
        query: str,
        top_k: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """同时搜索假设和运行

        Args:
            query: 自然语言查询
            top_k: 每类返回前 K 个结果
        Returns:
            {"hypotheses": [...], "runs": [...]}
        """
        hyps = await self.search_hypotheses(query, top_k=top_k)
        runs = await self.search_runs(query, top_k=top_k)
        return {"hypotheses": hyps, "runs": runs}

    # ========== 统计方法 ==========

    async def get_stats(self) -> Dict[str, Any]:
        """获取索引统计

        Returns:
            {"collections": {"coscientist_hypotheses": {...}, "coscientist_runs": {...}},
             "note": "..."}
        """
        from app.services.knowledge.vector import get_vector_store

        store = get_vector_store()
        # VectorStore 没有直接的 count 方法，返回集合是否存在
        # 实际统计需要 ChromaDB 支持，这里返回基本信息
        return {
            "collections": {
                COLLECTION_HYPOTHESES: {"name": COLLECTION_HYPOTHESES},
                COLLECTION_RUNS: {"name": COLLECTION_RUNS},
            },
            "vector_store_available": store._client is not None,
            "note": "统计信息依赖 ChromaDB 实际连接状态",
        }

    # ========== 文本构建辅助方法 ==========

    def _build_hypothesis_text(self, h: Hypothesis) -> str:
        """构建假设的索引文本

        将假设的关键信息组合成适合向量化的文本。
        """
        parts: List[str] = []

        if h.name:
            parts.append(f"假设: {h.name}")
        if h.description:
            parts.append(f"描述: {h.description}")
        if h.mechanism:
            parts.append(f"机制: {h.mechanism}")
        if h.evolution_strategy and h.evolution_strategy != "initial":
            parts.append(f"进化策略: {h.evolution_strategy}")
        if h.elo_score is not None:
            parts.append(f"Elo评分: {h.elo_score:.0f}")
        if h.rank is not None:
            parts.append(f"排名: #{h.rank}")
        if h.novelty_score is not None:
            parts.append(f"新颖性: {h.novelty_score:.1f}")
        if h.plausibility_score is not None:
            parts.append(f"可信度: {h.plausibility_score:.1f}")

        return " | ".join(parts) if parts else "（空假设）"

    def _build_run_text(self, run: CoScientistRun) -> str:
        """构建运行的索引文本"""
        parts: List[str] = []

        if run.research_goal:
            parts.append(f"研究目标: {run.research_goal}")
        if run.case_type:
            parts.append(f"案例类型: {run.case_type}")
        if run.meta_review:
            parts.append(f"元评审: {run.meta_review}")
        if run.status:
            parts.append(f"状态: {run.status}")
        parts.append(f"轮次: {run.current_round}/{run.max_rounds}")

        return " | ".join(parts) if parts else "（空运行）"


__all__ = [
    "CoScientistIndexer",
    "COLLECTION_HYPOTHESES",
    "COLLECTION_RUNS",
]
