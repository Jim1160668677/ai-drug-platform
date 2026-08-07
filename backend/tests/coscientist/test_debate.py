"""Scientific Debate 科学辩论机制 — 单元测试

覆盖：
- 三角色 LLM 调用（正方/反方/裁判）
- 辩论回合管理（max_rounds 控制）
- 收敛条件（consensus_score >= 阈值 或 mechanism_agreed）
- 假设修正合成（综合辩论结果产出 refined_hypothesis）
- LLM 响应解析（JSON 容错 + 代码块提取）
- 异常处理（LLM 调用失败不崩溃）
- Token/cost 累计
- 信号量并发控制
"""
import asyncio
import json
import pytest

from app.services.coscientist.algorithms.debate import (
    DebateResult,
    DebateTurn,
    ScientificDebate,
)


class MockLLMRouter:
    """Mock LLM Router — 按预设序列返回响应"""

    def __init__(self, responses=None, default_response=None):
        # responses: list of dict，按调用顺序返回
        self.responses = responses or []
        self.default_response = default_response or {"content": "{}", "token_usage": {"total": 10}, "cost_usd": 0.001}
        self.call_count = 0
        self.calls = []  # 记录所有调用

    async def quick(self, prompt, system=None):
        self.call_count += 1
        self.calls.append({"prompt": prompt, "system": system})

        if self.call_count <= len(self.responses):
            resp = self.responses[self.call_count - 1]
        else:
            resp = self.default_response

        # 支持 str 或 dict
        if isinstance(resp, str):
            return {"content": resp, "token_usage": {"total": 10}, "cost_usd": 0.001}
        return resp


class FailingLLMRouter:
    """总是失败的 LLM Router"""

    async def quick(self, prompt, system=None):
        raise RuntimeError("LLM 服务不可用")


def _make_hypothesis(hid="1", name="测试假设", description="假设描述", mechanism="机制"):
    return {"id": hid, "name": name, "description": description, "mechanism": mechanism}


class TestDebateDataclasses:
    """数据类测试"""

    def test_debate_turn_defaults(self):
        turn = DebateTurn(
            round_num=1,
            proponent_argument="正方",
            opponent_argument="反方",
            judge_assessment="裁判",
            consensus_score=0.5,
            mechanism_agreed=False,
        )
        assert turn.round_num == 1
        assert turn.proponent_argument == "正方"
        assert turn.consensus_score == 0.5
        assert turn.mechanism_agreed is False

    def test_debate_result_defaults(self):
        result = DebateResult(
            hypothesis_id="1",
            original_hypothesis={"id": "1"},
        )
        assert result.hypothesis_id == "1"
        assert result.refined_hypothesis is None
        assert result.turns == []
        assert result.final_consensus == 0.0
        assert result.converged is False
        assert result.total_rounds == 0
        assert result.token_usage["total"] == 0
        assert result.cost_usd == 0.0
        assert result.error is None


class TestDebateFlow:
    """完整辩论流程测试"""

    @pytest.mark.asyncio
    async def test_debate_converges_on_high_consensus(self):
        """高共识度触发收敛（提前结束）"""
        responses = [
            # 轮 1: 正方
            {"content": json.dumps({"argument": "支持假设的论据"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
            # 轮 1: 反方
            {"content": json.dumps({"argument": "质疑假设的论据"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
            # 轮 1: 裁判 — 高共识度，触发收敛
            {"content": json.dumps({
                "consensus_score": 0.9,
                "mechanism_agreed": True,
                "assessment": "双方在核心机制上一致",
                "quality_score": 0.85,
            }), "token_usage": {"total": 30}, "cost_usd": 0.005},
            # 综合修正
            {"content": json.dumps({
                "name": "修正假设",
                "description": "修正描述",
                "mechanism": "修正机制",
                "change_log": "微调",
                "novelty": 8, "plausibility": 9, "testability": 7, "safety": 8,
            }), "token_usage": {"total": 40}, "cost_usd": 0.008},
        ]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=3, convergence_threshold=0.85)

        result = await debate.conduct_debate(
            _make_hypothesis(),
            research_goal="研究目标",
        )

        assert result.converged is True
        assert result.total_rounds == 1  # 第一轮就收敛
        assert result.final_consensus >= 0.85
        assert len(result.turns) == 1
        assert result.refined_hypothesis is not None
        assert result.refined_hypothesis["name"] == "修正假设"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_debate_runs_all_rounds_without_convergence(self):
        """未收敛时跑满所有轮数"""
        # 每轮裁判都返回低共识度
        responses = []
        for round_num in range(1, 4):  # 3 轮
            responses.extend([
                {"content": json.dumps({"argument": f"正方轮{round_num}"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
                {"content": json.dumps({"argument": f"反方轮{round_num}"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
                {"content": json.dumps({
                    "consensus_score": 0.3,
                    "mechanism_agreed": False,
                    "assessment": "双方分歧严重",
                    "quality_score": 0.4,
                }), "token_usage": {"total": 30}, "cost_usd": 0.005},
            ])
        # 综合修正
        responses.append({"content": json.dumps({
            "name": "最终修正",
            "description": "最终描述",
            "mechanism": "最终机制",
        }), "token_usage": {"total": 40}, "cost_usd": 0.008})

        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=3, convergence_threshold=0.85)

        result = await debate.conduct_debate(_make_hypothesis(), "研究目标")

        assert result.converged is False
        assert result.total_rounds == 3
        assert len(result.turns) == 3
        assert result.final_consensus < 0.85

    @pytest.mark.asyncio
    async def test_debate_mechanism_agreed_triggers_convergence(self):
        """mechanism_agreed=True 即使共识度低也触发收敛"""
        responses = [
            {"content": json.dumps({"argument": "正方"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
            {"content": json.dumps({"argument": "反方"}), "token_usage": {"total": 50}, "cost_usd": 0.01},
            # 共识度低，但 mechanism_agreed=True
            {"content": json.dumps({
                "consensus_score": 0.5,
                "mechanism_agreed": True,
                "assessment": "核心机制一致",
                "quality_score": 0.7,
            }), "token_usage": {"total": 30}, "cost_usd": 0.005},
            {"content": json.dumps({"name": "修正"}), "token_usage": {"total": 40}, "cost_usd": 0.008},
        ]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=3, convergence_threshold=0.85)

        result = await debate.conduct_debate(_make_hypothesis(), "研究目标")

        assert result.converged is True
        assert result.total_rounds == 1

    @pytest.mark.asyncio
    async def test_debate_token_and_cost_accumulated(self):
        """Token 和 cost 累计正确"""
        responses = [
            {"content": json.dumps({"argument": "正方"}), "token_usage": {"total": 100}, "cost_usd": 0.02},
            {"content": json.dumps({"argument": "反方"}), "token_usage": {"total": 80}, "cost_usd": 0.015},
            {"content": json.dumps({
                "consensus_score": 0.9, "mechanism_agreed": True,
                "assessment": "一致",
            }), "token_usage": {"total": 50}, "cost_usd": 0.01},
            {"content": json.dumps({"name": "修正"}), "token_usage": {"total": 60}, "cost_usd": 0.012},
        ]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=3, convergence_threshold=0.85)

        result = await debate.conduct_debate(_make_hypothesis(), "研究目标")

        # 100 + 80 + 50 + 60 = 290
        assert result.token_usage["total"] == 290
        # 0.02 + 0.015 + 0.01 + 0.012 = 0.057
        assert abs(result.cost_usd - 0.057) < 0.001


class TestDebateErrorHandling:
    """异常处理测试"""

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_crash(self):
        """LLM 调用失败时辩论不崩溃，记录 error"""
        debate = ScientificDebate(FailingLLMRouter(), max_rounds=2)

        result = await debate.conduct_debate(_make_hypothesis(), "研究目标")

        assert result.error is not None
        assert "LLM 服务不可用" in result.error or "不可用" in result.error
        # 失败时无修正假设
        assert result.refined_hypothesis is None

    @pytest.mark.asyncio
    async def test_debate_with_empty_hypothesis(self):
        """空假设字段不崩溃（回退到 str(hypothesis)）"""
        router = MockLLMRouter(default_response={
            "content": json.dumps({
                "argument": "论据",
                "consensus_score": 0.9,
                "mechanism_agreed": True,
                "assessment": "一致",
            }),
            "token_usage": {"total": 10},
            "cost_usd": 0.001,
        })
        debate = ScientificDebate(router, max_rounds=1, convergence_threshold=0.85)

        # 只有 id，无 name/description/mechanism
        result = await debate.conduct_debate({"id": "1"}, "研究目标")

        # 不崩溃即可（可能收敛或跑满轮数）
        assert result.hypothesis_id == "1"


class TestResponseParsing:
    """LLM 响应解析测试"""

    def test_parse_plain_dict(self):
        """直接 dict 响应"""
        debate = ScientificDebate(MockLLMRouter())
        result = {"content": '{"argument": "测试论据"}', "token_usage": {"total": 10}, "cost_usd": 0.001}
        parsed = debate._parse_debate_response(result)

        assert parsed["argument"] == "测试论据"
        assert parsed["token_usage"]["total"] == 10
        assert parsed["cost_usd"] == 0.001

    def test_parse_json_code_block(self):
        """解析 ```json 代码块"""
        debate = ScientificDebate(MockLLMRouter())
        content = '```json\n{"argument": "代码块论据", "consensus_score": 0.8}\n```'
        result = {"content": content, "token_usage": {}, "cost_usd": 0.0}
        parsed = debate._parse_debate_response(result)

        assert parsed["argument"] == "代码块论据"
        assert parsed["consensus_score"] == 0.8

    def test_parse_plain_code_block(self):
        """解析 ``` 代码块"""
        debate = ScientificDebate(MockLLMRouter())
        content = '```\n{"argument": "普通代码块"}\n```'
        result = {"content": content, "token_usage": {}, "cost_usd": 0.0}
        parsed = debate._parse_debate_response(result)

        assert parsed["argument"] == "普通代码块"

    def test_parse_non_json_falls_back_to_content(self):
        """非 JSON 内容回退到原始文本"""
        debate = ScientificDebate(MockLLMRouter())
        content = "这是纯文本论据，不是 JSON"
        result = {"content": content, "token_usage": {}, "cost_usd": 0.0}
        parsed = debate._parse_debate_response(result)

        assert parsed["argument"] == content

    def test_parse_string_response(self):
        """字符串响应"""
        debate = ScientificDebate(MockLLMRouter())
        parsed = debate._parse_debate_response("纯字符串论据")

        assert parsed["argument"] == "纯字符串论据"
        assert parsed["token_usage"] == {}
        assert parsed["cost_usd"] == 0.0

    def test_parse_json_with_extra_text(self):
        """JSON 前后有额外文本"""
        debate = ScientificDebate(MockLLMRouter())
        content = '论据如下：{"argument": "提取的论据", "consensus_score": 0.7} 以上是论据。'
        result = {"content": content, "token_usage": {}, "cost_usd": 0.0}
        parsed = debate._parse_debate_response(result)

        assert parsed["argument"] == "提取的论据"
        assert parsed["consensus_score"] == 0.7

    def test_parse_assessment_as_argument(self):
        """无 argument 字段时用 assessment 作为 argument"""
        debate = ScientificDebate(MockLLMRouter())
        content = '{"assessment": "裁判评估文本"}'
        result = {"content": content, "token_usage": {}, "cost_usd": 0.0}
        parsed = debate._parse_debate_response(result)

        # argument 兼容 assessment
        assert "裁判评估文本" in parsed.get("argument", "") or "assessment" in parsed


class TestJudgeConvergence:
    """裁判判定测试"""

    @pytest.mark.asyncio
    async def test_judge_returns_all_fields(self):
        """裁判返回所有必需字段"""
        responses = [{
            "content": json.dumps({
                "consensus_score": 0.7,
                "mechanism_agreed": False,
                "assessment": "部分一致",
                "quality_score": 0.6,
            }),
            "token_usage": {"total": 30},
            "cost_usd": 0.005,
        }]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=1, convergence_threshold=0.85)

        judgment = await debate._judge_convergence(
            "假设", "目标", "正方论据", "反方论据", 1,
        )

        assert judgment["consensus_score"] == 0.7
        assert judgment["mechanism_agreed"] is False
        assert judgment["assessment"] == "部分一致"
        assert judgment["quality_score"] == 0.6

    @pytest.mark.asyncio
    async def test_judge_defaults_on_missing_fields(self):
        """裁判响应缺字段时使用默认值"""
        responses = [{
            "content": json.dumps({"assessment": "只有评估"}),
            "token_usage": {"total": 30},
            "cost_usd": 0.005,
        }]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=1, convergence_threshold=0.85)

        judgment = await debate._judge_convergence("假设", "目标", "正方", "反方", 1)

        # 缺 consensus_score → 默认 0.0
        assert judgment["consensus_score"] == 0.0
        # 缺 mechanism_agreed → 默认 False
        assert judgment["mechanism_agreed"] is False
        assert judgment["assessment"] == "只有评估"
        # 缺 quality_score → 默认 0.0
        assert judgment["quality_score"] == 0.0


class TestSynthesizeRefinedHypothesis:
    """假设修正合成测试"""

    @pytest.mark.asyncio
    async def test_synthesize_merges_fields(self):
        """合成修正假设合并原始字段 + 修正字段"""
        original = {
            "id": "1",
            "name": "原假设",
            "description": "原描述",
            "mechanism": "原机制",
            "extra_field": "保留",
        }
        turns = [DebateTurn(
            round_num=1,
            proponent_argument="正方论据较长内容",
            opponent_argument="反方论据较长内容",
            judge_assessment="裁判评估较长内容",
            consensus_score=0.8,
            mechanism_agreed=True,
        )]
        responses = [{
            "content": json.dumps({
                "name": "修正假设",
                "description": "修正描述",
                "mechanism": "修正机制",
                "change_log": "调整机制",
                "novelty": 8,
                "plausibility": 9,
                "testability": 7,
                "safety": 8,
            }),
            "token_usage": {"total": 40},
            "cost_usd": 0.008,
        }]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=1)

        refined = await debate._synthesize_refined_hypothesis(original, "目标", turns)

        # 修正字段覆盖原始
        assert refined["name"] == "修正假设"
        assert refined["description"] == "修正描述"
        assert refined["mechanism"] == "修正机制"
        # 原始字段保留
        assert refined["id"] == "1"
        assert refined["extra_field"] == "保留"
        # 新增评分字段
        assert refined["novelty_score"] == 8.0
        assert refined["plausibility_score"] == 9.0
        assert refined["testability_score"] == 7.0
        assert refined["safety_score"] == 8.0
        # 标记为辩论修正
        assert refined["debate_refined"] is True
        assert refined["change_log"] == "调整机制"

    @pytest.mark.asyncio
    async def test_synthesize_preserves_original_on_partial_response(self):
        """部分字段缺失时保留原始值"""
        original = {
            "id": "1",
            "name": "原假设",
            "description": "原描述",
            "mechanism": "原机制",
        }
        turns = [DebateTurn(1, "正方", "反方", "裁判", 0.8, True)]
        # 只修正 name，其他字段缺失
        responses = [{
            "content": json.dumps({"name": "新名称"}),
            "token_usage": {"total": 40},
            "cost_usd": 0.008,
        }]
        router = MockLLMRouter(responses)
        debate = ScientificDebate(router, max_rounds=1)

        refined = await debate._synthesize_refined_hypothesis(original, "目标", turns)

        assert refined["name"] == "新名称"
        # 缺失字段保留原始
        assert refined["description"] == "原描述"
        assert refined["mechanism"] == "原机制"


class TestFormatHypothesis:
    """假设格式化测试"""

    def test_format_full_hypothesis(self):
        debate = ScientificDebate(MockLLMRouter())
        hyp = {"name": "标题", "description": "描述", "mechanism": "机制"}
        text = debate._format_hypothesis(hyp)

        assert "标题: 标题" in text
        assert "描述: 描述" in text
        assert "机制: 机制" in text

    def test_format_partial_hypothesis(self):
        debate = ScientificDebate(MockLLMRouter())
        hyp = {"name": "只有标题"}
        text = debate._format_hypothesis(hyp)
        assert "标题: 只有标题" in text

    def test_format_empty_hypothesis_falls_back_to_str(self):
        debate = ScientificDebate(MockLLMRouter())
        hyp = {"id": "1"}
        text = debate._format_hypothesis(hyp)
        # 无 name/description/mechanism 时回退到 str(hypothesis)
        assert "1" in text


class TestConcurrencyControl:
    """并发控制测试"""

    @pytest.mark.asyncio
    async def test_semaphore_serializes_debate(self):
        """信号量限制并发辩论"""
        call_log = []
        active_concurrent = [0]
        max_concurrent = [0]

        class TrackingRouter:
            async def quick(self, prompt, system=None):
                active_concurrent[0] += 1
                max_concurrent[0] = max(max_concurrent[0], active_concurrent[0])
                call_log.append(prompt[:20])
                await asyncio.sleep(0.05)
                active_concurrent[0] -= 1
                return {
                    "content": json.dumps({
                        "argument": "论据",
                        "consensus_score": 0.9,
                        "mechanism_agreed": True,
                        "assessment": "一致",
                    }),
                    "token_usage": {"total": 10},
                    "cost_usd": 0.001,
                }

        # 信号量=1，强制串行
        sem = asyncio.Semaphore(1)
        debate1 = ScientificDebate(TrackingRouter(), max_rounds=1, convergence_threshold=0.85, semaphore=sem)
        debate2 = ScientificDebate(TrackingRouter(), max_rounds=1, convergence_threshold=0.85, semaphore=sem)

        await asyncio.gather(
            debate1.conduct_debate(_make_hypothesis("1"), "目标"),
            debate2.conduct_debate(_make_hypothesis("2"), "目标"),
        )

        # 信号量=1 时最大并发应为 1
        assert max_concurrent[0] == 1