"""合成路线生成器 — AiZynthFinder MCTS 搜索 + Mock 降级

真实模式（settings.AIZYNTH_USE_MOCK=False）：调用 MolecularAI/aizynthfinder
执行 MCTS 逆合成搜索，返回多条候选路线。CPU 密集，用 asyncio.to_thread 包装。

Mock 模式（默认）：基于 SMILES 长度 + 官能团特征生成 3-5 条伪路线，
每条 3-6 步反应，覆盖常见反应类型（酰胺化/Suzuki 偶联/还原胺化等）。
不依赖真实包，保证测试可运行。

返回结构：
    {
        "routes": [{route_id, steps, n_steps, total_yield_estimate}],
        "n_routes": int,
        "source": "aizynthfinder" | "mock",
        "smiles": str,
    }
"""
import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


# Mock 反应类型 / 试剂 / 条件池 — 提前构造避免重复
_REACTION_TYPES: List[str] = [
    "酰胺化",
    "还原胺化",
    "Suzuki偶联",
    "Buchwald-Hartwig",
    "SnAr",
    "氢化",
    "保护",
    "脱保护",
]

_REAGENTS: List[str] = [
    "EDC/HOBt",
    "Pd(PPh3)4",
    "NaBH4",
    "H2/Pd-C",
    "TFA",
    "DMAP",
    "Et3N",
    "K2CO3",
]

_CONDITIONS: List[str] = [
    "室温, DMF",
    "80°C, THF",
    "回流, EtOH",
    "0°C to rt, DCM",
]


def _to_uuid(value: Any) -> Optional[Any]:
    """占位 UUID 归一化（与其他模块保持一致的 helper 风格）"""
    import uuid as _uuid

    if value is None:
        return None
    if isinstance(value, _uuid.UUID):
        return value
    return _uuid.UUID(value)


class SynthesisRouteGenerator:
    """合成路线生成器 — AiZynthFinder MCTS 或 Mock

    用法：
        gen = SynthesisRouteGenerator(db)
        result = await gen.generate_routes("CC(=O)Oc1ccccc1C(=O)O")
    """

    def __init__(self, db: AsyncSession = None):
        self.db = db

    async def generate_routes(
        self, smiles: str, max_routes: int = 5
    ) -> Dict[str, Any]:
        """为目标分子生成多条合成路线

        Args:
            smiles: 目标分子 SMILES
            max_routes: 最多返回路线数（受 settings.SYNTHESIS_MAX_ROUTES 约束）
        Returns:
            {routes, n_routes, source, smiles}
        """
        if not smiles or not smiles.strip():
            logger.warning("generate_routes: smiles 为空")
            return {
                "routes": [],
                "n_routes": 0,
                "source": "mock",
                "smiles": smiles,
            }

        # 上限受配置约束
        max_routes = min(max_routes, settings.SYNTHESIS_MAX_ROUTES)

        if settings.AIZYNTH_USE_MOCK:
            return await self._generate_mock(smiles, max_routes)

        # 真实模式：调用 AiZynthFinder
        try:
            return await asyncio.to_thread(self._generate_aizynth, smiles, max_routes)
        except ImportError as e:
            logger.warning(f"aizynthfinder 不可用，降级 Mock: {e}")
            return await self._generate_mock(smiles, max_routes)
        except Exception as e:
            logger.warning(f"AiZynthFinder 搜索失败，降级 Mock: {e}")
            return await self._generate_mock(smiles, max_routes)

    # ------------------------------------------------------------------
    # 真实模式：AiZynthFinder MCTS
    # ------------------------------------------------------------------
    def _generate_aizynth(
        self, smiles: str, max_routes: int
    ) -> Dict[str, Any]:
        """调用 AiZynthFinder 执行 MCTS 逆合成搜索（同步，CPU 密集）

        需要：pip install aizynthfinder
        配置：政策文件 + stock 文件（默认内置）
        """
        from aizynthfinder.aizynthfinder import AiZynthFinder as AIZynthFinder  # type: ignore

        # AiZynthFinder 需要配置文件路径；若未提供，使用默认配置
        # 这里用最小可用配置：仅 stock，无 policy
        finder = AIZynthFinder(configdict=None)
        finder.target_smiles = smiles
        finder.prepare_tree()

        # MCTS 搜索
        finder.tree_search(show_progress=False)
        routes_data = finder.build_routes(min_routes=max_routes)

        routes: List[Dict[str, Any]] = []
        for idx, r in enumerate(routes_data, start=1):
            steps = []
            for s_idx, step in enumerate(r.get("reaction_tree", {}).get("children", []), start=1):
                steps.append({
                    "step": s_idx,
                    "reaction": step.get("reaction", "未知"),
                    "reagents": step.get("reagents", []),
                    "conditions": step.get("conditions", ""),
                    "intermediate_smiles": step.get("smiles", ""),
                })
            routes.append({
                "route_id": idx,
                "steps": steps,
                "n_steps": len(steps),
                "total_yield_estimate": round(
                    0.8 ** max(1, len(steps)), 3
                ),
            })

        logger.info(
            f"AiZynthFinder 为 {smiles[:30]} 生成 {len(routes)} 条路线"
        )
        return {
            "routes": routes,
            "n_routes": len(routes),
            "source": "aizynthfinder",
            "smiles": smiles,
        }

    # ------------------------------------------------------------------
    # Mock 模式：基于 SMILES 特征的伪路线生成
    # ------------------------------------------------------------------
    async def _generate_mock(
        self, smiles: str, max_routes: int
    ) -> Dict[str, Any]:
        """Mock 路线生成 — 基于 SMILES 长度 + 官能团特征

        算法：
        - 步骤数 = max(3, len(smiles) // 10)  # SMILES 越长步骤越多
        - 反应类型/试剂/条件从预定义池中选取
        - 生成 3-5 条路线，每条路线的步骤数在基础值附近波动
        """
        # 基础步数：SMILES 越长步骤越多
        base_steps = max(3, len(smiles) // 10)

        # 官能团检测 — 影响反应类型选择
        has_amide = "C(=O)N" in smiles or "NC(=O)" in smiles
        has_aromatic = "c1ccccc1" in smiles or "c1" in smiles
        has_halogen = any(x in smiles for x in ["F", "Cl", "Br", "I"])
        has_nitro = "N(=O)" in smiles

        n_routes = min(max_routes, random.randint(3, 5))
        routes: List[Dict[str, Any]] = []

        for r_idx in range(n_routes):
            # 步数在 base_steps 附近波动（±1，最少 3）
            n_steps = max(3, base_steps + random.randint(-1, 1))
            n_steps = min(n_steps, 6)  # Mock 上限 6 步

            steps: List[Dict[str, Any]] = []
            # 起始中间体（简化：用 SMILES 前缀模拟）
            intermediate = smiles[:max(5, len(smiles) // 2)]

            for s_idx in range(1, n_steps + 1):
                # 按官能团优先选择反应类型
                if has_amide and s_idx == 1:
                    reaction = "酰胺化"
                elif has_aromatic and s_idx == n_steps:
                    reaction = random.choice(
                        ["Suzuki偶联", "Buchwald-Hartwig", "SnAr"]
                    )
                elif has_halogen and s_idx <= 2:
                    reaction = random.choice(
                        ["Suzuki偶联", "Buchwald-Hartwig"]
                    )
                elif has_nitro and s_idx == 1:
                    reaction = "氢化"
                else:
                    reaction = random.choice(_REACTION_TYPES)

                # 试剂与反应类型匹配
                reagent = random.choice(_REAGENTS)
                condition = random.choice(_CONDITIONS)

                # 中间体 SMILES（Mock：逐步截断/扩展）
                if s_idx < n_steps:
                    intermediate = smiles[: max(3, len(smiles) - s_idx * 3)]
                else:
                    intermediate = smiles  # 最后一步产出目标

                steps.append({
                    "step": s_idx,
                    "reaction": reaction,
                    "reagents": [reagent],
                    "conditions": condition,
                    "intermediate_smiles": intermediate,
                })

            # 总收率估算：0.5-0.8，步数越多收率越低
            yield_est = round(max(0.5, 0.85 ** n_steps), 3)
            yield_est = min(yield_est, 0.8)

            routes.append({
                "route_id": r_idx + 1,
                "steps": steps,
                "n_steps": n_steps,
                "total_yield_estimate": yield_est,
            })

        # 按步数升序排序（步数少的优先）
        routes.sort(key=lambda r: r["n_steps"])

        logger.info(
            f"[Mock] 为 {smiles[:30]}... 生成 {n_routes} 条路线 "
            f"(base_steps={base_steps})"
        )
        return {
            "routes": routes,
            "n_routes": n_routes,
            "source": "mock",
            "smiles": smiles,
        }
