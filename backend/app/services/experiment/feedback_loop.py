"""干湿闭环反馈 — Dry-Wet Loop 核心"""
import logging
import math
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """干湿闭环反馈引擎

    比对 dry prediction（计算预测）vs wet result（湿实验结果），
    计算误差，触发模型权重更新，生成下一迭代建议。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def apply_feedback(self, experiment) -> Dict[str, Any]:
        """应用干湿闭环反馈

        Args:
            experiment: Experiment ORM 对象（已含 result 和 config）
        Returns:
            {feedback: {error_metrics, model_updated, next_iteration, suggested_adjustments}}
        """
        config = experiment.config or {}
        result = experiment.result or {}

        # 提取预测值和实测值
        predicted = config.get("predicted", {})
        measured = result.get("measured", {})

        # 计算误差
        error_metrics = self._compute_errors(predicted, measured)

        # 判断方向是否一致
        direction_match = self._check_direction(predicted, measured)

        # 尝试联邦学习权重更新（P3 框架）
        model_updated = False
        try:
            from app.services.optimizer.federated_learning import FederatedLearner
            learner = FederatedLearner()
            update_result = await learner.update_weights({
                "experiment_id": str(experiment.id),
                "error": error_metrics,
                "gradients": "placeholder",  # 实际需计算梯度
            })
            model_updated = update_result.get("status") == "submitted"
        except Exception as e:
            logger.info(f"联邦学习未启用（P3 框架）: {e}")

        # 标记反馈已应用
        experiment.feedback_applied = True

        # 生成下一迭代建议
        next_iteration = (experiment.iteration or 1) + 1
        suggested_adjustments = self._suggest_adjustments(error_metrics, direction_match, experiment)

        return {
            "feedback": {
                "error_metrics": error_metrics,
                "direction_match": direction_match,
                "model_updated": model_updated,
                "next_iteration": next_iteration,
                "suggested_adjustments": suggested_adjustments,
            },
            "experiment_id": str(experiment.id),
            "iteration": experiment.iteration or 1,
        }

    def _compute_errors(self, predicted, measured) -> Dict[str, float]:
        """计算预测与实测的误差

        兼容三种输入格式：
        - float/int：直接计算绝对误差
        - dict：按共有 key 计算多指标误差
        - 空值：返回零误差
        """
        # 标准化为 dict
        pred_dict = self._normalize_metrics(predicted)
        meas_dict = self._normalize_metrics(measured)

        if not pred_dict or not meas_dict:
            return {"mae": 0, "rmse": 0, "mape": 0, "note": "无预测/实测数据"}

        # 找到共有的 key
        common_keys = set(pred_dict.keys()) & set(meas_dict.keys())
        if not common_keys:
            return {"mae": 0, "rmse": 0, "mape": 0, "note": "无匹配指标"}

        errors: List[float] = []
        pct_errors: List[float] = []

        for key in common_keys:
            try:
                p = float(pred_dict[key])
                m = float(meas_dict[key])
                abs_err = abs(p - m)
                errors.append(abs_err)
                if m != 0:
                    pct_errors.append(abs_err / abs(m) * 100)
            except (ValueError, TypeError):
                continue

        if not errors:
            return {"mae": 0, "rmse": 0, "mape": 0, "note": "无法计算数值误差"}

        mae = sum(errors) / len(errors)
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        mape = sum(pct_errors) / len(pct_errors) if pct_errors else 0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 2),
            "metrics_compared": list(common_keys),
        }

    def _normalize_metrics(self, value) -> Dict[str, float]:
        """将预测/实测值标准化为 dict 格式

        - None/空：返回 {}
        - float/int：返回 {"value": float}
        - dict：原样返回
        - list：尝试转为 {idx: v}
        - str：尝试 float 转换，失败返回 {}
        """
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, (int, float)):
            try:
                return {"value": float(value)}
            except (ValueError, TypeError):
                return {}
        if isinstance(value, (list, tuple)):
            return {str(i): v for i, v in enumerate(value) if isinstance(v, (int, float))}
        if isinstance(value, str):
            try:
                return {"value": float(value)}
            except ValueError:
                return {}
        return {}

    def _check_direction(self, predicted, measured) -> bool:
        """检查预测方向是否与实测一致"""
        pred_dict = self._normalize_metrics(predicted)
        meas_dict = self._normalize_metrics(measured)

        common_keys = set(pred_dict.keys()) & set(meas_dict.keys())
        if not common_keys:
            return True  # 无数据时默认一致

        for key in common_keys:
            try:
                p = float(pred_dict[key])
                m = float(meas_dict[key])
                # 如果预测和实测符号相反（一正一负），方向不一致
                if (p > 0 and m < 0) or (p < 0 and m > 0):
                    return False
            except (ValueError, TypeError):
                continue
        return True

    def _suggest_adjustments(
        self,
        error_metrics: Dict,
        direction_match: bool,
        experiment,
    ) -> List[str]:
        """基于误差生成下一迭代建议"""
        suggestions: List[str] = []
        mape = error_metrics.get("mape", 0)

        if mape > 50:
            suggestions.append("预测误差较大（MAPE>50%），建议调整模型参数或增加训练数据")
        elif mape > 20:
            suggestions.append("预测误差中等（20%<MAPE<50%），建议微调模型")
        else:
            suggestions.append("预测误差可接受（MAPE<20%），模型表现良好")

        if not direction_match:
            suggestions.append("预测方向与实测不一致，建议检查模型假设和数据预处理")

        # 根据实验类型给建议
        if experiment.exp_type == "cytotoxicity":
            suggestions.append("建议在下一迭代中测试更广的浓度梯度")
        elif experiment.exp_type == "pdx":
            suggestions.append("建议增加 PDX 模型样本量以提高统计效力")

        return suggestions

    async def apply_clinical_feedback(
        self,
        feedback_data: Dict[str, Any],
        treatment_id: str,
    ) -> Dict[str, Any]:
        """应用临床反馈到闭环

        1. 计算实际vs预期疗效差异
        2. 记录不良反应
        3. 触发方案优化建议
        4. 关联实验数据（通过 treatment_id）
        """
        from app.models.treatment import Treatment
        treatment = await self.db.get(Treatment, treatment_id)

        expected_efficacy = (treatment.efficacy_score if treatment else 0.5) or 0.5
        efficacy_map = {"complete": 1.0, "partial": 0.6, "stable": 0.4, "progressive": 0.1}
        actual_efficacy = efficacy_map.get(feedback_data.get("efficacy", ""), 0.5)

        efficacy_diff = actual_efficacy - expected_efficacy
        adverse_reactions = feedback_data.get("adverse_reactions") or []

        suggestions: List[str] = []
        if efficacy_diff < -0.2:
            suggestions.append("实际疗效显著低于预期，建议调整用药方案或更换药物")
        elif efficacy_diff < 0:
            suggestions.append("实际疗效略低于预期，建议微调剂量")
        else:
            suggestions.append("实际疗效符合或超过预期，方案有效")

        if adverse_reactions:
            suggestions.append(f"记录到 {len(adverse_reactions)} 项不良反应，建议评估风险收益比")

        return {
            "treatment_id": treatment_id,
            "loop_stage": "clinical_validation",
            "expected_efficacy": round(expected_efficacy, 3),
            "actual_efficacy": round(actual_efficacy, 3),
            "efficacy_diff": round(efficacy_diff, 3),
            "adverse_reactions_count": len(adverse_reactions),
            "optimization_suggestions": suggestions,
            "next_stage": "dry_prediction_update",
        }
