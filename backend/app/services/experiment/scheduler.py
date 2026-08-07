"""ExperimentScheduler — DSL-based experiment scheduling

Schedule experiments from ExperimentDSL, compile to execution steps,
generate Nextflow params / LIMS CSV, detect conflicts, and write audit logs.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.experiment.dsl import ExperimentDSL
from app.services.experiment.dsl_compiler import DSLCompiler

logger = logging.getLogger(__name__)


class ExperimentScheduler:
    """Schedule experiments from ExperimentDSL.

    Usage:
        scheduler = ExperimentScheduler()
        result = scheduler.schedule(dsl, project_id)
    """

    def __init__(self, compiler: Optional[DSLCompiler] = None):
        self.compiler = compiler or DSLCompiler()

    def schedule(
        self,
        dsl: ExperimentDSL,
        project_id: str,
        hypothesis_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Schedule experiment from DSL, return schedule result.

        Returns:
            {
                schedule_id: str,
                project_id: str,
                steps: [...],
                nextflow_params: {...},
                nextflow_pipeline: str,
                lims_csv: str,
                conflicts: [],
                audit_log_id: str,
                created_at: str,
            }
        """
        schedule_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        compiled = self.compiler.compile(dsl)
        steps = compiled["steps"]
        nextflow_params = compiled["nextflow_params"]
        nextflow_pipeline = nextflow_params.get("pipeline", "generic_pipeline.nf")
        lims_csv = compiled["lims_csv"]

        conflicts = self.detect_conflicts([], {
            "schedule_id": schedule_id,
            "exp_type": dsl.exp_type,
            "steps": steps,
        })

        audit_log_id = self._write_audit_log(schedule_id, dsl, steps)

        result: Dict[str, Any] = {
            "schedule_id": schedule_id,
            "project_id": project_id,
            "steps": steps,
            "nextflow_params": nextflow_params,
            "nextflow_pipeline": nextflow_pipeline,
            "lims_csv": lims_csv,
            "conflicts": conflicts,
            "audit_log_id": audit_log_id,
            "created_at": created_at,
        }

        if hypothesis_ids:
            result["hypothesis_ids"] = hypothesis_ids

        logger.info(
            "Experiment scheduled: schedule_id=%s exp_type=%s pipeline=%s steps=%d",
            schedule_id, dsl.exp_type, nextflow_pipeline, len(steps),
        )
        return result

    def detect_conflicts(
        self,
        existing_experiments: List[Dict[str, Any]],
        new_schedule: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Detect resource conflicts (time/instrument/reagent).

        Placeholder: returns empty list. Future implementation will check
        instrument availability, reagent stock, and time slot overlap.
        """
        return []

    def _generate_nextflow_params(self, dsl: ExperimentDSL) -> Dict[str, Any]:
        """Generate Nextflow pipeline parameters for computational experiments."""
        return self.compiler._build_nextflow_params(dsl)  # type: ignore

    def _write_audit_log(
        self,
        schedule_id: str,
        dsl: ExperimentDSL,
        steps: List[Dict[str, Any]],
    ) -> str:
        """Write audit log, return audit_id (uuid4 string)."""
        audit_id = str(uuid.uuid4())
        logger.info(
            "Audit log: schedule_id=%s audit_id=%s exp_type=%s steps=%d",
            schedule_id, audit_id, dsl.exp_type, len(steps),
        )
        return audit_id
