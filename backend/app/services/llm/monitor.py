"""LLM 性能监控 — 从 AnalysisJob 聚合指标

提供延迟分布、成功率、token 统计、成本趋势等监控数据。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus

logger = logging.getLogger(__name__)


class LLMMonitor:
    """LLM 性能监控聚合器

    从 AnalysisJob 表聚合调用指标，支持按时间范围和 tier 查询。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_summary(self, days: int = 7) -> Dict[str, Any]:
        """获取近期汇总指标"""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(
                func.count(AnalysisJob.id).label("total_calls"),
                func.sum(
                    func.case(
                        (AnalysisJob.status == JobStatus.COMPLETED, 1),
                        else_=0,
                    )
                ).label("success_count"),
                func.avg(AnalysisJob.duration_sec).label("avg_duration"),
                func.coalesce(func.sum(AnalysisJob.cost_usd), 0).label("total_cost"),
                func.coalesce(func.sum(AnalysisJob.token_count), 0).label("total_tokens"),
            )
            .where(AnalysisJob.created_at >= since)
        )
        result = await self.db.execute(stmt)
        row = result.one()

        total = row.total_calls or 0
        success = row.success_count or 0
        return {
            "days": days,
            "total_calls": total,
            "success_calls": success,
            "failed_calls": total - success,
            "success_rate": round(success / total, 4) if total > 0 else 0.0,
            "avg_duration_sec": round(float(row.avg_duration or 0), 3),
            "total_cost_usd": round(float(row.total_cost or 0), 4),
            "total_tokens": int(row.total_tokens or 0),
        }

    async def get_timeline(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取每日趋势"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                func.date(AnalysisJob.created_at).label("date"),
                func.count(AnalysisJob.id).label("calls"),
                func.coalesce(func.sum(AnalysisJob.cost_usd), 0).label("cost"),
                func.avg(AnalysisJob.duration_sec).label("avg_duration"),
                func.sum(
                    func.case(
                        (AnalysisJob.status == JobStatus.COMPLETED, 1),
                        else_=0,
                    )
                ).label("success"),
            )
            .where(AnalysisJob.created_at >= since)
            .group_by(func.date(AnalysisJob.created_at))
            .order_by(func.date(AnalysisJob.created_at))
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "date": str(r.date),
                "calls": r.calls,
                "cost_usd": round(float(r.cost or 0), 4),
                "avg_duration_sec": round(float(r.avg_duration or 0), 3),
                "success_rate": round(r.success / r.calls, 4) if r.calls else 0.0,
            }
            for r in rows
        ]

    async def get_by_tier(self, days: int = 7) -> List[Dict[str, Any]]:
        """按 tier 聚合"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                AnalysisJob.tier,
                func.count(AnalysisJob.id).label("calls"),
                func.coalesce(func.sum(AnalysisJob.cost_usd), 0).label("cost"),
                func.avg(AnalysisJob.duration_sec).label("avg_duration"),
            )
            .where(AnalysisJob.created_at >= since)
            .group_by(AnalysisJob.tier)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "tier": r.tier,
                "calls": r.calls,
                "cost_usd": round(float(r.cost or 0), 4),
                "avg_duration_sec": round(float(r.avg_duration or 0), 3),
            }
            for r in result.all()
        ]

    async def get_by_model(self, days: int = 7) -> List[Dict[str, Any]]:
        """按模型聚合"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                AnalysisJob.model_used,
                func.count(AnalysisJob.id).label("calls"),
                func.coalesce(func.sum(AnalysisJob.cost_usd), 0).label("cost"),
                func.coalesce(func.sum(AnalysisJob.token_count), 0).label("tokens"),
            )
            .where(AnalysisJob.created_at >= since)
            .group_by(AnalysisJob.model_used)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "model": r.model_used or "unknown",
                "calls": r.calls,
                "cost_usd": round(float(r.cost or 0), 4),
                "tokens": int(r.tokens or 0),
            }
            for r in result.all()
        ]

    async def get_recent_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的错误调用"""
        stmt = (
            select(AnalysisJob)
            .where(AnalysisJob.status == JobStatus.FAILED)
            .order_by(AnalysisJob.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        jobs = result.scalars().all()
        return [
            {
                "id": str(j.id),
                "tier": j.tier,
                "model": j.model_used,
                "error": j.error,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]


__all__ = ["LLMMonitor"]
