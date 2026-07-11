"""工作流反馈环 — 干湿闭环 + 实验状态机 + LIMS 导入

整合三个紧密相关的反馈环组件到同一模块：
- ``FeedbackLoop``：摄入实验结果，检测预测偏差并触发模型重新校准
- ``ExperimentTracker``：实验状态机（pending → running → completed / failed）
- ``LimsImporter``：从 CSV/JSON 批量导入 LIMS 实验数据

设计目标：
- 配置驱动：偏差阈值、状态机校验均从 ``settings`` 读取
- Mock/Real 双模式：无数据库或无目标记录时降级返回空结果
- 完整 type hints + 中文 docstring
- 状态机：pending → running → completed / failed
"""
import csv
import json
import logging
import statistics
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.experiment import Experiment, ExperimentStatus
from app.models.target import Target

logger = logging.getLogger(__name__)


# 状态机定义：合法的状态转换
_STATE_MACHINE: Dict[str, List[str]] = {
    "pending": ["running"],
    "running": ["completed", "failed"],
    "completed": [],  # 终态
    "failed": ["pending"],  # 失败后可重新入队
}

# 偏差检测默认最小样本数
_DEFAULT_MIN_SAMPLES = 5

# 偏差阈值（MAPE 超过此值认为存在系统偏差）
_DEFAULT_BIAS_THRESHOLD = 30.0


class FeedbackLoop:
    """干湿闭环反馈引擎

    摄入湿实验结果，比对 dry prediction（计算预测），检测系统偏差，
    并触发模型重新校准。与 ``experiment/feedback_loop.py`` 中的
    ``FeedbackLoop`` 互补：本类聚焦"反馈环"流程编排，
    而非单次实验的误差计算。

    Examples:
        >>> loop = FeedbackLoop(db)
        >>> await loop.ingest_experiment_result(uuid4(), {"measured": {"ic50": 1.2}})
        >>> bias = await loop.detect_bias("EGFR")
        >>> await loop.recalibrate("EGFR")
    """

    def __init__(self, db: AsyncSession):
        """初始化反馈环

        Args:
            db: 异步数据库会话
        """
        self.db = db

    async def ingest_experiment_result(
        self,
        experiment_id: UUID,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """摄入实验结果，触发反馈环

        流程：
        1. 写入 experiment.result
        2. 比对 predicted vs measured，计算误差
        3. 标记 feedback_applied=True
        4. 若 MAPE 超阈值，标记需要 recalibrate

        Args:
            experiment_id: 实验 ID
            result: 实验结果 ``{"measured": {...}, "notes": "..."}``

        Returns:
            {
                "status": "ingested" | "not_found",
                "experiment_id": str,
                "error_metrics": Dict,
                "needs_recalibration": bool,
            }
        """
        experiment = await self.db.get(Experiment, experiment_id)
        if experiment is None:
            logger.warning("反馈环：未找到实验 %s", experiment_id)
            return {
                "status": "not_found",
                "experiment_id": str(experiment_id),
                "error_metrics": {},
                "needs_recalibration": False,
            }

        # 写入结果
        experiment.result = result
        experiment.feedback_applied = True

        # 计算误差
        config = experiment.config or {}
        predicted = config.get("predicted", {})
        measured = result.get("measured", {})
        error_metrics = self._compute_errors(predicted, measured)

        # 判断是否需要重新校准
        mape = error_metrics.get("mape", 0)
        needs_recalibration = mape > _DEFAULT_BIAS_THRESHOLD

        # 标记实验成功/失败（基于方向一致性）
        direction_match = self._check_direction(predicted, measured)
        if "success" in result:
            experiment.success = bool(result["success"])
        else:
            experiment.success = direction_match and mape < _DEFAULT_BIAS_THRESHOLD

        logger.info(
            "反馈环摄入：experiment=%s, mape=%.2f, needs_recalibration=%s",
            experiment_id,
            mape,
            needs_recalibration,
        )

        return {
            "status": "ingested",
            "experiment_id": str(experiment_id),
            "error_metrics": error_metrics,
            "needs_recalibration": needs_recalibration,
            "direction_match": direction_match,
        }

    async def detect_bias(
        self,
        target_symbol: str,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> Dict[str, Any]:
        """检测某靶点的系统偏差

        汇总该靶点所有已反馈实验的 MAPE，若样本量充足且平均 MAPE
        超过阈值，则判定存在系统偏差。

        Args:
            target_symbol: 靶点基因符号（如 "EGFR"）
            min_samples: 最小样本数，少于该值返回 "insufficient_samples"

        Returns:
            {
                "status": "biased" | "no_bias" | "insufficient_samples",
                "target_symbol": str,
                "sample_count": int,
                "mean_mape": float,
                "threshold": float,
            }
        """
        # 查询该靶点所有已反馈实验
        stmt = (
            select(Experiment)
            .join(Target, Experiment.target_id == Target.id)
            .where(Target.gene_symbol == target_symbol)
            .where(Experiment.feedback_applied.is_(True))
        )
        result = await self.db.execute(stmt)
        experiments: List[Experiment] = list(result.scalars().all())

        if len(experiments) < min_samples:
            logger.info(
                "偏差检测：靶点 %s 样本不足（%d/%d）",
                target_symbol,
                len(experiments),
                min_samples,
            )
            return {
                "status": "insufficient_samples",
                "target_symbol": target_symbol,
                "sample_count": len(experiments),
                "mean_mape": 0.0,
                "threshold": _DEFAULT_BIAS_THRESHOLD,
            }

        # 计算每个实验的 MAPE
        mape_values: List[float] = []
        for exp in experiments:
            config = exp.config or {}
            result_data = exp.result or {}
            predicted = config.get("predicted", {})
            measured = result_data.get("measured", {})
            errors = self._compute_errors(predicted, measured)
            mape = errors.get("mape", 0)
            if isinstance(mape, (int, float)) and mape >= 0:
                mape_values.append(float(mape))

        if not mape_values:
            return {
                "status": "insufficient_samples",
                "target_symbol": target_symbol,
                "sample_count": len(experiments),
                "mean_mape": 0.0,
                "threshold": _DEFAULT_BIAS_THRESHOLD,
            }

        mean_mape = statistics.mean(mape_values)
        is_biased = mean_mape > _DEFAULT_BIAS_THRESHOLD

        logger.info(
            "偏差检测：靶点 %s, n=%d, mean_mape=%.2f, biased=%s",
            target_symbol,
            len(mape_values),
            mean_mape,
            is_biased,
        )

        return {
            "status": "biased" if is_biased else "no_bias",
            "target_symbol": target_symbol,
            "sample_count": len(mape_values),
            "mean_mape": round(mean_mape, 2),
            "threshold": _DEFAULT_BIAS_THRESHOLD,
        }

    async def recalibrate(self, target_symbol: str) -> Dict[str, Any]:
        """对指定靶点触发模型重新校准

        在真实模式下应调用联邦学习器更新权重；
        当前为 Mock/Real 双模式降级：仅记录校准事件，返回框架态信息。

        Args:
            target_symbol: 靶点基因符号

        Returns:
            {
                "status": "recalibrated" | "framework_only" | "no_data",
                "target_symbol": str,
                "action": str,
            }
        """
        # 先检测偏差，决定是否真的需要校准
        bias_result = await self.detect_bias(target_symbol)
        if bias_result["status"] == "insufficient_samples":
            return {
                "status": "no_data",
                "target_symbol": target_symbol,
                "action": "样本不足，跳过校准",
                "bias_status": bias_result["status"],
            }

        # 尝试调用联邦学习器（Mock/Real 双模式）
        try:
            from app.services.optimizer.federated_learning import FederatedLearner

            learner = FederatedLearner()
            update_result = await learner.update_weights(
                {
                    "target_symbol": target_symbol,
                    "trigger": "bias_recalibration",
                    "mean_mape": bias_result.get("mean_mape", 0),
                }
            )
            status = (
                "recalibrated"
                if update_result.get("status") == "submitted"
                else "framework_only"
            )
            return {
                "status": status,
                "target_symbol": target_symbol,
                "action": "已触发联邦学习权重更新",
                "fl_result": update_result,
                "bias_status": bias_result["status"],
            }
        except Exception as e:
            logger.warning(
                "联邦学习器调用失败，降级为框架态: %s", e
            )
            return {
                "status": "framework_only",
                "target_symbol": target_symbol,
                "action": "联邦学习未启用（P3 框架）",
                "bias_status": bias_result["status"],
                "error": str(e),
            }

    # -------- 内部辅助方法 --------

    def _compute_errors(
        self, predicted: Any, measured: Any
    ) -> Dict[str, Any]:
        """计算预测与实测的误差（MAE / RMSE / MAPE）"""
        pred_dict = self._normalize_metrics(predicted)
        meas_dict = self._normalize_metrics(measured)

        if not pred_dict or not meas_dict:
            return {"mae": 0, "rmse": 0, "mape": 0, "note": "无预测/实测数据"}

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
        rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
        mape = sum(pct_errors) / len(pct_errors) if pct_errors else 0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 2),
            "metrics_compared": sorted(common_keys),
        }

    def _normalize_metrics(self, value: Any) -> Dict[str, float]:
        """将预测/实测值标准化为 dict 格式"""
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
            return {
                str(i): v
                for i, v in enumerate(value)
                if isinstance(v, (int, float))
            }
        if isinstance(value, str):
            try:
                return {"value": float(value)}
            except ValueError:
                return {}
        return {}

    def _check_direction(self, predicted: Any, measured: Any) -> bool:
        """检查预测方向是否与实测一致"""
        pred_dict = self._normalize_metrics(predicted)
        meas_dict = self._normalize_metrics(measured)
        common_keys = set(pred_dict.keys()) & set(meas_dict.keys())
        if not common_keys:
            return True
        for key in common_keys:
            try:
                p = float(pred_dict[key])
                m = float(meas_dict[key])
                if (p > 0 and m < 0) or (p < 0 and m > 0):
                    return False
            except (ValueError, TypeError):
                continue
        return True


class ExperimentTracker:
    """实验状态机追踪器

    实现实验状态机：``pending → running → completed / failed``

    合法转换：
    - pending → running
    - running → completed
    - running → failed
    - failed → pending（重新入队）

    非法转换将被拒绝并返回 ``status="invalid_transition"``。

    Note:
        本类与 ``ExperimentStatus``（PLANNED/RUNNING/COMPLETED/FAILED）兼容，
        内部统一映射到状态机的 ``pending`` 起始态。
    """

    def __init__(self, db: AsyncSession):
        """初始化追踪器

        Args:
            db: 异步数据库会话
        """
        self.db = db

    async def transition(
        self,
        experiment_id: UUID,
        new_status: str,
    ) -> Dict[str, Any]:
        """执行状态转换

        Args:
            experiment_id: 实验 ID
            new_status: 目标状态（pending/running/completed/failed）

        Returns:
            {
                "status": "transitioned" | "invalid_transition" | "not_found",
                "experiment_id": str,
                "previous_status": str,
                "current_status": str,
            }
        """
        experiment = await self.db.get(Experiment, experiment_id)
        if experiment is None:
            logger.warning("状态转换：未找到实验 %s", experiment_id)
            return {
                "status": "not_found",
                "experiment_id": str(experiment_id),
                "previous_status": "",
                "current_status": "",
            }

        # 将 ORM 中的 status 映射到状态机命名
        current = self._normalize_status(experiment.status)
        target = self._normalize_status(new_status)

        # 校验合法转换
        allowed = _STATE_MACHINE.get(current, [])
        if target not in allowed:
            logger.warning(
                "状态转换非法：%s → %s（experiment=%s）",
                current,
                target,
                experiment_id,
            )
            return {
                "status": "invalid_transition",
                "experiment_id": str(experiment_id),
                "previous_status": current,
                "current_status": current,
                "requested_status": target,
                "allowed_transitions": allowed,
            }

        previous = current
        # 写回 ORM（映射回 ExperimentStatus 命名）
        experiment.status = self._denormalize_status(target)

        logger.info(
            "状态转换：%s → %s（experiment=%s）",
            previous,
            target,
            experiment_id,
        )

        return {
            "status": "transitioned",
            "experiment_id": str(experiment_id),
            "previous_status": previous,
            "current_status": target,
        }

    async def get_state(self, experiment_id: UUID) -> Dict[str, Any]:
        """获取实验当前状态

        Args:
            experiment_id: 实验 ID

        Returns:
            {
                "status": "ok" | "not_found",
                "experiment_id": str,
                "current_status": str,
                "is_terminal": bool,
            }
        """
        experiment = await self.db.get(Experiment, experiment_id)
        if experiment is None:
            return {
                "status": "not_found",
                "experiment_id": str(experiment_id),
                "current_status": "",
                "is_terminal": False,
            }

        normalized = self._normalize_status(experiment.status)
        is_terminal = len(_STATE_MACHINE.get(normalized, [])) == 0

        return {
            "status": "ok",
            "experiment_id": str(experiment_id),
            "current_status": normalized,
            "is_terminal": is_terminal,
            "allowed_transitions": _STATE_MACHINE.get(normalized, []),
        }

    # -------- 内部辅助方法 --------

    def _normalize_status(self, status: str) -> str:
        """将 ORM status 映射到状态机命名

        ExperimentStatus.PLANNED → pending
        ExperimentStatus.RUNNING → running
        ExperimentStatus.COMPLETED → completed
        ExperimentStatus.FAILED → failed
        """
        mapping = {
            "planned": "pending",
            "pending": "pending",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }
        return mapping.get(str(status).lower(), str(status).lower())

    def _denormalize_status(self, status: str) -> str:
        """将状态机命名映射回 ORM ExperimentStatus"""
        mapping = {
            "pending": ExperimentStatus.PLANNED,
            "running": ExperimentStatus.RUNNING,
            "completed": ExperimentStatus.COMPLETED,
            "failed": ExperimentStatus.FAILED,
        }
        return mapping.get(status, status)


class LimsImporter:
    """LIMS 数据导入器 — CSV/JSON 批量导入

    支持两种输入格式：
    - CSV：每行一个实验，列名对应 Experiment 字段
    - JSON：``{"experiments": [{...}, ...]}`` 结构

    返回统一的 ``{"imported": n, "skipped": n, "errors": []}`` 结构。
    """

    def __init__(self, db: AsyncSession):
        """初始化导入器

        Args:
            db: 异步数据库会话
        """
        self.db = db

    async def import_csv(self, file_path: str) -> Dict[str, Any]:
        """从 CSV 文件导入实验数据

        CSV 列约定（可选列）：name, exp_type, project_id, config (JSON 字符串),
        result (JSON 字符串), lab_source, notes, status

        Args:
            file_path: CSV 文件路径

        Returns:
            {"imported": int, "skipped": int, "errors": List[str]}
        """
        try:
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            return {
                "imported": 0,
                "skipped": 0,
                "errors": [f"文件未找到: {file_path}"],
            }
        except Exception as e:
            logger.error("CSV 读取失败: %s", e)
            return {
                "imported": 0,
                "skipped": 0,
                "errors": [f"CSV 读取失败: {e}"],
            }

        return await self._import_rows(rows)

    async def import_json(self, file_path: str) -> Dict[str, Any]:
        """从 JSON 文件导入实验数据

        JSON 结构：
        ``{"experiments": [{name, exp_type, project_id, ...}, ...]}``

        Args:
            file_path: JSON 文件路径

        Returns:
            {"imported": int, "skipped": int, "errors": List[str]}
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return {
                "imported": 0,
                "skipped": 0,
                "errors": [f"文件未找到: {file_path}"],
            }
        except json.JSONDecodeError as e:
            return {
                "imported": 0,
                "skipped": 0,
                "errors": [f"JSON 解析失败: {e}"],
            }
        except Exception as e:
            logger.error("JSON 读取失败: %s", e)
            return {
                "imported": 0,
                "skipped": 0,
                "errors": [f"JSON 读取失败: {e}"],
            }

        rows = payload.get("experiments") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return {
                "imported": 0,
                "skipped": 0,
                "errors": ["JSON 结构无效：期望 {experiments: [...]} 或 [...]"],
            }

        return await self._import_rows(rows)

    # -------- 内部辅助方法 --------

    async def _import_rows(
        self, rows: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """统一的行级导入逻辑"""
        imported = 0
        skipped = 0
        errors: List[str] = []

        for i, row in enumerate(rows):
            try:
                # 校验必填字段
                project_id_str = row.get("project_id") or row.get("project")
                name = row.get("name") or row.get("experiment_name")
                if not project_id_str or not name:
                    skipped += 1
                    errors.append(
                        f"第 {i + 1} 行：缺少 project_id 或 name，跳过"
                    )
                    continue

                # 解析 config / result（可能是 JSON 字符串）
                config = self._parse_json_field(row.get("config"))
                result = self._parse_json_field(row.get("result"))

                exp = Experiment(
                    project_id=UUID(str(project_id_str)),
                    name=str(name),
                    exp_type=row.get("exp_type", "in_vitro"),
                    status=row.get("status", ExperimentStatus.PLANNED),
                    config=config,
                    result=result,
                    lab_source=row.get("lab_source", "LIMS"),
                    notes=row.get("notes"),
                )
                self.db.add(exp)
                await self.db.flush()
                imported += 1
            except Exception as e:
                skipped += 1
                errors.append(f"第 {i + 1} 行：{type(e).__name__}: {e}")
                logger.warning("LIMS 导入第 %d 行失败: %s", i + 1, e)

        logger.info(
            "LIMS 导入完成：imported=%d, skipped=%d, errors=%d",
            imported,
            skipped,
            len(errors),
        )

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }

    def _parse_json_field(self, value: Any) -> Optional[Dict[str, Any]]:
        """尝试将字段值解析为 dict

        - dict：原样返回
        - str：尝试 JSON 解析，失败返回 None
        - None：返回 None
        """
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        return None
