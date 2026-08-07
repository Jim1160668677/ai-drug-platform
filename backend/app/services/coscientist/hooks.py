"""Co-Scientist 自动触发钩子 — 各业务端点调用此模块触发自动推理

设计原则：
- 最小侵入：各端点只需在完成业务逻辑后调用一行 fire_auto_trigger()
- 异步非阻塞：业务流程不等待推理，钩子内部用 asyncio.create_task
- 容错：触发失败不影响业务流程，仅记录日志
- 可关闭：通过 settings.COSCIENTIST_AUTO_TRIGGER_ENABLED 全局开关

使用示例（在任意业务端点末尾）：

    from app.services.coscientist.hooks import fire_auto_trigger
    from app.models.coscientist_insight import TriggerEvent

    # 业务逻辑完成后...
    await fire_auto_trigger(
        db=db, user=current_user,
        trigger_event=TriggerEvent.TARGETS_DISCOVERED,
        project_id=str(project_id),
        entity_id=str(target.id),
        entity_name=target.gene_symbol,
    )
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.coscientist_insight import TriggerEvent
from app.models.user import User

logger = logging.getLogger(__name__)


def _is_auto_trigger_enabled() -> bool:
    """自动触发全局开关（默认开启）"""
    return getattr(settings, "COSCIENTIST_AUTO_TRIGGER_ENABLED", True)


async def fire_auto_trigger(
    db: AsyncSession,
    user: User,
    trigger_event: str,
    project_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    extra_evidence: Optional[str] = None,
    commit_first: bool = True,
) -> None:
    """业务事件触发自动推理（异步非阻塞，容错）

    Args:
        db: 数据库会话（用于创建运行记录，需先 commit 业务数据）
        user: 触发用户
        trigger_event: 触发事件类型（见 TriggerEvent）
        project_id: 项目 ID
        entity_id: 实体 ID
        entity_name: 实体名称（用于洞察展示）
        extra_evidence: 额外证据文本
        commit_first: 是否先 commit 业务事务（默认 True，确保业务数据落盘后再触发）

    设计要点：
    - 先 commit 业务数据（确保推理能读到最新数据）
    - 再调用 trigger_auto_reasoning 创建运行记录
    - 运行记录与业务数据在同一事务，但 Supervisor 异步执行
    - 任何异常被捕获，不影响业务流程
    """
    if not _is_auto_trigger_enabled():
        return

    try:
        if commit_first:
            try:
                await db.commit()
            except Exception:
                pass  # 调用方可能已 commit，忽略

        from app.services.coscientist.auto_trigger import trigger_auto_reasoning

        run_id = await trigger_auto_reasoning(
            db=db,
            user=user,
            trigger_event=trigger_event,
            project_id=project_id,
            entity_id=entity_id,
            entity_name=entity_name,
            extra_evidence=extra_evidence,
        )

        if run_id:
            logger.info(
                "[hook] 自动触发 %s → run %s（实体 %s）",
                trigger_event, run_id, entity_id or "N/A",
            )
        else:
            logger.warning("[hook] 触发 %s 未创建运行", trigger_event)

    except Exception as e:
        # 触发失败不影响业务流程
        logger.exception("[hook] 自动触发 %s 失败（不影响业务）: %s", trigger_event, e)


# ========== 便捷函数（按模块封装） ==========

async def on_data_parsed(
    db: AsyncSession, user: User, project_id: Optional[str],
    dataset_id: str, dataset_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """数据集解析完成 → 研究方向推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.DATA_PARSED,
        project_id=project_id, entity_id=dataset_id,
        entity_name=dataset_name, extra_evidence=extra,
    )


async def on_targets_discovered(
    db: AsyncSession, user: User, project_id: Optional[str],
    target_id: str, gene_symbol: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """靶点发现完成 → 老药重定位推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.TARGETS_DISCOVERED,
        project_id=project_id, entity_id=target_id,
        entity_name=gene_symbol, extra_evidence=extra,
    )


async def on_experiment_completed(
    db: AsyncSession, user: User, project_id: Optional[str],
    experiment_id: str, experiment_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """实验完成 → 假设验证推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.EXPERIMENT_COMPLETED,
        project_id=project_id, entity_id=experiment_id,
        entity_name=experiment_name, extra_evidence=extra,
    )


async def on_experiment_failed(
    db: AsyncSession, user: User, project_id: Optional[str],
    experiment_id: str, experiment_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """实验失败 → 失败原因推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.EXPERIMENT_FAILED,
        project_id=project_id, entity_id=experiment_id,
        entity_name=experiment_name, extra_evidence=extra,
    )


async def on_treatment_generated(
    db: AsyncSession, user: User, project_id: Optional[str],
    treatment_id: str, treatment_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """治疗方案生成 → 协同效应推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.TREATMENT_GENERATED,
        project_id=project_id, entity_id=treatment_id,
        entity_name=treatment_name, extra_evidence=extra,
    )


async def on_molecule_generated(
    db: AsyncSession, user: User, project_id: Optional[str],
    molecule_id: str, molecule_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """分子生成完成 → 成药性推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.MOLECULE_GENERATED,
        project_id=project_id, entity_id=molecule_id,
        entity_name=molecule_name, extra_evidence=extra,
    )


async def on_genome_interpreted(
    db: AsyncSession, user: User, project_id: Optional[str],
    assessment_id: str, trait_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """基因组解读完成 → 个性化治疗推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.GENOME_INTERPRETED,
        project_id=project_id, entity_id=assessment_id,
        entity_name=trait_name, extra_evidence=extra,
    )


async def on_docking_completed(
    db: AsyncSession, user: User, project_id: Optional[str],
    job_id: str, job_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """分子对接完成 → 结合模式分析推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.DOCKING_COMPLETED,
        project_id=project_id, entity_id=job_id,
        entity_name=job_name, extra_evidence=extra,
    )


async def on_structure_predicted(
    db: AsyncSession, user: User, project_id: Optional[str],
    structure_id: str, structure_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """蛋白结构预测完成 → 别构位点推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.STRUCTURE_PREDICTED,
        project_id=project_id, entity_id=structure_id,
        entity_name=structure_name, extra_evidence=extra,
    )


async def on_benchmark_completed(
    db: AsyncSession, user: User, project_id: Optional[str],
    report_id: str, case_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """基准评测完成 → 性能差距分析推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.BENCHMARK_COMPLETED,
        project_id=project_id, entity_id=report_id,
        entity_name=case_id, extra_evidence=extra,
    )


async def on_screening_completed(
    db: AsyncSession, user: User, project_id: Optional[str],
    job_id: str, job_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """双上下文筛选完成 → 条件放大器机制推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.SCREENING_COMPLETED,
        project_id=project_id, entity_id=job_id,
        entity_name=job_name, extra_evidence=extra,
    )


async def on_vaccine_designed(
    db: AsyncSession, user: User, project_id: Optional[str],
    job_id: str, job_name: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """mRNA 疫苗设计完成 → 免疫原性优化推理"""
    await fire_auto_trigger(
        db=db, user=user, trigger_event=TriggerEvent.VACCINE_DESIGNED,
        project_id=project_id, entity_id=job_id,
        entity_name=job_name, extra_evidence=extra,
    )


__all__ = [
    "fire_auto_trigger",
    "on_data_parsed",
    "on_targets_discovered",
    "on_experiment_completed",
    "on_experiment_failed",
    "on_treatment_generated",
    "on_molecule_generated",
    "on_genome_interpreted",
    "on_docking_completed",
    "on_structure_predicted",
    "on_benchmark_completed",
    "on_screening_completed",
    "on_vaccine_designed",
]
