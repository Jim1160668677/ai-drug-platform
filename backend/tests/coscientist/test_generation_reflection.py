"""Generation + Reflection Agent 单元测试"""
import json
import pytest

from app.services.coscientist.agents.generation import GenerationAgent
from app.services.coscientist.agents.reflection import ReflectionAgent


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


class TestGenerationAgent:
    @pytest.mark.asyncio
    async def test_generate(self):
        client = MockLLMClient([{"content": json.dumps({"hypotheses": [
            {"name": "H1", "description": "d1", "mechanism": "m1", "novelty": 8, "plausibility": 7, "testability": 9, "safety": 8, "key_evidence": ["e1"]},
            {"name": "H2", "description": "d2", "mechanism": "m2", "novelty": 9},
        ]}), "usage": {"prompt_tokens": 100, "completion_tokens": 200}, "model": "m"}])
        agent = GenerationAgent(client)
        r = await agent.run(research_goal="癌症", count=2)
        assert len(r["hypotheses"]) == 2
        assert r["hypotheses"][0]["name"] == "H1"
        assert r["hypotheses"][0]["novelty_score"] == 8.0
        assert r["hypotheses"][0]["evolution_strategy"] == "initial"
        assert r["hypotheses"][1]["key_evidence"] == []

    @pytest.mark.asyncio
    async def test_generate_with_existing(self):
        client = MockLLMClient([{"content": json.dumps({"hypotheses": [{"name": "新", "description": "d", "mechanism": "m"}]}), "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "m"}])
        agent = GenerationAgent(client)
        r = await agent.run("目标", count=1, existing_hypotheses=[{"name": "已有", "description": "d"}])
        assert len(r["hypotheses"]) == 1
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_empty_response(self):
        client = MockLLMClient([{"content": "not json", "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}])
        agent = GenerationAgent(client)
        r = await agent.run("目标", count=3)
        assert r["hypotheses"] == []

    @pytest.mark.asyncio
    async def test_generate_llm_failure(self):
        agent = GenerationAgent(FailingLLMClient())
        r = await agent.run("目标", count=3)
        assert r["hypotheses"] == []
        assert r["error"] is not None


class TestReflectionAgent:
    @pytest.mark.asyncio
    async def test_reflect_single(self):
        client = MockLLMClient([{"content": json.dumps({
            "flaws": [
                {"description": "逻辑漏洞", "severity": 8, "category": "logic", "suggestion": "修复"},
                {"description": "证据不足", "severity": 5, "category": "evidence"},
            ],
            "strengths": ["机制合理"],
            "overall_assessment": "可行",
            "improvement_priority": ["修复逻辑"],
        }), "usage": {"prompt_tokens": 100, "completion_tokens": 80}, "model": "m"}])
        agent = ReflectionAgent(client)
        r = await agent.run(_hyp(), "目标")
        assert r["hypothesis_id"] == "1"
        assert len(r["flaws"]) == 2
        assert r["flaws"][0]["severity"] == 8
        assert r["strengths"] == ["机制合理"]

    @pytest.mark.asyncio
    async def test_severity_clamped(self):
        client = MockLLMClient([{"content": json.dumps({"flaws": [
            {"description": "A", "severity": 15, "category": "logic"},
            {"description": "B", "severity": -2, "category": "safety"},
        ]}), "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}])
        agent = ReflectionAgent(client)
        r = await agent.run(_hyp(), "目标")
        assert r["flaws"][0]["severity"] == 10
        assert r["flaws"][1]["severity"] == 1

    @pytest.mark.asyncio
    async def test_batch(self):
        responses = [{"content": json.dumps({"flaws": [{"description": f"f{i}", "severity": 7, "category": "logic"}], "strengths": [], "overall_assessment": f"a{i}"}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"} for i in range(3)]
        agent = ReflectionAgent(MockLLMClient(responses))
        results = await agent.run_batch([_hyp(str(i)) for i in range(3)], "目标")
        assert len(results) == 3
        assert all(r["flaws"][0]["severity"] == 7 for r in results)

    @pytest.mark.asyncio
    async def test_batch_with_failure(self):
        agent = ReflectionAgent(FailingLLMClient())
        results = await agent.run_batch([_hyp(str(i)) for i in range(3)], "目标")
        assert len(results) == 3
        assert all("error" in r for r in results)