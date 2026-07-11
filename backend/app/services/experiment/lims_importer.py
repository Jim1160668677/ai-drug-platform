"""LIMS 数据导入器 — 实验室信息管理系统数据接入"""
import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiment import Experiment, ExperimentStatus

logger = logging.getLogger(__name__)


class LimsImporter:
    """LIMS 数据导入器 — 批量导入实验数据"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def import_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """从 LIMS 标准格式导入实验数据

        Args:
            payload: {
                experiments: [
                    {name, exp_type, project_id, config, result, lab_source, ...}
                ]
            }
        Returns:
            {count, imported_ids, errors}
        """
        experiments_data = payload.get("experiments", [])
        if not experiments_data:
            return {"count": 0, "imported_ids": [], "errors": ["无实验数据"]}

        imported_ids: List[str] = []
        errors: List[str] = []

        for i, exp_data in enumerate(experiments_data):
            try:
                project_id_str = exp_data.get("project_id")
                if not project_id_str:
                    errors.append(f"第 {i+1} 条：缺少 project_id")
                    continue

                exp = Experiment(
                    project_id=UUID(project_id_str),
                    name=exp_data.get("name", f"LIMS_Import_{i+1}"),
                    exp_type=exp_data.get("exp_type", "in_vitro"),
                    status=exp_data.get("status", ExperimentStatus.PLANNED),
                    config=exp_data.get("config"),
                    result=exp_data.get("result"),
                    success=exp_data.get("success"),
                    iteration=exp_data.get("iteration", 1),
                    lab_source=exp_data.get("lab_source", "LIMS"),
                    notes=exp_data.get("notes"),
                )
                self.db.add(exp)
                await self.db.flush()
                imported_ids.append(str(exp.id))
            except Exception as e:
                errors.append(f"第 {i+1} 条：{str(e)}")
                logger.warning(f"LIMS 导入第 {i+1} 条失败: {e}")

        return {
            "count": len(imported_ids),
            "imported_ids": imported_ids,
            "errors": errors,
            "total_received": len(experiments_data),
        }
