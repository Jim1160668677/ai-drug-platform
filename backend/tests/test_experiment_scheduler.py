"""ExperimentScheduler — unit tests"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.experiment.dsl import ExperimentDSL, ExperimentVariable, ExperimentControl, ExperimentReadout
from app.services.experiment.scheduler import ExperimentScheduler


@pytest.fixture
def scheduler():
    return ExperimentScheduler()


@pytest.fixture
def cytotoxicity_dsl():
    return ExperimentDSL(
        exp_type="cytotoxicity",
        variables=[
            ExperimentVariable(
                name="concentration",
                values=[0.01, 0.1, 1, 10, 100],
                unit="μM",
            )
        ],
        controls=[
            ExperimentControl(name="untreated", value=0, is_negative_control=True),
        ],
        readouts=[
            ExperimentReadout(name="cell_viability", type="continuous", unit="%"),
        ],
        replicates=3,
    )


class TestScheduleDSL:
    def test_schedule_generates_steps(self, scheduler, cytotoxicity_dsl):
        result = scheduler.schedule(cytotoxicity_dsl, "proj-1", hypothesis_ids=["hyp-1"])

        assert "steps" in result
        assert len(result["steps"]) > 0
        assert "schedule_id" in result
        assert "created_at" in result
        assert result["project_id"] == "proj-1"
        assert result["hypothesis_ids"] == ["hyp-1"]
        assert "nextflow_params" in result
        assert "lims_csv" in result
        assert "audit_log_id" in result
        assert "conflicts" in result
        assert isinstance(result["conflicts"], list)


class TestConflictDetection:
    def test_no_conflicts_empty_history(self, scheduler):
        result = scheduler.detect_conflicts([], {})
        assert result == []

    def test_no_conflicts_with_existing(self, scheduler):
        existing = [{"schedule_id": "s1", "exp_type": "cytotoxicity"}]
        result = scheduler.detect_conflicts(existing, {})
        assert result == []


class TestAuditLog:
    @patch("app.services.experiment.scheduler.logger")
    def test_audit_log_writes_to_logger(self, mock_logger, scheduler, cytotoxicity_dsl):
        audit_id = scheduler._write_audit_log("sched-1", cytotoxicity_dsl, [{"order": 1}])

        assert audit_id  # non-empty string
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        log_msg = call_args[1]
        assert "sched-1" in log_msg
