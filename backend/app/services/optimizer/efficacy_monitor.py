"""疗效监测器 — P3 实时流式监测"""
import logging
from datetime import datetime, timezone
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
        """检查治疗方案疗效（整合实验结果 + 持久化监测数据）

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
        recist_responses: List[str] = []

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
            if result.get("response"):
                recist_responses.append(result["response"])
            for ae in result.get("adverse_events", []) or []:
                adverse_events.append(str(ae))
            if not exp.success and exp.status == ExperimentStatus.COMPLETED:
                adverse_events.append(f"实验未达预期: {exp.name}")

        # 合并持久化监测数据
        monitoring = treatment.monitoring_data or {}
        for outcome in monitoring.get("outcomes", []) or []:
            if outcome.get("response"):
                recist_responses.append(outcome["response"])
            if outcome.get("efficacy") is not None:
                try:
                    efficacy_scores.append(float(outcome["efficacy"]))
                except (ValueError, TypeError):
                    pass
        for ae in monitoring.get("adverse_events", []) or []:
            symptom = ae.get("symptom")
            if symptom:
                adverse_events.append(f"{symptom} (CTCAE {ae.get('ctcae_grade', '?')}级)")

        # 计算当前疗效
        current_efficacy = sum(efficacy_scores) / len(efficacy_scores) if efficacy_scores else 0

        # 趋势分析
        trend = self._analyze_trend(efficacy_scores)

        # RECIST 汇总
        orr_info = self._compute_orr(recist_responses)
        dcr_info = self._compute_dcr(recist_responses)

        # 推荐
        recommendation = self._recommend(current_efficacy, trend, adverse_events)

        return {
            "treatment_id": str(treatment_id),
            "treatment_name": treatment.name,
            "current_efficacy": round(current_efficacy, 3),
            "trend": trend,
            "adverse_events": adverse_events[:10],
            "adverse_events_count": len(adverse_events),
            "recommendation": recommendation,
            "experiments_count": len(experiments),
            "efficacy_history": efficacy_scores,
            "recist_summary": {
                "responses": recist_responses,
                "orr": orr_info["orr"],
                "dcr": dcr_info["dcr"],
                "cr": orr_info["cr"],
                "pr": orr_info["pr"],
                "sd": dcr_info["sd"],
                "pd": dcr_info["pd"],
            },
            "monitoring_records": {
                "outcomes": len(monitoring.get("outcomes", [])),
                "adverse_events": len(monitoring.get("adverse_events", [])),
                "last_updated": monitoring.get("last_updated"),
            },
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
        """记录疗效结局（持久化到 Treatment.monitoring_data）

        Args:
            treatment_id: 治疗方案 ID
            outcome: {"response", "lesions", "time", "event"}
        Returns:
            {treatment_id, response, recorded_at, outcome_id}
        """
        treatment = await self.db.get(Treatment, treatment_id)
        if not treatment:
            return {"error": "治疗方案不存在", "treatment_id": str(treatment_id)}

        response = outcome.get("response")
        if not response and outcome.get("lesions"):
            response = self._recist_classify(outcome["lesions"])

        recorded_at = datetime.now(timezone.utc).isoformat()
        record = {
            "id": str(UUID(int=len((treatment.monitoring_data or {}).get("outcomes", [])))),
            "response": response,
            "lesions": outcome.get("lesions"),
            "time": outcome.get("time"),
            "event": outcome.get("event"),
            "recorded_at": recorded_at,
        }

        # 持久化到 monitoring_data.outcomes 列表
        monitoring = treatment.monitoring_data or {}
        outcomes_list = monitoring.get("outcomes", [])
        outcomes_list.append(record)
        monitoring["outcomes"] = outcomes_list
        # 更新汇总统计
        all_responses = [o.get("response") for o in outcomes_list if o.get("response")]
        monitoring["orr"] = self._compute_orr(all_responses)
        monitoring["dcr"] = self._compute_dcr(all_responses)
        monitoring["last_updated"] = recorded_at
        treatment.monitoring_data = monitoring

        await self.db.flush()
        logger.info(
            "记录疗效结局: treatment=%s response=%s (累计 %d 条)",
            treatment_id, response, len(outcomes_list),
        )

        return {
            "treatment_id": str(treatment_id),
            "response": response,
            "recorded": True,
            "recorded_at": recorded_at,
            "outcome_id": record["id"],
            "total_outcomes": len(outcomes_list),
        }

    async def record_adverse_event(
        self,
        treatment_id: UUID,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录不良事件（持久化到 Treatment.monitoring_data）

        Args:
            treatment_id: 治疗方案 ID
            event: {"symptom", "severity", "description"}
        Returns:
            {treatment_id, ctcae_grade, symptom, recorded_at, total_ae}
        """
        treatment = await self.db.get(Treatment, treatment_id)
        if not treatment:
            return {"error": "治疗方案不存在", "treatment_id": str(treatment_id)}

        grade = self._grade_adverse_event(event)
        recorded_at = datetime.now(timezone.utc).isoformat()
        record = {
            "symptom": event.get("symptom"),
            "severity": event.get("severity"),
            "description": event.get("description"),
            "ctcae_grade": grade,
            "recorded_at": recorded_at,
        }

        # 持久化到 monitoring_data.adverse_events 列表
        monitoring = treatment.monitoring_data or {}
        ae_list = monitoring.get("adverse_events", [])
        ae_list.append(record)
        monitoring["adverse_events"] = ae_list
        # 更新 AE 分级分布
        all_grades = [ae.get("ctcae_grade", 1) for ae in ae_list]
        monitoring["ae_distribution"] = {str(i): all_grades.count(i) for i in range(1, 6)}
        monitoring["last_updated"] = recorded_at
        treatment.monitoring_data = monitoring

        await self.db.flush()
        logger.info(
            "记录不良事件: treatment=%s grade=%d symptom=%s (累计 %d 条)",
            treatment_id, grade, event.get("symptom"), len(ae_list),
        )

        return {
            "treatment_id": str(treatment_id),
            "ctcae_grade": grade,
            "symptom": event.get("symptom"),
            "recorded": True,
            "recorded_at": recorded_at,
            "total_adverse_events": len(ae_list),
        }

    async def global_summary(self, project_id: Optional[UUID] = None) -> Dict[str, Any]:
        """全局疗效汇总

        Args:
            project_id: 项目 ID（可选，限定范围）
        Returns:
            {total_treatments, total_outcomes, overall_orr, overall_dcr,
             median_pfs_days, median_os_days, ae_distribution, by_target, records}
        """
        stmt = select(Treatment)
        if project_id:
            stmt = stmt.where(Treatment.project_id == project_id)
        treatments = (await self.db.execute(stmt)).scalars().all()

        # 收集所有实验结果中的响应
        all_responses: List[str] = []
        all_aes: List[int] = []
        # 按靶点分组
        by_target: Dict[str, Dict[str, Any]] = {}
        # 记录列表（用于前端展示）
        records: List[Dict[str, Any]] = []
        # 生存时间样本（用于估算中位 PFS / OS）
        pfs_samples: List[float] = []
        os_samples: List[float] = []

        for t in treatments:
            exps = (await self.db.execute(
                select(Experiment).where(Experiment.treatment_id == t.id)
                .order_by(Experiment.created_at.asc())
            )).scalars().all()
            target_key = (
                getattr(t, "target_name", None)
                or getattr(t, "name", None)
                or f"treatment-{str(t.id)[:8]}"
            )
            target_bucket = by_target.setdefault(
                target_key, {"count": 0, "responses": [], "aes": 0}
            )
            for exp in exps:
                result = exp.result or {}
                response = result.get("response")
                if response:
                    all_responses.append(response)
                    target_bucket["responses"].append(response)
                # 收集不良事件
                ae_list = result.get("adverse_events", []) or []
                for ae in ae_list:
                    grade = self._grade_adverse_event(ae if isinstance(ae, dict) else {"severity": ae})
                    all_aes.append(grade)
                    target_bucket["aes"] += 1
                # 生存时间样本
                if result.get("pfs_days") is not None:
                    try:
                        pfs_samples.append(float(result["pfs_days"]))
                    except (ValueError, TypeError):
                        pass
                if result.get("os_days") is not None:
                    try:
                        os_samples.append(float(result["os_days"]))
                    except (ValueError, TypeError):
                        pass
                # 构造记录条目
                follow_up_days = result.get("follow_up_days") or result.get("time") or result.get("days")
                records.append({
                    "id": str(exp.id),
                    "treatment_id": str(t.id),
                    "treatment_name": getattr(t, "name", None),
                    "target_name": target_key if target_key != f"treatment-{str(t.id)[:8]}" else None,
                    "recist_response": response,
                    "follow_up_days": follow_up_days,
                    "adverse_events": ae_list if isinstance(ae_list, list) else [],
                    "created_at": exp.created_at.isoformat() if exp.created_at else None,
                })

        orr_info = self._compute_orr(all_responses)
        dcr_info = self._compute_dcr(all_responses)
        ae_dist = {str(i): all_aes.count(i) for i in range(1, 6)}

        # 顶层标量化（前端方便直接展示）
        overall_orr = orr_info["orr"]
        overall_dcr = dcr_info["dcr"]

        # 中位 PFS / OS（简化为样本中位数）
        median_pfs_days = self._median(pfs_samples) if pfs_samples else None
        median_os_days = self._median(os_samples) if os_samples else None

        # 按靶点汇总 ORR/DCR
        by_target_summary: Dict[str, Any] = {}
        for target, bucket in by_target.items():
            t_orr = self._compute_orr(bucket["responses"])
            t_dcr = self._compute_dcr(bucket["responses"])
            by_target_summary[target] = {
                "count": bucket["count"] + len(bucket["responses"]),
                "orr": t_orr["orr"],
                "dcr": t_dcr["dcr"],
                "ae_count": bucket["aes"],
            }

        return {
            "total_treatments": len(treatments),
            "total_outcomes": len(all_responses),
            "orr": orr_info,
            "dcr": dcr_info,
            "overall_orr": overall_orr,
            "overall_dcr": overall_dcr,
            "median_pfs_days": median_pfs_days,
            "median_os_days": median_os_days,
            "ae_distribution": ae_dist,
            "by_target": by_target_summary,
            "records": records,
        }

    @staticmethod
    def _median(values: List[float]) -> Optional[float]:
        """计算中位数"""
        if not values:
            return None
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        mid = n // 2
        if n % 2 == 1:
            return sorted_vals[mid]
        return round((sorted_vals[mid - 1] + sorted_vals[mid]) / 2, 2)
