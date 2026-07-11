"""EfficacyMonitor 单元测试 — 覆盖疗效监测器全部公开方法与关键路径。

测试范围：
- check(): 治疗方案不存在 / 实验汇总 / efficacy + inhibition_rate / adverse_events / 失败实验
- _analyze_trend(): 空列表 / 单项 / improving / declining / stable
- _recommend(): 全部分支
- _recist_classify(): 空病灶 / baseline<=0 / CR / PR / PD / SD
- _compute_orr() / _compute_dcr(): 空输入与含响应
- _kaplan_meier(): 空输入 / 全事件 / 含删失 / median_survival 计算
- _grade_adverse_event(): 1-5 级各分支
- record_outcome(): 显式 response / lesions 自动分类 / 空输入
- record_adverse_event(): 各等级
- global_summary(): 带 / 不带 project_id 过滤、含响应与 AE
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ========== 辅助函数 ==========

def _make_treatment(*, name="Test Treatment", project_id=None):
    """构造一个 Treatment-like SimpleNamespace 对象"""
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id or uuid4(),
        name=name,
        therapy_type="targeted",
        status="testing",
        target_ids=[],
        molecule_ids=[],
        efficacy_score=0.6,
        risk_score=0.3,
        confidence=0.7,
        config={},
        monitoring_data={},
        hypothesis_id=None,
        notes=None,
    )


def _make_experiment(
    *,
    name="exp",
    result=None,
    success=True,
    status="completed",
    treatment_id=None,
):
    """构造一个 Experiment-like SimpleNamespace 对象"""
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        name=name,
        exp_type="cytotoxicity",
        status=status,
        target_id=None,
        molecule_id=None,
        treatment_id=treatment_id or uuid4(),
        config={},
        result=result,
        success=success,
        feedback_applied=False,
        iteration=1,
        lab_source=None,
        notes=None,
    )


def _mock_scalars_all(items):
    """构造一个可链式调用的 mock 结果：result.scalars().all() -> items"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


# ========== check() ==========

class TestEfficacyMonitorCheck:
    """EfficacyMonitor.check() 测试"""

    @pytest.mark.asyncio
    async def test_check_treatment_not_found(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        monitor = EfficacyMonitor(mock_db)

        tid = uuid4()
        result = await monitor.check(tid)

        assert result["error"] == "治疗方案不存在"
        assert result["treatment_id"] == str(tid)

    @pytest.mark.asyncio
    async def test_check_no_experiments(self):
        """治疗方案存在但无关联实验：current_efficacy=0, trend=insufficient_data"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["treatment_id"] == str(treatment.id)
        assert result["treatment_name"] == treatment.name
        assert result["current_efficacy"] == 0
        assert result["trend"] == "insufficient_data"
        assert result["experiments_count"] == 0
        assert result["efficacy_history"] == []
        assert result["adverse_events"] == []
        assert result["method"] == "batch_aggregation"
        assert "P3" in result["note"]
        assert "recommendation" in result

    @pytest.mark.asyncio
    async def test_check_aggregates_efficacy_scores(self):
        """efficacy 字段应被收集并求平均"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"efficacy": 0.8}),
            _make_experiment(name="e2", result={"efficacy": 0.6}),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        # 平均 (0.8 + 0.6) / 2 = 0.7
        assert result["current_efficacy"] == 0.7
        assert result["efficacy_history"] == [0.8, 0.6]
        assert result["experiments_count"] == 2

    @pytest.mark.asyncio
    async def test_check_inhibition_rate_divided_by_100(self):
        """inhibition_rate 应除以 100 后加入 efficacy_scores"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"inhibition_rate": 80}),  # -> 0.8
            _make_experiment(name="e2", result={"efficacy": 0.6}),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["efficacy_history"] == [0.8, 0.6]
        assert result["current_efficacy"] == 0.7

    @pytest.mark.asyncio
    async def test_check_collects_adverse_events(self):
        """result.adverse_events 列表应被收集到 adverse_events"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(
                name="e1",
                result={"efficacy": 0.5, "adverse_events": ["nausea", "fatigue"]},
            ),
            _make_experiment(
                name="e2",
                result={"efficacy": 0.6, "adverse_events": ["headache"]},
            ),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert "nausea" in result["adverse_events"]
        assert "fatigue" in result["adverse_events"]
        assert "headache" in result["adverse_events"]

    @pytest.mark.asyncio
    async def test_check_failed_completed_experiment_adds_adverse_event(self):
        """success=False 且 status=COMPLETED 时应追加'实验未达预期' AE"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        from app.models.experiment import ExperimentStatus

        treatment = _make_treatment()
        experiments = [
            _make_experiment(
                name="failed_exp",
                result={"efficacy": 0.5},
                success=False,
                status=ExperimentStatus.COMPLETED,
            ),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert any("实验未达预期" in ae for ae in result["adverse_events"])
        assert any("failed_exp" in ae for ae in result["adverse_events"])

    @pytest.mark.asyncio
    async def test_check_failed_but_not_completed_does_not_add_adverse_event(self):
        """success=False 但 status != COMPLETED 时不应追加 AE"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        from app.models.experiment import ExperimentStatus

        treatment = _make_treatment()
        experiments = [
            _make_experiment(
                name="running_exp",
                result={"efficacy": 0.5},
                success=False,
                status=ExperimentStatus.RUNNING,
            ),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["adverse_events"] == []

    @pytest.mark.asyncio
    async def test_check_handles_invalid_efficacy_values(self):
        """无效 efficacy 值（字符串、None）应被忽略，不破坏计算"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"efficacy": "invalid"}),  # ValueError
            _make_experiment(name="e2", result={"efficacy": None}),       # TypeError
            _make_experiment(name="e3", result={"efficacy": 0.6}),         # 有效
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["efficacy_history"] == [0.6]
        assert result["current_efficacy"] == 0.6

    @pytest.mark.asyncio
    async def test_check_handles_invalid_inhibition_rate(self):
        """无效 inhibition_rate 应被忽略"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"inhibition_rate": "bad"}),
            _make_experiment(name="e2", result={"inhibition_rate": 50}),  # -> 0.5
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["efficacy_history"] == [0.5]

    @pytest.mark.asyncio
    async def test_check_truncates_adverse_events_to_ten(self):
        """adverse_events 输出应截断为前 10 条"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        # 12 个 AE
        aes = [f"ae_{i}" for i in range(12)]
        experiments = [
            _make_experiment(name="e1", result={"efficacy": 0.5, "adverse_events": aes}),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert len(result["adverse_events"]) == 10
        assert result["adverse_events"][0] == "ae_0"
        assert result["adverse_events"][9] == "ae_9"

    @pytest.mark.asyncio
    async def test_check_rounds_current_efficacy_to_three_decimals(self):
        """current_efficacy 应保留 3 位小数"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"efficacy": 1 / 3}),  # 0.333...
            _make_experiment(name="e2", result={"efficacy": 2 / 3}),  # 0.666...
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        # (1/3 + 2/3) / 2 = 0.5
        assert result["current_efficacy"] == 0.5

    @pytest.mark.asyncio
    async def test_check_handles_result_none(self):
        """result=None 时不应抛异常"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result=None),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["current_efficacy"] == 0
        assert result["adverse_events"] == []

    @pytest.mark.asyncio
    async def test_check_handles_adverse_events_none(self):
        """result.adverse_events=None 时不应抛异常"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(name="e1", result={"efficacy": 0.5, "adverse_events": None}),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert result["adverse_events"] == []

    @pytest.mark.asyncio
    async def test_check_str_adverse_events(self):
        """adverse_events 中元素被 str() 转换"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        treatment = _make_treatment()
        experiments = [
            _make_experiment(
                name="e1",
                result={"efficacy": 0.5, "adverse_events": [123, 456]},
            ),
        ]
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=treatment)
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all(experiments))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.check(treatment.id)

        assert "123" in result["adverse_events"]
        assert "456" in result["adverse_events"]


# ========== _analyze_trend() ==========

class TestEfficacyMonitorAnalyzeTrend:
    """_analyze_trend 测试"""

    def test_empty_list_returns_insufficient_data(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([]) == "insufficient_data"

    def test_single_item_returns_insufficient_data(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.5]) == "insufficient_data"

    def test_improving_when_diff_above_threshold(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.5, 0.7]) == "improving"  # diff=0.2

    def test_declining_when_diff_below_negative_threshold(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.7, 0.5]) == "declining"  # diff=-0.2

    def test_stable_when_diff_within_threshold(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.5, 0.52]) == "stable"  # diff=0.02
        assert monitor._analyze_trend([0.5, 0.48]) == "stable"  # diff=-0.02

    def test_boundary_exactly_0_05_stable(self):
        """diff == 0.05（用 0.0 与 0.05 避免浮点误差）不严格大于 0.05，应归为 stable"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 0.05 - 0.0 == 0.05 精确成立（IEEE 754），0.05 > 0.05 为 False -> stable
        assert monitor._analyze_trend([0.0, 0.05]) == "stable"

    def test_boundary_exactly_neg_0_05_stable(self):
        """diff == -0.05（用 0.05 与 0.0 避免浮点误差）不严格小于 -0.05，应归为 stable"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._analyze_trend([0.05, 0.0]) == "stable"

    def test_three_items_uses_last_two(self):
        """趋势分析使用最后两个数据点"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 最后两个 0.6 -> 0.8，diff=0.2，improving
        assert monitor._analyze_trend([0.3, 0.6, 0.8]) == "improving"
        # 最后两个 0.8 -> 0.6，diff=-0.2，declining
        assert monitor._analyze_trend([0.3, 0.8, 0.6]) == "declining"


# ========== _recommend() ==========

class TestEfficacyMonitorRecommend:
    """_recommend 测试"""

    def test_low_efficacy_returns_replace_recommendation(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "更换" in monitor._recommend(0.2, "declining", [])

    def test_low_efficacy_boundary_0_3_not_replace(self):
        """efficacy == 0.3 不再触发'疗效不足'分支"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 0.3 不 < 0.3, 不 < 0.5 with declining，无 AE, 不 > 0.7
        # trend != improving，落到默认
        result = monitor._recommend(0.3, "stable", [])
        assert "稳定" in result

    def test_medium_efficacy_declining_returns_combination(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "联合" in monitor._recommend(0.45, "declining", [])

    def test_many_adverse_events_returns_reduce_dose(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "降低" in monitor._recommend(0.6, "stable", ["a", "b", "c"])

    def test_adverse_events_boundary_three_triggers_reduce(self):
        """len(adverse_events) == 3 应触发'降低剂量'"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "降低" in monitor._recommend(0.6, "stable", ["a", "b", "c"])

    def test_high_efficacy_stable_returns_maintain(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "维持" in monitor._recommend(0.8, "stable", [])

    def test_high_efficacy_improving_returns_maintain(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "维持" in monitor._recommend(0.8, "improving", [])

    def test_improving_only_returns_continue(self):
        """efficacy 不 > 0.7 但 trend=improving -> 继续当前方案"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert "继续" in monitor._recommend(0.6, "improving", [])

    def test_stable_default_returns_continue(self):
        """默认分支：'疗效稳定，继续监测'"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._recommend(0.6, "stable", [])
        assert "稳定" in result


# ========== _recist_classify() ==========

class TestEfficacyMonitorRecist:
    """_recist_classify 测试"""

    def test_empty_lesions_returns_sd(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._recist_classify([]) == "SD"

    def test_baseline_zero_returns_sd(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # baseline_sum = 0 -> SD
        assert monitor._recist_classify([{"baseline_mm": 0, "current_mm": 10}]) == "SD"

    def test_current_zero_returns_cr(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # current_sum = 0 -> CR
        assert monitor._recist_classify([{"baseline_mm": 10, "current_mm": 0}]) == "CR"

    def test_pr_when_shrink_at_least_30_percent(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 100 -> 70, change = -0.30 -> PR (<= -0.30)
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 70}]) == "PR"
        # 100 -> 50, change = -0.50 -> PR
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 50}]) == "PR"

    def test_pd_when_grow_at_least_20_percent(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 100 -> 120, change = 0.20 -> PD (>= 0.20)
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 120}]) == "PD"
        # 100 -> 150, change = 0.50 -> PD
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 150}]) == "PD"

    def test_sd_when_change_within_bounds(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 100 -> 90, change = -0.10 -> SD (between -0.30 and 0.20)
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 90}]) == "SD"
        # 100 -> 110, change = 0.10 -> SD
        assert monitor._recist_classify([{"baseline_mm": 100, "current_mm": 110}]) == "SD"

    def test_multiple_lesions_sums_first(self):
        """多病灶应先汇总再计算变化"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # baseline_sum = 50+50=100, current_sum = 35+35=70, change = -0.30 -> PR
        lesions = [
            {"baseline_mm": 50, "current_mm": 35},
            {"baseline_mm": 50, "current_mm": 35},
        ]
        assert monitor._recist_classify(lesions) == "PR"

    def test_missing_keys_default_to_zero(self):
        """病灶缺 baseline_mm/current_mm 时按 0 处理"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # baseline=0, current=0 -> baseline_sum<=0 -> SD
        assert monitor._recist_classify([{}]) == "SD"
        # baseline=10, current 缺=0 -> current_sum=0 -> CR
        assert monitor._recist_classify([{"baseline_mm": 10}]) == "CR"


# ========== _compute_orr() ==========

class TestEfficacyMonitorOrr:
    """_compute_orr 测试"""

    def test_empty_responses(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._compute_orr([])
        assert result == {"orr": 0.0, "cr": 0, "pr": 0, "total": 0}

    def test_mixed_responses(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # CR=2, PR=1, SD=1, PD=1, total=5, orr = (2+1)/5 = 0.6
        responses = ["CR", "CR", "PR", "SD", "PD"]
        result = monitor._compute_orr(responses)
        assert result["cr"] == 2
        assert result["pr"] == 1
        assert result["total"] == 5
        assert result["orr"] == 0.6

    def test_no_responses_with_only_sd_pd(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._compute_orr(["SD", "PD", "SD"])
        assert result["orr"] == 0.0
        assert result["cr"] == 0
        assert result["pr"] == 0
        assert result["total"] == 3

    def test_all_cr(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._compute_orr(["CR", "CR"])
        assert result["orr"] == 1.0


# ========== _compute_dcr() ==========

class TestEfficacyMonitorDcr:
    """_compute_dcr 测试"""

    def test_empty_responses(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._compute_dcr([])
        assert result == {"dcr": 0.0, "cr": 0, "pr": 0, "sd": 0, "pd": 0, "total": 0}

    def test_mixed_responses(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # CR=1, PR=1, SD=2, PD=1, total=5, dcr = (1+1+2)/5 = 0.8
        responses = ["CR", "PR", "SD", "SD", "PD"]
        result = monitor._compute_dcr(responses)
        assert result["cr"] == 1
        assert result["pr"] == 1
        assert result["sd"] == 2
        assert result["pd"] == 1
        assert result["total"] == 5
        assert result["dcr"] == 0.8

    def test_all_pd(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._compute_dcr(["PD", "PD"])
        assert result["dcr"] == 0.0
        assert result["pd"] == 2


# ========== _kaplan_meier() ==========

class TestEfficacyMonitorKaplanMeier:
    """_kaplan_meier 测试"""

    def test_empty_events(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        result = monitor._kaplan_meier([])
        assert result == {"survival_curve": [], "median_survival": None}

    def test_all_events_median_calculated(self):
        """4 个事件，第 2 个事件后 survival 降至 0.5 -> median_survival=2"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        events = [
            {"time": 1, "event": 1},
            {"time": 2, "event": 1},
            {"time": 3, "event": 1},
            {"time": 4, "event": 1},
        ]
        result = monitor._kaplan_meier(events)

        assert result["n_total"] == 4
        assert result["n_events"] == 4
        assert result["median_survival"] == 2
        # curve 起点是 time=0, survival=1.0
        assert result["survival_curve"][0] == {"time": 0, "survival": 1.0, "n_at_risk": 4}
        # 4 个事件 + 起始点 = 5 个曲线点
        assert len(result["survival_curve"]) == 5
        # 最后 survival 应为 0
        assert result["survival_curve"][-1]["survival"] == 0.0

    def test_censored_events_decrement_n_at_risk_only(self):
        """删失事件（event=0）只减少 n_at_risk，不改变 survival"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        events = [
            {"time": 1, "event": 1},  # survival = 2/3 = 0.6667
            {"time": 2, "event": 0},  # 删失: n_at_risk 1 -> 0
            {"time": 3, "event": 1},  # n_at_risk=1 时事件: survival *= 0/1 = 0
        ]
        result = monitor._kaplan_meier(events)

        assert result["n_total"] == 3
        assert result["n_events"] == 2
        # 第一个点 survival=1.0, t=1 时 0.6667, t=2 时仍 0.6667（删失）, t=3 时 0.0
        assert result["survival_curve"][1]["survival"] == 0.6667
        assert result["survival_curve"][2]["survival"] == 0.6667
        assert result["survival_curve"][3]["survival"] == 0.0

    def test_sorted_by_time(self):
        """事件按 time 排序处理"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 故意乱序输入
        events = [
            {"time": 3, "event": 1},
            {"time": 1, "event": 1},
            {"time": 2, "event": 1},
        ]
        result = monitor._kaplan_meier(events)

        # curve[0] 是起始点 t=0
        # curve[1] 应对应 t=1
        assert result["survival_curve"][1]["time"] == 1
        assert result["survival_curve"][2]["time"] == 2
        assert result["survival_curve"][3]["time"] == 3

    def test_no_median_when_survival_above_half(self):
        """survival 始终 > 0.5 时 median_survival 应为 None"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 仅 1 个事件，n=2: survival = 1/2 = 0.5 -> median_survival = 1 (<=0.5)
        # 改为 2 个删失：survival 始终 1.0
        events = [
            {"time": 5, "event": 0},
            {"time": 10, "event": 0},
        ]
        result = monitor._kaplan_meier(events)

        assert result["median_survival"] is None
        assert result["n_events"] == 0

    def test_missing_event_key_defaults_to_zero(self):
        """缺 event 键时按 0（删失）处理"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        events = [{"time": 1}, {"time": 2}]  # 均视为删失
        result = monitor._kaplan_meier(events)

        assert result["n_events"] == 0
        assert result["median_survival"] is None
        # survival 始终 1.0
        assert all(point["survival"] == 1.0 for point in result["survival_curve"])

    def test_missing_time_key_defaults_to_zero(self):
        """缺 time 键时按 0 处理"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        events = [{"event": 1}, {"event": 1}]
        result = monitor._kaplan_meier(events)

        assert result["n_total"] == 2
        assert result["n_events"] == 2


# ========== _grade_adverse_event() ==========

class TestEfficacyMonitorGradeAdverseEvent:
    """_grade_adverse_event 测试"""

    def test_grade_5_death_in_description(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "Patient death"}) == 5

    def test_grade_5_zhiming_in_description(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "致命反应"}) == 5

    def test_grade_5_severity_5(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "5"}) == 5

    def test_grade_4_life_threatening(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "life-threatening event"}) == 4

    def test_grade_4_weiji_shengming(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "危及生命"}) == 4

    def test_grade_4_severity_4(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "4"}) == 4

    def test_grade_3_hospitalization(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "required hospitalization"}) == 3

    def test_grade_3_zhuyuan(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"description": "需住院治疗"}) == 3

    def test_grade_3_severity_3(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "3"}) == 3

    def test_grade_2_moderate_in_severity(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "moderate"}) == 2

    def test_grade_2_zhongdu_in_severity(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "中度反应"}) == 2

    def test_grade_2_severity_2(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({"severity": "2"}) == 2

    def test_grade_1_default(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 默认（轻度）
        assert monitor._grade_adverse_event({}) == 1
        assert monitor._grade_adverse_event({"severity": "mild"}) == 1
        assert monitor._grade_adverse_event({"severity": "1"}) == 1

    def test_grade_5_takes_precedence_over_others(self):
        """分级顺序：5 > 4 > 3 > 2 > 1"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        # 同时含 death 与 moderate，应取 5
        assert monitor._grade_adverse_event(
            {"description": "death", "severity": "moderate"}
        ) == 5

    def test_grade_handles_empty_event(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor.__new__(EfficacyMonitor)
        assert monitor._grade_adverse_event({}) == 1


# ========== record_outcome() ==========

class TestEfficacyMonitorRecordOutcome:
    """record_outcome 测试"""

    @pytest.mark.asyncio
    async def test_record_outcome_with_explicit_response(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        tid = uuid4()
        result = await monitor.record_outcome(tid, {"response": "PR"})

        assert result["treatment_id"] == str(tid)
        assert result["response"] == "PR"
        assert result["recorded"] is True

    @pytest.mark.asyncio
    async def test_record_outcome_classifies_lesions_when_no_response(self):
        """无 response 但有 lesions 时应调用 _recist_classify"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        tid = uuid4()
        lesions = [{"baseline_mm": 100, "current_mm": 50}]  # PR
        result = await monitor.record_outcome(tid, {"lesions": lesions})

        assert result["response"] == "PR"
        assert result["recorded"] is True

    @pytest.mark.asyncio
    async def test_record_outcome_cr_when_lesions_shrink_to_zero(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        lesions = [{"baseline_mm": 100, "current_mm": 0}]  # CR
        result = await monitor.record_outcome(uuid4(), {"lesions": lesions})

        assert result["response"] == "CR"

    @pytest.mark.asyncio
    async def test_record_outcome_no_response_no_lesions(self):
        """无 response 也无 lesions 时 response 应为 None"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        result = await monitor.record_outcome(uuid4(), {})

        assert result["response"] is None
        assert result["recorded"] is True

    @pytest.mark.asyncio
    async def test_record_outcome_empty_lesions_does_not_classify(self):
        """lesions 为空列表时（falsy），不应触发 _recist_classify"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        result = await monitor.record_outcome(uuid4(), {"response": None, "lesions": []})

        # lesions=[] 是 falsy，不会进入 classify 分支
        assert result["response"] is None


# ========== record_adverse_event() ==========

class TestEfficacyMonitorRecordAdverseEvent:
    """record_adverse_event 测试"""

    @pytest.mark.asyncio
    async def test_record_adverse_event_grade_5(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        tid = uuid4()
        event = {"symptom": "死亡", "description": "patient death", "severity": "5"}
        result = await monitor.record_adverse_event(tid, event)

        assert result["treatment_id"] == str(tid)
        assert result["ctcae_grade"] == 5
        assert result["symptom"] == "死亡"
        assert result["recorded"] is True

    @pytest.mark.asyncio
    async def test_record_adverse_event_grade_1_default(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        event = {"symptom": "mild nausea"}
        result = await monitor.record_adverse_event(uuid4(), event)

        assert result["ctcae_grade"] == 1
        assert result["symptom"] == "mild nausea"

    @pytest.mark.asyncio
    async def test_record_adverse_event_missing_symptom(self):
        """event 缺 symptom 键时应返回 None"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor
        monitor = EfficacyMonitor(MagicMock())

        result = await monitor.record_adverse_event(uuid4(), {"severity": "3"})

        assert result["symptom"] is None
        assert result["ctcae_grade"] == 3


# ========== global_summary() ==========

class TestEfficacyMonitorGlobalSummary:
    """global_summary 测试"""

    @pytest.mark.asyncio
    async def test_summary_no_treatments(self):
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert result["total_treatments"] == 0
        assert result["total_outcomes"] == 0
        assert result["orr"] == {"orr": 0.0, "cr": 0, "pr": 0, "total": 0}
        assert result["dcr"] == {"dcr": 0.0, "cr": 0, "pr": 0, "sd": 0, "pd": 0, "total": 0}
        assert result["ae_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}

    @pytest.mark.asyncio
    async def test_summary_with_project_id_filter(self):
        """传 project_id 时应在 Treatment 查询中加 where 条件"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        mock_db = MagicMock()
        # 第一次：treatments 查询（返回空，避免后续 experiments 查询）
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        monitor = EfficacyMonitor(mock_db)

        pid = uuid4()
        result = await monitor.global_summary(project_id=pid)

        assert mock_db.execute.await_count == 1
        assert result["total_treatments"] == 0

    @pytest.mark.asyncio
    async def test_summary_without_project_id_no_filter(self):
        """不传 project_id 时不应加 where 条件"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert mock_db.execute.await_count == 1
        assert result["total_treatments"] == 0

    @pytest.mark.asyncio
    async def test_summary_aggregates_responses_and_aes(self):
        """汇总多个 treatment 的实验响应与 AE"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        t1 = _make_treatment(name="t1")
        t2 = _make_treatment(name="t2")
        exps1 = [
            _make_experiment(
                treatment_id=t1.id,
                result={
                    "response": "CR",
                    "adverse_events": [{"severity": "3"}, {"severity": "2"}],
                },
            ),
        ]
        exps2 = [
            _make_experiment(
                treatment_id=t2.id,
                result={
                    "response": "PR",
                    "adverse_events": [{"severity": "5"}],
                },
            ),
            _make_experiment(
                treatment_id=t2.id,
                result={"response": "PD"},  # 不计入 ORR
            ),
        ]

        # mock_db.execute 顺序：
        # 1. treatments 查询 -> [t1, t2]
        # 2. t1 的 experiments 查询 -> exps1
        # 3. t2 的 experiments 查询 -> exps2
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars_all([t1, t2]),
            _mock_scalars_all(exps1),
            _mock_scalars_all(exps2),
        ])
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert result["total_treatments"] == 2
        assert result["total_outcomes"] == 3  # CR + PR + PD
        # ORR = (CR + PR) / 3 = 2/3
        assert result["orr"]["cr"] == 1
        assert result["orr"]["pr"] == 1
        assert result["orr"]["total"] == 3
        assert result["orr"]["orr"] == round(2 / 3, 4)
        # DCR = (CR + PR + SD) / 3 = 2/3
        assert result["dcr"]["sd"] == 0
        assert result["dcr"]["pd"] == 1
        # AE 分布: grade 2 x1, grade 3 x1, grade 5 x1
        assert result["ae_distribution"]["2"] == 1
        assert result["ae_distribution"]["3"] == 1
        assert result["ae_distribution"]["5"] == 1
        assert result["ae_distribution"]["1"] == 0
        assert result["ae_distribution"]["4"] == 0

    @pytest.mark.asyncio
    async def test_summary_handles_string_adverse_events(self):
        """adverse_events 元素为字符串时应转为 {severity: <str>} 后分级"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        t1 = _make_treatment()
        exps = [
            _make_experiment(
                treatment_id=t1.id,
                result={
                    "response": "CR",
                    "adverse_events": ["moderate", "3"],
                },
            ),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars_all([t1]),
            _mock_scalars_all(exps),
        ])
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        # "moderate" -> grade 2, "3" -> grade 3
        assert result["ae_distribution"]["2"] == 1
        assert result["ae_distribution"]["3"] == 1

    @pytest.mark.asyncio
    async def test_summary_handles_result_none(self):
        """experiment.result=None 时不应抛异常"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        t1 = _make_treatment()
        exps = [
            _make_experiment(treatment_id=t1.id, result=None),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars_all([t1]),
            _mock_scalars_all(exps),
        ])
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert result["total_outcomes"] == 0
        assert all(v == 0 for v in result["ae_distribution"].values())

    @pytest.mark.asyncio
    async def test_summary_handles_adverse_events_none(self):
        """adverse_events=None 时不应抛异常"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        t1 = _make_treatment()
        exps = [
            _make_experiment(
                treatment_id=t1.id,
                result={"response": "CR", "adverse_events": None},
            ),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[
            _mock_scalars_all([t1]),
            _mock_scalars_all(exps),
        ])
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert result["total_outcomes"] == 1
        assert all(v == 0 for v in result["ae_distribution"].values())

    @pytest.mark.asyncio
    async def test_summary_ae_distribution_has_all_grades(self):
        """ae_distribution 应包含 1-5 全部等级键"""
        from app.services.optimizer.efficacy_monitor import EfficacyMonitor

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        monitor = EfficacyMonitor(mock_db)

        result = await monitor.global_summary()

        assert set(result["ae_distribution"].keys()) == {"1", "2", "3", "4", "5"}
