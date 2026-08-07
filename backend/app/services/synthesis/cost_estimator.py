"""合成成本估算器 — 基于步数 / 规模 / 难度的成本模型

成本模型：
    试剂成本 = sum(step_count * 50.0) * target_scale_grams / 10   # 每步 50 USD，按规模缩放
    人工成本 = SYNTHESIS_LABOR_RATE_USD_PER_HR * SYNTHESIS_HOURS_PER_STEP * n_steps  # 80 * 4 * 步数
    设备成本 = SYNTHESIS_COST_PER_STEP_USD * n_steps              # 150 * 步数
    间接成本 = (试剂 + 人工 + 设备) * 0.2                          # 20% 间接费
    总成本   = 试剂 + 人工 + 设备 + 间接

难度加成：sa_score > 6 时总成本 × 1.5（难合成需更多尝试）
成本上限：total > SYNTHESIS_MAX_COST_USD 时标记警告
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[Any]:
    """占位 UUID 归一化（与其他模块保持一致的 helper 风格）"""
    import uuid as _uuid

    if value is None:
        return None
    if isinstance(value, _uuid.UUID):
        return value
    return _uuid.UUID(value)


class SynthesisCostEstimator:
    """合成成本估算器

    用法：
        est = SynthesisCostEstimator(db)
        result = await est.estimate(routes_result, sa_score=4.5, target_scale_grams=10.0)
    """

    def __init__(self, db: AsyncSession = None):
        self.db = db

    async def estimate(
        self,
        routes: Dict[str, Any],
        sa_score: float = 5.0,
        target_scale_grams: float = 10.0,
    ) -> Dict[str, Any]:
        """估算合成总成本

        Args:
            routes: SynthesisRouteGenerator.generate_routes() 返回的 dict
            sa_score: 可行性 SAscore（1-10），>6 时触发难度加成
            target_scale_grams: 目标合成规模（克），默认 10g
        Returns:
            {total_cost_usd, cost_per_gram, breakdown, target_scale_grams,
             is_cost_effective, warning, source}
        """
        routes_list = routes.get("routes", []) if routes else []

        # 最优路线步数（routes 已按步数升序排序）
        n_steps = 0
        if routes_list:
            n_steps = routes_list[0].get("n_steps", 0)
        n_steps = max(1, n_steps)  # 至少 1 步，避免除零

        # ---- 成本分项 ----
        # 1. 试剂成本：每步 50 USD，按规模缩放（10g 基准）
        reagent_cost = n_steps * 50.0 * target_scale_grams / 10.0

        # 2. 人工成本：时薪 × 每步工时 × 步数
        labor_cost = (
            settings.SYNTHESIS_LABOR_RATE_USD_PER_HR
            * settings.SYNTHESIS_HOURS_PER_STEP
            * n_steps
        )

        # 3. 设备成本：每步固定设备折旧
        equipment_cost = settings.SYNTHESIS_COST_PER_STEP_USD * n_steps

        # 4. 间接成本：前 3 项之和 × 20%
        overhead = (reagent_cost + labor_cost + equipment_cost) * 0.2

        # ---- 总成本 ----
        total = reagent_cost + labor_cost + equipment_cost + overhead

        # ---- 难度加成：sa_score > 6 时成本 × 1.5 ----
        if sa_score > 6:
            total = total * 1.5
            logger.info(
                f"难度加成（sa_score={sa_score}>6）：成本 ×1.5 = {total:.2f}"
            )

        total = round(total, 2)
        cost_per_gram = round(total / target_scale_grams, 2) if target_scale_grams > 0 else 0.0

        # ---- 成本上限检查 ----
        is_cost_effective = total < settings.SYNTHESIS_MAX_COST_USD
        warning = ""
        if not is_cost_effective:
            warning = (
                f"成本过高（${total:.2f} 超过上限 "
                f"${settings.SYNTHESIS_MAX_COST_USD}），建议优化路线或缩小规模"
            )
            logger.warning(warning)

        breakdown = {
            "materials": round(reagent_cost, 2),
            "labor": round(labor_cost, 2),
            "equipment": round(equipment_cost, 2),
            "overhead": round(overhead, 2),
        }

        logger.info(
            f"成本估算: steps={n_steps} scale={target_scale_grams}g "
            f"total=${total} /gram=${cost_per_gram} sa={sa_score}"
        )
        return {
            "total_cost_usd": total,
            "cost_per_gram": cost_per_gram,
            "breakdown": breakdown,
            "target_scale_grams": target_scale_grams,
            "is_cost_effective": is_cost_effective,
            "warning": warning,
            "source": "model",
        }
