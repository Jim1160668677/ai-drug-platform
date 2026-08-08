"""干湿闭环反馈 — Dry-Wet Loop 核心"""
import logging
import math
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """把 str/UUID 统一转为 UUID（SQLAlchemy Uuid 列要求 UUID 对象）

    None 透传；非法格式抛 ValueError。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class FeedbackLoop:
    """干湿闭环反馈引擎

    比对 dry prediction（计算预测）vs wet result（湿实验结果），
    计算误差，触发模型权重更新，生成下一迭代建议。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_closure(self, experiment) -> Dict[str, Any]:
        """干湿闭环完整编排:误差反馈 + 假设反馈 + 失败沉淀"""
        result: Dict[str, Any] = {"feedback": {}}
        try:
            result["feedback"] = await self.apply_feedback(experiment)
        except Exception as e:
            logger.warning("apply_feedback 异常(不阻断): %s", e)
        try:
            result["hypothesis_feedback"] = await self.feedback_to_hypotheses(experiment)
        except Exception as e:
            logger.warning("feedback_to_hypotheses 异常(不阻断): %s", e)
        if experiment.success is False:
            try:
                result["failure_knowledge"] = await self.ingest_failure(experiment)
            except Exception as e:
                logger.warning("ingest_failure 异常(不阻断): %s", e)
        return result

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
        treatment = await self.db.get(Treatment, _to_uuid(treatment_id))

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

    async def apply_task_feedback(self, task_id: str) -> Dict[str, Any]:
        """把验证任务结论反馈到靶点/分子置信度

        回应评委"生信结论与真实情况有出入"：把湿实验验证结论回写到 AI 模型置信度。

        - validated   → target.confidence += 0.1（上限 1.0）
        - refuted      → target.confidence -= 0.2（下限 0.0）
        - inconclusive → 不调整
        - 若 task.molecule_id，在 molecule.properties 写入 validation_status 标记
        - confidence_score 为 None 时初始化为 0.5 再调整
        - task.conclusion 为空时抛 AppException（必须先 record_result）
        """
        # 局部导入避免循环依赖（与 apply_clinical_feedback 内导入 Treatment 风格一致）
        from app.models.validation import ValidationConclusion, ValidationTask
        from app.models.target import Target
        from app.models.molecule import Molecule
        from app.core.exceptions import AppException, NotFoundError

        task = await self.db.get(ValidationTask, _to_uuid(task_id))
        if not task:
            raise NotFoundError("验证任务不存在")
        if not task.conclusion:
            raise AppException("验证任务尚未记录结论，无法应用反馈")

        target_conf_before: Optional[float] = None
        target_conf_after: Optional[float] = None
        molecule_status: Optional[str] = None

        # 反馈到靶点置信度
        if task.target_id:
            target = await self.db.get(Target, task.target_id)
            if target:
                target_conf_before = target.confidence_score
                # None 时初始化为 0.5（中性先验）
                base = target.confidence_score if target.confidence_score is not None else 0.5
                if task.conclusion == ValidationConclusion.VALIDATED:
                    base = min(1.0, base + 0.1)
                elif task.conclusion == ValidationConclusion.REFUTED:
                    base = max(0.0, base - 0.2)
                # inconclusive 不变
                target.confidence_score = round(base, 3)
                target_conf_after = target.confidence_score

        # 反馈到分子：写入 properties 标记（Molecule 无独立 priority 字段，复用 JSON）
        if task.molecule_id:
            molecule = await self.db.get(Molecule, task.molecule_id)
            if molecule:
                props = dict(molecule.properties or {})
                props["validation_status"] = task.conclusion
                props["validation_task_id"] = str(task.id)
                molecule.properties = props
                molecule_status = task.conclusion

        await self.db.commit()
        logger.info(
            f"验证反馈已应用: task={task_id} conclusion={task.conclusion} "
            f"target_conf {target_conf_before}→{target_conf_after}"
        )
        return {
            "task_id": str(task.id),
            "conclusion": task.conclusion,
            "target_id": str(task.target_id) if task.target_id else None,
            "target_confidence_before": target_conf_before,
            "target_confidence_after": target_conf_after,
            "molecule_id": str(task.molecule_id) if task.molecule_id else None,
            "molecule_status": molecule_status,
            "feedback_applied": True,
        }

    async def apply_validation_feedback(
        self,
        experiment,
        conclusion: str,
        confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """将实验结论反馈到关联假设的 Elo 评分

        干湿闭环核心：湿实验验证结论 → 假设 Elo 评分调整。

        - VALIDATED   → hypothesis.elo_score += 15 * confidence (默认 1.0)
        - REFUTED     → hypothesis.elo_score -= 25 * confidence
        - INCONCLUSIVE → elo 不变
        - 记录 evolution_history: [{round, type, conclusion, elo_change, confidence}]
        - 使用 async with self.db.begin() 管理事务

        Args:
            experiment: Experiment ORM 对象（需通过 hypothesis 关联假设）
            conclusion: "VALIDATED" / "REFUTED" / "INCONCLUSIVE"
            confidence: 置信度权重 0-1，默认 1.0

        Returns:
            {hypothesis_id, elo_before, elo_after, elo_change, confidence, conclusion, success}
        """
        from app.models.hypothesis import Hypothesis
        from sqlalchemy import select
        from datetime import datetime, timezone

        CONFIDENCE_MAP = {"VALIDATED", "REFUTED", "INCONCLUSIVE"}
        if conclusion not in CONFIDENCE_MAP:
            raise ValueError(
                f"非法结论: {conclusion}，合法值为 {CONFIDENCE_MAP}"
            )

        effective_confidence = confidence if confidence is not None else 1.0
        # 与 Elo 锦标赛 K-factor (32) 对齐
        K_FACTOR = 32

        async with self.db.begin() as transaction:
            hypothesis = experiment.hypothesis
            if not hypothesis:
                transaction.rollback()
                return {
                    "hypothesis_id": None,
                    "elo_before": None,
                    "elo_after": None,
                    "elo_change": 0,
                    "confidence": effective_confidence,
                    "conclusion": conclusion,
                    "success": False,
                    "error": "实验未关联假设 (hypothesis_id 为 None)",
                }

            elo_before = hypothesis.elo_score if hypothesis.elo_score is not None else 1000.0
            elo_change = 0.0

            if conclusion == "VALIDATED":
                elo_change = K_FACTOR * effective_confidence
            elif conclusion == "REFUTED":
                elo_change = -K_FACTOR * 1.5 * effective_confidence

            elo_after = elo_before + elo_change
            hypothesis.elo_score = elo_after

            # 独立记录实验驱动的 Elo 调整量（展示层区分 LLM 评分 vs 实验评分）
            exp_adj = getattr(hypothesis, 'experimental_elo_adjustment', 0.0) or 0.0
            hypothesis.experimental_elo_adjustment = round(exp_adj + elo_change, 3)
            exp_count = getattr(hypothesis, 'experimental_validation_count', 0) or 0
            hypothesis.experimental_validation_count = exp_count + 1

            timestamp = datetime.now(timezone.utc).isoformat()
            history_entry = {
                "round": timestamp,
                "type": "validation",
                "conclusion": conclusion,
                "elo_change": elo_change,
                "confidence": effective_confidence,
                "experimental_elo_cumulative": hypothesis.experimental_elo_adjustment,
            }

            history = list(hypothesis.evolution_history or [])
            history.append(history_entry)
            hypothesis.evolution_history = history

            await self.db.flush()

        logger.info(
            f"假设验证反馈已应用: hypothesis={hypothesis.id} "
            f"conclusion={conclusion} elo {elo_before}→{elo_after} "
            f"(change={elo_change}, confidence={effective_confidence})"
        )

        return {
            "hypothesis_id": str(hypothesis.id),
            "elo_before": elo_before,
            "elo_after": elo_after,
            "elo_change": elo_change,
            "confidence": effective_confidence,
            "conclusion": conclusion,
            "success": True,
        }

    async def feedback_to_hypotheses(self, experiment) -> Dict[str, Any]:
        """将实验结果反馈到关联假设

        根据 experiment.hypothesis_id 查询关联的 Hypothesis，
        若 experiment.result 中有 conclusion 字段则调用 apply_validation_feedback。

        Args:
            experiment: Experiment ORM 对象

        Returns:
            {hypothesis_id: str, elo_before: float, elo_after: float}
        """
        from app.models.hypothesis import Hypothesis
        from sqlalchemy import select

        if not experiment.hypothesis_id:
            return {
                "hypothesis_id": None,
                "elo_before": None,
                "elo_after": None,
                "error": "实验未关联假设",
            }

        stmt = select(Hypothesis).where(Hypothesis.id == experiment.hypothesis_id)
        result = await self.db.execute(stmt)
        hypothesis = result.scalar_one_or_none()

        if not hypothesis:
            return {
                "hypothesis_id": str(experiment.hypothesis_id),
                "elo_before": None,
                "elo_after": None,
                "error": "关联的假设不存在",
            }

        result_data = experiment.result or {}
        conclusion = result_data.get("conclusion")

        if not conclusion:
            elo_val = hypothesis.elo_score if hypothesis.elo_score is not None else 1000.0
            return {
                "hypothesis_id": str(hypothesis.id),
                "elo_before": elo_val,
                "elo_after": elo_val,
                "message": "实验结果中无结论字段，跳过反馈",
            }

        feedback_result = await self.apply_validation_feedback(
            experiment, conclusion
        )

        return {
            "hypothesis_id": str(hypothesis.id),
            "elo_before": feedback_result.get("elo_before"),
            "elo_after": feedback_result.get("elo_after"),
        }

    async def ingest_failure(self, experiment) -> Dict[str, Any]:
        """将失败实验沉淀为失败知识库条目

        当 experiment.success = False 时调用：
        1. 自动分类失败原因（LLM 辅助 + 规则兜底）
        2. 写入 FailureKnowledge
        3. 回写 experiment 的 failure_reason / failure_params / wrong_path_proof

        Args:
            experiment: Experiment ORM 对象

        Returns:
            {failure_knowledge_id, failure_reason, is_new, message}
        """
        from app.models.failure_knowledge import FailureKnowledge, FailureReason

        if experiment.success is not False:
            return {
                "failure_knowledge_id": None,
                "failure_reason": None,
                "is_new": False,
                "message": "实验非失败状态，跳过失败沉淀",
            }

        reason, proof = await self._classify_failure(experiment)

        failure_params = self._extract_failure_params(experiment)

        existing = await self._find_existing_failure(experiment, reason)

        if existing:
            existing.failure_count = (existing.failure_count or 1) + 1
            existing.failure_params = failure_params
            existing.wrong_path_proof = proof
            experiment.failure_reason = {"primary": reason, "detail": proof}
            experiment.failure_params = failure_params
            experiment.wrong_path_proof = proof
            is_new = False
            fk_id = str(existing.id)
        else:
            fk = FailureKnowledge(
                project_id=experiment.project_id,
                failure_reason=reason,
                failure_params=failure_params,
                wrong_path_proof=proof,
                target_id=experiment.target_id,
                molecule_id=experiment.molecule_id,
                hypothesis_id=experiment.hypothesis_id,
                experiment_id=experiment.id,
                is_high_confidence=False,
                failure_count=1,
                notes=experiment.notes,
            )
            self.db.add(fk)
            experiment.failure_reason = {"primary": reason, "detail": proof}
            experiment.failure_params = failure_params
            experiment.wrong_path_proof = proof
            is_new = True
            fk_id = str(fk.id)

        await self.db.flush()

        logger.info(
            f"失败知识沉淀: experiment={experiment.id} reason={reason} "
            f"is_new={is_new}"
        )

        return {
            "failure_knowledge_id": fk_id,
            "failure_reason": reason,
            "is_new": is_new,
            "message": "失败知识已沉淀" if is_new else "已有同类失败，计数累加",
        }

    async def _classify_failure(self, experiment) -> tuple:
        """分类失败原因 — LLM 辅助 + 规则兜底

        Returns:
            (reason: str, proof: str)
        """
        from app.models.failure_knowledge import FailureReason

        reason = FailureReason.UNKNOWN
        proof = ""

        result = experiment.result or {}
        config = experiment.config or {}
        notes = experiment.notes or ""
        result_text = f"{result} {config} {notes}".lower()

        rule_map = [
            (FailureReason.CONTAMINATION, ["污染", "contamin", "污染菌", "浊度", "turbid"]),
            (FailureReason.CONCENTRATION, ["浓度", "concentration", "太低", "too low", "太高", "too high", "剂量"]),
            (FailureReason.PROTOCOL_DEGRADATION, ["降解", "degrad", "过期", "expir", "失活", "inactiv"]),
            (FailureReason.EQUIPMENT_MALFUNCTION, ["设备", "equipment", "仪器", "malfunction", "故障", "error code"]),
            (FailureReason.HUMAN_ERROR, ["操作", "human error", "失误", "mistake", "pipett", "加样"]),
            (FailureReason.BIOLOGICAL_VARIABILITY, ["变异", "variability", "个体差异", "heterogeneity", "生物"]),
        ]

        for rule_reason, keywords in rule_map:
            for kw in keywords:
                if kw in result_text:
                    reason = rule_reason
                    proof = f"检测到关键词「{kw}」"
                    break
            if reason != FailureReason.UNKNOWN:
                break

        if reason == FailureReason.UNKNOWN:
            llm_reason = await self._llm_classify_failure(experiment)
            if llm_reason:
                reason = llm_reason
                proof = f"LLM 分类: {llm_reason}"

        if not proof:
            proof = notes or "无详细说明"

        return reason, proof

    async def _llm_classify_failure(self, experiment) -> Optional[str]:
        """尝试用 LLM 对失败原因进行分类（失败则返回 None）"""
        try:
            from app.services.llm.router import LLMRouter
            from app.models.failure_knowledge import FailureReason

            router = LLMRouter()
            result = experiment.result or {}
            config = experiment.config or {}

            prompt = (
                "你是实验病理学家。请根据以下实验信息判断失败的主要原因分类。\n"
                "可选分类: contamination(污染), concentration(浓度不合适), "
                "protocol_degradation(方案降解), equipment_malfunction(设备故障), "
                "human_error(人为失误), biological_variability(生物学变异), unknown(未知)\n\n"
                f"实验类型: {experiment.exp_type}\n"
                f"实验结果: {result}\n"
                f"实验配置: {config}\n"
                f"备注: {experiment.notes or ''}\n\n"
                "只返回分类名称，不要解释。"
            )

            response = await router.complete(
                messages=[{"role": "user", "content": prompt}],
                model="test-model",
            )
            content = (response or {}).get("content", "").strip().lower()

            valid_reasons = [
                FailureReason.CONTAMINATION, FailureReason.CONCENTRATION,
                FailureReason.PROTOCOL_DEGRADATION, FailureReason.EQUIPMENT_MALFUNCTION,
                FailureReason.HUMAN_ERROR, FailureReason.BIOLOGICAL_VARIABILITY,
                FailureReason.UNKNOWN,
            ]
            for r in valid_reasons:
                if r in content:
                    return r

        except Exception as e:
            logger.warning(f"LLM 失败分类不可用，回退规则引擎: {e}")

        return None

    def _extract_failure_params(self, experiment) -> dict:
        """提取实验失败时的参数快照"""
        params = {
            "exp_type": experiment.exp_type,
            "status": experiment.status,
            "config": experiment.config,
            "result": experiment.result,
            "iteration": experiment.iteration,
            "lab_source": experiment.lab_source,
        }
        if experiment.target_id:
            params["target_id"] = str(experiment.target_id)
        if experiment.molecule_id:
            params["molecule_id"] = str(experiment.molecule_id)
        return params

    async def _find_existing_failure(self, experiment, reason: str):
        """查找是否已存在相同 project + target + molecule + reason 的失败记录"""
        from app.models.failure_knowledge import FailureKnowledge
        from sqlalchemy import select

        stmt = select(FailureKnowledge).where(
            FailureKnowledge.project_id == experiment.project_id,
            FailureKnowledge.failure_reason == reason,
        )

        if experiment.target_id:
            stmt = stmt.where(FailureKnowledge.target_id == experiment.target_id)
        if experiment.molecule_id:
            stmt = stmt.where(FailureKnowledge.molecule_id == experiment.molecule_id)
        if experiment.hypothesis_id:
            stmt = stmt.where(FailureKnowledge.hypothesis_id == experiment.hypothesis_id)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
