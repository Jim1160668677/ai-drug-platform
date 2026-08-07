"""Ranking + Proximity Agent 单元测试"""
import json
import pytest

from app.services.coscientist.agents.ranking import RankingAgent
from app.services.coscientist.agents.proximity import ProximityAgent


class MockLLMClient:
    def __init__(self, responses=None, default_response=None):
        self.responses = responses or []
        self.default_response = default_response or {"content": "{}", "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"}
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        return self.responses[self.call_count - 1] if self.call_count <= len(self.responses) else self.default_response


class FailingLLMClient:
    async def chat(self, messages, **kwargs):
        raise RuntimeError("LLM 不可用")


def _hyp(hid="1", name="测试", desc="描述", mech="机制"):
    return {"id": hid, "name": name, "description": desc, "mechanism": mech}


class TestRankingAgent:
    @pytest.mark.asyncio
    async def test_winner_a(self):
        client = MockLLMClient([{"content": json.dumps({"winner": "A", "confidence": 0.9, "reasoning": "A更好", "winning_criteria": ["novelty"]}), "usage": {"prompt_tokens": 80, "completion_tokens": 40}, "model": "m"}])
        agent = RankingAgent(client)
        r = await agent.compare_pair(_hyp("1"), _hyp("2"), "目标")
        assert r.winner == "A"
        assert r.confidence == 0.9
        assert r.hypothesis_a_id == "1"
        assert "novelty" in r.winning_criteria

    @pytest.mark.asyncio
    async def test_winner_b(self):
        client = MockLLMClient([{"content": json.dumps({"winner": "B", "confidence": 0.7}), "usage": {"prompt_tokens": 80, "completion_tokens": 40}, "model": "m"}])
        agent = RankingAgent(client)
        r = await agent.compare_pair(_hyp("1"), _hyp("2"))
        assert r.winner == "B"

    @pytest.mark.asyncio
    async def test_tie(self):
        client = MockLLMClient([{"content": json.dumps({"winner": "tie", "confidence": 0.5}), "usage": {"prompt_tokens": 80, "completion_tokens": 40}, "model": "m"}])
        agent = RankingAgent(client)
        r = await agent.compare_pair(_hyp("1"), _hyp("2"))
        assert r.winner == "tie"

    @pytest.mark.asyncio
    async def test_invalid_winner_defaults_tie(self):
        client = MockLLMClient([{"content": json.dumps({"winner": "X", "confidence": 0.5}), "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}])
        agent = RankingAgent(client)
        r = await agent.compare_pair(_hyp("1"), _hyp("2"))
        assert r.winner == "tie"

    @pytest.mark.asyncio
    async def test_llm_failure(self):
        agent = RankingAgent(FailingLLMClient())
        r = await agent.compare_pair(_hyp("1"), _hyp("2"))
        assert r.winner == "tie"
        assert r.confidence == 0.5

    @pytest.mark.asyncio
    async def test_score_batch(self):
        responses = [
            {"content": json.dumps({"quality": 0.8, "novelty": 0.9}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"},
            {"content": json.dumps({"quality": 0.6, "novelty": 0.7}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"},
        ]
        agent = RankingAgent(MockLLMClient(responses))
        scores = await agent.score_batch([_hyp("1"), _hyp("2")], "目标")
        assert scores["1"]["quality"] == 0.8
        assert scores["2"]["quality"] == 0.6


class TestProximityAgent:
    @pytest.mark.asyncio
    async def test_with_llm(self):
        client = MockLLMClient([{"content": json.dumps({"semantic_similarity": 0.85, "mechanism_overlap": 0.9, "recommendation": "merge", "shared_concepts": ["靶点A"], "unique_to_a": ["x"], "unique_to_b": ["y"]}), "usage": {"prompt_tokens": 60, "completion_tokens": 40}, "model": "m"}])
        agent = ProximityAgent(client, jaccard_threshold=0.0)
        r = await agent.run([_hyp("1"), _hyp("2")], "目标", use_llm=True)
        assert len(r["pairs"]) == 1
        assert r["pairs"][0]["semantic_similarity"] == 0.85
        assert r["pairs"][0]["recommendation"] == "merge"
        assert r["pairs"][0]["method"] == "llm"
        assert r["llm_calls"] == 1

    @pytest.mark.asyncio
    async def test_jaccard_only(self):
        agent = ProximityAgent(MockLLMClient(), jaccard_threshold=0.7)
        hyps = [
            {"id": "1", "name": "EGFR 抑制剂", "description": "抑制 EGFR", "mechanism": "阻断 EGFR 信号"},
            {"id": "2", "name": "完全不同", "description": "无关描述", "mechanism": "无关机制"},
        ]
        r = await agent.run(hyps, "目标", use_llm=False)
        assert len(r["pairs"]) == 1
        assert r["pairs"][0]["method"] == "jaccard_only"
        assert r["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_single_hypothesis(self):
        agent = ProximityAgent(MockLLMClient())
        r = await agent.run([_hyp()])
        assert r["pairs"] == []
        assert r["total_pairs"] == 0

    @pytest.mark.asyncio
    async def test_empty(self):
        agent = ProximityAgent(MockLLMClient())
        r = await agent.run([])
        assert r["pairs"] == []

    def test_jaccard_identical(self):
        agent = ProximityAgent(MockLLMClient())
        hyp = {"name": "相同", "description": "描述", "mechanism": "机制"}
        assert agent._jaccard_similarity(hyp, hyp) > 0.5

    def test_jaccard_different(self):
        agent = ProximityAgent(MockLLMClient())
        assert agent._jaccard_similarity({"name": "aaa", "description": "aaa", "mechanism": "aaa"}, {"name": "zzz", "description": "zzz", "mechanism": "zzz"}) < 0.3

    def test_jaccard_empty(self):
        agent = ProximityAgent(MockLLMClient())
        assert agent._jaccard_similarity({}, {}) == 0.0