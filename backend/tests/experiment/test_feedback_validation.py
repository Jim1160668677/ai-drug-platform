"""干湿闭环反馈 — 假设 Elo 评分反馈单元测试

覆盖目标：
- apply_validation_feedback: VALIDATED/REFUTED/INCONCLUSIVE 三种结论的 elo 变化
- feedback_to_hypotheses: 数据流转（查询假设 → 调用反馈 → 返回结果）
- confidence 参数的加权效果
- 边界条件：无假设关联、非法结论、默认 confidence

测试策略：
- 数据库会话全部 Mock（MagicMock + AsyncMock）
- Hypothesis / Experiment ORM 对象用 SimpleNamespace 构造
- 不依赖真实数据库
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ============================================================
# apply_validation_feedback
# ============================================================

class TestApplyValidationFeedbackValidated:
    """VALIDATED 结论 → elo +15 * confidence"""

    @pytest.mark.asyncio
    async def test_validated_default_confidence(self):
        """VALIDATED + 默认 confidence(1.0) → elo +15"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "VALIDATED")

        assert result["success"] is True
        assert result["conclusion"] == "VALIDATED"
        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == 1015.0
        assert result["elo_change"] == 15.0
        assert result["confidence"] == 1.0

        assert hypothesis.elo_score == 1015.0
        assert len(hypothesis.evolution_history) == 1
        entry = hypothesis.evolution_history[0]
        assert entry["type"] == "validation"
        assert entry["conclusion"] == "VALIDATED"
        assert entry["elo_change"] == 15.0
        assert entry["confidence"] == 1.0
        assert "round" in entry

    @pytest.mark.asyncio
    async def test_validated_with_custom_confidence(self):
        """VALIDATED + confidence=0.5 → elo +7.5"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(
            experiment, "VALIDATED", confidence=0.5
        )

        assert result["elo_change"] == 7.5
        assert result["elo_after"] == 1007.5
        assert result["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_validated_with_zero_confidence(self):
        """VALIDATED + confidence=0 → elo 不变"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(
            experiment, "VALIDATED", confidence=0.0
        )

        assert result["elo_change"] == 0.0
        assert result["elo_after"] == 1000.0


class TestApplyValidationFeedbackRefuted:
    """REFUTED 结论 → elo -25 * confidence"""

    @pytest.mark.asyncio
    async def test_refuted_default_confidence(self):
        """REFUTED + 默认 confidence(1.0) → elo -25"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "REFUTED")

        assert result["success"] is True
        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == 975.0
        assert result["elo_change"] == -25.0

        assert hypothesis.elo_score == 975.0
        entry = hypothesis.evolution_history[0]
        assert entry["elo_change"] == -25.0

    @pytest.mark.asyncio
    async def test_refuted_with_custom_confidence(self):
        """REFUTED + confidence=0.6 → elo -15"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(
            experiment, "REFUTED", confidence=0.6
        )

        assert result["elo_change"] == -15.0
        assert result["elo_after"] == 985.0


class TestApplyValidationFeedbackInconclusive:
    """INCONCLUSIVE 结论 → elo 不变"""

    @pytest.mark.asyncio
    async def test_inconclusive_no_change(self):
        """INCONCLUSIVE → elo 保持不变"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(
            experiment, "INCONCLUSIVE"
        )

        assert result["success"] is True
        assert result["elo_change"] == 0.0
        assert result["elo_after"] == 1000.0
        assert hypothesis.elo_score == 1000.0

        entry = hypothesis.evolution_history[0]
        assert entry["conclusion"] == "INCONCLUSIVE"
        assert entry["elo_change"] == 0.0


class TestApplyValidationFeedbackEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_no_hypothesis_returns_error(self):
        """实验未关联假设 → 返回 success=False"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            hypothesis=None,
            hypothesis_id=None,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "VALIDATED")

        assert result["success"] is False
        assert result["hypothesis_id"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_conclusion_raises(self):
        """非法结论抛 ValueError"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)

        with pytest.raises(ValueError, match="非法结论"):
            await loop.apply_validation_feedback(experiment, "INVALID")

    @pytest.mark.asyncio
    async def test_none_elo_score_defaults_to_1000(self):
        """hypothesis.elo_score 为 None 时默认 1000.0"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=None,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "VALIDATED")

        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == 1015.0

    @pytest.mark.asyncio
    async def test_appended_to_existing_evolution_history(self):
        """evolution_history 已有记录时追加而非覆盖"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        existing_entry = {"round": "old", "type": "initial", "elo_change": 0}
        hypothesis = SimpleNamespace(
            id=uuid4(),
            elo_score=1000.0,
            evolution_history=[existing_entry],
        )
        experiment = SimpleNamespace(
            hypothesis=hypothesis,
            hypothesis_id=hypothesis.id,
        )

        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.apply_validation_feedback(experiment, "VALIDATED")

        assert len(hypothesis.evolution_history) == 2
        assert hypothesis.evolution_history[0] == existing_entry
        assert hypothesis.evolution_history[1]["type"] == "validation"


# ============================================================
# feedback_to_hypotheses
# ============================================================

class TestFeedbackToHypotheses:
    """feedback_to_hypotheses 数据流转测试"""

    @pytest.mark.asyncio
    async def test_with_conclusion_calls_apply_feedback(self):
        """result 中有 conclusion → 调用 apply_validation_feedback"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis_id = uuid4()
        hypothesis = SimpleNamespace(
            id=hypothesis_id,
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            result={"conclusion": "VALIDATED"},
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none = MagicMock(
            return_value=hypothesis
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.feedback_to_hypotheses(experiment)

        assert result["hypothesis_id"] == str(hypothesis_id)
        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == 1015.0

    @pytest.mark.asyncio
    async def test_without_conclusion_skips_feedback(self):
        """result 中无 conclusion → 跳过反馈，elo 不变"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis_id = uuid4()
        hypothesis = SimpleNamespace(
            id=hypothesis_id,
            elo_score=1000.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            result={},
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none = MagicMock(
            return_value=hypothesis
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        loop = FeedbackLoop(mock_db)
        result = await loop.feedback_to_hypotheses(experiment)

        assert result["hypothesis_id"] == str(hypothesis_id)
        assert result["elo_before"] == 1000.0
        assert result["elo_after"] == 1000.0
        assert "message" in result

    @pytest.mark.asyncio
    async def test_no_hypothesis_id(self):
        """experiment.hypothesis_id 为 None → 返回错误"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            hypothesis_id=None,
            hypothesis=None,
            result=None,
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        result = await loop.feedback_to_hypotheses(experiment)

        assert result["hypothesis_id"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_hypothesis_not_found(self):
        """hypothesis_id 存在但假设不存在 → 返回错误"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hid = uuid4()
        experiment = SimpleNamespace(
            hypothesis_id=hid,
            hypothesis=None,
            result={"conclusion": "VALIDATED"},
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none = MagicMock(
            return_value=None
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        loop = FeedbackLoop(mock_db)
        result = await loop.feedback_to_hypotheses(experiment)

        assert result["hypothesis_id"] == str(hid)
        assert result["elo_before"] is None
        assert result["elo_after"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_none_result_dict(self):
        """experiment.result 为 None → 视为无 conclusion"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        hypothesis_id = uuid4()
        hypothesis = SimpleNamespace(
            id=hypothesis_id,
            elo_score=950.0,
            evolution_history=[],
        )
        experiment = SimpleNamespace(
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            result=None,
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none = MagicMock(
            return_value=hypothesis
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        loop = FeedbackLoop(mock_db)
        result = await loop.feedback_to_hypotheses(experiment)

        assert result["elo_before"] == 950.0
        assert result["elo_after"] == 950.0


# ============================================================
# confidence 加权效果综合测试
# ============================================================

class TestConfidenceWeighting:
    """confidence 参数对 elo 变化的加权效果"""

    @pytest.mark.asyncio
    async def test_confidence_spectrum(self):
        """测试 confidence 从 0 到 1 的加权效果"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        test_cases = [
            (0.0, 0.0),
            (0.25, 3.75),
            (0.5, 7.5),
            (0.75, 11.25),
            (1.0, 15.0),
        ]

        for conf, expected_change in test_cases:
            hypothesis = SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
            )
            experiment = SimpleNamespace(
                hypothesis=hypothesis,
                hypothesis_id=hypothesis.id,
            )

            mock_db = MagicMock()
            mock_db.begin = MagicMock()
            mock_db.begin.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock()
            )
            mock_db.begin.return_value.__aexit__ = AsyncMock(
                return_value=None
            )
            mock_db.flush = AsyncMock()

            loop = FeedbackLoop(mock_db)
            result = await loop.apply_validation_feedback(
                experiment, "VALIDATED", confidence=conf
            )

            assert abs(result["elo_change"] - expected_change) < 0.001, (
                f"confidence={conf}: expected elo_change={expected_change}, "
                f"got {result['elo_change']}"
            )

    @pytest.mark.asyncio
    async def test_refuted_confidence_spectrum(self):
        """测试 REFUTED 下 confidence 的加权效果"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        test_cases = [
            (0.0, 0.0),
            (0.5, -12.5),
            (1.0, -25.0),
        ]

        for conf, expected_change in test_cases:
            hypothesis = SimpleNamespace(
                id=uuid4(),
                elo_score=1000.0,
                evolution_history=[],
            )
            experiment = SimpleNamespace(
                hypothesis=hypothesis,
                hypothesis_id=hypothesis.id,
            )

            mock_db = MagicMock()
            mock_db.begin = MagicMock()
            mock_db.begin.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock()
            )
            mock_db.begin.return_value.__aexit__ = AsyncMock(
                return_value=None
            )
            mock_db.flush = AsyncMock()

            loop = FeedbackLoop(mock_db)
            result = await loop.apply_validation_feedback(
                experiment, "REFUTED", confidence=conf
            )

            assert abs(result["elo_change"] - expected_change) < 0.001


# ============================================================
# run_closure 完整编排
# ============================================================

class TestRunClosure:
    """run_closure: 误差反馈 + 假设反馈 + 失败沉淀的完整编排"""

    def _make_db(self):
        mock_db = MagicMock()
        mock_db.begin = MagicMock()
        mock_db.begin.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db.begin.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db

    @pytest.mark.asyncio
    async def test_success_calls_feedback_and_hypothesis_feedback(self):
        """成功实验: 调 apply_feedback + feedback_to_hypotheses, 不调 ingest_failure"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            hypothesis_id=uuid4(),
            target_id=uuid4(),
            molecule_id=uuid4(),
            exp_type="cytotoxicity",
            status="completed",
            success=True,
            config={"predicted": {"ic50": 10}},
            result={"measured": {"ic50": 9}, "conclusion": "VALIDATED"},
            iteration=1,
            lab_source="lab",
            notes=None,
        )

        mock_db = self._make_db()
        loop = FeedbackLoop(mock_db)
        loop.apply_feedback = AsyncMock(return_value={"feedback": {"mae": 1.0}})
        loop.feedback_to_hypotheses = AsyncMock(
            return_value={"hypothesis_id": str(experiment.hypothesis_id),
                          "elo_before": 1000.0, "elo_after": 1015.0}
        )
        loop.ingest_failure = AsyncMock(
            return_value={"failure_knowledge_id": None,
                          "failure_reason": None, "is_new": False}
        )

        result = await loop.run_closure(experiment)

        loop.apply_feedback.assert_awaited_once()
        loop.feedback_to_hypotheses.assert_awaited_once()
        loop.ingest_failure.assert_not_awaited()

        assert "feedback" in result
        assert result["hypothesis_feedback"]["elo_after"] == 1015.0
        assert "failure_knowledge" not in result

    @pytest.mark.asyncio
    async def test_failure_calls_ingest_failure(self):
        """失败实验: 额外调用 ingest_failure"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            hypothesis_id=uuid4(),
            success=False,
            config={},
            result={"conclusion": "REFUTED"},
            exp_type="cytotoxicity",
            status="completed",
            iteration=1,
            lab_source="lab",
            target_id=None,
            molecule_id=None,
            notes=None,
        )

        mock_db = self._make_db()
        loop = FeedbackLoop(mock_db)
        loop.apply_feedback = AsyncMock(return_value={"feedback": {}})
        loop.feedback_to_hypotheses = AsyncMock(
            return_value={"hypothesis_id": str(experiment.hypothesis_id),
                          "elo_before": 1000.0, "elo_after": 975.0}
        )
        loop.ingest_failure = AsyncMock(
            return_value={"failure_knowledge_id": "fk-1",
                          "failure_reason": "concentration", "is_new": True}
        )

        result = await loop.run_closure(experiment)

        loop.ingest_failure.assert_awaited_once()
        assert result["failure_knowledge"]["failure_reason"] == "concentration"
        assert result["failure_knowledge"]["is_new"] is True

    @pytest.mark.asyncio
    async def test_feedback_exception_does_not_break_chain(self):
        """apply_feedback 抛异常时仍继续后续反馈"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            hypothesis_id=uuid4(),
            success=False,
            config={},
            result={"conclusion": "REFUTED"},
            exp_type="cytotoxicity",
            status="completed",
            iteration=1,
            lab_source="lab",
            target_id=None,
            molecule_id=None,
            notes=None,
        )

        mock_db = self._make_db()
        loop = FeedbackLoop(mock_db)
        loop.apply_feedback = AsyncMock(side_effect=RuntimeError("boom"))
        loop.feedback_to_hypotheses = AsyncMock(
            return_value={"hypothesis_id": str(experiment.hypothesis_id),
                          "elo_before": 1000.0, "elo_after": 975.0}
        )
        loop.ingest_failure = AsyncMock(
            return_value={"failure_knowledge_id": "fk-2",
                          "failure_reason": "unknown", "is_new": True}
        )

        result = await loop.run_closure(experiment)

        assert result["feedback"] == {}
        loop.feedback_to_hypotheses.assert_awaited_once()
        loop.ingest_failure.assert_awaited_once()
        assert result["failure_knowledge"]["failure_reason"] == "unknown"