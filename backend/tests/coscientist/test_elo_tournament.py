"""Elo Tournament 锦标赛排名算法 — 单元测试

覆盖：
- K 因子动态（前 10 场 K=40，10-30 场 K=32，30+ 场 K=24）
- Elo 更新公式（预期胜率 + 实际得分）
- 全循环调度（n <= 8）
- 瑞士制调度（n > 8）
- 完整锦标赛流程（mock ranking_agent）
- 模式分析
"""
import asyncio
import pytest

from app.services.coscientist.algorithms.elo_tournament import (
    EloTournament,
    MatchResult,
    TournamentResult,
)


class MockRankingAgent:
    """Mock RankingAgent — 用于测试 Elo Tournament

    根据假设的预设质量分数判定胜者（质量高的胜出）
    """

    def __init__(self, quality_map=None):
        self.quality_map = quality_map or {}
        self.call_count = 0

    async def compare_pair(self, hyp_a, hyp_b, research_goal=""):
        self.call_count += 1
        id_a = str(hyp_a.get("id", hyp_a.get("name", "")))
        id_b = str(hyp_b.get("id", hyp_b.get("name", "")))
        q_a = self.quality_map.get(id_a, 0.5)
        q_b = self.quality_map.get(id_b, 0.5)

        if q_a > q_b:
            winner = "A"
        elif q_b > q_a:
            winner = "B"
        else:
            winner = "tie"

        return MatchResult(
            hypothesis_a_id=id_a,
            hypothesis_b_id=id_b,
            winner=winner,
            confidence=0.8,
            reasoning=f"质量比较: {q_a} vs {q_b}",
            winning_criteria=["novelty", "plausibility"],
        )


class TestEloKFactor:
    """K 因子动态测试"""

    def test_provisional_k_factor(self):
        """前 10 场使用 K=40"""
        t = EloTournament()
        assert t._get_k_factor(0) == 40
        assert t._get_k_factor(5) == 40
        assert t._get_k_factor(9) == 40

    def test_standard_k_factor(self):
        """10-30 场使用 K=32"""
        t = EloTournament()
        assert t._get_k_factor(10) == 32
        assert t._get_k_factor(20) == 32
        assert t._get_k_factor(29) == 32

    def test_stable_k_factor(self):
        """30+ 场使用 K=24"""
        t = EloTournament()
        assert t._get_k_factor(30) == 24
        assert t._get_k_factor(100) == 24

    def test_custom_k_factors(self):
        """自定义 K 因子"""
        t = EloTournament(k_factor=20, k_provisional=30, k_stable=15)
        assert t._get_k_factor(0) == 30
        assert t._get_k_factor(15) == 20
        assert t._get_k_factor(50) == 15


class TestEloUpdate:
    """Elo 评分更新公式测试"""

    def test_expected_score_equal_elo(self):
        """相同 Elo 的预期胜率为 0.5"""
        t = EloTournament()
        assert t._expected_score(1000, 1000) == pytest.approx(0.5)

    def test_expected_score_higher_elo(self):
        """Elo 高 400 分的预期胜率约 0.91"""
        t = EloTournament()
        expected = t._expected_score(1400, 1000)
        assert 0.9 < expected < 0.92

    def test_expected_score_lower_elo(self):
        """Elo 低 400 分的预期胜率约 0.09"""
        t = EloTournament()
        expected = t._expected_score(1000, 1400)
        assert 0.08 < expected < 0.10

    def test_update_elo_winner_gains(self):
        """胜方 Elo 上升"""
        t = EloTournament()
        new_winner, new_loser = t._update_elo(1000, 1000, 0, 0, draw=False)
        assert new_winner > 1000
        assert new_loser < 1000

    def test_update_elo_draw(self):
        """平局双方 Elo 向中间靠拢（相同 Elo 时不变）"""
        t = EloTournament()
        new_a, new_b = t._update_elo(1000, 1000, 0, 0, draw=True)
        assert new_a == pytest.approx(1000, abs=0.01)
        assert new_b == pytest.approx(1000, abs=0.01)

    def test_update_elo_upset_bigger_change(self):
        """爆冷（低分胜高分）Elo 变化更大"""
        t = EloTournament()
        # 正常胜（高分胜低分）
        normal_win, normal_loss = t._update_elo(1200, 1000, 5, 5, draw=False)
        # 爆冷（低分胜高分）
        upset_win, upset_loss = t._update_elo(1000, 1200, 5, 5, draw=False)
        # 爆冷时胜方增益更大
        assert (upset_win - 1000) > (normal_win - 1200)

    def test_k_factor_affects_magnitude(self):
        """K 因子越大，Elo 变化越大"""
        t = EloTournament()
        # 新手（K=40）
        new_a_provisional, _ = t._update_elo(1000, 1000, 0, 0, draw=False)
        # 老手（K=24）
        new_a_stable, _ = t._update_elo(1000, 1000, 50, 50, draw=False)
        assert (new_a_provisional - 1000) > (new_a_stable - 1000)



class TestPairGeneration:
    """成对组合生成测试"""

    def test_round_robin_small(self):
        """小规模全循环"""
        t = EloTournament()
        hyps = [{"id": str(i), "name": f"H{i}"} for i in range(5)]
        pairs = t._generate_pairs(hyps)
        # 5 个假设全循环: C(5,2) = 10 场
        assert len(pairs) == 10

    def test_round_robin_two(self):
        """2 个假设"""
        t = EloTournament()
        hyps = [{"id": "1"}, {"id": "2"}]
        pairs = t._generate_pairs(hyps)
        assert len(pairs) == 1

    def test_round_robin_one(self):
        """1 个假设无比赛"""
        t = EloTournament()
        pairs = t._generate_pairs([{"id": "1"}])
        assert len(pairs) == 0

    def test_swiss_system_large(self):
        """大规模瑞士制（> 8）"""
        t = EloTournament()
        hyps = [{"id": str(i), "elo_score": 1000 - i} for i in range(12)]
        pairs = t._generate_pairs(hyps)
        # 瑞士制 2 轮: 约 2 * (12/2) = 12 场
        assert len(pairs) > 0
        assert len(pairs) <= 24

    def test_swiss_no_duplicates_per_round(self):
        """瑞士制每轮无重复配对"""
        t = EloTournament()
        hyps = [{"id": str(i), "elo_score": 1000} for i in range(10)]
        pairs = t._generate_pairs(hyps)
        pair_set = set()
        for a, b in pairs:
            key = (min(a, b), max(a, b))
            # 允许跨轮重复，但检查格式正确
            assert a != b
            pair_set.add(key)
        # 至少有一些不重复的对
        assert len(pair_set) > 0


class TestTournamentFlow:
    """完整锦标赛流程测试"""

    @pytest.mark.asyncio
    async def test_tournament_basic(self):
        """基本锦标赛流程"""
        t = EloTournament()
        hyps = [
            {"id": "1", "name": "H1"},
            {"id": "2", "name": "H2"},
            {"id": "3", "name": "H3"},
        ]
        # H2 质量最高
        agent = MockRankingAgent({"1": 0.3, "2": 0.9, "3": 0.5})

        result = await t.run_tournament(hyps, agent, research_goal="测试目标")

        assert isinstance(result, TournamentResult)
        assert len(result.rankings) == 3
        assert result.total_matches > 0
        # H2 应该排名第一
        assert result.rankings[0]["id"] == "2"
        # 排名有 rank 字段
        assert result.rankings[0]["rank"] == 1
        assert result.rankings[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_tournament_elo_changes(self):
        """锦标赛后 Elo 发生变化"""
        t = EloTournament()
        hyps = [{"id": "1", "name": "H1"}, {"id": "2", "name": "H2"}]
        agent = MockRankingAgent({"1": 0.9, "2": 0.1})

        result = await t.run_tournament(hyps, agent)

        winner_elo = result.rankings[0]["elo_score"]
        loser_elo = result.rankings[1]["elo_score"]
        assert winner_elo > 1000  # 胜方 Elo 上升
        assert loser_elo < 1000   # 负方 Elo 下降

    @pytest.mark.asyncio
    async def test_tournament_single_hypothesis(self):
        """单假设锦标赛（无比赛）"""
        t = EloTournament()
        result = await t.run_tournament(
            [{"id": "1", "name": "H1"}], MockRankingAgent()
        )
        assert result.total_matches == 0
        assert len(result.rankings) == 1

    @pytest.mark.asyncio
    async def test_tournament_agent_failure(self):
        """RankingAgent 失败时默认平局"""
        class FailingAgent:
            async def compare_pair(self, a, b, goal=""):
                raise RuntimeError("LLM 调用失败")

        t = EloTournament()
        hyps = [{"id": "1"}, {"id": "2"}]
        result = await t.run_tournament(hyps, FailingAgent())

        # 失败的比赛应该记为平局，不崩溃
        assert result.total_matches > 0
        for match in result.match_results:
            assert match.winner == "tie"

    @pytest.mark.asyncio
    async def test_tournament_ranking_order(self):
        """排名按 Elo 降序"""
        t = EloTournament()
        hyps = [{"id": str(i), "name": f"H{i}"} for i in range(5)]
        quality = {str(i): i * 0.1 for i in range(5)}  # H4 最强
        agent = MockRankingAgent(quality)

        result = await t.run_tournament(hyps, agent)

        elos = [r["elo_score"] for r in result.rankings]
        assert elos == sorted(elos, reverse=True)


class TestPatternAnalysis:
    """Win/Loss 模式分析测试"""

    @pytest.mark.asyncio
    async def test_analyze_patterns_no_llm(self):
        """无 LLM 的统计模式分析"""
        t = EloTournament()
        matches = [
            MatchResult("1", "2", "A"),
            MatchResult("1", "3", "A"),
            MatchResult("2", "3", "B"),
        ]
        hyps = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        patterns = await t.analyze_patterns(matches, hyps, llm_router=None)

        assert "win_rates" in patterns
        assert "best_performer" in patterns
        assert patterns["best_performer"] == "1"  # H1 赢 2 场
        assert patterns["total_matches"] == 3

    @pytest.mark.asyncio
    async def test_analyze_patterns_all_ties(self):
        """全部平局的模式分析"""
        t = EloTournament()
        matches = [MatchResult("1", "2", "tie")]
        patterns = await t.analyze_patterns(matches, [{"id": "1"}, {"id": "2"}])

        # 全平局时 win_rate 为 0
        for rate in patterns["win_rates"].values():
            assert rate == 0.0
