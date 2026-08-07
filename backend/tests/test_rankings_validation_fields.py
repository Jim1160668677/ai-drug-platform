"""RankedHypothesisView 序列化实验验证字段"""
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.coscientist import RankedHypothesisView


class TestRankedHypothesisValidationFields:
    def test_serializes_experimental_validation_fields(self):
        hyp = SimpleNamespace(
            id=uuid4(),
            name="H1",
            elo_score=1015.0,
            experimental_elo_adjustment=15.0,
            experimental_validation_count=1,
            status="active",
        )
        view = RankedHypothesisView.model_validate(hyp)
        assert view.experimental_elo_adjustment == 15.0
        assert view.experimental_validation_count == 1

    def test_missing_fields_default_none(self):
        hyp = SimpleNamespace(
            id=uuid4(),
            name="H2",
            elo_score=1000.0,
            status="active",
        )
        view = RankedHypothesisView.model_validate(hyp)
        assert view.experimental_elo_adjustment is None
        assert view.experimental_validation_count is None
