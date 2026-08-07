"""药物可开发性评估器 — 5 维度干实验预筛选

回应评委意见：药物分子是否容易合成、毒理、制剂递送、生产成本如何。
在送入湿实验前先用算法做预筛选，把明显不可合成/高毒/高成本的分子挡在湿实验门外。

5 维度：
1. 合成可及性 SA Score（assess_synthesizability）
2. 毒理风险（assess_toxicity，复用 predict_admet 的 PAINS/toxicophore/hERG）
3. 制剂递送评分（assess_formulation，基于 LogP/TPSA/MW 口服适合度）
4. 生产成本估算（estimate_cost，基于 SA + 复杂度）
5. 综合决策（_compute_overall：go/revise/no_go）
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.developability import DevelopabilityAssessment

logger = logging.getLogger(__name__)


class DevelopabilityAssessor:
    """药物可开发性评估器

    启发式算法，不引入新 ML 依赖。RDKit 不可用时降级到字符估算
    （与现有 assess_druglikeness 模式一致）。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assess(
        self,
        molecule: Any,
        created_by: Optional[str] = None,
    ) -> DevelopabilityAssessment:
        """对分子做完整 5 维度评估并持久化

        Args:
            molecule: Molecule ORM 对象（需有 smiles 字段）
            created_by: 创建者用户 ID
        Returns:
            DevelopabilityAssessment 持久化对象
        """
        smiles = molecule.smiles
        props = molecule.properties or {}

        # 5 维度评估（同步 CPU 密集计算）
        sa_score, sa_label = self.assess_synthesizability(smiles)
        tox_risk, tox_alerts = self.assess_toxicity(smiles)
        form_score, form_notes = self.assess_formulation(smiles, props)
        cost, breakdown = self.estimate_cost(smiles, sa_score, props)
        overall, recommendation, rationale = self._compute_overall(
            sa_score, tox_risk, form_score, cost
        )

        # 反查 project_id（通过 molecule.target → target.project_id）
        project_id = None
        if molecule.target_id:
            from app.models.target import Target
            target = await self.db.get(Target, molecule.target_id)
            if target:
                project_id = target.project_id

        # 计算版本号（同分子历史评估数 + 1）
        from sqlalchemy import select, func as sa_func
        count_stmt = select(sa_func.count()).select_from(DevelopabilityAssessment).where(
            DevelopabilityAssessment.molecule_id == molecule.id
        )
        existing_count = (await self.db.execute(count_stmt)).scalar() or 0

        assessment = DevelopabilityAssessment(
            molecule_id=molecule.id,
            project_id=project_id,
            version=existing_count + 1,
            created_by=created_by,
            sa_score=sa_score,
            sa_ease_label=sa_label,
            toxicity_risk=tox_risk,
            toxicity_alerts=tox_alerts,
            formulation_score=form_score,
            formulation_notes=form_notes,
            cost_estimate_usd=cost,
            cost_breakdown=breakdown,
            overall_score=overall,
            recommendation=recommendation,
            rationale=rationale,
        )
        self.db.add(assessment)
        await self.db.commit()
        await self.db.refresh(assessment)
        return assessment

    def assess_synthesizability(self, smiles: str) -> Tuple[float, str]:
        """合成可及性 SA Score（1-10，越低越易合成）

        rdkit 可用：基于 Bertz 复杂度 + 立体中心数 + 大环数 → 归一化到 1-10
        rdkit 不可用：基于 SMILES 长度 + 分支数 + 立体符号数 → 启发式估算

        Returns:
            (sa_score, ease_label) — ease_label: easy(≤3)/medium(3-6)/hard(>6)
        """
        if not smiles:
            return 5.0, "medium"

        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors, FindMolChiralCenters

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return 5.0, "medium"

            # Bertz 复杂度（越大越复杂），归一化到 0-1
            bertz = Descriptors.BertzCT(mol)
            bertz_norm = min(1.0, bertz / 1000.0)

            # 立体中心数
            chiral_centers = len(FindMolChiralCenters(mol))

            # 大环数（环原子数 >= 12）
            ring_info = mol.GetRingInfo()
            macro_cycles = sum(
                1 for ring in ring_info.AtomRings() if len(ring) >= 12
            )

            # 综合计算 SA Score
            # 基础 1.0 + Bertz 贡献 0-4 + 立体贡献 0-3 + 大环贡献 0-2
            sa_score = 1.0 + bertz_norm * 4.0 + min(3.0, chiral_centers * 0.5) + min(2.0, macro_cycles * 1.0)
            sa_score = max(1.0, min(10.0, sa_score))
            sa_score = round(sa_score, 2)

        except ImportError:
            # Mock 模式：基于 SMILES 字符特征估算
            sa_score = self._mock_sa_score(smiles)
        except Exception as e:
            logger.warning(f"SA Score 计算失败，降级 Mock: {e}")
            sa_score = self._mock_sa_score(smiles)

        # 标签
        if sa_score <= 3:
            label = "easy"
        elif sa_score <= 6:
            label = "medium"
        else:
            label = "hard"

        return sa_score, label

    def _mock_sa_score(self, smiles: str) -> float:
        """Mock SA Score — rdkit 不可用时的字符估算"""
        # SMILES 长度（越长越复杂）
        length_factor = min(4.0, len(smiles) / 15.0)
        # 分支数
        branch_factor = min(2.0, smiles.count("(") * 0.4)
        # 立体符号数
        stereo_factor = min(2.0, (smiles.count("@") + smiles.count("/") + smiles.count("\\")) * 0.5)
        # 环数
        ring_factor = min(2.0, sum(1 for d in "123456789" if d in smiles) * 0.5)

        sa_score = 1.0 + length_factor + branch_factor + stereo_factor + ring_factor
        return round(max(1.0, min(10.0, sa_score)), 2)

    def assess_toxicity(self, smiles: str) -> Tuple[str, List[Dict[str, str]]]:
        """毒理风险评级 — 复用 predict_admet 的 PAINS/toxicophore/hERG 信号

        Returns:
            (risk_level, alerts) — risk_level: low/moderate/high
                                  alerts: [{name, smarts, severity}]
        """
        if not smiles:
            return "low", []

        try:
            from app.services.analyzer.molecule_designer import predict_admet
            admet = predict_admet(smiles)

            if admet.get("error"):
                return "low", []

            pains_alerts = admet.get("pains_alerts", [])
            tox_alerts = admet.get("toxicophore_alerts", [])
            herg_risk = admet.get("herg_risk", "low")

            # 汇总 alerts
            alerts: List[Dict[str, str]] = []
            for a in pains_alerts:
                alerts.append({
                    "name": a.get("name", "unknown"),
                    "smarts": a.get("smarts", ""),
                    "severity": "warning",
                })
            for a in tox_alerts:
                alerts.append({
                    "name": a.get("name", "unknown"),
                    "smarts": a.get("smarts", ""),
                    "severity": "danger",
                })

            # 分级规则：
            # - hERG=high 或 alerts >= 3 → high
            # - alerts 1-2 或 hERG=medium → moderate
            # - 否则 → low
            risk_count = len(alerts)
            if herg_risk == "high" or risk_count >= 3:
                risk = "high"
            elif risk_count >= 1 or herg_risk == "medium":
                risk = "moderate"
            else:
                risk = "low"

            return risk, alerts

        except Exception as e:
            logger.warning(f"毒理评估失败，降级 low: {e}")
            return "low", []

    def assess_formulation(self, smiles: str, props: Dict[str, Any]) -> Tuple[float, str]:
        """制剂递送评分 — 基于 LogP/TPSA/MW 的口服适合度规则

        Returns:
            (score 0-1, notes) — 越高越适合口服
        """
        if not smiles:
            return 0.5, "无 SMILES，默认中等评分"

        # 从 props 提取理化参数，或重新计算
        mw = props.get("mw")
        logp = props.get("logp")
        tpsa = props.get("tpsa")

        # 若 props 缺失，尝试 rdkit 重算
        if mw is None or logp is None or tpsa is None:
            try:
                from app.services.analyzer.molecule_designer import assess_druglikeness
                druglike = assess_druglikeness(smiles)
                if not druglike.get("error"):
                    mw = mw or druglike.get("mw")
                    logp = logp or druglike.get("logp")
                    tpsa = tpsa or druglike.get("tpsa")
            except Exception:
                pass

        # 仍缺失则用默认值
        mw = mw or 300.0
        logp = logp or 2.0
        tpsa = tpsa or 60.0

        # 口服适合度评分规则（0-1）：
        # - MW 200-500 最佳（+0.3），<200 或 >500 减分
        # - LogP 1-3 最佳（+0.3），>5 或 <-1 减分
        # - TPSA <140 最佳（+0.2），>170 严重减分
        # - Veber 规则（rotatable<=10 && tpsa<=140）+0.2
        score = 0.5  # 基础分
        notes_parts: List[str] = []

        if 200 <= mw <= 500:
            score += 0.2
            notes_parts.append(f"MW={mw:.0f} 在口服窗口内")
        elif mw > 500:
            score -= 0.15
            notes_parts.append(f"MW={mw:.0f} 偏大（>500），口服吸收差")
        else:
            notes_parts.append(f"MW={mw:.0f} 偏小")

        if 1 <= logp <= 3:
            score += 0.2
            notes_parts.append(f"LogP={logp:.1f} 适合口服")
        elif logp > 5:
            score -= 0.15
            notes_parts.append(f"LogP={logp:.1f} 过高（>5），溶解性差")
        elif logp < -1:
            score -= 0.1
            notes_parts.append(f"LogP={logp:.1f} 过低（<-1），渗透性差")
        else:
            notes_parts.append(f"LogP={logp:.1f} 可接受")

        if tpsa <= 140:
            score += 0.15
            notes_parts.append(f"TPSA={tpsa:.0f} 适合口服")
        else:
            score -= 0.1
            notes_parts.append(f"TPSA={tpsa:.0f} 偏大（>140），渗透性差")

        score = max(0.0, min(1.0, score))
        return round(score, 3), "；".join(notes_parts)

    def estimate_cost(
        self, smiles: str, sa_score: float, props: Dict[str, Any]
    ) -> Tuple[float, Dict[str, float]]:
        """生产成本估算（USD/克）— 基于 SA Score + 复杂度的启发式公式

        Returns:
            (cost_usd, breakdown) — breakdown: {materials, labor, overhead}
        """
        # 原料数（粗略估算：SMILES 中的大写原子数）
        n_atoms = sum(1 for c in smiles if c.isupper()) if smiles else 5
        n_alerts = 0
        try:
            from app.services.analyzer.molecule_designer import predict_admet
            admet = predict_admet(smiles) if smiles else {}
            n_alerts = len(admet.get("pains_alerts", [])) + len(admet.get("toxicophore_alerts", []))
        except Exception:
            n_alerts = 0

        # 公式（计划文档确定）：
        # cost = 500 + sa_score * 300 + n_alerts * 200 + (1 - formulation_score) * 500
        # 但此处 formulation_score 依赖 assess_formulation，为避免循环依赖，用 sa_score 近似
        formulation_penalty = max(0, (sa_score - 3)) * 100  # SA>3 时增加制剂难度成本
        cost = 500 + sa_score * 300 + n_alerts * 200 + formulation_penalty
        cost = round(cost, 2)

        # 分项：materials(40%) / labor(40%) / overhead(20%)
        breakdown = {
            "materials": round(cost * 0.4, 2),
            "labor": round(cost * 0.4, 2),
            "overhead": round(cost * 0.2, 2),
        }
        return cost, breakdown

    def _compute_overall(
        self,
        sa_score: float,
        tox_risk: str,
        form_score: float,
        cost: float,
    ) -> Tuple[float, str, str]:
        """综合评分 + go/revise/no_go 决策

        决策规则（计划文档确定）：
        - tox=high → no_go
        - sa>8 or cost>5000 → revise
        - 否则 → go

        Returns:
            (overall_score 0-1, recommendation, rationale)
        """
        # 综合评分（0-1）：sa_score 归一化到 0-1（越低越好→反向）
        sa_norm = max(0.0, min(1.0, 1.0 - (sa_score - 1) / 9.0))
        # 毒理分级转分
        tox_map = {"low": 1.0, "moderate": 0.5, "high": 0.0}
        tox_score = tox_map.get(tox_risk, 0.5)
        # 成本归一化（cost 500-5000+ 映射到 1.0-0.0）
        cost_norm = max(0.0, min(1.0, 1.0 - (cost - 500) / 4500.0))

        # 加权平均：sa 30% + tox 35% + formulation 20% + cost 15%
        overall = (
            sa_norm * 0.30 + tox_score * 0.35 + form_score * 0.20 + cost_norm * 0.15
        )
        overall = round(max(0.0, min(1.0, overall)), 3)

        # 决策规则
        reasons: List[str] = []
        if tox_risk == "high":
            recommendation = "no_go"
            reasons.append("毒理风险过高（high），不建议推进")
        elif sa_score > 8:
            recommendation = "revise"
            reasons.append(f"合成难度过高（SA={sa_score}），建议优化结构")
        elif cost > 5000:
            recommendation = "revise"
            reasons.append(f"生产成本过高（${cost:.0f}/g），建议优化合成路线")
        else:
            recommendation = "go"
            reasons.append("5 维度评估通过，可推进至湿实验验证")

        # 补充说明
        if form_score < 0.4:
            reasons.append(f"制剂递送评分偏低（{form_score}），需关注口服吸收")
        if tox_risk == "moderate":
            reasons.append("存在中等毒理风险，建议在湿实验中重点监测")

        rationale = "；".join(reasons)
        return overall, recommendation, rationale
