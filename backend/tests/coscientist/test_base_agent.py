"""BaseAgent 基类单元测试"""
import asyncio
import json
import pytest

from app.services.coscientist.agents.base import BaseAgent


class MockLLMClient:
    def __init__(self, responses=None, default_response=None):
        self.responses = responses or []
        self.default_response = default_response or {
            "content": "{}", "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "mock"
        }
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        return self.default_response


class FailingLLMClient:
    async def chat(self, messages, **kwargs):
        raise RuntimeError("LLM 服务不可用")


class TimeoutLLMClient:
    async def chat(self, messages, **kwargs):
        await asyncio.sleep(10)
        return {"content": "", "usage": {}, "model": ""}


class TestBaseAgentQuick:
    @pytest.mark.asyncio
    async def test_adapts_response_format(self):
        client = MockLLMClient([{"content": "ok", "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "m"}])
        agent = BaseAgent(client, agent_name="t")
        r = await agent.quick("p", system="s")
        assert r["content"] == "ok"
        assert r["token_usage"]["prompt"] == 100
        assert r["token_usage"]["total"] == 150
        assert r["model"] == "m"
        assert r["error"] is None

    @pytest.mark.asyncio
    async def test_accumulates_stats(self):
        client = MockLLMClient(default_response={"content": "x", "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "m"})
        agent = BaseAgent(client, agent_name="t")
        await agent.quick("p1")
        await agent.quick("p2")
        assert agent.call_count == 2
        assert agent.total_token_usage["total"] == 300

    @pytest.mark.asyncio
    async def test_handles_failure(self):
        agent = BaseAgent(FailingLLMClient(), agent_name="t")
        r = await agent.quick("p")
        assert r["content"] == ""
        assert r["error"] is not None
        assert agent.error_count == 1

    @pytest.mark.asyncio
    async def test_handles_timeout(self):
        agent = BaseAgent(TimeoutLLMClient(), agent_name="t", timeout=0.1)
        r = await agent.quick("p")
        assert r["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_semaphore(self):
        client = MockLLMClient(default_response={"content": "ok", "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"})
        agent = BaseAgent(client, semaphore=asyncio.Semaphore(1), agent_name="t")
        results = await asyncio.gather(agent.quick("p1"), agent.quick("p2"))
        assert all(r["content"] == "ok" for r in results)


class TestBaseAgentJsonParsing:
    def test_plain_json(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json('{"k": "v"}') == {"k": "v"}

    def test_json_code_block(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json('```json\n{"k": "v"}\n```') == {"k": "v"}

    def test_plain_code_block(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json('```\n{"k": "v"}\n```') == {"k": "v"}

    def test_extra_text(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json('text {"k": "v"} more') == {"k": "v"}

    def test_array(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert len(agent._parse_json('[{"a": 1}, {"b": 2}]')) == 2

    def test_invalid_returns_default(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json("not json", default={"fb": True}) == {"fb": True}

    def test_empty(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        assert agent._parse_json("") == {}


class TestBaseAgentStats:
    def test_get_stats(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        agent.call_count = 5
        agent.error_count = 1
        agent.total_token_usage["total"] = 500
        stats = agent.get_stats()
        assert stats["call_count"] == 5
        assert stats["error_count"] == 1
        assert stats["total_tokens"] == 500

    def test_reset_stats(self):
        agent = BaseAgent(MockLLMClient(), agent_name="t")
        agent.call_count = 5
        agent.reset_stats()
        assert agent.call_count == 0
        assert agent.total_token_usage["total"] == 0