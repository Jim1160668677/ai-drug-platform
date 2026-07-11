"""全局看板端点 — 跨项目统计聚合"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.project import Project
from app.models.dataset import Dataset
from app.models.target import Target
from app.models.hypothesis import Hypothesis, HypothesisStatus
from app.models.experiment import Experiment
from app.models.treatment import Treatment
from app.models.molecule import Molecule
from app.api.v1.schemas import StandardResponse
from app.schemas.common import success_response

router = APIRouter()


@router.get("/overview", response_model=StandardResponse, summary="全局看板聚合统计")
async def dashboard_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """跨项目全局统计 — 用于 dashboard 全局看板

    性能优化：使用 GROUP BY 批量聚合替代逐项目 N+1 查询，
    将查询数从 6N+9（N=项目数）降至固定 15 次。

    返回：
    - global: 全局聚合指标（项目数、数据集、靶点、分子、假设、实验、治疗方案）
    - by_cancer_type: 按癌种分组的项目数
    - by_status: 按项目状态分组
    - projects: 每个项目的明细统计（id/name/cancer_type/stage/status/各资源计数）
    - recent_experiments: 最近 10 条实验（跨项目）
    """
    # ---- 全局聚合（9 次查询）----
    total_projects = (await db.execute(select(func.count(Project.id)))).scalar() or 0
    total_datasets = (await db.execute(select(func.count(Dataset.id)))).scalar() or 0
    total_targets = (await db.execute(select(func.count(Target.id)))).scalar() or 0
    total_molecules = (await db.execute(select(func.count(Molecule.id)))).scalar() or 0
    total_hypotheses = (await db.execute(select(func.count(Hypothesis.id)))).scalar() or 0
    total_experiments = (await db.execute(select(func.count(Experiment.id)))).scalar() or 0
    total_treatments = (await db.execute(select(func.count(Treatment.id)))).scalar() or 0
    completed_hypotheses = (
        await db.execute(
            select(func.count(Hypothesis.id)).where(Hypothesis.status == HypothesisStatus.COMPLETED)
        )
    ).scalar() or 0
    successful_experiments = (
        await db.execute(select(func.count(Experiment.id)).where(Experiment.success == True))  # noqa: E712
    ).scalar() or 0

    # ---- 按癌种 / 状态分组（2 次查询）----
    cancer_rows = (
        await db.execute(
            select(Project.cancer_type, func.count(Project.id))
            .group_by(Project.cancer_type)
        )
    ).all()
    by_cancer_type = {ct or "未分类": cnt for ct, cnt in cancer_rows}

    status_rows = (
        await db.execute(
            select(Project.status, func.count(Project.id)).group_by(Project.status)
        )
    ).all()
    by_status = {s or "unknown": cnt for s, cnt in status_rows}

    # ---- 批量获取每项目资源计数（6 次 GROUP BY 查询，替代 6N 次）----
    projects = (
        await db.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()

    # 各资源按 project_id 分组计数
    ds_counts = dict(
        (await db.execute(
            select(Dataset.project_id, func.count(Dataset.id)).group_by(Dataset.project_id)
        )).all()
    )
    tg_counts = dict(
        (await db.execute(
            select(Target.project_id, func.count(Target.id)).group_by(Target.project_id)
        )).all()
    )
    # Molecule 通过 Target 关联到 project
    mo_rows = (
        await db.execute(
            select(Target.project_id, func.count(Molecule.id))
            .join(Target, Molecule.target_id == Target.id, isouter=True)
            .group_by(Target.project_id)
        )
    ).all()
    mo_counts = {pid: cnt for pid, cnt in mo_rows if pid is not None}
    hy_counts = dict(
        (await db.execute(
            select(Hypothesis.project_id, func.count(Hypothesis.id)).group_by(Hypothesis.project_id)
        )).all()
    )
    ex_counts = dict(
        (await db.execute(
            select(Experiment.project_id, func.count(Experiment.id)).group_by(Experiment.project_id)
        )).all()
    )
    tr_counts = dict(
        (await db.execute(
            select(Treatment.project_id, func.count(Treatment.id)).group_by(Treatment.project_id)
        )).all()
    )

    # 合并为项目明细
    projects_data: List[Dict[str, Any]] = []
    for p in projects:
        pid = p.id
        projects_data.append({
            "id": str(pid),
            "name": p.name,
            "patient_pseudonym": p.patient_pseudonym,
            "cancer_type": p.cancer_type,
            "stage": p.stage,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "counts": {
                "datasets": ds_counts.get(pid, 0),
                "targets": tg_counts.get(pid, 0),
                "molecules": mo_counts.get(pid, 0),
                "hypotheses": hy_counts.get(pid, 0),
                "experiments": ex_counts.get(pid, 0),
                "treatments": tr_counts.get(pid, 0),
            },
        })

    # ---- 最近实验（1 次查询）----
    recent = (
        await db.execute(
            select(Experiment, Project.name.label("project_name"))
            .join(Project, Experiment.project_id == Project.id, isouter=True)
            .order_by(Experiment.created_at.desc())
            .limit(10)
        )
    ).all()
    recent_experiments = [
        {
            "id": str(exp.id),
            "name": exp.name,
            "exp_type": exp.exp_type,
            "status": exp.status,
            "success": exp.success,
            "iteration": exp.iteration,
            "project_id": str(exp.project_id),
            "project_name": pname or "—",
            "created_at": exp.created_at.isoformat() if exp.created_at else None,
        }
        for exp, pname in recent
    ]

    return success_response({
        "global": {
            "projects": total_projects,
            "datasets": total_datasets,
            "targets": total_targets,
            "molecules": total_molecules,
            "hypotheses": total_hypotheses,
            "experiments": total_experiments,
            "treatments": total_treatments,
            "completed_hypotheses": completed_hypotheses,
            "successful_experiments": successful_experiments,
            "hypothesis_completion_rate": round(completed_hypotheses / total_hypotheses, 2) if total_hypotheses else 0,
            "experiment_success_rate": round(successful_experiments / total_experiments, 2) if total_experiments else 0,
        },
        "by_cancer_type": by_cancer_type,
        "by_status": by_status,
        "projects": projects_data,
        "recent_experiments": recent_experiments,
    })
