"""假设进化策略决策器 — Co-Scientist 核心算法

基于 Nature 论文 Co-Scientist 的假设进化机制（Enhancement/Combination/Simplification）。

设计要点：
- 纯启发式决策器（无需 LLM），根据 Reflection 和 Proximity 结果触发策略
- Enhancement: 假设有 >= 2 个 severity >= 7 的 flaws → LLM 改进
- Combination: 两假设 similarity > 0.7 且机制互补 → LLM 融合
- Simplification: Testability < 5 或描述 > 500 字 → LLM 简化
- Keep: 无上述触发（对照组，保持不变）

实际进化执行由 EvolutionAgent（P3）完成，本模块只负责策略决策。

参考论文：Section "Evolution process" + Extended Data Fig. 5
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EvolutionPlan:
    """单个假设的进化计划"""
    hypothesis_id: str
    strategy: str  # enhancement / combination / simplification / keep
    target_hypothesis_id: Optional[str] = None  # Combination 时的搭档假设 ID
    flaws: List[Dict[str, Any]] = field(default_factory=list)  # Enhancement 时的缺陷列表
    similarity: Optional[float] = None  # Combination 时的相似度
    complexity_issues: List[str] = field(default_factory=list)  # Simplification 时的问题
    reason: str = ""  # 触发原因说明


class EvolutionStrategist:
    """假设进化策略决策器

    用法：
        strategist = EvolutionStrategist()
        plans = strategist.decide_strategies(hypotheses, critiques, proximity_result)
        # plans 是每个假设的进化计划列表
    """

    def __init__(
        self,
        severity_threshold: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        complexity_len_threshold: Optional[int] = None,
        testability_threshold: float = 5.0,
    ):
        self.severity_threshold = severity_threshold or getattr(
            settings, "COSCIENTIST_EVOLUTION_SEVERITY_THRESHOLD", 7
        )
        self.similarity_threshold = similarity_threshold or getattr(
            settings, "COSCIENTIST_EVOLUTION_SIMILARITY_THRESHOLD", 0.7
        )
        self.complexity_len_threshold = complexity_len_threshold or getattr(
            settings, "COSCIENTIST_EVOLUTION_COMPLEXITY_LEN_THRESHOLD", 500
        )
        self.testability_threshold = testability_threshold

    def decide_strategies(
        self,
        hypotheses: List[Dict[str, Any]],
        critiques: List[Dict[str, Any]],
        proximity_result: Optional[Dict[str, Any]] = None,
    ) -> List[EvolutionPlan]:
        """为每个假设决定进化策略

        Args:
            hypotheses: 假设列表
            critiques: ReflectionAgent 的批判结果
                [{hypothesis_id, flaws: [{description, severity}], ...}]
            proximity_result: ProximityAgent 的相似度结果
                {pairs: [{id_a, id_b, semantic_similarity, recommendation}]}
        Returns:
            进化计划列表（每个假设一个）
        """
        # 构建 critique 查找表
        critique_map: Dict[str, Dict[str, Any]] = {}
        for c in critiques:
            hid = str(c.get("hypothesis_id", ""))
            critique_map[hid] = c

        # 构建相似度查找表
        similarity_map: Dict[str, List[tuple]] = {}
        if proximity_result and "pairs" in proximity_result:
            for pair in proximity_result["pairs"]:
                id_a = str(pair.get("id_a", ""))
                id_b = str(pair.get("id_b", ""))
                sim = float(pair.get("semantic_similarity", 0.0))
                rec = pair.get("recommendation", "keep_separate")
                if id_a not in similarity_map:
                    similarity_map[id_a] = []
                if id_b not in similarity_map:
                    similarity_map[id_b] = []
                similarity_map[id_a].append((id_b, sim, rec))
                similarity_map[id_b].append((id_a, sim, rec))

        plans: List[EvolutionPlan] = []
        used_in_combination: set = set()

        for hyp in hypotheses:
            hyp_id = str(hyp.get("id", hyp.get("name", "")))
            plan = self._decide_single(
                hyp, hyp_id, critique_map, similarity_map, used_in_combination
            )
            plans.append(plan)

        return plans

    def _decide_single(
        self,
        hypothesis: Dict[str, Any],
        hyp_id: str,
        critique_map: Dict[str, Dict[str, Any]],
        similarity_map: Dict[str, List[tuple]],
        used_in_combination: set,
    ) -> EvolutionPlan:
        """为单个假设决定进化策略

        优先级：Combination > Enhancement > Simplification > Keep
        """
        # 1. 检查 Combination（合并）— 两假设相似度高且推荐合并
        if hyp_id in similarity_map and hyp_id not in used_in_combination:
            for partner_id, sim, rec in similarity_map[hyp_id]:
                if (
                    sim >= self.similarity_threshold
                    and rec == "merge"
                    and partner_id not in used_in_combination
                ):
                    used_in_combination.add(hyp_id)
                    used_in_combination.add(partner_id)
                    return EvolutionPlan(
                        hypothesis_id=hyp_id,
                        strategy="combination",
                        target_hypothesis_id=partner_id,
                        similarity=sim,
                        reason=f"与假设 {partner_id} 相似度 {sim:.2f}，推荐合并",
                    )

        # 2. 检查 Enhancement（增强）— 有高严重度缺陷
        critique = critique_map.get(hyp_id, {})
        flaws = critique.get("flaws", [])
        severe_flaws = [
            f for f in flaws
            if int(f.get("severity", 0)) >= self.severity_threshold
        ]
        if len(severe_flaws) >= 2:
            return EvolutionPlan(
                hypothesis_id=hyp_id,
                strategy="enhancement",
                flaws=severe_flaws,
                reason=f"发现 {len(severe_flaws)} 个严重缺陷（severity>={self.severity_threshold}）",
            )

        # 3. 检查 Simplification（简化）— 可测试性低或描述过长
        testability = float(hypothesis.get("testability_score", 10.0))
        description = hypothesis.get("description", "") or ""
        complexity_issues = []

        if testability < self.testability_threshold:
            complexity_issues.append(
                f"可测试性评分 {testability} 低于阈值 {self.testability_threshold}"
            )

        if len(description) > self.complexity_len_threshold:
            complexity_issues.append(
                f"描述长度 {len(description)} 超过阈值 {self.complexity_len_threshold}"
            )

        if complexity_issues:
            return EvolutionPlan(
                hypothesis_id=hyp_id,
                strategy="simplification",
                complexity_issues=complexity_issues,
                reason="; ".join(complexity_issues),
            )

        # 4. Keep（保持不变）
        return EvolutionPlan(
            hypothesis_id=hyp_id,
            strategy="keep",
            reason="无需进化（无严重缺陷、无高相似度对、复杂度正常）",
        )

    def summarize_plans(self, plans: List[EvolutionPlan]) -> Dict[str, int]:
        """统计各策略的假设数量"""
        summary = {"enhancement": 0, "combination": 0, "simplification": 0, "keep": 0}
        for plan in plans:
            if plan.strategy in summary:
                summary[plan.strategy] += 1
        return summary
