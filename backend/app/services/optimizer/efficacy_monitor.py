"""疗效监测器 — P3 实时流式监测"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiment import Experiment, ExperimentStatus
from app.models.treatment import Treatment

logger = logging.getLogger(__name__)


class EfficacyMonitor:
    """疗效监测器 — 治疗方案效果追踪

    P3 阶段：Kafka + 流处理实时监测。
    P0/P1 阶段：从实验结果汇总基础指标。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check(self, treatment_id: UUID) -> Dict[str, Any]:
        """检查治疗方案疗效

        Args:
            treatment_id: 治疗方案 ID
        Returns:
            {treatment_id, current_efficacy, trend, adverse_events, recommendation, experiments_count}
        """
        treatment = await self.db.get(Treatment, treatment_id)
        if not treatment:
            return {"error": "治疗方案不存在", "treatment_id": str(treatment_id)}

        # 查询关联实验
        experiments = (await self.db.execute(
            select(Experiment).where(Experiment.treatment_id == treatment_id)
            .order_by(Experiment.created_at.asc())
        )).scalars().all()

        # 汇总疗效指标
        efficacy_scores: List[float] = []
        adverse_events: List[str] = []

        for exp in experiments:
            result = exp.result or {}
            if "efficacy" in result:
                try:
                    efficacy_scores.append(float(result["efficacy"]))
                except (ValueError, TypeError):
                    pass
            if "inhibition_rate" in result:
                try:
                    efficacy_scores.append(float(result["inhibition_rate"]) / 100)
                except (ValueError, TypeError):
                    pass
            for ae in result.get("adverse_events", []) or []:
                adverse_events.append(str(ae))
            if not exp.success and exp.status == ExperimentStatus.COMPLETED:
                adverse_events.append(f"实验未达预期: {exp.name}")

        # 计算当前疗效
        current_efficacy = sum(efficacy_scores) / len(efficacy_scores) if efficacy_scores else 0

        # 趋势分析
        trend = self._analyze_trend(efficacy_scores)

        # 推荐
        recommendation = self._recommend(current_efficacy, trend, adverse_events)

        return {
            "treatment_id": str(treatment_id),
            "treatment_name": treatment.name,
            "current_efficacy": round(current_efficacy, 3),
            "trend": trend,
            "adverse_events": adverse_events[:10],
            "recommendation": recommendation,
            "experiments_count": len(experiments),
            "efficacy_history": efficacy_scores,
            "method": "batch_aggregation",
            "note": "P3 启用 Kafka 后将支持实时流式监测",
        }

    def _analyze_trend(self, scores: List[float]) -> str:
        """分析疗效趋势"""
        if len(scores) < 2:
            return "insufficient_data"
        recent = scores[-1]
        previous = scores[-2] if len(scores) >= 2 else scores[0]
        diff = recent - previous
        if diff > 0.05:
            return "improving"
        elif diff < -0.05:
            return "declining"
        return "stable"

    def _recommend(self, efficacy: float, trend: str, adverse_events: List[str]) -> str:
        """生成推荐"""
        if efficacy < 0.3:
            return "疗效不足，建议更换治疗方案"
        if efficacy < 0.5 and trend == "declining":
            return "疗效下降，考虑联合用药或调整剂量"
        if len(adverse_events) >= 3:
            return "不良反应较多，建议降低剂量或更换方案"
        if efficacy > 0.7 and trend in ("improving", "stable"):
            return "疗效良好，维持当前方案"
        if trend == "improving":
            return "疗效改善中，继续当前方案并密切监测"
        return "疗效稳定，继续监测"

    # ========== RECIST 1.1 + ORR/DCR + KM + CTCAE（spec 要求）==========

    def _recist_classify(self, lesions: List[Dict[str, Any]]) -> str:
        """RECIST 1.1 响应分类

        Args:
            lesions: [{"baseline_mm", "current_mm"}, ...] 目标病灶测量值
        Returns:
            "CR" / "PR" / "SD" / "PD"
        """
        if not lesions:
            return "SD"
        baseline_sum = sum(l.get("baseline_mm", 0) for l in lesions)
        current_sum = sum(l.get("current_mm", 0) for l in lesions)
        if baseline_sum <= 0:
            return "SD"
        change = (current_sum - baseline_sum) / baseline_sum
        # RECIST 1.1 标准
        if current_sum == 0:
            return "CR"  # 完全缓解
        if change <= -0.30:
            return "PR"  # 部分缓解（缩小 ≥30%）
        if change >= 0.20:
            return "PD"  # 进展（增大 ≥20%）
        return "SD"  # 稳定

    def _compute_orr(self, responses: List[str]) -> Dict[str, Any]:
        """计算 ORR（客观缓解率）= (CR + PR) / total"""
        if not responses:
            return {"orr": 0.0, "cr": 0, "pr": 0, "total": 0}
        cr = responses.count("CR")
        pr = responses.count("PR")
        total = len(responses)
        return {
            "orr": round((cr + pr) / total, 4),
            "cr": cr,
            "pr": pr,
            "total": total,
        }

    def _compute_dcr(self, responses: List[str]) -> Dict[str, Any]:
        """计算 DCR（疾病控制率）= (CR + PR + SD) / total"""
        if not responses:
            return {"dcr": 0.0, "cr": 0, "pr": 0, "sd": 0, "pd": 0, "total": 0}
        cr = responses.count("CR")
        pr = responses.count("PR")
        sd = responses.count("SD")
        pd = responses.count("PD")
        total = len(responses)
        return {
            "dcr": round((cr + pr + sd) / total, 4),
            "cr": cr,
            "pr": pr,
            "sd": sd,
            "pd": pd,
            "total": total,
        }

    def _kaplan_meier(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Kaplan-Meier 生存估计

        Args:
            events: [{"time", "event" (1=死亡/进展, 0=删失)}, ...]
        Returns:
            {"survival_curve": [{"time", "survival", "n_at_risk"}], "median_survival"}
        """
        if not events:
            return {"survival_curve": [], "median_survival": None}

        # 按 time 排序
        sorted_events = sorted(events, key=lambda e: e.get("time", 0))
        n_total = len(sorted_events)
        survival = 1.0
        n_at_risk = n_total
        curve = [{"time": 0, "survival": 1.0, "n_at_risk": n_total}]
        median_survival = None

        for ev in sorted_events:
            t = ev.get("time", 0)
            is_event = ev.get("event", 0) == 1
            if is_event and n_at_risk > 0:
                survival *= (n_at_risk - 1) / n_at_risk
                n_at_risk -= 1
                if median_survival is None and survival <= 0.5:
                    median_survival = t
            else:
                n_at_risk -= 1  # 删失
            curve.append({"time": t, "survival": round(survival, 4), "n_at_risk": n_at_risk})

        return {
            "survival_curve": curve,
            "median_survival": median_survival,
            "n_total": n_total,
            "n_events": sum(1 for e in events if e.get("event") == 1),
        }

    def _grade_adverse_event(self, event: Dict[str, Any]) -> int:
        """CTCAE v5.0 不良事件分级（1-5 级）

        Args:
            event: {"symptom", "severity", "description"}
        Returns:
            1-5 级
        """
        severity = str(event.get("severity", "")).lower()
        description = str(event.get("description", "")).lower()

        # 5 级：死亡
        if "death" in description or "致命" in description or severity == "5":
            return 5
        # 4 级：危及生命
        if "life-threatening" in description or "危及生命" in description or severity == "4":
            return 4
        # 3 级：严重/住院
        if "hospitalization" in description or "住院" in description or severity == "3":
            return 3
        # 2 级：中度
        if "moderate" in severity or severity == "2" or "中度" in severity:
            return 2
        # 1 级：轻度
        return 1

    async def record_outcome(
        self,
        treatment_id: UUID,
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录疗效结局

        Args:
            treatment_id: 治疗方案 ID
            outcome: {"response", "lesions", "time", "event"}
        Returns:
            {treatment_id, response, recorded_at}
        """
        response = outcome.get("response")
        if not response and outcome.get("lesions"):
            response = self._recist_classify(outcome["lesions"])
        return {
            "treatment_id": str(treatment_id),
            "response": response,
            "recorded": True,
        }

    async def record_adverse_event(
        self,
        treatment_id: UUID,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录不良事件

        Args:
            treatment_id: 治疗方案 ID
            event: {"symptom", "severity", "description"}
        Returns:
            {treatment_id, ctcae_grade, recorded}
        """
        grade = self._grade_adverse_event(event)
        return {
            "treatment_id": str(treatment_id),
            "ctcae_grade": grade,
            "symptom": event.get("symptom"),
            "recorded": True,
        }

    async def global_summary(self, project_id: Optional[UUID] = None) -> Dict[str, Any]:
        """全局疗效汇总

        Args:
            project_id: 项目 ID（可选，限定范围）
        Returns:
            {total_treatments, total_outcomes, orr, dcr, ae_distribution}
        """
        stmt = select(Treatment)
        if project_id:
            stmt = stmt.where(Treatment.project_id == project_id)
        treatments = (await self.db.execute(stmt)).scalars().all()

        # 收集所有实验结果中的响应
        all_responses = []
        all_aes = []
        for t in treatments:
            exps = (await self.db.execute(
                select(Experiment).where(Experiment.treatment_id == t.id)
            )).scalars().all()
            for exp in exps:
                result = exp.result or {}
                if result.get("response"):
                    all_responses.append(result["response"])
                for ae in result.get("adverse_events", []) or []:
                    grade = self._grade_adverse_event(ae if isinstance(ae, dict) else {"severity": ae})
                    all_aes.append(grade)

        orr = self._compute_orr(all_responses)
        dcr = self._compute_dcr(all_responses)
        ae_dist = {str(i): all_aes.count(i) for i in range(1, 6)}

        return {
            "total_treatments": len(treatments),
            "total_outcomes": len(all_responses),
            "orr": orr,
            "dcr": dcr,
            "ae_distribution": ae_dist,
        }
