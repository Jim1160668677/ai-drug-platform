"""合成规划编排器 — 编排路线生成 / 可行性预测 / 成本估算并持久化

流程：
    plan(smiles, user)
      → SynthesisRouteGenerator.generate_routes()
      → FeasibilityPredictor.predict()
      → SynthesisCostEstimator.estimate()
      → 持久化 SynthesisPlan（routes / sa_score / sc_score / cost / challenges）
      → （可选）LLM 生成自然语言推荐

持久化使用 self.db.add(plan) + await self.db.flush()，不 commit
（由调用方控制事务，与 ValidationOrchestrator 模式一致）。
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.synthesis_plan import (
    SynthesisFeasibility,
    SynthesisPlan,
    SynthesisSource,
)

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """把 str/UUID 统一转为 UUID（SQLAlchemy Uuid 列要求 UUID 对象）

    None 透传；非法格式抛 ValueError（调用方应确保合法）。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class SynthesisPlanner:
    """合成规划编排器

    用法：
        planner = SynthesisPlanner(db, llm_client=client, llm_config=config)
        result = await planner.plan("CC(=O)Oc1ccccc1C(=O)O", user=current_user)
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client=None,
        llm_config=None,
    ):
        """初始化

        Args:
            db: 数据库会话
            llm_client: LLM 客户端实例（可选，用于生成自然语言推荐）
            llm_config: 数据库激活的 LLMConfig（可选，用于动态选择模型）
        """
        self.db = db
        self.llm_client = llm_client
        self.llm_config = llm_config

    async def plan(
        self,
        smiles: str,
        user,
        max_routes: int = 5,
        target_scale_grams: float = 10.0,
        molecule_id: Optional[str] = None,
        project_id: Optional[str] = None,
        molecule_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """编排完整合成规划流程

        Args:
            smiles: 目标分子 SMILES
            user: 当前用户（ORM 对象，需有 .id）
            max_routes: 最多生成路线数
            target_scale_grams: 目标合成规模（克）
            molecule_id: 关联分子 ID（可空，支持裸 SMILES）
            project_id: 关联项目 ID（可空）
            molecule_name: 分子名称（可空）
        Returns:
            完整规划结果 dict（含 plan_id）
        """
        # 局部导入避免循环依赖
        from .route_generator import SynthesisRouteGenerator
        from .feasibility_predictor import FeasibilityPredictor
        from .cost_estimator import SynthesisCostEstimator

        # 1. 路线生成
        route_gen = SynthesisRouteGenerator(self.db)
        routes_result = await route_gen.generate_routes(smiles, max_routes=max_routes)

        # 2. 可行性预测
        feasibility_pred = FeasibilityPredictor(self.db)
        feasibility_result = await feasibility_pred.predict(smiles, routes_result)

        # 3. 成本估算
        cost_est = SynthesisCostEstimator(self.db)
        cost_result = await cost_est.estimate(
            routes_result,
            sa_score=feasibility_result.get("sa_score", 5.0),
            target_scale_grams=target_scale_grams,
        )

        # 4. 持久化 SynthesisPlan
        plan = SynthesisPlan(
            owner_id=user.id,
            molecule_id=_to_uuid(molecule_id),
            project_id=_to_uuid(project_id),
            smiles=smiles,
            molecule_name=molecule_name,
            routes=routes_result.get("routes", []),
            n_routes=routes_result.get("n_routes", 0),
            n_steps_best=feasibility_result.get("n_steps"),
            sa_score=feasibility_result.get("sa_score"),
            sc_score=feasibility_result.get("sc_score"),
            feasibility_label=feasibility_result.get("feasibility_label"),
            challenges=feasibility_result.get("challenges", []),
            total_cost_usd=cost_result.get("total_cost_usd"),
            cost_breakdown=cost_result.get("breakdown"),
            cost_per_gram=cost_result.get("cost_per_gram"),
            source_engine=routes_result.get("source", "mock"),
        )
        self.db.add(plan)
        await self.db.flush()  # 不 commit，由调用方控制事务
        plan_id = str(plan.id)
        logger.info(f"合成规划已持久化: {plan_id} (smiles={smiles[:20]}...)")

        # 5. （可选）LLM 生成自然语言推荐
        recommendation = ""
        risk_assessment = ""
        recommended_route_idx = None
        if self.llm_client is not None:
            try:
                recommendation, risk_assessment, recommended_route_idx = (
                    await self._generate_llm_recommendation(
                        smiles, routes_result, feasibility_result, cost_result
                    )
                )
                if recommendation:
                    plan.llm_recommendation = recommendation
                if risk_assessment:
                    plan.risk_assessment = risk_assessment
                if recommended_route_idx is not None:
                    plan.recommended_route_idx = recommended_route_idx
                await self.db.flush()
            except Exception as e:
                logger.warning(f"LLM 推荐生成失败（不影响主流程）: {e}")

        return {
            "plan_id": plan_id,
            "smiles": smiles,
            "routes": routes_result.get("routes", []),
            "n_routes": routes_result.get("n_routes", 0),
            "n_steps_best": feasibility_result.get("n_steps"),
            "sa_score": feasibility_result.get("sa_score"),
            "sc_score": feasibility_result.get("sc_score"),
            "feasibility_label": feasibility_result.get("feasibility_label"),
            "challenges": feasibility_result.get("challenges", []),
            "total_cost_usd": cost_result.get("total_cost_usd"),
            "cost_per_gram": cost_result.get("cost_per_gram"),
            "cost_breakdown": cost_result.get("breakdown"),
            "is_cost_effective": cost_result.get("is_cost_effective"),
            "warning": cost_result.get("warning", ""),
            "source_engine": routes_result.get("source", "mock"),
            "recommendation": recommendation,
            "risk_assessment": risk_assessment,
            "recommended_route_idx": recommended_route_idx,
        }

    async def get_plan(self, plan_id: str) -> Optional[SynthesisPlan]:
        """按 ID 加载合成规划记录

        Args:
            plan_id: SynthesisPlan ID（str 或 UUID）
        Returns:
            SynthesisPlan ORM 对象，或 None
        """
        return await self.db.get(SynthesisPlan, _to_uuid(plan_id))

    async def list_plans(
        self, user, page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """查询当前用户的合成规划列表（按 created_at 倒序，分页）

        Args:
            user: 当前用户（ORM 对象，需有 .id）
            page: 页码（从 1 开始）
            page_size: 每页条数
        Returns:
            {items: [...], total, page, page_size}
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        # 总数
        count_stmt = (
            select(sa_func.count())
            .select_from(SynthesisPlan)
            .where(SynthesisPlan.owner_id == user.id)
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # 分页查询
        stmt = (
            select(SynthesisPlan)
            .where(SynthesisPlan.owner_id == user.id)
            .order_by(SynthesisPlan.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        plans = result.scalars().all()

        items = [self._serialize_plan(p) for p in plans]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # LLM 推荐生成
    # ------------------------------------------------------------------
    async def _generate_llm_recommendation(
        self,
        smiles: str,
        routes: Dict[str, Any],
        feasibility: Dict[str, Any],
        cost: Dict[str, Any],
    ) -> tuple:
        """调用 LLM 生成自然语言合成推荐

        Returns:
            (recommendation, risk_assessment, recommended_route_idx)
        """
        # 复用 LLMOrchestrator 的 select_model（如 llm_config 可用）
        model = self._select_model()

        # 构造合成建议 prompt
        routes_list = routes.get("routes", [])
        best_route = routes_list[0] if routes_list else {}

        prompt = self._build_synthesis_prompt(
            smiles, routes_list, best_route, feasibility, cost
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是药物合成路线评估专家。基于逆合成路线、SA/SC 评分和成本数据，"
                    "给出结构化的合成推荐和风险评估。\n\n"
                    "要求：\n"
                    "- 推荐最优路线并说明理由（步数/收率/成本权衡）\n"
                    "- 评估合成难点（关键步骤、官能团兼容性）\n"
                    "- 成本效益分析（单克成本 vs 商业价值）\n"
                    "- 给出下一步建议（放大生产/工艺优化）\n"
                    "- 输出 Markdown 格式，控制在 800 字以内\n"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        response = await self.llm_client.chat(messages, model=model)
        recommendation = response.get("content", "")
        risk_assessment = self._extract_risk(recommendation, feasibility)
        recommended_route_idx = 0 if routes_list else None

        return recommendation, risk_assessment, recommended_route_idx

    def _select_model(self) -> str:
        """选择 LLM 模型 — 复用 LLMOrchestrator.select_model 逻辑

        若 llm_config 可用，优先使用 deep_model；否则回退 settings.LLM_MODEL_DEEP
        """
        try:
            from app.models.analysis_job import AnalysisTier

            if self.llm_config is not None:
                # 复用 LLMOrchestrator 的选择逻辑（避免直接耦合，复制关键判断）
                return (
                    getattr(self.llm_config, "deep_model", None)
                    or getattr(self.llm_config, "test_model", None)
                    or settings.LLM_MODEL_DEEP
                )
            return settings.LLM_MODEL_DEEP
        except Exception:
            return settings.LLM_MODEL_DEEP

    def _build_synthesis_prompt(
        self,
        smiles: str,
        routes: List[Dict[str, Any]],
        best_route: Dict[str, Any],
        feasibility: Dict[str, Any],
        cost: Dict[str, Any],
    ) -> str:
        """构造合成建议 prompt"""
        steps_desc = ""
        for step in best_route.get("steps", []):
            steps_desc += (
                f"  {step.get('step')}. {step.get('reaction')} "
                f"| 试剂: {', '.join(step.get('reagents', []))} "
                f"| 条件: {step.get('conditions')}\n"
            )

        challenges_desc = ""
        for ch in feasibility.get("challenges", []):
            challenges_desc += (
                f"  - {ch.get('name')}（{ch.get('severity')}）：{ch.get('mitigation')}\n"
            )

        return (
            f"## 目标分子\nSMILES: {smiles}\n\n"
            f"## 最优合成路线（{best_route.get('n_steps', 0)} 步，"
            f"预估总收率 {best_route.get('total_yield_estimate', 0)}）\n"
            f"{steps_desc}\n"
            f"## 可行性评估\n"
            f"  - SAscore: {feasibility.get('sa_score')}（1-10，越低越易合成）\n"
            f"  - SCScore: {feasibility.get('sc_score')}（1-5，越低越易合成）\n"
            f"  - 可行性标签: {feasibility.get('feasibility_label')}\n"
            f"  - 挑战:\n{challenges_desc}\n"
            f"## 成本估算（目标规模 {cost.get('target_scale_grams')}g）\n"
            f"  - 总成本: ${cost.get('total_cost_usd')}\n"
            f"  - 单克成本: ${cost.get('cost_per_gram')}\n"
            f"  - 分项: 试剂 ${cost.get('breakdown', {}).get('materials')} / "
            f"人工 ${cost.get('breakdown', {}).get('labor')} / "
            f"设备 ${cost.get('breakdown', {}).get('equipment')} / "
            f"间接 ${cost.get('breakdown', {}).get('overhead')}\n"
            f"  - 成本效益: {'合理' if cost.get('is_cost_effective') else '过高'}\n"
            f"  - 警告: {cost.get('warning', '无')}\n\n"
            f"请给出合成推荐和风险评估。"
        )

    def _extract_risk(
        self, recommendation: str, feasibility: Dict[str, Any]
    ) -> str:
        """从可行性结果中提取风险评估摘要"""
        challenges = feasibility.get("challenges", [])
        label = feasibility.get("feasibility_label", "medium")

        if not challenges:
            if label == "easy":
                return "低风险：合成路线成熟，步骤少，无特殊挑战。"
            elif label == "medium":
                return "中等风险：合成可行但需关注关键步骤收率。"
            else:
                return "高风险：合成难度大，建议进一步优化路线。"

        high_risk = [c for c in challenges if c.get("severity") == "high"]
        if high_risk:
            return f"高风险：存在 {len(high_risk)} 项高危挑战，需专项评估。"
        medium_risk = [c for c in challenges if c.get("severity") == "medium"]
        if medium_risk:
            return f"中等风险：存在 {len(medium_risk)} 项中等挑战，需针对性缓解。"
        return "低风险：仅有轻微挑战，常规工艺可应对。"

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def _serialize_plan(self, plan: SynthesisPlan) -> Dict[str, Any]:
        """序列化 SynthesisPlan ORM 为 dict"""
        return {
            "id": str(plan.id),
            "smiles": plan.smiles,
            "molecule_id": str(plan.molecule_id) if plan.molecule_id else None,
            "project_id": str(plan.project_id) if plan.project_id else None,
            "molecule_name": plan.molecule_name,
            "n_routes": plan.n_routes,
            "n_steps_best": plan.n_steps_best,
            "sa_score": plan.sa_score,
            "sc_score": plan.sc_score,
            "feasibility_label": plan.feasibility_label,
            "total_cost_usd": plan.total_cost_usd,
            "cost_per_gram": plan.cost_per_gram,
            "source_engine": plan.source_engine,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }
