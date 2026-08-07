"""Experiment Schedule API — 测试 POST /experiments/schedule 端点"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID


class TestScheduleEndpoint:
    @pytest.mark.asyncio
    async def test_schedule_experiment_endpoint(self, client, auth_headers):
        """Test POST /experiments/schedule endpoint"""
        payload = {
            "dsl": {
                "exp_type": "cytotoxicity",
                "variables": [{"name": "drug_conc", "values": [1, 10, 100], "unit": "nM"}],
                "controls": [{"name": "vehicle", "value": "DMSO", "is_negative_control": True}],
                "readouts": [{"name": "viability", "type": "continuous", "unit": "%"}],
                "replicates": 3,
            },
            "project_id": "12345678-1234-5678-1234-567812345678",
        }

        mock_result = {
            "schedule_id": "sched-1",
            "steps": [{"name": "step1"}],
            "conflicts": [],
            "audit_log_id": "audit-1",
        }

        with patch('app.services.experiment.scheduler.ExperimentScheduler') as MockScheduler:
            mock_instance = MagicMock()
            mock_instance.schedule = MagicMock(return_value=mock_result)
            MockScheduler.return_value = mock_instance

            response = await client.post("/api/v1/experiments/schedule", json=payload, headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["schedule_id"] == "sched-1"
