"""治疗方案规划器 — P3 强化学习组合优化"""
import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target import Target, EvidenceGrade
from app.models.treatment import Treatment, TreatmentType, TreatmentStatus

logger = logging.getLogger(__name__)


# 证据等级 → 数值评分
GRADE_SCORE = {
    EvidenceGrade.LEVEL_I: 1.0,
    EvidenceGrade.LEVEL_II: 0.75,
    EvidenceGrade.LEVEL_III: 0.5,
    EvidenceGrade.LEVEL_IV: 0.25,
}


class TreatmentPlanner:
    """治疗方案规划器 — 多疗法组合优化

    P3 阶段：使用强化学习搜索最优疗法组合。
    P0/P1 阶段：基于规则的组合评分（证据等级 + 药物类药性）。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._torch_available = self._check_torch()

    def _check_torch(self) -> bool:
        try:
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    async def optimize(self, project_id: UUID) -> Dict[str, Any]:
        """优化治疗方案组合

        Args:
            project_id: 项目 ID
        Returns:
            {combinations, optimal, method}
        """
        # 查询项目的靶点和现有治疗方案
        targets = (await self.db.execute(
            select(Target).where(Target.project_id == project_id)
            .order_by(Target.confidence_score.desc())
        )).scalars().all()

        treatments = (await self.db.execute(
            select(Treatment).where(Treatment.project_id == project_id)
        )).scalars().all()

        if self._torch_available:
            result = await self._optimize_rl(targets, treatments)
        else:
            result = self._optimize_rule_based(targets, treatments)

        # 将推荐组合保存为 Treatment 记录（仅保存最优组合，避免重复）
        optimal = result.get("optimal")
        if optimal:
            await self._persist_optimal_treatment(project_id, optimal, targets)

        result["treatments_existing"] = len(treatments)
        return result

    async def _persist_optimal_treatment(
        self,
        project_id: UUID,
        optimal: Dict[str, Any],
        targets: List[Target],
    ) -> None:
        """将最优组合方案持久化为 Treatment 记录"""
        combo_treatments = optimal.get("treatments", [])
        if not combo_treatments:
            return

        # 构建 name 和 therapy_type
        drug_names = [t.get("drug") or t.get("target", "") for t in combo_treatments]
        name = " + ".join(drug_names) if drug_names else "优化方案"
        therapy_type = (
            TreatmentType.COMBINATION if len(combo_treatments) > 1
            else combo_treatments[0].get("type", TreatmentType.TARGETED)
        )

        # 收集关联靶点 ID
        target_symbols = {t.get("target") for t in combo_treatments if t.get("target")}
        target_ids = [
            str(t.id) for t in targets if t.gene_symbol in target_symbols
        ]

        efficacy = optimal.get("predicted_efficacy")
        risk = optimal.get("risk")
        confidence = (
            max(0.0, min(1.0, (efficacy or 0) - (risk or 0)))
            if efficacy is not None and risk is not None
            else None
        )

        treatment = Treatment(
            project_id=project_id,
            name=name,
            therapy_type=therapy_type,
            status=TreatmentStatus.PROPOSED,
            target_ids=target_ids or None,
            molecule_ids=None,
            efficacy_score=efficacy,
            risk_score=risk,
            confidence=confidence,
            config={
                "combinations": combo_treatments,
                "rationale": optimal.get("rationale"),
                "method": "optimizer",
            },
        )
        self.db.add(treatment)
        await self.db.flush()

    def _optimize_rule_based(
        self,
        targets: List[Target],
        treatments: List[Treatment],
    ) -> Dict[str, Any]:
        """基于规则的组合优化"""
        combinations: List[Dict[str, Any]] = []

        # 策略1：靶向治疗 + 免疫治疗组合
        targeted_targets = [t for t in targets if t.evidence_grade in (EvidenceGrade.LEVEL_I, EvidenceGrade.LEVEL_II)]
        if targeted_targets:
            top_target = targeted_targets[0]
            predicted_efficacy = self._estimate_efficacy(top_target, combine_with_immuno=True)
            risk = self._estimate_risk(top_target, combination=True)
            combinations.append({
                "treatments": [
                    {"type": TreatmentType.TARGETED, "target": top_target.gene_symbol, "drug": (top_target.approved_drugs or [{}])[0].get("name", "TKI")},
                    {"type": TreatmentType.IMMUNO, "target": "PD-L1", "drug": "Pembrolizumab"},
                ],
                "predicted_efficacy": predicted_efficacy,
                "risk": risk,
                "rationale": f"靶向 {top_target.gene_symbol}（证据等级 {top_target.evidence_grade}）联合免疫检查点抑制",
            })

        # 策略2：单药靶向治疗
        if targeted_targets:
            top_target = targeted_targets[0]
            predicted_efficacy = self._estimate_efficacy(top_target, combine_with_immuno=False)
            risk = self._estimate_risk(top_target, combination=False)
            combinations.append({
                "treatments": [
                    {"type": TreatmentType.TARGETED, "target": top_target.gene_symbol, "drug": (top_target.approved_drugs or [{}])[0].get("name", "TKI")},
                ],
                "predicted_efficacy": predicted_efficacy,
                "risk": risk,
                "rationale": f"单药靶向 {top_target.gene_symbol}，安全性较高",
            })

        # 策略3：化疗 + 靶向（如果存在 III 级证据靶点）
        grade3_targets = [t for t in targets if t.evidence_grade == EvidenceGrade.LEVEL_III]
        if grade3_targets:
            t3 = grade3_targets[0]
            combinations.append({
                "treatments": [
                    {"type": TreatmentType.CHEMO, "drug": "Carboplatin+Pemetrexed"},
                    {"type": TreatmentType.TARGETED, "target": t3.gene_symbol},
                ],
                "predicted_efficacy": 0.55,
                "risk": 0.45,
                "rationale": f"化疗联合 {t3.gene_symbol} 靶向探索（III 级证据）",
            })

        # 排序选最优
        combinations.sort(key=lambda x: x["predicted_efficacy"] - x["risk"], reverse=True)
        optimal = combinations[0] if combinations else None

        return {
            "combinations": combinations,
            "optimal": optimal,
            "method": "rule_based",
            "note": "P3 启用 PyTorch 后将使用强化学习优化" if not self._torch_available else None,
            "targets_considered": len(targets),
            "treatments_existing": len(treatments),
        }

    async def _optimize_rl(
        self,
        targets: List[Target],
        treatments: List[Treatment],
    ) -> Dict[str, Any]:
        """强化学习组合优化（P3 框架）"""
        # P3 框架：先调规则方法，再标注 RL 可用
        rule_result = self._optimize_rule_based(targets, treatments)
        rule_result["method"] = "rl_framework"
        rule_result["note"] = "PyTorch 可用，P3 强化学习框架已加载，当前降级为规则评分"
        return rule_result

    def _estimate_efficacy(self, target: Target, combine_with_immuno: bool = False) -> float:
        """估算疗效评分（0-1）"""
        grade_score = GRADE_SCORE.get(target.evidence_grade, 0.25)
        confidence = target.confidence_score or 0.5
        efficacy = grade_score * 0.5 + confidence * 0.5
        if combine_with_immuno:
            efficacy = min(1.0, efficacy + 0.15)
        return round(efficacy, 3)

    def _estimate_risk(self, target: Target, combination: bool = False) -> float:
        """估算风险评分（0-1）"""
        base_risk = 0.2
        if combination:
            base_risk += 0.15
        if target.evidence_grade in (EvidenceGrade.LEVEL_III, EvidenceGrade.LEVEL_IV):
            base_risk += 0.1
        return round(min(base_risk, 0.8), 3)

    # ========== Pareto 前沿 + Q-learning + UCB（spec 要求）==========

    def _pareto_front(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算 Pareto 前沿 — 多目标优化（疗效↑ + 风险↓）

        Args:
            candidates: [{"predicted_efficacy", "risk", ...}]
        Returns:
            Pareto 最优解集合
        """
        if not candidates:
            return []
        front = []
        for i, c in enumerate(candidates):
            eff_i = c.get("predicted_efficacy", 0)
            risk_i = c.get("risk", 1)
            dominated = False
            for j, other in enumerate(candidates):
                if i == j:
                    continue
                eff_j = other.get("predicted_efficacy", 0)
                risk_j = other.get("risk", 1)
                # other 支配 c：疗效 >= 且风险 <=，且至少一个严格 <
                if eff_j >= eff_i and risk_j <= risk_i and (eff_j > eff_i or risk_j < risk_i):
                    dominated = True
                    break
            if not dominated:
                front.append(c)
        return front

    def _q_update(
        self,
        q_table: Dict[str, float],
        state: str,
        action: str,
        reward: float,
        alpha: float = 0.1,
        gamma: float = 0.9,
    ) -> Dict[str, float]:
        """Q-learning 更新

        Q(s,a) ← Q(s,a) + α [r + γ max_a' Q(s',a') - Q(s,a)]

        Args:
            q_table: Q 表 {state_action: value}
            state: 当前状态
            action: 采取的动作
            reward: 获得的奖励
            alpha: 学习率
            gamma: 折扣因子
        Returns:
            更新后的 Q 表
        """
        key = f"{state}:{action}"
        current = q_table.get(key, 0.0)
        # 简化：假设下一状态的最大 Q 值为 0（无转移信息）
        td_target = reward
        td_error = td_target - current
        q_table[key] = current + alpha * td_error
        return q_table

    def _ucb_select(
        self,
        candidates: List[Dict[str, Any]],
        q_table: Dict[str, float],
        visit_counts: Dict[str, int],
        c: float = 1.414,
    ) -> Dict[str, Any]:
        """UCB（Upper Confidence Bound）选择

        balance exploitation（Q 值）和 exploration（访问次数少）

        Args:
            candidates: 候选方案列表
            q_table: Q 表
            visit_counts: {action: n}
            c: 探索常数（默认 sqrt(2)）
        Returns:
            UCB 值最高的候选
        """
        import math

        total_visits = sum(visit_counts.values()) or 1
        best_score = -float("inf")
        best = candidates[0] if candidates else None
        for cand in candidates:
            action = cand.get("rationale", str(cand))
            q_value = q_table.get(action, 0.0)
            n = visit_counts.get(action, 0)
            if n == 0:
                return cand  # 未访问的优先探索
            ucb = q_value + c * math.sqrt(math.log(total_visits) / n)
            if ucb > best_score:
                best_score = ucb
                best = cand
        return best


# 别名 — spec 期望类名 TreatmentOptimizer
TreatmentOptimizer = TreatmentPlanner
