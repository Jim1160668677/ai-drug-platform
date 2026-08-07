"""ReasoningChannel + MockLLMClient 修复验证测试

复现 agent 功能无法正常使用的三个根因：
1. run_id 始终为 "pending"（reasoning.py 未生成唯一 ID）
2. supervisor 失败时 error 字段被丢弃（前端看不到失败原因）
3. MockLLMClient 返回纯文本而非 JSON（generation 解析失败 → 空假设 → 推理中断）

修复目标：
1. reason() 生成唯一 run_id
2. reason() 返回结果包含 error 字段
3. MockLLMClient 检测 system prompt JSON 要求并返回合规 JSON
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.intelligence.channels.reasoning import ReasoningChannel


def _make_mock_stores():
    """构造 mock context_store 和 trace_store（隔离 DB 依赖）"""
    context_store = MagicMock()
    context_store.save_research_goal = AsyncMock()
    context_store.save_snapshot = AsyncMock()
    context_store.get_last_snapshot = AsyncMock(return_value=None)  # 无历史快照

    trace_store = MagicMock()
    # create_trace_callback 是同步方法，返回一个 async callback
    trace_store.create_trace_callback = MagicMock(return_value=AsyncMock())

    return context_store, trace_store


def _make_empty_response_llm():
    """构造返回空内容的 LLM client（模拟 generation 失败场景）"""
    llm_client = AsyncMock()
    llm_client.chat = AsyncMock(return_value={
        "content": "",  # 空内容 → _parse_json 返回 {} → 空假设 → supervisor 报错
        "usage": {"prompt_tokens": 10, "completion_tokens": 0},
        "model": "mock",
    })
    return llm_client


# ========== RED: run_id 不应为 "pending" ==========

class TestReasoningChannelRunId:
    """验证 reason() 生成唯一 run_id 而非 'pending'"""

    @pytest.mark.asyncio
    async def test_run_id_is_not_pending(self):
        context_store, trace_store = _make_mock_stores()
        channel = ReasoningChannel(_make_empty_response_llm(), context_store, trace_store)

        result = await channel.reason(
            session_id=uuid.uuid4(),
            research_goal="发现某疾病的新靶点",
            user=MagicMock(id=uuid.uuid4()),
        )

        assert result["run_id"] != "pending", "run_id 不应为 'pending'"
        # 应为有效 UUID 格式
        uuid.UUID(result["run_id"])

    @pytest.mark.asyncio
    async def test_run_id_is_unique_across_calls(self):
        """两次调用应生成不同的 run_id"""
        context_store, trace_store = _make_mock_stores()
        channel = ReasoningChannel(_make_empty_response_llm(), context_store, trace_store)

        r1 = await channel.reason(
            session_id=uuid.uuid4(), research_goal="目标1", user=MagicMock(id=uuid.uuid4()),
        )
        r2 = await channel.reason(
            session_id=uuid.uuid4(), research_goal="目标2", user=MagicMock(id=uuid.uuid4()),
        )

        assert r1["run_id"] != r2["run_id"], "两次调用应生成不同 run_id"


# ========== RED: supervisor 失败时应传递 error 字段 ==========

class TestReasoningChannelErrorPropagation:
    """验证 supervisor 失败时 error 字段被传递到返回结果"""

    @pytest.mark.asyncio
    async def test_error_field_present_on_failure(self):
        context_store, trace_store = _make_mock_stores()
        channel = ReasoningChannel(_make_empty_response_llm(), context_store, trace_store)

        result = await channel.reason(
            session_id=uuid.uuid4(),
            research_goal="发现某疾病的新靶点",
            user=MagicMock(id=uuid.uuid4()),
        )

        assert "error" in result, "失败时应包含 error 字段"
        assert result["error"], "error 字段不应为空"
        assert result["final_rankings"] == []
        assert result["total_rounds"] == 0

    @pytest.mark.asyncio
    async def test_error_message_contains_failure_reason(self):
        """error 消息应包含具体失败原因（如 '无假设产出'）"""
        context_store, trace_store = _make_mock_stores()
        channel = ReasoningChannel(_make_empty_response_llm(), context_store, trace_store)

        result = await channel.reason(
            session_id=uuid.uuid4(),
            research_goal="发现某疾病的新靶点",
            user=MagicMock(id=uuid.uuid4()),
        )

        # error 应包含失败原因关键词
        assert "假设" in result["error"] or "generation" in result["error"].lower(), \
            f"error 应包含失败原因，实际: {result.get('error')}"


# ========== RED: MockLLMClient 应为 Co-Scientist agent 返回 JSON ==========

class TestMockLLMClientCoscientistJSON:
    """验证 MockLLMClient 检测 system prompt JSON 要求并返回合规 JSON"""

    @pytest.mark.asyncio
    async def test_mock_llm_returns_json_for_generation(self):
        from app.clients.mock.llm_mock import MockLLMClient
        from app.services.coscientist.agents.prompts import GENERATION_SYSTEM, GENERATION_USER

        client = MockLLMClient()
        prompt = GENERATION_USER.format(
            research_goal="发现某疾病的新靶点",
            existing_hypotheses="（无）",
            evidence="（无具体证据）",
            count=3,
        )
        result = await client.chat([
            {"role": "system", "content": GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ])

        parsed = json.loads(result["content"])
        assert "hypotheses" in parsed
        assert len(parsed["hypotheses"]) > 0
        for h in parsed["hypotheses"]:
            assert "name" in h
            assert "description" in h

    @pytest.mark.asyncio
    async def test_mock_llm_returns_json_for_reflection(self):
        from app.clients.mock.llm_mock import MockLLMClient
        from app.services.coscientist.agents.prompts import REFLECTION_SYSTEM, REFLECTION_USER

        client = MockLLMClient()
        prompt = REFLECTION_USER.format(
            research_goal="发现某疾病的新靶点",
            name="测试假设",
            description="假设描述",
            mechanism="机制说明",
            evidence="相关证据",
        )
        result = await client.chat([
            {"role": "system", "content": REFLECTION_SYSTEM},
            {"role": "user", "content": prompt},
        ])

        parsed = json.loads(result["content"])
        assert "flaws" in parsed or "overall_assessment" in parsed

    @pytest.mark.asyncio
    async def test_mock_llm_preserves_qa_behavior_without_system_json(self):
        """无 JSON 要求的 system prompt 时应保持原有 QA 行为"""
        from app.clients.mock.llm_mock import MockLLMClient

        client = MockLLMClient()
        result = await client.chat([
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "EGFR 是什么？"},
        ])

        # 应返回 EGFR 相关的 Markdown 文本（非 JSON）
        assert "EGFR" in result["content"]
        # 不应能解析为 JSON（保持原有 QA 行为）
        try:
            json.loads(result["content"])
            # 如果能解析为 JSON，说明误判了
            assert False, "无 JSON 要求时不应返回 JSON"
        except (json.JSONDecodeError, ValueError):
            pass  # 预期行为


# ========== GREEN 验证: Mock 模式下完整推理流程应成功 ==========

class TestReasoningChannelEndToEndWithMockLLM:
    """修复后验证：Mock 模式下 reasoning channel 能完成推理流程"""

    @pytest.mark.asyncio
    async def test_mock_mode_reasoning_completes_with_rankings(self):
        """Mock 模式下 reason() 应返回非空 final_rankings"""
        from app.clients.mock.llm_mock import MockLLMClient

        context_store, trace_store = _make_mock_stores()
        channel = ReasoningChannel(MockLLMClient(), context_store, trace_store)

        result = await channel.reason(
            session_id=uuid.uuid4(),
            research_goal="发现 EGFR 突变非小细胞肺癌的新治疗靶点",
            user=MagicMock(id=uuid.uuid4()),
            max_rounds=1,
            initial_count=3,
        )

        assert result["run_id"] != "pending"
        assert result.get("error") is None or not result.get("error"), \
            f"Mock 模式不应失败: {result.get('error')}"
        assert len(result["final_rankings"]) > 0, "应返回非空 final_rankings"
        assert result["total_rounds"] >= 1
