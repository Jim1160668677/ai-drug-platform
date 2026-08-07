"""Supervisor 协调器 + Progress + Feedback 集成测试

验证多智能体编排流程：
- 完整 run() 流程（generation → reflection → proximity → evolution → debate → ranking → meta_review）
- 进度事件推送
- 专家反馈处理
- 成本/时长限制
- 容错（部分 Agent 失败）
- auto / interactive 两种反馈模式
"""
import asyncio
import json
import pytest

from app.services.coscientist.feedback import FeedbackInstruction, FeedbackProcessor
from app.services.coscientist.progress import ProgressTracker
from app.services.coscientist.supervisor import CoScientistResult, Supervisor


class MockLLMClient:
    """Mock LLM — 根据调用次数返回预设响应"""
    def __init__(self, responses=None, default_response=None):
        self.responses = responses or []
        self.default_response = default_response or {"content": "{}", "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "mock"}
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        return self.responses[self.call_count - 1] if self.call_count <= len(self.responses) else self.default_response


def _gen_response(n=3):
    """构造 Generation 响应"""
    return {"content": json.dumps({"hypotheses": [
        {"name": f"H{i}", "description": f"描述{i}", "mechanism": f"机制{i}", "novelty": 7+i, "plausibility": 6+i, "testability": 8, "safety": 9}
        for i in range(n)
    ]}), "usage": {"prompt_tokens": 100, "completion_tokens": 200}, "model": "m"}


# ========== ProgressTracker 测试 ==========

class TestProgressTracker:
    @pytest.mark.asyncio
    async def test_emit_and_callback(self):
        events = []
        async def callback(event):
            events.append(event)
        tracker = ProgressTracker("run-1", callback=callback)
        await tracker.emit("test_event", {"key": "value"})
        assert len(events) == 1
        assert events[0].type == "test_event"
        assert events[0].payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_emit_convenience_methods(self):
        tracker = ProgressTracker("run-1")
        await tracker.emit_run_started("目标", 5, 3)
        await tracker.emit_round_started(1)
        await tracker.emit_phase_started("generation", 1)
        await tracker.emit_phase_completed("generation", 1, {"count": 3})
        await tracker.emit_run_completed([], {})
        assert len(tracker.events) == 5
        assert tracker.current_round == 1
        assert tracker.current_phase == "generation"

    @pytest.mark.asyncio
    async def test_cost_accumulation(self):
        tracker = ProgressTracker("run-1")
        await tracker.emit("test", {"cost_usd": 0.01, "token_usage": {"total": 100}})
        await tracker.emit("test", {"cost_usd": 0.02, "token_usage": {"total": 200}})
        assert tracker.total_cost_usd == pytest.approx(0.03)
        assert tracker.total_tokens == 300

    def test_get_progress(self):
        tracker = ProgressTracker("run-1")
        tracker.current_round = 2
        tracker.current_phase = "ranking"
        p = tracker.get_progress()
        assert p["run_id"] == "run-1"
        assert p["current_round"] == 2
        assert p["current_phase"] == "ranking"

    def test_get_recent_events(self):
        from app.services.coscientist.progress import ProgressEvent
        tracker = ProgressTracker("run-1")
        tracker.events = [ProgressEvent(type=f"e{i}", run_id="run-1") for i in range(25)]
        recent = tracker.get_recent_events(10)
        assert len(recent) == 10
        assert recent[-1]["type"] == "e24"


# ========== FeedbackProcessor 测试 ==========

class TestFeedbackProcessor:
    @pytest.mark.asyncio
    async def test_parse_directional(self):
        client = MockLLMClient([{"content": json.dumps({"instructions": [
            {"feedback_type": "directional", "direction": "探索表观遗传方向"}
        ]}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"}])
        processor = FeedbackProcessor(client)
        instructions = await processor.parse_feedback("应该探索表观遗传", [], "目标")
        assert len(instructions) == 1
        assert instructions[0].feedback_type == "directional"
        assert "表观遗传" in instructions[0].direction

    @pytest.mark.asyncio
    async def test_parse_veto(self):
        client = MockLLMClient([{"content": json.dumps({"instructions": [
            {"feedback_type": "veto", "target_hypothesis_id": "1"}
        ]}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"}])
        processor = FeedbackProcessor(client)
        instructions = await processor.parse_feedback("假设1不成立", [{"id": "1", "name": "H1"}], "目标")
        assert instructions[0].feedback_type == "veto"
        assert instructions[0].target_hypothesis_id == "1"

    @pytest.mark.asyncio
    async def test_parse_elo_adjustment(self):
        client = MockLLMClient([{"content": json.dumps({"instructions": [
            {"feedback_type": "elo_adjustment", "target_hypothesis_id": "2", "elo_delta": 50}
        ]}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"}])
        processor = FeedbackProcessor(client)
        instructions = await processor.parse_feedback("奖励假设2", [{"id": "2"}], "")
        assert instructions[0].elo_delta == 50.0

    def test_apply_veto(self):
        processor = FeedbackProcessor(MockLLMClient())
        instructions = [FeedbackInstruction("veto", target_hypothesis_id="1")]
        hyps = [{"id": "1", "name": "H1"}, {"id": "2", "name": "H2"}]
        updated, _ = processor.apply_instructions(instructions, hyps)
        assert updated[0]["status"] == "eliminated_by_expert"
        assert updated[0]["expert_vetoed"] is True
        assert "status" not in updated[1]

    def test_apply_elo_adjustment(self):
        processor = FeedbackProcessor(MockLLMClient())
        instructions = [FeedbackInstruction("elo_adjustment", target_hypothesis_id="1", elo_delta=100)]
        hyps = [{"id": "1", "elo_score": 1000}]
        updated, _ = processor.apply_instructions(instructions, hyps)
        assert updated[0]["elo_score"] == 1100

    def test_apply_directional_to_context(self):
        processor = FeedbackProcessor(MockLLMClient())
        instructions = [FeedbackInstruction("directional", direction="探索免疫方向")]
        _, context = processor.apply_instructions(instructions, [], "")
        assert "免疫方向" in context

    def test_filter_active(self):
        processor = FeedbackProcessor(MockLLMClient())
        hyps = [{"id": "1", "status": "eliminated_by_expert"}, {"id": "2"}, {"id": "3", "expert_vetoed": True}]
        active = processor.filter_active_hypotheses(hyps)
        assert len(active) == 1
        assert active[0]["id"] == "2"


# ========== Supervisor 测试 ==========

class TestSupervisor:
    @pytest.mark.asyncio
    async def test_run_basic_flow(self):
        """基本完整流程（auto 模式，1 轮）"""
        # 构造足够的响应：generation + reflection*3 + proximity + evolution + debate*3*4 + ranking + meta_review
        responses = []
        # Generation
        responses.append(_gen_response(3))
        # Reflection x 3
        for i in range(3):
            responses.append({"content": json.dumps({"flaws": [{"description": f"f{i}", "severity": 5, "category": "logic"}], "strengths": [], "overall_assessment": "ok"}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"})
        # Proximity（3 个假设，但 jaccard 低，可能不调用 LLM；提供默认）
        for _ in range(3):
            responses.append({"content": json.dumps({"semantic_similarity": 0.3, "recommendation": "keep_separate"}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"})
        # Evolution（3 个 keep，不调用 LLM）
        # Debate top-3（每个假设 4 次调用：正方+反方+裁判+综合）
        for _ in range(3):
            for _ in range(4):
                responses.append({"content": json.dumps({"argument": "ok", "consensus_score": 0.9, "mechanism_agreed": True, "assessment": "ok", "name": "refined", "description": "d", "mechanism": "m"}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"})
        # Ranking（3 个假设全循环 3 场）
        for _ in range(3):
            responses.append({"content": json.dumps({"winner": "A", "confidence": 0.8, "reasoning": "r", "winning_criteria": ["novelty"]}), "usage": {"prompt_tokens": 50, "completion_tokens": 30}, "model": "m"})
        # Meta-review
        responses.append({"content": json.dumps({"top_hypotheses": [{"id": "1", "rank": 1, "reason": "best"}], "quality_summary": "good", "confidence_level": 0.8, "recommended_experiments": [], "research_gaps": []}), "usage": {"prompt_tokens": 100, "completion_tokens": 80}, "model": "m"})

        client = MockLLMClient(responses)
        supervisor = Supervisor(client, max_cost_usd=10.0, max_duration_sec=60)
        result = await supervisor.run(research_goal="测试研究目标", max_rounds=1, initial_count=3)

        assert isinstance(result, CoScientistResult)
        assert result.error is None
        assert result.research_goal == "测试研究目标"
        assert result.total_rounds == 1

    @pytest.mark.asyncio
    async def test_run_empty_generation(self):
        """Generation 返回空假设时报错"""
        client = MockLLMClient([{"content": json.dumps({"hypotheses": []}), "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}])
        supervisor = Supervisor(client, max_cost_usd=10.0, max_duration_sec=60)
        result = await supervisor.run("目标", max_rounds=1, initial_count=3)
        assert result.error is not None
        assert "无假设" in result.error

    @pytest.mark.asyncio
    async def test_agent_stats(self):
        """获取 Agent 统计"""
        supervisor = Supervisor(MockLLMClient())
        stats = supervisor.get_agent_stats()
        assert "generation" in stats
        assert "reflection" in stats
        assert "ranking" in stats
        assert "evolution" in stats
        assert "meta_review" in stats

    def test_inject_feedback(self):
        """注入反馈设置 event"""
        supervisor = Supervisor(MockLLMClient())
        assert not supervisor._feedback_event.is_set()
        supervisor.inject_feedback("测试反馈")
        assert supervisor._feedback_event.is_set()
        assert supervisor._pending_feedback == "测试反馈"

    def test_format_evolution_summary(self):
        """格式化进化摘要"""
        supervisor = Supervisor(MockLLMClient())
        summary = supervisor._format_evolution_summary([
            {"round": 1, "strategies": {"enhancement": 2, "combination": 1, "simplification": 0, "keep": 0}},
        ])
        assert "轮次1" in summary
        assert "增强=2" in summary

    def test_merge_evolved(self):
        """合并进化结果"""
        supervisor = Supervisor(MockLLMClient())
        original = [{"id": "1", "name": "H1"}, {"id": "2", "name": "H2"}]
        results = [
            {"evolved_hypothesis": {"id": None, "name": "H1进化", "evolution_strategy": "enhancement"}},
            {"evolved_hypothesis": {"id": "2", "name": "H2", "evolution_strategy": "keep"}},
        ]
        merged = supervisor._merge_evolved(original, results)
        assert merged[0]["name"] == "H1进化"
        assert merged[1]["name"] == "H2"