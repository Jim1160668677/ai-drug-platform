"""干湿闭环验证编排器 — ValidationTask 全流程编排

流程：submit_task → link_experiment → record_result → apply_feedback

- submit_task：创建并提交验证任务（draft → submitted），校验 project/target/molecule 存在性
- link_experiment：关联湿实验记录（→ in_progress）
- record_result：记录实验结果与结论（→ validated/refuted/inconclusive，状态即结论）
- apply_feedback：触发 FeedbackLoop.apply_task_feedback 反馈到 target.confidence_score（幂等）

注意：SQLAlchemy Uuid(as_uuid=True) 列要求 uuid.UUID 对象，外部传入的 str ID 需先经 _to_uuid 归一化。
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.experiment import Experiment
from app.models.molecule import Molecule
from app.models.project import Project
from app.models.target import Target
from app.models.validation import (
    ValidationConclusion,
    ValidationTask,
    ValidationTaskStatus,
    ValidationTaskType,
)

logger = logging.getLogger(__name__)


# 合法值集合 — 提前构造，避免每次调用重新构建
_VALID_TASK_TYPES = {
    ValidationTaskType.TARGET_KNOCKDOWN,
    ValidationTaskType.TARGET_OVEREXPRESSION,
    ValidationTaskType.BINDING_ASSAY,
    ValidationTaskType.CELL_VIABILITY,
    ValidationTaskType.ANIMAL_STUDY,
    ValidationTaskType.TOXICITY_STUDY,
}
_VALID_CONCLUSIONS = {
    ValidationConclusion.VALIDATED,
    ValidationConclusion.REFUTED,
    ValidationConclusion.INCONCLUSIVE,
}


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """把 str/UUID 统一转为 UUID（SQLAlchemy Uuid 列要求 UUID 对象）

    None 透传；非法格式抛 ValueError（调用方应确保合法）。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class ValidationOrchestrator:
    """干湿闭环验证编排器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_task(self, data: dict) -> ValidationTask:
        """创建并提交验证任务（draft → submitted）

        校验：
        - project_id 必填且存在
        - hypothesis 非空
        - task_type 必须在合法集合
        - 若提供 target_id / molecule_id，校验存在性
        """
        project_id = data.get("project_id")
        if not project_id:
            raise ValidationError("project_id 不能为空")
        project_uuid = _to_uuid(project_id)
        if not await self.db.get(Project, project_uuid):
            raise NotFoundError("项目不存在")

        hypothesis = (data.get("hypothesis") or "").strip()
        if not hypothesis:
            raise ValidationError("hypothesis（验证假设）不能为空")

        task_type = data.get("task_type")
        if task_type not in _VALID_TASK_TYPES:
            raise ValidationError(f"非法 task_type: {task_type}")

        target_id = data.get("target_id")
        if target_id:
            if not await self.db.get(Target, _to_uuid(target_id)):
                raise NotFoundError("靶点不存在")
        molecule_id = data.get("molecule_id")
        if molecule_id:
            if not await self.db.get(Molecule, _to_uuid(molecule_id)):
                raise NotFoundError("分子不存在")

        task = ValidationTask(
            project_id=project_uuid,
            target_id=_to_uuid(target_id),
            molecule_id=_to_uuid(molecule_id),
            treatment_id=_to_uuid(data.get("treatment_id")),
            task_type=task_type,
            hypothesis=hypothesis,
            prediction=data.get("prediction"),
            status=ValidationTaskStatus.SUBMITTED,
            submitted_at=datetime.now(timezone.utc),
            partner_id=_to_uuid(data.get("partner_id")),
            notes=data.get("notes"),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"验证任务已提交: {task.id} (type={task_type})")
        return task

    async def link_experiment(self, task_id: str, experiment_id: str) -> ValidationTask:
        """把验证任务关联到具体湿实验记录（→ in_progress）"""
        task = await self._get_task(task_id)
        if not await self.db.get(Experiment, _to_uuid(experiment_id)):
            raise NotFoundError("实验不存在")
        task.experiment_id = _to_uuid(experiment_id)
        task.status = ValidationTaskStatus.IN_PROGRESS
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def record_result(
        self,
        task_id: str,
        actual_result: str,
        conclusion: str,
        next_action: Optional[str] = None,
    ) -> ValidationTask:
        """记录实验结果 + 结论（→ validated/refuted/inconclusive）

        状态即结论：记录结果后 status 直接设为 conclusion 值。
        """
        task = await self._get_task(task_id)
        if conclusion not in _VALID_CONCLUSIONS:
            raise ValidationError(f"非法 conclusion: {conclusion}")
        task.actual_result = actual_result
        task.conclusion = conclusion
        task.next_action = next_action
        task.status = conclusion  # validated/refuted/inconclusive 即状态
        task.result_received_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"验证任务 {task_id} 记录结果: {conclusion}")
        return task

    async def apply_feedback(self, task_id: str) -> Dict[str, Any]:
        """触发 FeedbackLoop 把验证结论反馈到 AI 模型置信度（幂等）

        - 若 feedback_applied 已 True，直接返回 skipped 状态，不重复调整
        - 否则调用 FeedbackLoop.apply_task_feedback，并标记 task.feedback_applied=True
        """
        task = await self._get_task(task_id)
        if task.feedback_applied:
            # 幂等：已应用过则返回当前状态，不重复调整 confidence
            return {
                "task_id": str(task.id),
                "feedback_applied": True,
                "skipped": True,
                "message": "反馈已应用过，跳过重复调整",
            }
        # 局部导入避免循环依赖
        from app.services.experiment.feedback_loop import FeedbackLoop

        loop = FeedbackLoop(self.db)
        result = await loop.apply_task_feedback(str(task.id))
        task.feedback_applied = True
        await self.db.commit()
        return result

    async def _get_task(self, task_id: str) -> ValidationTask:
        """加载验证任务，不存在抛 NotFoundError"""
        task = await self.db.get(ValidationTask, _to_uuid(task_id))
        if not task:
            raise NotFoundError("验证任务不存在")
        return task
