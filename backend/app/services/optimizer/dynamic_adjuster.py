"""动态调整器 — P3 根据疗效实时调整治疗方案

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/优化器服务层.md

RL 状态/动作/奖励建模：
- state: (efficacy_bucket, trend_bucket, ae_bucket)
- action: {maintain, increase_dose, decrease_dose, add_combination, switch}
- reward: efficacy_improvement - ae_penalty
"""
import logging
from typing import Any, Dict, List, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)


class DynamicAdjuster:
    """动态治疗方案调整器

    P3 阶段：根据实时疗效数据流，使用 RL 动态调整药物剂量/组合。
    P0/P1 阶段：基于规则的静态调整建议 + RL 状态建模框架。
    """

    def __init__(self):
        self._q_table: Dict[str, float] = {}
        self._visit_counts: Dict[str, int] = {}

    async def adjust(
        self,
        treatment_id: UUID,
        efficacy_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据疗效数据动态调整治疗方案

        Args:
            treatment_id: 治疗方案 ID
            efficacy_data: {current_efficacy, trend, adverse_events, ...}
        Returns:
            {adjustment, reason, new_config, urgency, rl_state, rl_action}
        """
        current_efficacy = efficacy_data.get("current_efficacy", 0)
        trend = efficacy_data.get("trend", "stable")
        adverse_events = efficacy_data.get("adverse_events", [])

        # 1. RL 状态建模
        rl_state = self._rl_state(efficacy_data)
        rl_action = self._rl_action(rl_state)
        rl_reward = self._rl_reward(efficacy_data)

        # 2. Q-learning 更新
        self._q_update(rl_state, rl_action, rl_reward)

        # 3. 规则建议（保兼容）
        adjustments = []
        urgency = "low"
        if current_efficacy < 0.3:
            adjustments.append("考虑更换治疗方案或增加剂量")
            urgency = "high"
        elif current_efficacy < 0.5 and trend == "declining":
            adjustments.append("疗效下降，建议联合用药")
            urgency = "medium"
        if len(adverse_events) >= 3:
            adjustments.append("不良反应较多，建议降低剂量")
            urgency = "high" if urgency != "high" else "critical"
        elif adverse_events:
            adjustments.append("监测不良反应，必要时调整")
        if trend == "improving" and current_efficacy > 0.7:
            adjustments.append("疗效良好且持续改善，维持当前方案")
        elif trend == "stable" and current_efficacy > 0.5:
            adjustments.append("疗效稳定，维持当前方案")

        # 4. RL 动作映射到建议
        action_map = {
            "maintain": "维持当前方案",
            "increase_dose": "增加剂量",
            "decrease_dose": "降低剂量",
            "add_combination": "联合用药",
            "switch": "更换治疗方案",
        }
        rl_suggestion = action_map.get(rl_action, "维持当前方案")
        if rl_suggestion not in adjustments:
            adjustments.append(f"[RL] {rl_suggestion}")

        new_config = efficacy_data.get("current_config", {})
        if adjustments:
            new_config = {**new_config, "adjustment_notes": adjustments[0]}

        return {
            "treatment_id": str(treatment_id),
            "adjustments": adjustments,
            "reason": adjustments[0] if adjustments else "无需调整",
            "new_config": new_config,
            "urgency": urgency,
            "current_efficacy": current_efficacy,
            "trend": trend,
            "method": "rl_with_rules",
            "rl_state": rl_state,
            "rl_action": rl_action,
            "rl_reward": rl_reward,
            "q_value": self._q_table.get(f"{rl_state}:{rl_action}", 0.0),
        }

    def _rl_state(self, efficacy_data: Dict[str, Any]) -> str:
        """RL 状态编码 — (efficacy_bucket, trend_bucket, ae_bucket)"""
        eff = efficacy_data.get("current_efficacy", 0)
        if eff < 0.3:
            eff_bucket = "low"
        elif eff < 0.7:
            eff_bucket = "mid"
        else:
            eff_bucket = "high"

        trend = efficacy_data.get("trend", "stable")
        trend_bucket = trend[:3]  # "imp"/"dec"/"sta"/"ins"

        ae_count = len(efficacy_data.get("adverse_events", []))
        if ae_count == 0:
            ae_bucket = "none"
        elif ae_count < 3:
            ae_bucket = "few"
        else:
            ae_bucket = "many"

        return f"{eff_bucket}_{trend_bucket}_{ae_bucket}"

    def _rl_action(self, state: str) -> str:
        """RL 动作选择 — ε-贪心"""
        import random

        # 10% 探索
        if random.random() < 0.1:
            actions = ["maintain", "increase_dose", "decrease_dose", "add_combination", "switch"]
            return random.choice(actions)

        # 90% 利用：选 Q 值最高的动作
        actions = ["maintain", "increase_dose", "decrease_dose", "add_combination", "switch"]
        best_action = "maintain"
        best_q = -float("inf")
        for action in actions:
            q = self._q_table.get(f"{state}:{action}", 0.0)
            if q > best_q:
                best_q = q
                best_action = action
        return best_action

    def _rl_reward(self, efficacy_data: Dict[str, Any]) -> float:
        """RL 奖励函数 — efficacy_improvement - ae_penalty"""
        eff = efficacy_data.get("current_efficacy", 0)
        ae_count = len(efficacy_data.get("adverse_events", []))
        trend = efficacy_data.get("trend", "stable")

        # 疗效奖励
        reward = eff * 10
        if trend == "improving":
            reward += 2
        elif trend == "declining":
            reward -= 2

        # AE 惩罚
        reward -= ae_count * 0.5

        return round(reward, 4)

    def _q_update(
        self,
        state: str,
        action: str,
        reward: float,
        alpha: float = 0.1,
        gamma: float = 0.9,
    ) -> None:
        """Q-learning 更新（in-place）"""
        key = f"{state}:{action}"
        current = self._q_table.get(key, 0.0)
        # 简化：无下一状态转移信息
        td_target = reward
        td_error = td_target - current
        self._q_table[key] = current + alpha * td_error
        self._visit_counts[key] = self._visit_counts.get(key, 0) + 1
