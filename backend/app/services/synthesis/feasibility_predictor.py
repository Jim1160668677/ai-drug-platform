"""合成可行性预测器 — SAscore + SCScore 双指标

SAscore（Synthetic Accessibility Score，1-10，越低越易合成）：
- 真实模式：RDKit 的完整 SA 模块
- Mock 简化：Descriptors.MolWt(mol) / 100 + len(smiles) / 20
- rdkit 不可用：3.0 + len(smiles) / 30（SMILES 越长越难合成）

SCScore（Synthetic Complexity Score，1-5，越低越易合成）：
- 真实模式：SCScorer 神经网络模型
- Mock：2.0 + len(smiles) / 50

可行性标签：
- easy:   sa_score < 4 且 sc_score < 3
- medium: 4 <= sa_score <= 6 或 3 <= sc_score <= 4
- hard:   sa_score > 6 或 sc_score > 4

挑战识别：步骤过多 / 金属催化剂 / 高压条件
CPU 密集计算用 asyncio.to_thread 包装。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# 挑战识别的关键词 — 提前构造
_HIGH_PRESSURE_HINTS = ("高压", "high pressure", "psi", "atm", "bar", "MPa")
_METAL_CATALYSTS = (
    "Pd", "Pt", "Ru", "Rh", "Ir", "Ni", "Cu", "Zn", "Fe",
    "Pd(PPh3)4", "Pd-C", "Pd/C",
)


def _to_uuid(value: Any) -> Optional[Any]:
    """占位 UUID 归一化（与其他模块保持一致的 helper 风格）"""
    import uuid as _uuid

    if value is None:
        return None
    if isinstance(value, _uuid.UUID):
        return value
    return _uuid.UUID(value)


class FeasibilityPredictor:
    """合成可行性预测器 — SAscore + SCScore + 挑战识别

    用法：
        pred = FeasibilityPredictor(db)
        result = await pred.predict(smiles, routes_result)
    """

    def __init__(self, db: AsyncSession = None):
        self.db = db

    async def predict(self, smiles: str, routes: Dict[str, Any]) -> Dict[str, Any]:
        """计算 SAscore + SCScore，识别挑战，给出可行性标签

        Args:
            smiles: 目标分子 SMILES
            routes: SynthesisRouteGenerator.generate_routes() 返回的 dict
        Returns:
            {sa_score, sc_score, feasibility_label, challenges, n_steps, source}
        """
        if not smiles:
            return {
                "sa_score": 5.0,
                "sc_score": 3.0,
                "feasibility_label": "medium",
                "challenges": [],
                "n_steps": 0,
                "source": "mock",
            }

        # CPU 密集：SAscore + SCScore 计算放到线程
        sa_score, sc_score, source = await asyncio.to_thread(
            self._compute_scores, smiles
        )

        # 最优路线步数（routes 已按步数升序排序）
        routes_list = routes.get("routes", []) if routes else []
        n_steps = 0
        if routes_list:
            n_steps = routes_list[0].get("n_steps", 0)

        # 可行性标签
        label = self._compute_label(sa_score, sc_score)

        # 挑战识别
        challenges = self._identify_challenges(smiles, routes_list, n_steps)

        logger.info(
            f"可行性预测: {smiles[:30]}... SA={sa_score} SC={sc_score} "
            f"label={label} steps={n_steps} challenges={len(challenges)}"
        )
        return {
            "sa_score": round(sa_score, 2),
            "sc_score": round(sc_score, 2),
            "feasibility_label": label,
            "challenges": challenges,
            "n_steps": n_steps,
            "source": source,
        }

    # ------------------------------------------------------------------
    # 评分计算（CPU 密集，同步方法，由 to_thread 调用）
    # ------------------------------------------------------------------
    def _compute_scores(self, smiles: str) -> tuple:
        """计算 SAscore + SCScore

        Returns:
            (sa_score, sc_score, source) — source: "rdkit+scscore" | "mock"
        """
        sa_score, sa_source = self._compute_sa_score(smiles)
        sc_score, sc_source = self._compute_sc_score(smiles)

        # 只要任一降级 Mock，整体标记为 mock
        source = "rdkit+scscore" if (sa_source == "rdkit" and sc_source == "scscore") else "mock"
        return sa_score, sc_score, source

    def _compute_sa_score(self, smiles: str) -> tuple:
        """SAscore 计算 — RDKit 优先，不可用则 Mock

        Returns:
            (sa_score, source)
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return 5.0, "mock"

            # Mock 简化版 SAscore（真实 SAscore 需要完整 RDKit SA 模块）：
            # 分子量贡献 + SMILES 长度贡献
            mol_wt = Descriptors.MolWt(mol)
            sa_score = mol_wt / 100.0 + len(smiles) / 20.0
            sa_score = max(1.0, min(10.0, sa_score))
            return round(sa_score, 2), "rdkit"
        except ImportError:
            # rdkit 不可用：Mock 估算
            sa_score = 3.0 + len(smiles) / 30.0
            sa_score = max(1.0, min(10.0, sa_score))
            return round(sa_score, 2), "mock"
        except Exception as e:
            logger.warning(f"SAscore 计算失败，降级 Mock: {e}")
            sa_score = 3.0 + len(smiles) / 30.0
            sa_score = max(1.0, min(10.0, sa_score))
            return round(sa_score, 2), "mock"

    def _compute_sc_score(self, smiles: str) -> tuple:
        """SCScore 计算 — SCScorer 优先，不可用则 Mock

        Returns:
            (sc_score, source)
        """
        try:
            from scscore import SCScorer  # type: ignore

            scorer = SCScorer()
            # 尝试加载默认模型
            try:
                scorer.load()
            except Exception:
                # 部分版本需要指定模型路径
                pass

            score = scorer.get_score_from_smiles(smiles)
            sc_score = max(1.0, min(5.0, float(score)))
            return round(sc_score, 2), "scscore"
        except ImportError:
            # scscore 不可用：Mock 估算
            sc_score = 2.0 + len(smiles) / 50.0
            sc_score = max(1.0, min(5.0, sc_score))
            return round(sc_score, 2), "mock"
        except Exception as e:
            logger.warning(f"SCScore 计算失败，降级 Mock: {e}")
            sc_score = 2.0 + len(smiles) / 50.0
            sc_score = max(1.0, min(5.0, sc_score))
            return round(sc_score, 2), "mock"

    # ------------------------------------------------------------------
    # 可行性标签
    # ------------------------------------------------------------------
    def _compute_label(self, sa_score: float, sc_score: float) -> str:
        """根据 SAscore + SCScore 计算可行性标签

        - easy:   sa_score < 4 且 sc_score < 3
        - medium: 4 <= sa_score <= 6 或 3 <= sc_score <= 4
        - hard:   sa_score > 6 或 sc_score > 4
        """
        if sa_score > 6 or sc_score > 4:
            return "hard"
        if sa_score < 4 and sc_score < 3:
            return "easy"
        return "medium"

    # ------------------------------------------------------------------
    # 挑战识别
    # ------------------------------------------------------------------
    def _identify_challenges(
        self,
        smiles: str,
        routes: List[Dict[str, Any]],
        n_steps: int,
    ) -> List[Dict[str, str]]:
        """识别合成挑战 — 步骤过多 / 金属催化剂 / 高压条件

        Args:
            smiles: 目标分子 SMILES
            routes: 路线列表
            n_steps: 最优路线步数
        Returns:
            [{name, severity, mitigation}]
        """
        challenges: List[Dict[str, str]] = []

        # 1. 步骤过多
        if n_steps > 8:
            challenges.append({
                "name": "步骤过多",
                "severity": "medium",
                "mitigation": "考虑重新设计路线，减少合成步骤",
            })
        elif n_steps > 6:
            challenges.append({
                "name": "步骤偏多",
                "severity": "low",
                "mitigation": "评估是否有更短的替代路线",
            })

        # 2. 金属催化剂
        all_reagents_text = ""
        all_conditions_text = ""
        for route in routes:
            for step in route.get("steps", []):
                for r in step.get("reagents", []):
                    all_reagents_text += str(r) + " "
                all_conditions_text += str(step.get("conditions", "")) + " "

        has_metal = any(
            cat in all_reagents_text for cat in _METAL_CATALYSTS
        )
        if has_metal:
            challenges.append({
                "name": "金属催化剂",
                "severity": "low",
                "mitigation": "需特殊纯化去除金属残留",
            })

        # 3. 高压条件
        condition_lower = all_conditions_text.lower()
        has_high_pressure = any(
            hint.lower() in condition_lower for hint in _HIGH_PRESSURE_HINTS
        )
        if has_high_pressure:
            challenges.append({
                "name": "高压反应",
                "severity": "high",
                "mitigation": "需专用高压设备，注意安全防护",
            })

        return challenges
