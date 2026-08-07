"""Evolution Strategies 进化策略决策器 — 单元测试

覆盖：
- Enhancement 触发（>=2 个 severity >=7 的缺陷）
- Combination 触发（相似度 >= 阈值 且 recommendation=merge）
- Simplification 触发（testability 低 或 描述过长）
- Keep 默认（无任何触发条件）
- 策略优先级（Combination > Enhancement > Simplification > Keep）
- 互斥保护（一个假设只能参与一次 Combination）
- 批量决策 + 统计汇总
- 自定义阈值 + 配置回退
"""
import pytest

from app.services.coscientist.algorithms.evolution_strategies import (
    EvolutionPlan,
    EvolutionStrategist,
)


def _make_hypothesis(
    hid: str,
    description: str = "正常描述",
    testability_score: float = 8.0,
    name: str = None,
) -> dict:
    """构造测试假设"""
    h = {
        "id": hid,
        "name": name or f"H-{hid}",
        "description": description,
        "mechanism": "机制描述",
        "testability_score": testability_score,
    }
    return h


def _make_critique(hid: str, flaws: list) -> dict:
    """构造 Reflection 批判结果"""
    return {"hypothesis_id": hid, "flaws": flaws}


def _flaw(description: str, severity: int) -> dict:
    return {"description": description, "severity": severity}


class TestEvolutionPlanDataclass:
    """EvolutionPlan 数据类测试"""

    def test_default_plan(self):
        plan = EvolutionPlan(hypothesis_id="1", strategy="keep")
        assert plan.hypothesis_id == "1"
        assert plan.strategy == "keep"
        assert plan.target_hypothesis_id is None
        assert plan.flaws == []
        assert plan.similarity is None
        assert plan.complexity_issues == []
        assert plan.reason == ""


class TestEnhancementStrategy:
    """Enhancement（增强）策略测试"""

    def test_two_severe_flaws_triggers_enhancement(self):
        """2 个 severity>=7 的缺陷触发 Enhancement"""
        strategist = EvolutionStrategist(severity_threshold=7)
        hyps = [_make_hypothesis("1")]
        critiques = [_make_critique("1", [
            _flaw("缺陷A", 8),
            _flaw("缺陷B", 7),
        ])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert len(plans) == 1
        assert plans[0].strategy == "enhancement"
        assert plans[0].hypothesis_id == "1"
        assert len(plans[0].flaws) == 2
        assert "严重缺陷" in plans[0].reason

    def test_one_severe_flaw_no_enhancement(self):
        """只有 1 个严重缺陷不触发 Enhancement（需 >=2）"""
        strategist = EvolutionStrategist(severity_threshold=7)
        hyps = [_make_hypothesis("1", description="短描述")]
        critiques = [_make_critique("1", [_flaw("唯一严重缺陷", 9)])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert plans[0].strategy == "keep"

    def test_low_severity_flaws_no_enhancement(self):
        """severity < 阈值的缺陷不触发 Enhancement"""
        strategist = EvolutionStrategist(severity_threshold=7)
        hyps = [_make_hypothesis("1", description="短描述")]
        critiques = [_make_critique("1", [
            _flaw("轻微缺陷A", 5),
            _flaw("轻微缺陷B", 6),
        ])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert plans[0].strategy == "keep"

    def test_custom_severity_threshold(self):
        """自定义严重度阈值"""
        strategist = EvolutionStrategist(severity_threshold=5)
        hyps = [_make_hypothesis("1")]
        critiques = [_make_critique("1", [
            _flaw("中等缺陷A", 5),
            _flaw("中等缺陷B", 6),
        ])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert plans[0].strategy == "enhancement"
        assert len(plans[0].flaws) == 2

    def test_severe_flaws_filtered_in_plan(self):
        """Enhancement 计划只包含严重缺陷"""
        strategist = EvolutionStrategist(severity_threshold=7)
        hyps = [_make_hypothesis("1")]
        critiques = [_make_critique("1", [
            _flaw("严重A", 9),
            _flaw("轻微B", 3),
            _flaw("严重C", 8),
            _flaw("轻微D", 2),
        ])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert plans[0].strategy == "enhancement"
        assert len(plans[0].flaws) == 2
        severities = [f["severity"] for f in plans[0].flaws]
        assert all(s >= 7 for s in severities)


class TestCombinationStrategy:
    """Combination（合并）策略测试"""

    def test_high_similarity_merge_triggers_combination(self):
        """相似度 >= 阈值 + recommendation=merge 触发 Combination"""
        strategist = EvolutionStrategist(similarity_threshold=0.7)
        hyps = [_make_hypothesis("1"), _make_hypothesis("2")]
        critiques = []
        proximity = {
            "pairs": [{
                "id_a": "1",
                "id_b": "2",
                "semantic_similarity": 0.85,
                "recommendation": "merge",
            }]
        }
        plans = strategist.decide_strategies(hyps, critiques, proximity)

        plan_map = {p.hypothesis_id: p for p in plans}
        assert plan_map["1"].strategy == "combination"
        assert plan_map["1"].target_hypothesis_id == "2"
        assert plan_map["1"].similarity == pytest.approx(0.85)

    def test_low_similarity_no_combination(self):
        """相似度 < 阈值不触发 Combination"""
        strategist = EvolutionStrategist(similarity_threshold=0.7)
        hyps = [_make_hypothesis("1", description="短"), _make_hypothesis("2", description="短")]
        proximity = {
            "pairs": [{
                "id_a": "1", "id_b": "2",
                "semantic_similarity": 0.5,
                "recommendation": "merge",
            }]
        }
        plans = strategist.decide_strategies(hyps, [], proximity)

        for p in plans:
            assert p.strategy == "keep"

    def test_keep_separate_no_combination(self):
        """recommendation != merge 不触发 Combination"""
        strategist = EvolutionStrategist(similarity_threshold=0.7)
        hyps = [_make_hypothesis("1", description="短"), _make_hypothesis("2", description="短")]
        proximity = {
            "pairs": [{
                "id_a": "1", "id_b": "2",
                "semantic_similarity": 0.9,
                "recommendation": "keep_separate",
            }]
        }
        plans = strategist.decide_strategies(hyps, [], proximity)

        for p in plans:
            assert p.strategy == "keep"

    def test_combination_is_mutually_exclusive(self):
        """一个假设只能参与一次 Combination"""
        strategist = EvolutionStrategist(similarity_threshold=0.7)
        hyps = [
            _make_hypothesis("1", description="短"),
            _make_hypothesis("2", description="短"),
            _make_hypothesis("3", description="短"),
        ]
        proximity = {
            "pairs": [
                {"id_a": "1", "id_b": "2", "semantic_similarity": 0.9, "recommendation": "merge"},
                {"id_a": "1", "id_b": "3", "semantic_similarity": 0.85, "recommendation": "merge"},
            ]
        }
        plans = strategist.decide_strategies(hyps, [], proximity)
        combination_plans = [p for p in plans if p.strategy == "combination"]

        assert len(combination_plans) == 1
        assert combination_plans[0].hypothesis_id == "1"
        assert combination_plans[0].target_hypothesis_id == "2"


class TestSimplificationStrategy:
    """Simplification（简化）策略测试"""

    def test_low_testability_triggers_simplification(self):
        """可测试性评分低于阈值触发 Simplification"""
        strategist = EvolutionStrategist(testability_threshold=5.0)
        hyps = [_make_hypothesis("1", testability_score=3.0, description="短描述")]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "simplification"
        assert any("可测试性" in issue for issue in plans[0].complexity_issues)

    def test_long_description_triggers_simplification(self):
        """描述过长触发 Simplification"""
        strategist = EvolutionStrategist(complexity_len_threshold=100)
        long_desc = "x" * 200
        hyps = [_make_hypothesis("1", description=long_desc, testability_score=8.0)]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "simplification"
        assert any("描述长度" in issue for issue in plans[0].complexity_issues)

    def test_normal_testability_no_simplification(self):
        """正常可测试性不触发 Simplification"""
        strategist = EvolutionStrategist(testability_threshold=5.0)
        hyps = [_make_hypothesis("1", testability_score=8.0, description="短描述")]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "keep"

    def test_both_issues_combined_in_simplification(self):
        """可测试性低 + 描述过长 → 两个问题都记录"""
        strategist = EvolutionStrategist(
            testability_threshold=5.0,
            complexity_len_threshold=100,
        )
        long_desc = "y" * 200
        hyps = [_make_hypothesis("1", description=long_desc, testability_score=2.0)]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "simplification"
        assert len(plans[0].complexity_issues) == 2


class TestPriorityAndKeep:
    """策略优先级 + Keep 默认测试"""

    def test_combination_beats_enhancement(self):
        """Combination 优先级高于 Enhancement"""
        strategist = EvolutionStrategist(severity_threshold=7, similarity_threshold=0.7)
        hyps = [
            _make_hypothesis("1"),
            _make_hypothesis("2"),
        ]
        critiques = [_make_critique("1", [_flaw("严重A", 9), _flaw("严重B", 8)])]
        proximity = {
            "pairs": [{
                "id_a": "1", "id_b": "2",
                "semantic_similarity": 0.9, "recommendation": "merge",
            }]
        }
        plans = strategist.decide_strategies(hyps, critiques, proximity)
        plan_map = {p.hypothesis_id: p for p in plans}

        assert plan_map["1"].strategy == "combination"

    def test_enhancement_beats_simplification(self):
        """Enhancement 优先级高于 Simplification"""
        strategist = EvolutionStrategist(
            severity_threshold=7,
            testability_threshold=5.0,
        )
        hyps = [_make_hypothesis("1", testability_score=2.0, description="短")]
        critiques = [_make_critique("1", [_flaw("严重A", 9), _flaw("严重B", 8)])]
        plans = strategist.decide_strategies(hyps, critiques)

        assert plans[0].strategy == "enhancement"

    def test_keep_when_no_triggers(self):
        """无任何触发条件时默认 Keep"""
        strategist = EvolutionStrategist()
        hyps = [_make_hypothesis("1", testability_score=8.0, description="正常描述")]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "keep"
        assert "无需进化" in plans[0].reason

    def test_keep_when_critique_missing(self):
        """假设没有对应 critique 时为 Keep"""
        strategist = EvolutionStrategist()
        hyps = [_make_hypothesis("1", description="短")]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].strategy == "keep"


class TestBatchDecisions:
    """批量决策测试"""

    def test_mixed_strategies_in_batch(self):
        """混合策略批量决策"""
        strategist = EvolutionStrategist(
            severity_threshold=7,
            similarity_threshold=0.7,
            testability_threshold=5.0,
        )
        hyps = [
            _make_hypothesis("1", description="短"),
            _make_hypothesis("2", description="短"),
            _make_hypothesis("3", description="短"),
            _make_hypothesis("4", testability_score=2.0, description="短"),
            _make_hypothesis("5", description="短"),
        ]
        critiques = [_make_critique("5", [_flaw("严重A", 9), _flaw("严重B", 8)])]
        proximity = {
            "pairs": [{
                "id_a": "2", "id_b": "3",
                "semantic_similarity": 0.9, "recommendation": "merge",
            }]
        }
        plans = strategist.decide_strategies(hyps, critiques, proximity)
        plan_map = {p.hypothesis_id: p for p in plans}

        assert plan_map["1"].strategy == "keep"
        assert plan_map["2"].strategy == "combination"
        assert plan_map["3"].strategy == "keep"
        assert plan_map["4"].strategy == "simplification"
        assert plan_map["5"].strategy == "enhancement"

    def test_empty_hypotheses(self):
        """空假设列表"""
        strategist = EvolutionStrategist()
        plans = strategist.decide_strategies([], [])
        assert plans == []

    def test_no_proximity_result(self):
        """无 proximity_result 时不崩溃"""
        strategist = EvolutionStrategist()
        hyps = [_make_hypothesis("1", description="短")]
        plans = strategist.decide_strategies(hyps, [], proximity_result=None)
        assert plans[0].strategy == "keep"

    def test_no_proximity_pairs(self):
        """proximity_result 无 pairs 键时不崩溃"""
        strategist = EvolutionStrategist()
        hyps = [_make_hypothesis("1", description="短")]
        plans = strategist.decide_strategies(hyps, [], proximity_result={})
        assert plans[0].strategy == "keep"


class TestSummarizePlans:
    """策略汇总统计测试"""

    def test_summarize_mixed_plans(self):
        """汇总混合策略"""
        plans = [
            EvolutionPlan("1", "enhancement"),
            EvolutionPlan("2", "combination"),
            EvolutionPlan("3", "simplification"),
            EvolutionPlan("4", "keep"),
            EvolutionPlan("5", "keep"),
        ]
        strategist = EvolutionStrategist()
        summary = strategist.summarize_plans(plans)

        assert summary["enhancement"] == 1
        assert summary["combination"] == 1
        assert summary["simplification"] == 1
        assert summary["keep"] == 2

    def test_summarize_empty(self):
        """空计划列表"""
        strategist = EvolutionStrategist()
        summary = strategist.summarize_plans([])
        assert summary == {
            "enhancement": 0,
            "combination": 0,
            "simplification": 0,
            "keep": 0,
        }

    def test_summarize_unknown_strategy_ignored(self):
        """未知策略被忽略"""
        plans = [
            EvolutionPlan("1", "enhancement"),
            EvolutionPlan("2", "unknown_strategy"),
        ]
        strategist = EvolutionStrategist()
        summary = strategist.summarize_plans(plans)

        assert summary["enhancement"] == 1
        assert summary["keep"] == 0


class TestHypothesisIdFallback:
    """假设 ID 回退测试"""

    def test_id_fallback_to_name(self):
        """无 id 字段时回退到 name"""
        strategist = EvolutionStrategist()
        hyps = [{"name": "H1", "description": "短", "testability_score": 8.0}]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].hypothesis_id == "H1"
        assert plans[0].strategy == "keep"

    def test_string_id_normalization(self):
        """整数 ID 被转为字符串"""
        strategist = EvolutionStrategist()
        hyps = [{"id": 123, "name": "H1", "description": "短", "testability_score": 8.0}]
        plans = strategist.decide_strategies(hyps, [])

        assert plans[0].hypothesis_id == "123"