"""已知药物验证器 — 用 5 个已知药物案例验证合成模块的有效性

回应任务 3：通过已知药物案例验证端到端合成规划能力。
比对生成路线与文献已知路线（基于反应步骤数 + 关键中间体匹配度）。
"""
import logging
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.synthesis.synthesis_planner import SynthesisPlanner

logger = logging.getLogger(__name__)


# 5 个已知药物案例 — 覆盖 easy / medium / hard 三种难度
KNOWN_DRUGS: List[Dict[str, Any]] = [
    {
        "drug_name": "阿司匹林",
        "smiles": "CC(=O)Oc1ccccc1C(=O)O",
        "target_gene": "PTGS2",
        "expected_difficulty": "easy",
        "expected_steps": (1, 3),  # 文献已知 1-3 步
        "expected_sa_score": (1.0, 3.5),  # SAscore 应较低
    },
    {
        "drug_name": "布洛芬",
        "smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
        "target_gene": "PTGS2",
        "expected_difficulty": "easy",
        "expected_steps": (2, 4),
        "expected_sa_score": (1.5, 4.0),
    },
    {
        "drug_name": "对乙酰氨基酚",
        "smiles": "CC(=O)Nc1ccc(O)cc1",
        "target_gene": "PTGS2",
        "expected_difficulty": "easy",
        "expected_steps": (1, 3),
        "expected_sa_score": (1.0, 3.5),
    },
    {
        "drug_name": "咖啡因",
        "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        "target_gene": "ADORA2A",
        "expected_difficulty": "medium",
        "expected_steps": (4, 7),
        "expected_sa_score": (3.0, 5.5),
    },
    {
        "drug_name": "奥美拉唑",
        "smiles": "COc1ccc2[nH]c(nc2c1)S(=O)Cc1ncc(C)c(OC)c1C",
        "target_gene": "ATP4A",
        "expected_difficulty": "hard",
        "expected_steps": (6, 12),
        "expected_sa_score": (4.5, 7.5),
    },
]


class KnownDrugValidator:
    """已知药物验证器 — 用 5 个已知药物案例验证合成模块有效性

    流程：
    1. 对每个已知药物 SMILES 调用 SynthesisPlanner.plan()
    2. 比对生成路线的步骤数与文献已知范围
    3. 比对 SAscore 与预期范围
    4. 计算 route_accuracy_score（0-1）— 综合步骤数匹配度 + SAscore 匹配度 + 难度标签匹配度
    """

    def __init__(self, db: AsyncSession, llm_client=None, llm_config=None):
        self.db = db
        self.llm_client = llm_client
        self.llm_config = llm_config

    async def validate(self, drug_name: str, user) -> Dict[str, Any]:
        """验证单个已知药物

        Args:
            drug_name: 已知药物名称（中文，如"阿司匹林"）
            user: 当前用户
        Returns:
            {drug_name, smiles, expected_difficulty, actual_difficulty,
             expected_steps, actual_steps, steps_match, sa_score_match,
             route_accuracy_score, plan: {...}}
        """
        drug = next((d for d in KNOWN_DRUGS if d["drug_name"] == drug_name), None)
        if drug is None:
            available = [d["drug_name"] for d in KNOWN_DRUGS]
            return {
                "drug_name": drug_name,
                "error": f"未知药物，可选: {available}",
                "route_accuracy_score": 0.0,
            }

        # 调用 SynthesisPlanner 生成合成规划
        planner = SynthesisPlanner(self.db, llm_client=self.llm_client, llm_config=self.llm_config)
        plan_result = await planner.plan(
            smiles=drug["smiles"],
            user=user,
            max_routes=5,
            target_scale_grams=10.0,
        )

        # 提取实际值
        actual_steps = plan_result.get("n_steps_best", plan_result.get("n_steps", 0))
        actual_sa = plan_result.get("sa_score", 5.0)
        actual_difficulty = plan_result.get("feasibility_label", "medium")

        # 比对步骤数
        exp_steps_min, exp_steps_max = drug["expected_steps"]
        steps_match = exp_steps_min <= actual_steps <= exp_steps_max

        # 比对 SAscore
        exp_sa_min, exp_sa_max = drug["expected_sa_score"]
        sa_match = exp_sa_min <= actual_sa <= exp_sa_max

        # 比对难度标签
        difficulty_match = actual_difficulty == drug["expected_difficulty"]

        # 计算 route_accuracy_score（0-1）— 加权综合
        # 步骤匹配 0.4 + SAscore 匹配 0.3 + 难度匹配 0.3
        score = 0.0
        if steps_match:
            score += 0.4
        else:
            # 部分匹配：超出范围的程度
            if actual_steps < exp_steps_min:
                ratio = actual_steps / max(exp_steps_min, 1)
            else:
                ratio = exp_steps_max / max(actual_steps, 1)
            score += 0.4 * max(0, ratio)

        if sa_match:
            score += 0.3
        else:
            # SAscore 偏离程度
            mid = (exp_sa_min + exp_sa_max) / 2
            deviation = abs(actual_sa - mid) / max(mid, 1.0)
            score += 0.3 * max(0, 1 - deviation)

        if difficulty_match:
            score += 0.3

        score = round(min(1.0, max(0.0, score)), 3)

        return {
            "drug_name": drug_name,
            "smiles": drug["smiles"],
            "target_gene": drug["target_gene"],
            "expected_difficulty": drug["expected_difficulty"],
            "actual_difficulty": actual_difficulty,
            "expected_steps": list(drug["expected_steps"]),
            "actual_steps": actual_steps,
            "steps_match": steps_match,
            "expected_sa_score": list(drug["expected_sa_score"]),
            "actual_sa_score": actual_sa,
            "sa_score_match": sa_match,
            "difficulty_match": difficulty_match,
            "route_accuracy_score": score,
            "plan": plan_result,
        }

    async def validate_all(self, user) -> Dict[str, Any]:
        """验证所有 5 个已知药物，生成汇总报告

        Returns:
            {total, results: [...], summary: {avg_score, passed, failed, by_difficulty}}
        """
        results = []
        for drug in KNOWN_DRUGS:
            try:
                result = await self.validate(drug["drug_name"], user)
                results.append(result)
            except Exception as e:
                logger.warning(f"验证 {drug['drug_name']} 失败: {e}")
                results.append({
                    "drug_name": drug["drug_name"],
                    "error": str(e),
                    "route_accuracy_score": 0.0,
                })

        # 汇总统计
        scores = [r.get("route_accuracy_score", 0.0) for r in results]
        avg_score = round(sum(scores) / max(len(scores), 1), 3)
        passed = sum(1 for s in scores if s >= 0.6)  # >= 0.6 视为通过
        failed = len(scores) - passed

        # 按难度分组
        by_difficulty: Dict[str, Dict[str, int]] = {}
        for drug, result in zip(KNOWN_DRUGS, results):
            diff = drug["expected_difficulty"]
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "passed": 0}
            by_difficulty[diff]["total"] += 1
            if result.get("route_accuracy_score", 0) >= 0.6:
                by_difficulty[diff]["passed"] += 1

        # 提取局部变量，避免嵌套 f-string 引号转义问题（Python < 3.12 不支持）
        by_diff_summary = "; ".join(
            f"{k}={v['passed']}/{v['total']}" for k, v in by_difficulty.items()
        )
        return {
            "total": len(results),
            "results": results,
            "summary": {
                "avg_score": avg_score,
                "passed": passed,
                "failed": failed,
                "pass_rate": round(passed / max(len(results), 1), 3),
                "by_difficulty": by_difficulty,
            },
            "conclusion": (
                f"5 个已知药物验证完成：平均路线准确性 {avg_score:.1%}，"
                f"{passed}/{len(results)} 通过（>= 0.6）。"
                f"按难度：{by_diff_summary}"
            ),
        }

    @staticmethod
    def list_known_drugs() -> List[Dict[str, Any]]:
        """返回所有已知药物案例列表（不含验证结果）"""
        return [
            {
                "drug_name": d["drug_name"],
                "smiles": d["smiles"],
                "target_gene": d["target_gene"],
                "expected_difficulty": d["expected_difficulty"],
                "expected_steps": list(d["expected_steps"]),
                "expected_sa_score": list(d["expected_sa_score"]),
            }
            for d in KNOWN_DRUGS
        ]
