"""HypothesisComparator 单元测试 — 覆盖 hypothesis_comparator.py 全部方法

测试目标：
- compare() 主流程：空列表 / 未找到 / 全部命中 / 部分命中
- _extract_target_list()：target_list 优先 / 退化到 analysis_result / dict 与 str 混合 / 空输入
- _compute_shared_targets()：空集合 / 单集合 / 多集合交集
- _compute_unique_targets()：单/多假设独占靶点
- _compute_scores()：各 evidence_level、status 映射、归一化
- _generate_recommendations()：共享/无共享/最高分/独有靶点创新性/低分淘汰/合并建议
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.report.hypothesis_comparator import (
    HypothesisComparator,
    _DEFAULT_WEIGHTS,
)


# ============================================================
# 辅助工厂函数
# ============================================================

def make_hypothesis(
    hid=None,
    name="H1",
    status="draft",
    target_list=None,
    analysis_result=None,
):
    """构造一个轻量的 Hypothesis-like 对象（避免 ORM 依赖）"""
    return SimpleNamespace(
        id=hid if hid is not None else uuid4(),
        name=name,
        status=status,
        target_list=target_list,
        analysis_result=analysis_result,
    )


def make_mock_db(hypotheses):
    """构造 mock AsyncSession，execute 返回包含给定假设列表的结果"""
    db = MagicMock()
    result_mock = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = list(hypotheses)
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ============================================================
# __init__
# ============================================================

class TestInit:
    def test_init_stores_db(self):
        db = MagicMock()
        cmp = HypothesisComparator(db)
        assert cmp.db is db


# ============================================================
# compare()
# ============================================================

class TestCompareEmptyInput:
    @pytest.mark.asyncio
    async def test_compare_empty_list_returns_no_hypotheses(self):
        """空 ID 列表应返回 no_hypotheses 状态"""
        db = MagicMock()
        cmp = HypothesisComparator(db)
        result = await cmp.compare([])

        assert result["status"] == "no_hypotheses"
        assert result["shared_targets"] == []
        assert result["unique_targets"] == {}
        assert result["scores"] == {}
        assert result["hypotheses_summary"] == []
        assert result["recommendations"] == ["无可比较的假设"]
        # 不应调用数据库
        db.execute.assert_not_called()


class TestCompareNoHypothesesFound:
    @pytest.mark.asyncio
    async def test_compare_none_found_returns_no_hypotheses(self):
        """数据库未返回任何假设时应返回 no_hypotheses 状态"""
        db = make_mock_db([])
        cmp = HypothesisComparator(db)

        ids = [uuid4(), uuid4()]
        result = await cmp.compare(ids)

        assert result["status"] == "no_hypotheses"
        assert result["shared_targets"] == []
        assert result["unique_targets"] == {}
        assert result["scores"] == {}
        assert result["hypotheses_summary"] == []
        assert result["recommendations"] == ["未找到指定的假设"]
        db.execute.assert_awaited_once()


class TestCompareFullMatch:
    @pytest.mark.asyncio
    async def test_compare_all_found_status_compared(self):
        """所有 ID 命中数据库时 status=compared"""
        h1 = make_hypothesis(
            name="H1",
            status="completed",
            target_list=["EGFR", "KRAS", "TP53"],
            analysis_result={"evidence_level": "A"},
        )
        h2 = make_hypothesis(
            name="H2",
            status="completed",
            target_list=["EGFR", "KRAS", "MYC"],
            analysis_result={"evidence_level": "B"},
        )
        db = make_mock_db([h1, h2])
        cmp = HypothesisComparator(db)

        result = await cmp.compare([h1.id, h2.id])

        assert result["status"] == "compared"
        # 共享靶点 EGFR、KRAS
        assert result["shared_targets"] == ["EGFR", "KRAS"]
        # 独有靶点
        assert result["unique_targets"][str(h1.id)] == ["TP53"]
        assert result["unique_targets"][str(h2.id)] == ["MYC"]
        # 评分
        assert str(h1.id) in result["scores"]
        assert str(h2.id) in result["scores"]
        # 汇总
        assert len(result["hypotheses_summary"]) == 2
        summary_by_id = {s["id"]: s for s in result["hypotheses_summary"]}
        assert summary_by_id[str(h1.id)]["name"] == "H1"
        assert summary_by_id[str(h1.id)]["target_count"] == 3
        assert summary_by_id[str(h1.id)]["score"] == result["scores"][str(h1.id)]
        # 推荐至少包含共享靶点提示和最高分提示
        assert any("共享靶点" in r for r in result["recommendations"])
        assert any("综合评分最高" in r for r in result["recommendations"])


class TestComparePartialMatch:
    @pytest.mark.asyncio
    async def test_compare_partial_status(self):
        """仅部分 ID 命中时应返回 partial 状态"""
        h1 = make_hypothesis(name="H1", target_list=["EGFR"])
        db = make_mock_db([h1])  # 只返回 1 个
        cmp = HypothesisComparator(db)

        # 传入 2 个 ID，但 DB 只命中 1 个
        result = await cmp.compare([h1.id, uuid4()])

        assert result["status"] == "partial"
        assert len(result["hypotheses_summary"]) == 1


class TestCompareSingleHypothesis:
    @pytest.mark.asyncio
    async def test_compare_single_hypothesis(self):
        """单个假设：所有靶点都成为 unique_targets，无共享"""
        h = make_hypothesis(
            name="Only",
            target_list=["EGFR", "KRAS"],
            status="completed",
            analysis_result={"evidence_level": "A"},
        )
        db = make_mock_db([h])
        cmp = HypothesisComparator(db)

        result = await cmp.compare([h.id])

        assert result["status"] == "compared"
        # 单个假设：target 集合与自身相等 → 全部"独有"
        assert result["unique_targets"][str(h.id)] == ["EGFR", "KRAS"]
        # 单个假设共享靶点 = 自身（self-intersection）
        # 但代码逻辑：shared = target_sets[0]，对单元素来说就是自身集合
        assert set(result["shared_targets"]) == {"EGFR", "KRAS"}
        assert any("共享靶点" in r for r in result["recommendations"])


# ============================================================
# _extract_target_list()
# ============================================================

class TestExtractTargetList:
    def test_extract_from_target_list(self):
        """优先使用 target_list 字段"""
        h = make_hypothesis(target_list=["EGFR", "KRAS", "TP53"])
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR", "KRAS", "TP53"]

    def test_extract_from_target_list_coerces_to_str(self):
        """target_list 中的非字符串元素应被转为 str"""
        h = make_hypothesis(target_list=["EGFR", 123, None, "KRAS"])
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        # None 应被过滤
        assert result == ["EGFR", "123", "KRAS"]

    def test_extract_from_target_list_filters_falsy(self):
        """空字符串、None、0 等 falsy 值应被过滤"""
        h = make_hypothesis(target_list=["EGFR", "", None, "KRAS"])
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR", "KRAS"]

    def test_extract_fallback_to_analysis_result_dicts_gene_symbol(self):
        """target_list 为 None 时退化到 analysis_result.targets (dict with gene_symbol)"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={
                "targets": [
                    {"gene_symbol": "EGFR"},
                    {"gene_symbol": "KRAS"},
                ]
            },
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR", "KRAS"]

    def test_extract_fallback_to_analysis_result_dicts_symbol(self):
        """dict 无 gene_symbol 时使用 symbol 键"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": [{"symbol": "TP53"}]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["TP53"]

    def test_extract_fallback_to_analysis_result_dicts_id(self):
        """dict 无 gene_symbol/symbol 时使用 id 键"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": [{"id": "MYC"}]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["MYC"]

    def test_extract_fallback_to_analysis_result_strings(self):
        """analysis_result.targets 为字符串列表"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": ["EGFR", "KRAS"]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR", "KRAS"]

    def test_extract_fallback_to_analysis_result_mixed_types(self):
        """analysis_result.targets 混合 dict 与 str"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={
                "targets": [
                    {"gene_symbol": "EGFR"},
                    "KRAS",
                    {"symbol": "TP53"},
                    {"id": "MYC"},
                ]
            },
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR", "KRAS", "TP53", "MYC"]

    def test_extract_fallback_dict_with_no_valid_key_returns_empty(self):
        """dict 无 gene_symbol/symbol/id 时该条目被跳过"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": [{"foo": "bar"}, {"gene_symbol": "EGFR"}]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR"]

    def test_extract_fallback_dict_with_falsy_value_skipped(self):
        """dict 中 gene_symbol 为 falsy 时应继续尝试 symbol/id"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={
                "targets": [
                    {"gene_symbol": "", "symbol": "TP53"},
                    {"gene_symbol": None, "symbol": None, "id": "MYC"},
                ]
            },
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["TP53", "MYC"]

    def test_extract_target_list_empty_list_falls_back(self):
        """target_list 为空列表时应退化到 analysis_result"""
        h = make_hypothesis(
            target_list=[],
            analysis_result={"targets": ["EGFR"]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["EGFR"]

    def test_extract_target_list_not_list_falls_back(self):
        """target_list 不是 list 类型（如 dict）时应退化"""
        h = make_hypothesis(
            target_list={"EGFR": 1},  # 不是 list
            analysis_result={"targets": ["KRAS"]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == ["KRAS"]

    def test_extract_no_target_list_no_analysis_result_returns_empty(self):
        """target_list 与 analysis_result 都为 None 时返回空列表"""
        h = make_hypothesis(target_list=None, analysis_result=None)
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == []

    def test_extract_analysis_result_none_targets_returns_empty(self):
        """analysis_result 非 None 但 targets 为 None"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"other": "data"},  # 无 targets 键
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == []

    def test_extract_analysis_result_targets_empty_returns_empty(self):
        """analysis_result.targets 为空列表"""
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": []},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        assert result == []

    def test_extract_analysis_result_targets_empty_string_kept(self):
        """analysis_result.targets 中字符串路径不过滤 falsy（仅 target_list 路径过滤）

        注意：源代码 fallback 路径 `elif isinstance(t, str): result.append(t)`
        未做 `if t:` 检查，因此空字符串会被保留。该测试记录此既有行为。
        """
        h = make_hypothesis(
            target_list=None,
            analysis_result={"targets": ["EGFR", "", "KRAS"]},
        )
        cmp = HypothesisComparator(MagicMock())
        result = cmp._extract_target_list(h)
        # 空字符串被保留（仅 target_list 路径才会过滤 falsy）
        assert result == ["EGFR", "", "KRAS"]


# ============================================================
# _compute_shared_targets()
# ============================================================

class TestComputeSharedTargets:
    def test_empty_list_returns_empty_set(self):
        cmp = HypothesisComparator(MagicMock())
        assert cmp._compute_shared_targets([]) == set()

    def test_single_set_returns_self(self):
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_shared_targets([{"EGFR", "KRAS"}])
        assert result == {"EGFR", "KRAS"}

    def test_multiple_sets_with_intersection(self):
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_shared_targets([
            {"EGFR", "KRAS", "TP53"},
            {"EGFR", "KRAS", "MYC"},
            {"EGFR", "ABC"},
        ])
        assert result == {"EGFR"}

    def test_multiple_sets_no_intersection(self):
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_shared_targets([
            {"EGFR"},
            {"KRAS"},
        ])
        assert result == set()

    def test_one_empty_set_returns_empty(self):
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_shared_targets([
            {"EGFR", "KRAS"},
            set(),
        ])
        assert result == set()


# ============================================================
# _compute_unique_targets()
# ============================================================

class TestComputeUniqueTargets:
    def test_single_hypothesis_all_unique(self):
        """单个假设：所有靶点都是独有的"""
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_unique_targets({"h1": {"EGFR", "KRAS"}})
        assert result == {"h1": {"EGFR", "KRAS"}}

    def test_two_hypotheses_disjoint(self):
        """两个假设完全无重叠时全部独有"""
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_unique_targets({
            "h1": {"EGFR"},
            "h2": {"KRAS"},
        })
        assert result == {"h1": {"EGFR"}, "h2": {"KRAS"}}

    def test_two_hypotheses_with_overlap(self):
        """有共享靶点时独有靶点排除共享部分"""
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_unique_targets({
            "h1": {"EGFR", "KRAS", "TP53"},
            "h2": {"EGFR", "KRAS", "MYC"},
        })
        assert result == {"h1": {"TP53"}, "h2": {"MYC"}}

    def test_all_identical_no_unique(self):
        """所有假设靶点完全相同时无独有靶点"""
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_unique_targets({
            "h1": {"EGFR", "KRAS"},
            "h2": {"EGFR", "KRAS"},
        })
        assert result == {"h1": set(), "h2": set()}

    def test_three_hypotheses_unique_computed(self):
        """三个假设：独有靶点 = 自身 - 其他三者并集"""
        cmp = HypothesisComparator(MagicMock())
        result = cmp._compute_unique_targets({
            "h1": {"A", "B", "C"},
            "h2": {"A", "B", "D"},
            "h3": {"A", "E"},
        })
        # h1: {A,B,C} - {A,B,D,E} = {C}
        # h2: {A,B,D} - {A,B,C,E} = {D}
        # h3: {A,E} - {A,B,C,D} = {E}
        assert result == {"h1": {"C"}, "h2": {"D"}, "h3": {"E"}}

    def test_empty_dict_returns_empty(self):
        cmp = HypothesisComparator(MagicMock())
        assert cmp._compute_unique_targets({}) == {}


# ============================================================
# _compute_scores()
# ============================================================

class TestComputeScores:
    def _build(self, hypotheses, target_lists, target_sets):
        cmp = HypothesisComparator(MagicMock())
        return cmp._compute_scores(hypotheses, target_lists, target_sets)

    def test_scores_use_default_weights(self):
        """验证 _DEFAULT_WEIGHTS 内容"""
        assert _DEFAULT_WEIGHTS["target_count"] == 0.3
        assert _DEFAULT_WEIGHTS["unique_target_ratio"] == 0.3
        assert _DEFAULT_WEIGHTS["evidence_level"] == 0.2
        assert _DEFAULT_WEIGHTS["analysis_completeness"] == 0.2

    def test_score_evidence_level_A(self):
        h = make_hypothesis(
            status="completed",
            analysis_result={"evidence_level": "A"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        # target_count_score = 1/1 = 1.0
        # unique_ratio = 1/1 = 1.0 (单假设)
        # evidence_score = 1.0
        # status_score (completed) = 1.0
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 1.0 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_B(self):
        h = make_hypothesis(
            status="completed",
            analysis_result={"evidence_level": "B"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 0.7 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_C_default(self):
        h = make_hypothesis(
            status="completed",
            analysis_result={"evidence_level": "C"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 0.4 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_unknown_falls_back_to_C(self):
        """未知 evidence_level（如 D / Z）应映射为 0.4"""
        h = make_hypothesis(
            status="completed",
            analysis_result={"evidence_level": "Z"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 0.4 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_missing_defaults_C(self):
        """analysis_result 中无 evidence_level 默认 C"""
        h = make_hypothesis(
            status="completed",
            analysis_result={},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 0.4 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_lowercase_normalized(self):
        """小写 evidence_level 应被 upper() 后映射"""
        h = make_hypothesis(
            status="completed",
            analysis_result={"evidence_level": "a"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 1.0 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_evidence_level_none_analysis_result(self):
        """analysis_result 为 None 时默认 C"""
        h = make_hypothesis(
            status="completed",
            analysis_result=None,
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 0.4 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h.id)] == expected

    @pytest.mark.parametrize(
        "status,expected_status_score",
        [
            ("completed", 1.0),
            ("merged", 0.9),
            ("analyzing", 0.5),
            ("draft", 0.3),
            ("archived", 0.2),
            ("eliminated", 0.0),
            ("unknown_status", 0.3),  # 未知状态默认 0.3
        ],
    )
    def test_score_status_mapping(self, status, expected_status_score):
        h = make_hypothesis(
            status=status,
            analysis_result={"evidence_level": "A"},
        )
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        expected = round(
            0.3 * 1.0 + 0.3 * 1.0 + 0.2 * 1.0 + 0.2 * expected_status_score,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_target_count_normalization(self):
        """多个假设时靶点数量按最大值归一化"""
        h1 = make_hypothesis(status="completed", analysis_result={"evidence_level": "A"})
        h2 = make_hypothesis(status="completed", analysis_result={"evidence_level": "A"})
        # h1: 2 targets, h2: 4 targets → max=4
        target_lists = {str(h1.id): ["A", "B"], str(h2.id): ["A", "B", "C", "D"]}
        target_sets = {str(h1.id): {"A", "B"}, str(h2.id): {"A", "B", "C", "D"}}
        scores = self._build([h1, h2], target_lists, target_sets)

        # h1: target_count_score = 2/4 = 0.5; unique_ratio: {A,B}-{A,B,C,D}=0/2=0
        expected_h1 = round(
            0.3 * 0.5 + 0.3 * 0.0 + 0.2 * 1.0 + 0.2 * 1.0,
            4,
        )
        # h2: target_count_score = 4/4 = 1.0; unique_ratio: {A,B,C,D}-{A,B}=2/4=0.5
        expected_h2 = round(
            0.3 * 1.0 + 0.3 * 0.5 + 0.2 * 1.0 + 0.2 * 1.0,
            4,
        )
        assert scores[str(h1.id)] == expected_h1
        assert scores[str(h2.id)] == expected_h2

    def test_score_empty_target_lists_max_default_1(self):
        """空 target_lists 时 max_target_count default=1，避免除零"""
        h = make_hypothesis(status="draft", analysis_result={})
        scores = self._build([h], {str(h.id): []}, {str(h.id): set()})
        # target_count_score = 0/1 = 0; unique_ratio: 0/0 → 0
        # evidence_score (C default) = 0.4; status_score (draft) = 0.3
        expected = round(
            0.3 * 0.0 + 0.3 * 0.0 + 0.2 * 0.4 + 0.2 * 0.3,
            4,
        )
        assert scores[str(h.id)] == expected

    def test_score_all_empty_target_lists(self):
        """所有假设 target_lists 都为空时 max=0 → default=1"""
        h1 = make_hypothesis(status="draft", analysis_result={})
        h2 = make_hypothesis(status="draft", analysis_result={})
        target_lists = {str(h1.id): [], str(h2.id): []}
        target_sets = {str(h1.id): set(), str(h2.id): set()}
        scores = self._build([h1, h2], target_lists, target_sets)
        # 每个假设 target_count_score = 0/1 = 0; unique_ratio = 0/0 → 0
        expected = round(
            0.3 * 0.0 + 0.3 * 0.0 + 0.2 * 0.4 + 0.2 * 0.3,
            4,
        )
        assert scores[str(h1.id)] == expected
        assert scores[str(h2.id)] == expected

    def test_score_rounded_to_4_decimals(self):
        h = make_hypothesis(status="completed", analysis_result={"evidence_level": "A"})
        scores = self._build([h], {str(h.id): ["EGFR"]}, {str(h.id): {"EGFR"}})
        val = scores[str(h.id)]
        # 检查四舍五入到 4 位小数
        assert round(val, 4) == val


# ============================================================
# _generate_recommendations()
# ============================================================

class TestGenerateRecommendations:
    def _build(self, hypotheses, target_lists, target_sets, shared_targets, scores):
        cmp = HypothesisComparator(MagicMock())
        return cmp._generate_recommendations(
            hypotheses, target_lists, target_sets, shared_targets, scores
        )

    def test_with_shared_targets_emits_shared_recommendation(self):
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        target_sets = {str(h1.id): {"EGFR"}, str(h2.id): {"EGFR"}}
        scores = {str(h1.id): 0.8, str(h2.id): 0.6}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["EGFR"], str(h2.id): ["EGFR"]},
            target_sets,
            {"EGFR"},
            scores,
        )
        assert any("共享靶点" in r and "1" in r for r in recs)

    def test_without_shared_targets_emits_independent_recommendation(self):
        h1 = make_hypothesis(name="H1")
        target_sets = {str(h1.id): {"EGFR"}}
        scores = {str(h1.id): 0.8}
        recs = self._build(
            [h1],
            {str(h1.id): ["EGFR"]},
            target_sets,
            set(),  # 无共享靶点
            scores,
        )
        assert any("无共享靶点" in r for r in recs)

    def test_empty_scores_skips_best_recommendation(self):
        """scores 为空时应跳过最高分推荐"""
        h1 = make_hypothesis(name="H1")
        recs = self._build(
            [h1],
            {str(h1.id): ["EGFR"]},
            {str(h1.id): {"EGFR"}},
            {"EGFR"},
            {},  # 空 scores
        )
        assert not any("综合评分最高" in r for r in recs)

    def test_best_score_recommendation(self):
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        scores = {str(h1.id): 0.9, str(h2.id): 0.5}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["EGFR"], str(h2.id): ["KRAS"]},
            {str(h1.id): {"EGFR"}, str(h2.id): {"KRAS"}},
            set(),
            scores,
        )
        assert any("假设 'H1' 综合评分最高（0.9）" in r for r in recs)

    def test_best_score_best_hypothesis_not_found(self):
        """最高分 ID 对应假设不在 hypotheses 列表中（理论上不会发生，但防御性测试）"""
        h1 = make_hypothesis(name="H1")
        scores = {"nonexistent-id": 0.9}
        recs = self._build(
            [h1],
            {str(h1.id): ["EGFR"]},
            {str(h1.id): {"EGFR"}},
            set(),
            scores,
        )
        # best_h 找不到 → 跳过该推荐
        assert not any("综合评分最高" in r for r in recs)

    def test_unique_targets_innovation_recommendation(self):
        """独有靶点 >= 3 时应触发创新性推荐"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        # h1 独有 3 个靶点
        target_sets = {
            str(h1.id): {"A", "B", "C", "SHARED"},
            str(h2.id): {"SHARED"},
        }
        scores = {str(h1.id): 0.8, str(h2.id): 0.4}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["A", "B", "C", "SHARED"], str(h2.id): ["SHARED"]},
            target_sets,
            {"SHARED"},
            scores,
        )
        assert any("假设 'H1' 拥有 3 个独有靶点" in r for r in recs)

    def test_unique_targets_below_threshold_no_recommendation(self):
        """独有靶点 < 3 时不应触发创新性推荐"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        target_sets = {
            str(h1.id): {"A", "SHARED"},
            str(h2.id): {"SHARED"},
        }
        scores = {str(h1.id): 0.8, str(h2.id): 0.8}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["A", "SHARED"], str(h2.id): ["SHARED"]},
            target_sets,
            {"SHARED"},
            scores,
        )
        assert not any("独有靶点" in r and "创新性较高" in r for r in recs)

    def test_unique_targets_empty_set_skipped(self):
        """假设无任何靶点时应跳过创新性检查"""
        h1 = make_hypothesis(name="H1")
        target_sets = {str(h1.id): set()}
        scores = {str(h1.id): 0.5}
        recs = self._build(
            [h1],
            {str(h1.id): []},
            target_sets,
            set(),
            scores,
        )
        assert not any("创新性较高" in r for r in recs)

    def test_low_score_hypothesis_recommendation(self):
        """评分低于平均 50% 的假设应触发淘汰建议"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="LowScore")
        # avg = (0.8 + 0.1) / 2 = 0.45; avg*0.5 = 0.225; 0.1 < 0.225 → 触发
        scores = {str(h1.id): 0.8, str(h2.id): 0.1}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["A"], str(h2.id): ["B"]},
            {str(h1.id): {"A"}, str(h2.id): {"B"}},
            set(),
            scores,
        )
        assert any("假设 'LowScore' 综合评分显著低于平均" in r for r in recs)

    def test_no_low_score_when_all_equal(self):
        """所有评分相同时不应触发淘汰建议"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        scores = {str(h1.id): 0.5, str(h2.id): 0.5}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["A"], str(h2.id): ["B"]},
            {str(h1.id): {"A"}, str(h2.id): {"B"}},
            set(),
            scores,
        )
        assert not any("显著低于平均" in r for r in recs)

    def test_merge_recommendation_when_shared_and_multiple(self):
        """>=2 假设且有共享靶点时应触发合并建议"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        scores = {str(h1.id): 0.8, str(h2.id): 0.8}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["EGFR"], str(h2.id): ["EGFR"]},
            {str(h1.id): {"EGFR"}, str(h2.id): {"EGFR"}},
            {"EGFR"},
            scores,
        )
        assert any("合并为单一主线假设" in r for r in recs)

    def test_no_merge_recommendation_when_single_hypothesis(self):
        """单个假设时不应触发合并建议（即便有 shared_targets）"""
        h1 = make_hypothesis(name="H1")
        scores = {str(h1.id): 0.8}
        recs = self._build(
            [h1],
            {str(h1.id): ["EGFR"]},
            {str(h1.id): {"EGFR"}},
            {"EGFR"},
            scores,
        )
        assert not any("合并为单一主线假设" in r for r in recs)

    def test_no_merge_recommendation_when_no_shared(self):
        """无共享靶点时不应触发合并建议"""
        h1 = make_hypothesis(name="H1")
        h2 = make_hypothesis(name="H2")
        scores = {str(h1.id): 0.8, str(h2.id): 0.8}
        recs = self._build(
            [h1, h2],
            {str(h1.id): ["A"], str(h2.id): ["B"]},
            {str(h1.id): {"A"}, str(h2.id): {"B"}},
            set(),
            scores,
        )
        assert not any("合并为单一主线假设" in r for r in recs)

    def test_empty_scores_skips_low_score_recommendation(self):
        """scores 为空时应跳过低分淘汰推荐"""
        h1 = make_hypothesis(name="H1")
        recs = self._build(
            [h1],
            {str(h1.id): ["EGFR"]},
            {str(h1.id): {"EGFR"}},
            set(),
            {},
        )
        assert not any("显著低于平均" in r for r in recs)

    def test_full_recommendation_flow(self):
        """端到端验证：多假设 + 共享 + 高分 + 独有创新性 + 低分淘汰 + 合并"""
        h1 = make_hypothesis(name="HighScore")
        h2 = make_hypothesis(name="LowScore")
        # h1 独有 3 个，h2 独有 0 个，shared = 1
        target_sets = {
            str(h1.id): {"A", "B", "C", "SHARED"},
            str(h2.id): {"SHARED"},
        }
        scores = {str(h1.id): 0.9, str(h2.id): 0.1}
        recs = self._build(
            [h1, h2],
            {
                str(h1.id): ["A", "B", "C", "SHARED"],
                str(h2.id): ["SHARED"],
            },
            target_sets,
            {"SHARED"},
            scores,
        )
        # 1. 共享靶点推荐
        assert any("共享靶点" in r for r in recs)
        # 2. 最高分推荐
        assert any("HighScore" in r and "综合评分最高" in r for r in recs)
        # 3. 创新性推荐
        assert any("HighScore" in r and "创新性较高" in r for r in recs)
        # 4. 低分淘汰推荐
        assert any("LowScore" in r and "显著低于平均" in r for r in recs)
        # 5. 合并推荐
        assert any("合并为单一主线假设" in r for r in recs)


# ============================================================
# 集成：compare() 端到端与内部方法协作
# ============================================================

class TestCompareIntegration:
    @pytest.mark.asyncio
    async def test_compare_with_analysis_result_fallback(self):
        """假设 target_list 为 None 时通过 analysis_result 提取靶点"""
        h1 = make_hypothesis(
            name="H1",
            status="completed",
            target_list=None,
            analysis_result={
                "targets": [{"gene_symbol": "EGFR"}, {"gene_symbol": "KRAS"}],
                "evidence_level": "A",
            },
        )
        h2 = make_hypothesis(
            name="H2",
            status="completed",
            target_list=None,
            analysis_result={
                "targets": ["EGFR", "TP53"],
                "evidence_level": "B",
            },
        )
        db = make_mock_db([h1, h2])
        cmp = HypothesisComparator(db)

        result = await cmp.compare([h1.id, h2.id])

        assert result["status"] == "compared"
        assert result["shared_targets"] == ["EGFR"]
        assert result["unique_targets"][str(h1.id)] == ["KRAS"]
        assert result["unique_targets"][str(h2.id)] == ["TP53"]
        # 评分应非零
        assert result["scores"][str(h1.id)] > 0
        assert result["scores"][str(h2.id)] > 0

    @pytest.mark.asyncio
    async def test_compare_with_no_targets_at_all(self):
        """两个假设都没有任何靶点"""
        h1 = make_hypothesis(name="Empty1", status="draft", target_list=None, analysis_result=None)
        h2 = make_hypothesis(name="Empty2", status="draft", target_list=None, analysis_result=None)
        db = make_mock_db([h1, h2])
        cmp = HypothesisComparator(db)

        result = await cmp.compare([h1.id, h2.id])

        assert result["status"] == "compared"
        assert result["shared_targets"] == []
        # 每个假设的 unique_targets 也为空
        assert result["unique_targets"][str(h1.id)] == []
        assert result["unique_targets"][str(h2.id)] == []
        # scores 仍存在（基于 status/evidence_level）
        assert str(h1.id) in result["scores"]
        assert str(h2.id) in result["scores"]
        # hypotheses_summary target_count 应为 0
        summary_by_id = {s["id"]: s for s in result["hypotheses_summary"]}
        assert summary_by_id[str(h1.id)]["target_count"] == 0
        assert summary_by_id[str(h2.id)]["target_count"] == 0
        # 无共享靶点 → 应有"无共享靶点"推荐
        assert any("无共享靶点" in r for r in result["recommendations"])

    @pytest.mark.asyncio
    async def test_compare_calls_db_execute_with_select(self):
        """验证 compare 调用 db.execute 并使用 select 语句"""
        h1 = make_hypothesis(name="H1", target_list=["EGFR"])
        db = make_mock_db([h1])
        cmp = HypothesisComparator(db)

        await cmp.compare([h1.id])

        db.execute.assert_awaited_once()
        # 第一个参数应为 select 语句
        stmt = db.execute.await_args.args[0]
        # 简单验证它是 select 对象（避免直接 import select 做对比）
        assert hasattr(stmt, "where")

    @pytest.mark.asyncio
    async def test_compare_summary_sorted_unique_targets(self):
        """unique_targets 列表应排序后返回"""
        h1 = make_hypothesis(name="H1", target_list=["Z", "A", "M"])
        h2 = make_hypothesis(name="H2", target_list=["Y", "B"])
        db = make_mock_db([h1, h2])
        cmp = HypothesisComparator(db)

        result = await cmp.compare([h1.id, h2.id])

        # 全部独有，应排序
        assert result["unique_targets"][str(h1.id)] == ["A", "M", "Z"]
        assert result["unique_targets"][str(h2.id)] == ["B", "Y"]
        # shared_targets 也应排序（此处为空）
        assert result["shared_targets"] == []

    @pytest.mark.asyncio
    async def test_compare_logging_info_called(self):
        """验证 compare 完成后调用 logger.info"""
        h1 = make_hypothesis(name="H1", target_list=["EGFR"])
        db = make_mock_db([h1])
        cmp = HypothesisComparator(db)

        with patch(
            "app.services.report.hypothesis_comparator.logger"
        ) as mock_logger:
            await cmp.compare([h1.id])
            mock_logger.info.assert_called_once()
            # 验证日志消息包含关键信息
            args = mock_logger.info.call_args.args
            assert "假设比较完成" in args[0]

    @pytest.mark.asyncio
    async def test_compare_empty_logging_warning(self):
        """空 ID 列表时调用 logger.warning"""
        db = MagicMock()
        cmp = HypothesisComparator(db)

        with patch(
            "app.services.report.hypothesis_comparator.logger"
        ) as mock_logger:
            await cmp.compare([])
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_compare_not_found_logging_warning(self):
        """未找到假设时调用 logger.warning"""
        db = make_mock_db([])
        cmp = HypothesisComparator(db)

        with patch(
            "app.services.report.hypothesis_comparator.logger"
        ) as mock_logger:
            await cmp.compare([uuid4()])
            mock_logger.warning.assert_called_once()
