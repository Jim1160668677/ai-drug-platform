"""假设比较器 — 多假设并行对比与推荐

对 Sandbox 中的多个 ``Hypothesis`` 执行横向对比，输出：
- 共享靶点（shared_targets）：所有假设共同命中的靶点
- 独有靶点（unique_targets）：每个假设独占的靶点
- 推荐建议（recommendations）：基于靶点重叠度和证据分级的下一步行动
- 评分（scores）：每个假设的综合评分

设计目标：
- 配置驱动：评分权重从 ``settings`` 读取（未配置时使用默认值）
- Mock/Real 双模式：假设不存在或无 target_list 时降级返回空结果
- 完整 type hints + 中文 docstring
- 基于 ``Hypothesis`` 模型（``from app.models.hypothesis import Hypothesis``）
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.hypothesis import Hypothesis

logger = logging.getLogger(__name__)


# 默认评分权重（可在 settings 中覆盖）
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "target_count": 0.3,        # 候选靶点数量
    "unique_target_ratio": 0.3, # 独有靶点比例（创新性）
    "evidence_level": 0.2,      # 证据分级
    "analysis_completeness": 0.2, # 分析完成度
}


class HypothesisComparator:
    """多假设并行比较器

    横向对比 Sandbox 中的多个假设，识别共享/独有靶点并给出推荐。
    用于支持"多假设并行探索 → 收敛合并"的研发范式。

    Examples:
        >>> comparator = HypothesisComparator(db)
        >>> result = await comparator.compare([uuid4(), uuid4()])
        >>> "shared_targets" in result and "scores" in result
        True
    """

    def __init__(self, db: AsyncSession):
        """初始化比较器

        Args:
            db: 异步数据库会话
        """
        self.db = db

    async def compare(
        self,
        hypothesis_ids: List[UUID],
    ) -> Dict[str, Any]:
        """比较多假设

        Args:
            hypothesis_ids: 待比较的假设 ID 列表

        Returns:
            {
                "shared_targets": List[str],
                "unique_targets": {hypothesis_id: List[str]},
                "recommendations": List[str],
                "scores": {hypothesis_id: float},
                "hypotheses_summary": List[Dict],
                "status": "compared" | "no_hypotheses" | "partial",
            }
        """
        if not hypothesis_ids:
            logger.warning("假设比较：空 ID 列表")
            return {
                "shared_targets": [],
                "unique_targets": {},
                "recommendations": ["无可比较的假设"],
                "scores": {},
                "hypotheses_summary": [],
                "status": "no_hypotheses",
            }

        # 批量查询假设
        stmt = select(Hypothesis).where(Hypothesis.id.in_(hypothesis_ids))
        result = await self.db.execute(stmt)
        hypotheses: List[Hypothesis] = list(result.scalars().all())

        if not hypotheses:
            logger.warning("假设比较：未找到任何假设 %s", hypothesis_ids)
            return {
                "shared_targets": [],
                "unique_targets": {},
                "recommendations": ["未找到指定的假设"],
                "scores": {},
                "hypotheses_summary": [],
                "status": "no_hypotheses",
            }

        # 提取每个假设的靶点集合
        target_sets: Dict[str, set] = {}
        target_lists: Dict[str, List[str]] = {}
        for h in hypotheses:
            hid = str(h.id)
            tl = self._extract_target_list(h)
            target_lists[hid] = tl
            target_sets[hid] = set(tl)

        # 计算共享靶点
        shared_targets = self._compute_shared_targets(list(target_sets.values()))

        # 计算独有靶点
        unique_targets = self._compute_unique_targets(target_sets)

        # 计算评分
        scores = self._compute_scores(hypotheses, target_lists, target_sets)

        # 生成推荐
        recommendations = self._generate_recommendations(
            hypotheses, target_lists, target_sets, shared_targets, scores
        )

        # 汇总信息
        hypotheses_summary = [
            {
                "id": str(h.id),
                "name": h.name,
                "status": h.status,
                "target_count": len(target_lists[str(h.id)]),
                "score": scores.get(str(h.id), 0.0),
            }
            for h in hypotheses
        ]

        status = "compared" if len(hypotheses) == len(hypothesis_ids) else "partial"

        logger.info(
            "假设比较完成：%d/%d 假设，共享靶点 %d 个",
            len(hypotheses),
            len(hypothesis_ids),
            len(shared_targets),
        )

        return {
            "shared_targets": sorted(shared_targets),
            "unique_targets": {
                hid: sorted(targets) for hid, targets in unique_targets.items()
            },
            "recommendations": recommendations,
            "scores": scores,
            "hypotheses_summary": hypotheses_summary,
            "status": status,
        }

    # -------- 内部辅助方法 --------

    def _extract_target_list(self, hypothesis: Hypothesis) -> List[str]:
        """从 Hypothesis 中提取靶点符号列表

        优先使用 ``target_list`` 字段（JSON 列表），
        退化到 ``analysis_result`` 中的 targets，再退化到空列表。

        Args:
            hypothesis: 假设 ORM 对象

        Returns:
            靶点符号列表（字符串）
        """
        tl = hypothesis.target_list
        if tl and isinstance(tl, list):
            return [str(t) for t in tl if t]

        # 退化：从 analysis_result 中提取
        ar = hypothesis.analysis_result or {}
        targets = ar.get("targets") or []
        result: List[str] = []
        for t in targets:
            if isinstance(t, dict):
                sym = t.get("gene_symbol") or t.get("symbol") or t.get("id")
                if sym:
                    result.append(str(sym))
            elif isinstance(t, str):
                result.append(t)
        return result

    def _compute_shared_targets(self, target_sets: List[set]) -> set:
        """计算所有假设共享的靶点集合"""
        if not target_sets:
            return set()
        shared = set(target_sets[0])
        for ts in target_sets[1:]:
            shared &= ts
        return shared

    def _compute_unique_targets(
        self, target_sets: Dict[str, set]
    ) -> Dict[str, set]:
        """计算每个假设独占的靶点集合"""
        unique: Dict[str, set] = {}
        for hid, ts in target_sets.items():
            others: set = set()
            for other_hid, other_ts in target_sets.items():
                if other_hid == hid:
                    continue
                others |= other_ts
            unique[hid] = ts - others
        return unique

    def _compute_scores(
        self,
        hypotheses: List[Hypothesis],
        target_lists: Dict[str, List[str]],
        target_sets: Dict[str, set],
    ) -> Dict[str, float]:
        """为每个假设计算综合评分（0~1）

        评分维度（权重见 ``_DEFAULT_WEIGHTS``）：
        - target_count：候选靶点数量（归一化）
        - unique_target_ratio：独有靶点比例（创新性）
        - evidence_level：证据分级（A/B/C 映射为 1.0/0.7/0.4）
        - analysis_completeness：分析完成度（status 映射）

        Args:
            hypotheses: 假设列表
            target_lists: 每个假设的靶点列表
            target_sets: 每个假设的靶点集合

        Returns:
            {hypothesis_id: score}
        """
        # 权重（这里使用默认权重；P3 阶段可从 settings 读取）
        weights = _DEFAULT_WEIGHTS

        # 归一化分母
        max_target_count = max(
            (len(tl) for tl in target_lists.values()), default=1
        ) or 1

        scores: Dict[str, float] = {}
        for h in hypotheses:
            hid = str(h.id)
            tl = target_lists.get(hid, [])
            ts = target_sets.get(hid, set())

            # 维度 1：靶点数量（归一化）
            target_count_score = len(tl) / max_target_count if max_target_count else 0.0

            # 维度 2：独有靶点比例（创新性）
            total_targets = len(ts)
            others: set = set()
            for other_hid, other_ts in target_sets.items():
                if other_hid != hid:
                    others |= other_ts
            unique_targets = ts - others
            unique_ratio = (
                len(unique_targets) / total_targets if total_targets else 0.0
            )

            # 维度 3：证据分级（从 analysis_result 提取）
            ar = h.analysis_result or {}
            evidence_level = str(ar.get("evidence_level", "C")).upper()
            evidence_score = {"A": 1.0, "B": 0.7, "C": 0.4}.get(
                evidence_level, 0.4
            )

            # 维度 4：分析完成度
            status_score = {
                "completed": 1.0,
                "merged": 0.9,
                "analyzing": 0.5,
                "draft": 0.3,
                "archived": 0.2,
                "eliminated": 0.0,
            }.get(h.status, 0.3)

            score = (
                weights["target_count"] * target_count_score
                + weights["unique_target_ratio"] * unique_ratio
                + weights["evidence_level"] * evidence_score
                + weights["analysis_completeness"] * status_score
            )
            scores[hid] = round(score, 4)

        return scores

    def _generate_recommendations(
        self,
        hypotheses: List[Hypothesis],
        target_lists: Dict[str, List[str]],
        target_sets: Dict[str, set],
        shared_targets: set,
        scores: Dict[str, float],
    ) -> List[str]:
        """基于比较结果生成推荐建议"""
        recommendations: List[str] = []

        # 1. 共享靶点推荐
        if shared_targets:
            recommendations.append(
                f"发现 {len(shared_targets)} 个共享靶点，"
                "建议优先验证这些靶点（多假设共同支持，可靠性较高）"
            )
        else:
            recommendations.append(
                "各假设无共享靶点，建议评估各假设的独立创新性"
            )

        # 2. 最高分假设推荐
        if scores:
            best_hid = max(scores, key=scores.get)
            best_score = scores[best_hid]
            best_h = next((h for h in hypotheses if str(h.id) == best_hid), None)
            if best_h:
                recommendations.append(
                    f"假设 '{best_h.name}' 综合评分最高（{best_score}），"
                    "建议作为主线推进"
                )

        # 3. 独有靶点创新性提示
        for h in hypotheses:
            hid = str(h.id)
            ts = target_sets.get(hid, set())
            if not ts:
                continue
            others: set = set()
            for other_hid, other_ts in target_sets.items():
                if other_hid != hid:
                    others |= other_ts
            unique_targets = ts - others
            if len(unique_targets) >= 3:
                recommendations.append(
                    f"假设 '{h.name}' 拥有 {len(unique_targets)} 个独有靶点，"
                    "创新性较高，建议保留并行探索"
                )

        # 4. 低分假设淘汰建议
        if scores:
            avg_score = sum(scores.values()) / len(scores)
            low_score_hypotheses = [
                h
                for h in hypotheses
                if scores.get(str(h.id), 0) < avg_score * 0.5
            ]
            for h in low_score_hypotheses:
                recommendations.append(
                    f"假设 '{h.name}' 综合评分显著低于平均，"
                    f"建议归档或淘汰（status=eliminated）"
                )

        # 5. 合并建议
        if len(hypotheses) >= 2 and shared_targets:
            recommendations.append(
                "多个假设存在共享靶点，可考虑合并为单一主线假设"
                "（status=merged）以集中资源"
            )

        return recommendations
