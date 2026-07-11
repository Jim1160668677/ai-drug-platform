"""工作流反馈环单元测试 — FeedbackLoop / ExperimentTracker / LimsImporter

覆盖目标：
- FeedbackLoop: ingest_experiment_result / detect_bias / recalibrate + 内部辅助方法
- ExperimentTracker: transition / get_state + 状态映射辅助方法
- LimsImporter: import_csv / import_json / _import_rows / _parse_json_field

测试策略：
- 数据库会话、外部服务（联邦学习器）全部 Mock
- 覆盖成功路径、错误路径、边界条件（空输入、None、非法状态转换等）
"""
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


# ============================================================
# FeedbackLoop
# ============================================================

class TestFeedbackLoopInit:
    """FeedbackLoop 初始化测试"""

    def test_init_stores_db(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        assert loop.db is mock_db


class TestIngestExperimentResult:
    """ingest_experiment_result 测试"""

    @pytest.mark.asyncio
    async def test_not_found_returns_not_found_status(self):
        """实验不存在时返回 not_found"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)

        loop = FeedbackLoop(mock_db)
        exp_id = uuid4()
        result = await loop.ingest_experiment_result(exp_id, {"measured": {"ic50": 1.0}})

        assert result["status"] == "not_found"
        assert result["experiment_id"] == str(exp_id)
        assert result["error_metrics"] == {}
        assert result["needs_recalibration"] is False

    @pytest.mark.asyncio
    async def test_ingest_with_success_flag_in_result(self):
        """result 中含 success 字段时直接使用"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        experiment.config = {"predicted": {"ic50": 1.0}}
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        exp_id = uuid4()
        result_data = {
            "measured": {"ic50": 1.1},
            "success": True,
        }
        result = await loop.ingest_experiment_result(exp_id, result_data)

        assert result["status"] == "ingested"
        assert result["experiment_id"] == str(exp_id)
        assert result["needs_recalibration"] is False
        assert result["direction_match"] is True
        # 验证写入
        assert experiment.result == result_data
        assert experiment.feedback_applied is True
        assert experiment.success is True
        # 验证 error_metrics 含 mape
        assert "mape" in result["error_metrics"]

    @pytest.mark.asyncio
    async def test_ingest_without_success_uses_direction_and_mape(self):
        """result 中无 success 字段时基于 direction_match + mape 推导"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        experiment.config = {"predicted": {"ic50": 1.0}}
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_experiment_result(
            uuid4(), {"measured": {"ic50": 1.1}}
        )

        assert result["status"] == "ingested"
        assert result["direction_match"] is True
        # mape 较低，success 应为 True
        assert experiment.success is True

    @pytest.mark.asyncio
    async def test_ingest_high_mape_triggers_recalibration(self):
        """MAPE 超阈值时 needs_recalibration=True 且 success=False"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        # 预测 1.0，实测 100.0 → MAPE 极高
        experiment.config = {"predicted": {"ic50": 1.0}}
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_experiment_result(
            uuid4(), {"measured": {"ic50": 100.0}}
        )

        assert result["needs_recalibration"] is True
        assert result["error_metrics"]["mape"] > 30.0
        # direction_match 为 True 但 mape 高 → success=False
        assert experiment.success is False

    @pytest.mark.asyncio
    async def test_ingest_direction_mismatch_makes_success_false(self):
        """方向不一致时 success=False"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        experiment.config = {"predicted": {"ic50": 1.0}}
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_experiment_result(
            uuid4(), {"measured": {"ic50": -1.0}}
        )

        assert result["direction_match"] is False
        assert experiment.success is False

    @pytest.mark.asyncio
    async def test_ingest_with_none_config(self):
        """experiment.config 为 None 时降级处理"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        experiment.config = None
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_experiment_result(
            uuid4(), {"measured": {"ic50": 1.0}}
        )

        assert result["status"] == "ingested"
        assert result["error_metrics"]["mape"] == 0
        assert result["needs_recalibration"] is False

    @pytest.mark.asyncio
    async def test_ingest_success_false_in_result(self):
        """result['success'] = False 时 experiment.success=False"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiment = MagicMock()
        experiment.config = {"predicted": {"ic50": 1.0}}
        experiment.result = None
        experiment.feedback_applied = False
        experiment.success = None

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_experiment_result(
            uuid4(), {"measured": {"ic50": 1.1}, "success": False}
        )

        assert experiment.success is False


class TestDetectBias:
    """detect_bias 测试"""

    @pytest.mark.asyncio
    async def test_insufficient_samples(self):
        """样本数不足时返回 insufficient_samples"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        assert result["status"] == "insufficient_samples"
        assert result["target_symbol"] == "EGFR"
        assert result["sample_count"] == 0
        assert result["mean_mape"] == 0.0
        assert result["threshold"] == 30.0

    @pytest.mark.asyncio
    async def test_insufficient_samples_below_min(self):
        """样本数低于 min_samples 时返回 insufficient_samples"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        exp = SimpleNamespace(
            config={"predicted": {"ic50": 1.0}},
            result={"measured": {"ic50": 1.1}},
        )
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [exp]
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        assert result["status"] == "insufficient_samples"
        assert result["sample_count"] == 1

    @pytest.mark.asyncio
    async def test_biased_when_mean_mape_exceeds_threshold(self):
        """平均 MAPE 超阈值时返回 biased"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 100.0}},  # MAPE 极高
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        assert result["status"] == "biased"
        assert result["sample_count"] == 6
        assert result["mean_mape"] > 30.0

    @pytest.mark.asyncio
    async def test_no_bias_when_mean_mape_below_threshold(self):
        """平均 MAPE 低于阈值时返回 no_bias"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 1.05}},  # MAPE 约 5%
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        assert result["status"] == "no_bias"
        assert result["mean_mape"] < 30.0

    @pytest.mark.asyncio
    async def test_all_non_numeric_mape_returns_no_bias(self):
        """所有实验指标不可数值化时 mape=0，mean_mape=0 → no_bias"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        # 字符串指标使 float() 抛 ValueError → _compute_errors 返回 mape=0
        # mape=0 仍是非负数值，会被纳入 mape_values → mean_mape=0 → no_bias
        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": "abc"}},
                result={"measured": {"ic50": "xyz"}},
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        # mape=0 对所有实验 → mean_mape=0 < 30 → no_bias
        assert result["status"] == "no_bias"
        assert result["sample_count"] == 6
        assert result["mean_mape"] == 0.0

    @pytest.mark.asyncio
    async def test_detect_bias_with_none_config_and_result(self):
        """config/result 为 None 时 mape=0 被纳入计算"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(config=None, result=None)
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.detect_bias("EGFR", min_samples=5)

        # mape=0 → mean_mape=0 → no_bias
        assert result["status"] == "no_bias"
        assert result["mean_mape"] == 0.0


class TestRecalibrate:
    """recalibrate 测试"""

    @pytest.mark.asyncio
    async def test_no_data_when_insufficient_samples(self):
        """偏差检测样本不足时返回 no_data"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)
        result = await loop.recalibrate("EGFR")

        assert result["status"] == "no_data"
        assert result["target_symbol"] == "EGFR"
        assert "bias_status" in result

    @pytest.mark.asyncio
    async def test_recalibrated_when_fl_returns_submitted(self):
        """联邦学习器返回 submitted 时状态为 recalibrated"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        # 构造足够的高偏差实验使 detect_bias 返回 biased
        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 100.0}},
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)

        # Mock FederatedLearner
        mock_learner = MagicMock()
        mock_learner.update_weights = AsyncMock(
            return_value={"status": "submitted", "job_id": "fl_job_123"}
        )
        with patch(
            "app.services.optimizer.federated_learning.FederatedLearner",
            return_value=mock_learner,
        ):
            result = await loop.recalibrate("EGFR")

        assert result["status"] == "recalibrated"
        assert result["target_symbol"] == "EGFR"
        assert result["fl_result"]["status"] == "submitted"
        mock_learner.update_weights.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_framework_only_when_fl_returns_non_submitted(self):
        """联邦学习器返回非 submitted 时状态为 framework_only"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 100.0}},
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)

        mock_learner = MagicMock()
        mock_learner.update_weights = AsyncMock(
            return_value={"status": "pending"}
        )
        with patch(
            "app.services.optimizer.federated_learning.FederatedLearner",
            return_value=mock_learner,
        ):
            result = await loop.recalibrate("EGFR")

        assert result["status"] == "framework_only"
        assert result["bias_status"] == "biased"

    @pytest.mark.asyncio
    async def test_framework_only_on_exception(self):
        """联邦学习器抛异常时降级为 framework_only"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 100.0}},
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)

        with patch(
            "app.services.optimizer.federated_learning.FederatedLearner",
            side_effect=RuntimeError("FL unavailable"),
        ):
            result = await loop.recalibrate("EGFR")

        assert result["status"] == "framework_only"
        assert "error" in result
        assert "FL unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_recalibrate_no_bias_still_calls_fl(self):
        """no_bias 时仍会调用联邦学习器（返回 framework_only 或 recalibrated）"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        experiments = [
            SimpleNamespace(
                config={"predicted": {"ic50": 1.0}},
                result={"measured": {"ic50": 1.05}},
            )
            for _ in range(6)
        ]
        mock_db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = experiments
        mock_db.execute = AsyncMock(return_value=result_mock)

        loop = FeedbackLoop(mock_db)

        mock_learner = MagicMock()
        mock_learner.update_weights = AsyncMock(
            return_value={"status": "submitted"}
        )
        with patch(
            "app.services.optimizer.federated_learning.FederatedLearner",
            return_value=mock_learner,
        ):
            result = await loop.recalibrate("EGFR")

        # no_bias + submitted → recalibrated
        assert result["status"] == "recalibrated"
        assert result["bias_status"] == "no_bias"


class TestComputeErrors:
    """_compute_errors 测试"""

    def test_empty_predicted_returns_default(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors({}, {"ic50": 1.0})
        assert result == {"mae": 0, "rmse": 0, "mape": 0, "note": "无预测/实测数据"}

    def test_empty_measured_returns_default(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors({"ic50": 1.0}, {})
        assert result == {"mae": 0, "rmse": 0, "mape": 0, "note": "无预测/实测数据"}

    def test_none_inputs_return_default(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors(None, None)
        assert result == {"mae": 0, "rmse": 0, "mape": 0, "note": "无预测/实测数据"}

    def test_no_common_keys_returns_default(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors({"ic50": 1.0}, {"ec50": 2.0})
        assert result == {"mae": 0, "rmse": 0, "mape": 0, "note": "无匹配指标"}

    def test_normal_error_computation(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors(
            {"ic50": 1.0, "ec50": 2.0},
            {"ic50": 1.5, "ec50": 2.0},
        )
        # ic50: abs_err=0.5, pct_err=0.5/1.5*100=33.33
        # ec50: abs_err=0.0, pct_err=0.0
        # mae=(0.5+0.0)/2=0.25, mape=(33.33+0.0)/2=16.67
        assert result["mae"] == 0.25
        assert "rmse" in result
        assert result["mape"] == 16.67
        assert "metrics_compared" in result

    def test_measured_zero_excluded_from_pct_errors(self):
        """measured=0 时不计入 MAPE 但计入 MAE"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors(
            {"ic50": 1.0},
            {"ic50": 0.0},
        )
        # abs_err = 1.0, m=0 → 不加入 pct_errors
        assert result["mae"] == 1.0
        assert result["mape"] == 0  # pct_errors 为空 → mape=0

    def test_non_numeric_values_skipped(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors(
            {"ic50": "abc"},
            {"ic50": "xyz"},
        )
        # float("abc") raises ValueError → 跳过 → errors 为空
        assert result == {"mae": 0, "rmse": 0, "mape": 0, "note": "无法计算数值误差"}

    def test_mixed_numeric_and_non_numeric(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._compute_errors(
            {"ic50": 1.0, "ec50": "bad"},
            {"ic50": 2.0, "ec50": "value"},
        )
        # 只有 ic50 可计算: abs_err=1.0, pct_err=1.0/2.0*100=50.0
        assert result["mae"] == 1.0
        assert result["mape"] == 50.0


class TestNormalizeMetrics:
    """_normalize_metrics 测试"""

    def test_none_returns_empty_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics(None) == {}

    def test_dict_returned_as_is(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        d = {"ic50": 1.0, "ec50": 2.0}
        assert loop._normalize_metrics(d) is d

    def test_int_returns_value_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics(5) == {"value": 5.0}

    def test_float_returns_value_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics(3.14) == {"value": 3.14}

    def test_list_returns_indexed_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._normalize_metrics([1.0, 2.0, 3.0])
        assert result == {"0": 1.0, "1": 2.0, "2": 3.0}

    def test_list_with_non_numeric_filtered(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._normalize_metrics([1.0, "abc", 3.0, None])
        assert result == {"0": 1.0, "2": 3.0}

    def test_tuple_returns_indexed_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._normalize_metrics((1.0, 2.0))
        assert result == {"0": 1.0, "1": 2.0}

    def test_numeric_string_returns_value_dict(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics("1.5") == {"value": 1.5}

    def test_non_numeric_string_returns_empty(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics("abc") == {}

    def test_unsupported_type_returns_empty(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics({1, 2, 3}) == {}

    def test_empty_list_returns_empty(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._normalize_metrics([]) == {}


class TestCheckDirection:
    """_check_direction 测试"""

    def test_no_common_keys_returns_true(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._check_direction({"ic50": 1.0}, {"ec50": 2.0}) is True

    def test_direction_match_returns_true(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._check_direction({"ic50": 1.0}, {"ic50": 2.0}) is True
        assert loop._check_direction({"ic50": -1.0}, {"ic50": -2.0}) is True

    def test_direction_mismatch_returns_false(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        # p > 0, m < 0
        assert loop._check_direction({"ic50": 1.0}, {"ic50": -1.0}) is False
        # p < 0, m > 0
        assert loop._check_direction({"ic50": -1.0}, {"ic50": 1.0}) is False

    def test_non_numeric_values_skipped(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        # 非数值被跳过，不报错也不影响结果
        assert loop._check_direction({"ic50": "abc"}, {"ic50": "xyz"}) is True

    def test_none_inputs_returns_true(self):
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        assert loop._check_direction(None, None) is True

    def test_mixed_directions_one_mismatch_returns_false(self):
        """多个 key 中只要有一个方向不一致就返回 False"""
        from app.services.workflow.feedback_loop import FeedbackLoop

        loop = FeedbackLoop.__new__(FeedbackLoop)
        result = loop._check_direction(
            {"ic50": 1.0, "ec50": 2.0},
            {"ic50": 1.5, "ec50": -2.0},
        )
        assert result is False


# ============================================================
# ExperimentTracker
# ============================================================

class TestExperimentTrackerInit:
    """ExperimentTracker 初始化测试"""

    def test_init_stores_db(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        mock_db = MagicMock()
        tracker = ExperimentTracker(mock_db)
        assert tracker.db is mock_db


class TestTransition:
    """transition 测试"""

    @pytest.mark.asyncio
    async def test_not_found(self):
        """实验不存在时返回 not_found"""
        from app.services.workflow.feedback_loop import ExperimentTracker

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)

        tracker = ExperimentTracker(mock_db)
        exp_id = uuid4()
        result = await tracker.transition(exp_id, "running")

        assert result["status"] == "not_found"
        assert result["experiment_id"] == str(exp_id)
        assert result["previous_status"] == ""
        assert result["current_status"] == ""

    @pytest.mark.asyncio
    async def test_pending_to_running_valid(self):
        """pending → running 合法转换"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.PLANNED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "running")

        assert result["status"] == "transitioned"
        assert result["previous_status"] == "pending"
        assert result["current_status"] == "running"
        assert experiment.status == ExperimentStatus.RUNNING

    @pytest.mark.asyncio
    async def test_running_to_completed_valid(self):
        """running → completed 合法转换"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.RUNNING

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "completed")

        assert result["status"] == "transitioned"
        assert result["previous_status"] == "running"
        assert result["current_status"] == "completed"
        assert experiment.status == ExperimentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_running_to_failed_valid(self):
        """running → failed 合法转换"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.RUNNING

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "failed")

        assert result["status"] == "transitioned"
        assert result["current_status"] == "failed"
        assert experiment.status == ExperimentStatus.FAILED

    @pytest.mark.asyncio
    async def test_failed_to_pending_valid(self):
        """failed → pending 合法转换（重新入队）"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.FAILED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "pending")

        assert result["status"] == "transitioned"
        assert result["previous_status"] == "failed"
        assert result["current_status"] == "pending"
        assert experiment.status == ExperimentStatus.PLANNED

    @pytest.mark.asyncio
    async def test_invalid_transition_pending_to_completed(self):
        """pending → completed 非法转换"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.PLANNED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "completed")

        assert result["status"] == "invalid_transition"
        assert result["previous_status"] == "pending"
        assert result["current_status"] == "pending"
        assert result["requested_status"] == "completed"
        assert result["allowed_transitions"] == ["running"]
        # 状态不应被修改
        assert experiment.status == ExperimentStatus.PLANNED

    @pytest.mark.asyncio
    async def test_invalid_transition_completed_to_running(self):
        """completed → running 非法转换（终态）"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.COMPLETED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "running")

        assert result["status"] == "invalid_transition"
        assert result["allowed_transitions"] == []

    @pytest.mark.asyncio
    async def test_transition_with_pending_status_string(self):
        """直接用 'pending' 字符串作为当前状态"""
        from app.services.workflow.feedback_loop import ExperimentTracker

        experiment = MagicMock()
        experiment.status = "pending"

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "running")

        assert result["status"] == "transitioned"
        assert result["previous_status"] == "pending"

    @pytest.mark.asyncio
    async def test_transition_unknown_current_status(self):
        """未知当前状态 → 不在状态机中 → 无允许转换"""
        from app.services.workflow.feedback_loop import ExperimentTracker

        experiment = MagicMock()
        experiment.status = "unknown_state"

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.transition(uuid4(), "running")

        assert result["status"] == "invalid_transition"
        assert result["allowed_transitions"] == []


class TestGetState:
    """get_state 测试"""

    @pytest.mark.asyncio
    async def test_not_found(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)

        tracker = ExperimentTracker(mock_db)
        exp_id = uuid4()
        result = await tracker.get_state(exp_id)

        assert result["status"] == "not_found"
        assert result["experiment_id"] == str(exp_id)
        assert result["current_status"] == ""
        assert result["is_terminal"] is False

    @pytest.mark.asyncio
    async def test_terminal_state_completed(self):
        """completed 是终态"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.COMPLETED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.get_state(uuid4())

        assert result["status"] == "ok"
        assert result["current_status"] == "completed"
        assert result["is_terminal"] is True
        assert result["allowed_transitions"] == []

    @pytest.mark.asyncio
    async def test_non_terminal_state_pending(self):
        """pending 非终态"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.PLANNED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.get_state(uuid4())

        assert result["status"] == "ok"
        assert result["current_status"] == "pending"
        assert result["is_terminal"] is False
        assert result["allowed_transitions"] == ["running"]

    @pytest.mark.asyncio
    async def test_non_terminal_state_running(self):
        """running 非终态"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.RUNNING

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.get_state(uuid4())

        assert result["current_status"] == "running"
        assert result["is_terminal"] is False
        assert "completed" in result["allowed_transitions"]
        assert "failed" in result["allowed_transitions"]

    @pytest.mark.asyncio
    async def test_failed_state_can_requeue(self):
        """failed 状态可重新入队"""
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        experiment = MagicMock()
        experiment.status = ExperimentStatus.FAILED

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=experiment)

        tracker = ExperimentTracker(mock_db)
        result = await tracker.get_state(uuid4())

        assert result["current_status"] == "failed"
        assert result["is_terminal"] is False
        assert result["allowed_transitions"] == ["pending"]


class TestNormalizeStatus:
    """_normalize_status 测试"""

    def test_planned_maps_to_pending(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("planned") == "pending"

    def test_pending_maps_to_pending(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("pending") == "pending"

    def test_running_maps_to_running(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("running") == "running"

    def test_completed_maps_to_completed(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("completed") == "completed"

    def test_failed_maps_to_failed(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("failed") == "failed"

    def test_unknown_status_returns_lowercased(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("UNKNOWN") == "unknown"

    def test_uppercase_status_normalized(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._normalize_status("RUNNING") == "running"


class TestDenormalizeStatus:
    """_denormalize_status 测试"""

    def test_pending_maps_to_planned(self):
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._denormalize_status("pending") == ExperimentStatus.PLANNED

    def test_running_maps_to_running(self):
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._denormalize_status("running") == ExperimentStatus.RUNNING

    def test_completed_maps_to_completed(self):
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._denormalize_status("completed") == ExperimentStatus.COMPLETED

    def test_failed_maps_to_failed(self):
        from app.services.workflow.feedback_loop import ExperimentTracker
        from app.models.experiment import ExperimentStatus

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._denormalize_status("failed") == ExperimentStatus.FAILED

    def test_unknown_status_returned_as_is(self):
        from app.services.workflow.feedback_loop import ExperimentTracker

        tracker = ExperimentTracker.__new__(ExperimentTracker)
        assert tracker._denormalize_status("unknown") == "unknown"


# ============================================================
# LimsImporter
# ============================================================

class TestLimsImporterInit:
    """LimsImporter 初始化测试"""

    def test_init_stores_db(self):
        from app.services.workflow.feedback_loop import LimsImporter

        mock_db = MagicMock()
        importer = LimsImporter(mock_db)
        assert importer.db is mock_db


class TestImportCsv:
    """import_csv 测试"""

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter(MagicMock())
        result = await importer.import_csv("/nonexistent/file.csv")

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "文件未找到" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_csv_read_exception(self, tmp_path):
        """CSV 读取异常（如权限错误等）"""
        from app.services.workflow.feedback_loop import LimsImporter

        # 用一个目录路径触发读取异常（open 目录会抛 IsADirectoryError）
        importer = LimsImporter(MagicMock())
        result = await importer.import_csv(str(tmp_path))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "CSV 读取失败" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_valid_csv_import(self, tmp_path):
        """正常 CSV 导入"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        csv_content = (
            "name,exp_type,project_id,config,result,lab_source,notes,status\n"
            f"Exp1,in_vitro,{project_id},{{\"predicted\":{{\"ic50\":1.0}}}},"
            f"{{\"measured\":{{\"ic50\":1.1}}}},LabA,note1,planned\n"
            f"Exp2,in_vivo,{project_id},,,LabB,note2,running\n"
        )
        csv_file = tmp_path / "experiments.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_csv(str(csv_file))

        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == []
        assert mock_db.add.call_count == 2
        assert mock_db.flush.await_count == 2

    @pytest.mark.asyncio
    async def test_csv_with_missing_required_fields(self, tmp_path):
        """CSV 行缺少 project_id 或 name 时跳过"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        csv_content = (
            "name,exp_type,project_id\n"
            f"Exp1,in_vitro,{project_id}\n"
            ",in_vitro,\n"  # 缺 name 和 project_id
            f"Exp2,in_vitro,\n"  # 缺 project_id
        )
        csv_file = tmp_path / "experiments.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_csv(str(csv_file))

        assert result["imported"] == 1
        assert result["skipped"] == 2
        assert len(result["errors"]) == 2

    @pytest.mark.asyncio
    async def test_csv_with_invalid_project_id(self, tmp_path):
        """CSV 行 project_id 不是有效 UUID 时跳过"""
        from app.services.workflow.feedback_loop import LimsImporter

        csv_content = (
            "name,exp_type,project_id\n"
            "Exp1,in_vitro,not-a-uuid\n"
        )
        csv_file = tmp_path / "experiments.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_csv(str(csv_file))

        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_empty_csv_file(self, tmp_path):
        """空 CSV 文件（仅表头）"""
        from app.services.workflow.feedback_loop import LimsImporter

        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("name,exp_type,project_id\n", encoding="utf-8")

        mock_db = MagicMock()
        importer = LimsImporter(mock_db)
        result = await importer.import_csv(str(csv_file))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []


class TestImportJson:
    """import_json 测试"""

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter(MagicMock())
        result = await importer.import_json("/nonexistent/file.json")

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "文件未找到" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_json_decode_error(self, tmp_path):
        from app.services.workflow.feedback_loop import LimsImporter

        json_file = tmp_path / "invalid.json"
        json_file.write_text("{invalid json", encoding="utf-8")

        importer = LimsImporter(MagicMock())
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "JSON 解析失败" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_json_read_exception(self, tmp_path):
        """JSON 读取异常（路径是目录）"""
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter(MagicMock())
        result = await importer.import_json(str(tmp_path))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "JSON 读取失败" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_invalid_json_structure_not_list(self, tmp_path):
        """JSON 结构无效：experiments 不是列表"""
        from app.services.workflow.feedback_loop import LimsImporter

        json_file = tmp_path / "invalid_struct.json"
        json_file.write_text('{"experiments": "not_a_list"}', encoding="utf-8")

        importer = LimsImporter(MagicMock())
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "JSON 结构无效" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_invalid_json_structure_scalar(self, tmp_path):
        """JSON 结构无效：标量值"""
        from app.services.workflow.feedback_loop import LimsImporter

        json_file = tmp_path / "scalar.json"
        json_file.write_text("42", encoding="utf-8")

        importer = LimsImporter(MagicMock())
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert len(result["errors"]) == 1
        assert "JSON 结构无效" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_valid_json_with_experiments_key(self, tmp_path):
        """正常 JSON 导入（{experiments: [...]}）"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        payload = {
            "experiments": [
                {
                    "name": "Exp1",
                    "exp_type": "in_vitro",
                    "project_id": str(project_id),
                    "config": {"predicted": {"ic50": 1.0}},
                    "result": {"measured": {"ic50": 1.1}},
                    "lab_source": "LabA",
                    "notes": "note1",
                },
                {
                    "name": "Exp2",
                    "exp_type": "in_vivo",
                    "project_id": str(project_id),
                },
            ]
        }
        json_file = tmp_path / "experiments.json"
        json_file.write_text(json.dumps(payload), encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_valid_json_as_list(self, tmp_path):
        """正常 JSON 导入（顶层为列表）"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        payload = [
            {
                "name": "Exp1",
                "project_id": str(project_id),
            }
        ]
        json_file = tmp_path / "experiments_list.json"
        json_file.write_text(json.dumps(payload), encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 1
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_json_with_missing_fields(self, tmp_path):
        """JSON 行缺少必填字段时跳过"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        payload = {
            "experiments": [
                {"name": "Exp1", "project_id": str(project_id)},
                {"name": ""},  # 缺 project_id 和 name
                {"project_id": str(project_id)},  # 缺 name
            ]
        }
        json_file = tmp_path / "experiments.json"
        json_file.write_text(json.dumps(payload), encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 1
        assert result["skipped"] == 2
        assert len(result["errors"]) == 2

    @pytest.mark.asyncio
    async def test_json_with_experiment_name_alias(self, tmp_path):
        """支持 experiment_name 作为 name 别名"""
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        payload = {
            "experiments": [
                {
                    "experiment_name": "Exp1",
                    "project": str(project_id),
                }
            ]
        }
        json_file = tmp_path / "experiments.json"
        json_file.write_text(json.dumps(payload), encoding="utf-8")

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer.import_json(str(json_file))

        assert result["imported"] == 1
        assert result["errors"] == []


class TestImportRows:
    """_import_rows 测试"""

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from app.services.workflow.feedback_loop import LimsImporter

        mock_db = MagicMock()
        importer = LimsImporter(mock_db)
        result = await importer._import_rows([])

        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_successful_import(self):
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        rows = [
            {
                "name": "Exp1",
                "project_id": str(project_id),
                "exp_type": "in_vitro",
                "config": {"predicted": {"ic50": 1.0}},
            }
        ]

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer._import_rows(rows)

        assert result["imported"] == 1
        assert mock_db.add.call_count == 1

    @pytest.mark.asyncio
    async def test_missing_project_id_skipped(self):
        from app.services.workflow.feedback_loop import LimsImporter

        rows = [{"name": "Exp1"}]  # 缺 project_id

        mock_db = MagicMock()
        importer = LimsImporter(mock_db)
        result = await importer._import_rows(rows)

        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert "缺少 project_id 或 name" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_missing_name_skipped(self):
        from app.services.workflow.feedback_loop import LimsImporter

        rows = [{"project_id": str(uuid4())}]  # 缺 name

        mock_db = MagicMock()
        importer = LimsImporter(mock_db)
        result = await importer._import_rows(rows)

        assert result["imported"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_row_exception_caught(self):
        """行处理异常被捕获并记录"""
        from app.services.workflow.feedback_loop import LimsImporter

        # project_id 是有效 UUID 字符串，但 Experiment 构造抛异常
        rows = [
            {
                "name": "Exp1",
                "project_id": str(uuid4()),
            }
        ]

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)

        # Mock Experiment 构造函数抛异常
        with patch(
            "app.services.workflow.feedback_loop.Experiment",
            side_effect=RuntimeError("constructor failed"),
        ):
            result = await importer._import_rows(rows)

        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert "RuntimeError" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid_rows(self):
        from app.services.workflow.feedback_loop import LimsImporter

        project_id = uuid4()
        rows = [
            {"name": "Exp1", "project_id": str(project_id)},
            {"name": ""},  # 缺字段
            {"name": "Exp2", "project_id": str(project_id)},
        ]

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        importer = LimsImporter(mock_db)
        result = await importer._import_rows(rows)

        assert result["imported"] == 2
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1


class TestParseJsonField:
    """_parse_json_field 测试"""

    def test_none_returns_none(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        assert importer._parse_json_field(None) is None

    def test_dict_returned_as_is(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        d = {"key": "value"}
        assert importer._parse_json_field(d) is d

    def test_valid_json_string_parsed(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        result = importer._parse_json_field('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json_string_returns_none(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        assert importer._parse_json_field("not json") is None

    def test_json_string_that_is_not_dict_returns_none(self):
        """JSON 解析后非 dict（如列表）返回 None"""
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        assert importer._parse_json_field('[1, 2, 3]') is None

    def test_json_number_string_returns_none(self):
        """JSON 解析后为数字（非 dict）返回 None"""
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        assert importer._parse_json_field('42') is None

    def test_unsupported_type_returns_none(self):
        from app.services.workflow.feedback_loop import LimsImporter

        importer = LimsImporter.__new__(LimsImporter)
        assert importer._parse_json_field([1, 2, 3]) is None
        assert importer._parse_json_field(42) is None
        assert importer._parse_json_field(3.14) is None
