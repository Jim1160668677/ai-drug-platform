"""Evolution + MetaReview Agent 单元测试"""
import json
import pytest

from app.services.coscientist.agents.evolution import EvolutionAgent
from app.services.coscientist.agents.meta_review import MetaReviewAgent
from app.services.coscientist.algorithms.evolution_strategies import EvolutionPlan


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


class TestEvolutionAgent:
    @pytest.mark.asyncio
    async def test_keep_no_llm(self):
        client = MockLLMClient()
        agent = EvolutionAgent(client)
        plan = EvolutionPlan(hypothesis_id="1", strategy="keep")
        r = await agent.run(_hyp(), plan, "目标")
        assert r["strategy"] == "keep"
        assert r["evolved_hypothesis"]["evolution_strategy"] == "keep"
        assert client.call_count == 0
        assert r["cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_enhancement(self):
        client = MockLLMClient([{"content": json.dumps({"name": "增强", "description": "ed", "mechanism": "em", "change_log": "修复", "novelty": 9, "plausibility": 8, "testability": 7, "safety": 8}), "usage": {"prompt_tokens": 100, "completion_tokens": 80}, "model": "m"}])
        agent = EvolutionAgent(client)
        plan = EvolutionPlan("1", "enhancement", flaws=[{"description": "f", "severity": 8}, {"description": "g", "severity": 7}])
        r = await agent.run(_hyp(), plan, "目标")
        assert r["strategy"] == "enhancement"
        assert r["evolved_hypothesis"]["name"] == "增强"
        assert r["evolved_hypothesis"]["novelty_score"] == 9.0
        assert r["evolved_hypothesis"]["parent_ids"] == ["1"]

    @pytest.mark.asyncio
    async def test_combination_without_partner(self):
        agent = EvolutionAgent(MockLLMClient())
        plan = EvolutionPlan("1", "combination", target_hypothesis_id="2")
        r = await agent.run(_hyp(), plan, "目标", partner_hypothesis=None)
        assert r["error"] == "missing_partner"
        assert r["evolved_hypothesis"]["evolution_strategy"] == "combination_failed"

    @pytest.mark.asyncio
    async def test_combination_with_partner(self):
        client = MockLLMClient([{"content": json.dumps({"name": "融合", "description": "fd", "mechanism": "fm", "change_log": "合并"}), "usage": {"prompt_tokens": 120, "completion_tokens": 100}, "model": "m"}])
        agent = EvolutionAgent(client)
        plan = EvolutionPlan("1", "combination", target_hypothesis_id="2", similarity=0.85)
        r = await agent.run(_hyp("1"), plan, "目标", partner_hypothesis=_hyp("2"))
        assert r["strategy"] == "combination"
        assert r["evolved_hypothesis"]["name"] == "融合"
        assert "1" in r["evolved_hypothesis"]["parent_ids"]
        assert "2" in r["evolved_hypothesis"]["parent_ids"]

    @pytest.mark.asyncio
    async def test_simplification(self):
        client = MockLLMClient([{"content": json.dumps({"name": "简化", "description": "sd", "mechanism": "sm", "change_log": "聚焦", "testability": 9}), "usage": {"prompt_tokens": 80, "completion_tokens": 60}, "model": "m"}])
        agent = EvolutionAgent(client)
        plan = EvolutionPlan("1", "simplification", complexity_issues=["描述过长", "可测试性低"])
        r = await agent.run(_hyp(), plan, "目标")
        assert r["strategy"] == "simplification"
        assert r["evolved_hypothesis"]["testability_score"] == 9.0

    @pytest.mark.asyncio
    async def test_unknown_strategy(self):
        agent = EvolutionAgent(MockLLMClient())
        plan = EvolutionPlan("1", "unknown")
        r = await agent.run(_hyp(), plan, "目标")
        assert r["error"] is not None
        assert "unknown_strategy" in r["error"]

    @pytest.mark.asyncio
    async def test_batch(self):
        responses = [{"content": json.dumps({"name": "增强", "description": "d", "mechanism": "m"}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"}]
        client = MockLLMClient(responses)
        agent = EvolutionAgent(client)
        hyps = [_hyp("1"), _hyp("2")]
        plans = [EvolutionPlan("1", "enhancement", flaws=[{"description": "f", "severity": 8}]), EvolutionPlan("2", "keep")]
        results = await agent.run_batch(hyps, plans, "目标")
        assert len(results) == 2
        assert results[0]["strategy"] == "enhancement"
        assert results[1]["strategy"] == "keep"


class TestMetaReviewAgent:
    @pytest.mark.asyncio
    async def test_basic(self):
        client = MockLLMClient([{"content": json.dumps({
            "top_hypotheses": [{"id": "1", "rank": 1, "reason": "最佳"}, {"id": "2", "rank": 2, "reason": "次佳"}],
            "quality_summary": "良好", "diversity_assessment": "充足",
            "evolution_effectiveness": "有效",
            "recommended_experiments": ["实验A", "实验B"],
            "research_gaps": ["盲区1"],
            "final_recommendation": "推荐1",
            "confidence_level": 0.85,
        }), "usage": {"prompt_tokens": 200, "completion_tokens": 150}, "model": "m"}])
        agent = MetaReviewAgent(client)
        ranked = [{"id": "1", "name": "H1", "description": "d1", "elo_score": 1200, "rank": 1}, {"id": "2", "name": "H2", "description": "d2", "elo_score": 1100, "rank": 2}]
        r = await agent.run(ranked, "目标", evolution_summary="摘要")
        assert len(r["top_hypotheses"]) == 2
        assert r["top_hypotheses"][0]["id"] == "1"
        assert r["quality_summary"] == "良好"
        assert len(r["recommended_experiments"]) == 2
        assert r["confidence_level"] == 0.85

    @pytest.mark.asyncio
    async def test_empty_hypotheses(self):
        client = MockLLMClient([{"content": json.dumps({"top_hypotheses": [], "quality_summary": "无", "confidence_level": 0.3}), "usage": {"prompt_tokens": 50, "completion_tokens": 20}, "model": "m"}])
        agent = MetaReviewAgent(client)
        r = await agent.run([], "目标")
        assert r["top_hypotheses"] == []
        assert r["confidence_level"] == 0.3

    @pytest.mark.asyncio
    async def test_llm_failure(self):
        agent = MetaReviewAgent(FailingLLMClient())
        r = await agent.run([], "目标")
        assert r["top_hypotheses"] == []
        assert r["confidence_level"] == 0.5
        assert r["error"] is not None

    @pytest.mark.asyncio
    async def test_confidence_clamped(self):
        client = MockLLMClient([{"content": json.dumps({"confidence_level": 1.5}), "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}])
        agent = MetaReviewAgent(client)
        r = await agent.run([], "目标")
        assert r["confidence_level"] == 1.0