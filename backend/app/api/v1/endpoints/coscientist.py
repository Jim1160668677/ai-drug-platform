"""Co-Scientist API 端点 — 多智能体科学推理引擎

13 REST + 1 WebSocket：
- POST   /coscientist/runs                          创建运行
- GET    /coscientist/runs                          列出运行
- GET    /coscientist/runs/{run_id}                 运行详情
- POST   /coscientist/runs/{run_id}/cancel          取消运行
- POST   /coscientist/runs/{run_id}/feedback        提交专家反馈
- GET    /coscientist/runs/{run_id}/hypotheses      假设列表
- GET    /coscientist/runs/{run_id}/hypotheses/{hid} 假设详情
- GET    /coscientist/runs/{run_id}/rankings        排名
- GET    /coscientist/runs/{run_id}/debates         辩论日志
- GET    /coscientist/runs/{run_id}/progress        进度
- GET    /coscientist/runs/{run_id}/meta-review     元评审
- GET    /coscientist/runs/{run_id}/stats           统计
- GET    /coscientist/cases                         案例列表
- WS     /coscientist/runs/{run_id}/ws              实时进度
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import StandardResponse
from app.core.deps import get_current_user, get_db, get_llm_client_with_fallback, require_role
from app.core.security import UserRole
from app.db.session import get_db
from app.models.coscientist_run import CaseType, CoScientistRun, CoScientistDebateLog, RunStatus
from app.models.hypothesis import Hypothesis, HypothesisStatus
from app.models.user import User
from app.schemas.coscientist import (
    AgentActivity,
    AgentActivityFeedResponse,
    CaseInfo,
    CaseListResponse,
    DebateListResponse,
    DebateLogView,
    EvolutionEdge,
    EvolutionNode,
    EvolutionTreeResponse,
    FeedbackPayload,
    FeedbackResponse,
    MetaReviewResponse,
    RankedHypothesisView,
    RankingsResponse,
    RunCreate,
    RunListResponse,
    RunResponse,
    GenerateGoalRequest,
    GenerateGoalResponse,
)
from app.services.coscientist.cases import (
    get_case_adapter,
    get_all_case_info,
)
from app.services.coscientist.progress import ProgressTracker
from app.services.coscientist.supervisor import Supervisor

logger = logging.getLogger(__name__)

router = APIRouter()

# ========== 活跃运行管理 ==========

_active_supervisors: Dict[str, Supervisor] = {}
_active_trackers: Dict[str, ProgressTracker] = {}
_ws_clients: Dict[str, set] = {}  # run_id -> set of WebSocket


def _get_supervisor(run_id: str) -> Optional[Supervisor]:
    return _active_supervisors.get(run_id)


def _get_tracker(run_id: str) -> Optional[ProgressTracker]:
    return _active_trackers.get(run_id)


async def _ws_broadcast(run_id: str, event_type: str, payload: Dict):
    """向所有订阅该 run 的 WebSocket 客户端推送事件"""
    clients = _ws_clients.get(run_id, set())
    if not clients:
        return
    import json
    message = json.dumps({
        "type": event_type,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }, ensure_ascii=False, default=str)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def _collect_project_evidence(project_id: str) -> str:
    """收集项目前期所有分析结果作为 Co-Scientist 推理证据（委托 EvidenceCollector）

    重构（方向 A）：原内联实现已下沉到 EvidenceCollector.collect_project_evidence。
    本函数保留为薄包装，兼容端点内与 coscientist_insights 的历史调用。
    """
    from app.services.intelligence.evidence_collector import EvidenceCollector
    return await EvidenceCollector().collect_project_evidence(project_id)


async def _collect_project_evidence_legacy(project_id: str) -> str:
    """[已废弃] 原内联实现 — 保留供回退参考，新代码请用 EvidenceCollector"""
    from app.db.session import async_session_factory
    from app.models.target import Target
    from app.models.molecule import Molecule
    from app.models.treatment import Treatment
    from app.models.experiment import Experiment
    from app.models.dataset import Dataset
    from app.models.hypothesis import Hypothesis
    from uuid import UUID
    import json as _json

    try:
        project_uuid = UUID(str(project_id))
    except (ValueError, TypeError):
        return ""

    lines: List[str] = []

    async with async_session_factory() as db:
        # 并行查询所有相关数据
        targets_task = db.execute(
            select(Target).where(Target.project_id == project_uuid).limit(20)
        )
        molecules_task = db.execute(
            select(Molecule)
            .join(Target, Molecule.target_id == Target.id, isouter=True)
            .where(Target.project_id == project_uuid)
            .limit(20)
        )
        treatments_task = db.execute(
            select(Treatment).where(Treatment.project_id == project_uuid).limit(10)
        )
        experiments_task = db.execute(
            select(Experiment).where(Experiment.project_id == project_uuid)
            .order_by(Experiment.created_at.desc()).limit(15)
        )
        datasets_task = db.execute(
            select(Dataset).where(Dataset.project_id == project_uuid)
            .where(Dataset.parse_status == "completed").limit(5)
        )
        hypotheses_task = db.execute(
            select(Hypothesis).where(Hypothesis.project_id == project_uuid).limit(10)
        )

        targets_r, molecules_r, treatments_r, experiments_r, datasets_r, hypotheses_r = (
            await asyncio.gather(
                targets_task, molecules_task, treatments_task,
                experiments_task, datasets_task, hypotheses_task,
            )
        )

        targets = targets_r.scalars().all()
        molecules = molecules_r.scalars().all()
        treatments = treatments_r.scalars().all()
        experiments = experiments_r.scalars().all()
        datasets = datasets_r.scalars().all()
        hypotheses = hypotheses_r.scalars().all()

    # 格式化证据
    if targets:
        lines.append("## 已发现靶点")
        for t in targets[:15]:
            conf = f"（置信度 {float(t.confidence_score):.2f}）" if t.confidence_score else ""
            lines.append(f"- {t.gene_symbol}{conf}: {t.gene_name or ''}")
        lines.append("")

    if molecules:
        lines.append("## 候选分子")
        for m in molecules[:15]:
            props = m.properties or {}
            score = props.get("druglikeness_score", props.get("composite_score", "N/A"))
            lines.append(f"- {m.smiles[:50] if m.smiles else 'N/A'} (评分: {score})")
        lines.append("")

    if treatments:
        lines.append("## 治疗方案")
        for t in treatments[:10]:
            eff = f"疗效 {float(t.efficacy_score):.2f}" if t.efficacy_score else "疗效未知"
            risk = f"风险 {float(t.risk_score):.2f}" if t.risk_score else ""
            lines.append(f"- {t.name} ({t.therapy_type}): {eff} {risk}")
            # 包含监测数据
            monitoring = t.monitoring_data or {}
            if monitoring.get("outcomes"):
                lines.append(f"  监测记录: {len(monitoring['outcomes'])} 条结局")
            if monitoring.get("adverse_events"):
                lines.append(f"  不良事件: {len(monitoring['adverse_events'])} 条")
        lines.append("")

    if experiments:
        lines.append("## 实验结果")
        for e in experiments[:15]:
            result = e.result or {}
            status = e.status
            success = "成功" if e.success else "未达标"
            lines.append(f"- {e.name} ({e.exp_type}): {status} / {success}")
            if result.get("efficacy") is not None:
                lines.append(f"  疗效指标: {result['efficacy']}")
            if result.get("inhibition_rate") is not None:
                lines.append(f"  抑制率: {result['inhibition_rate']}%")
            if result.get("response"):
                lines.append(f"  RECIST 响应: {result['response']}")
        lines.append("")

    if datasets:
        lines.append("## 数据集分析结果")
        for ds in datasets[:5]:
            summary = ds.parsed_summary or {}
            lines.append(f"- {ds.name} ({ds.data_type})")
            analysis = summary.get("analysis_results") or {}
            if isinstance(analysis, dict):
                de = analysis.get("de") or {}
                if isinstance(de, dict):
                    genes = de.get("genes") or []
                    if genes:
                        top_genes = [g.get("gene", g.get("gene_id", "")) for g in genes[:5] if isinstance(g, dict)]
                        lines.append(f"  差异基因: 共 {len(genes)} 个，Top: {', '.join(top_genes)}")
                pathways = analysis.get("pathways") or summary.get("pathways") or []
                if pathways:
                    top_paths = [p.get("name", "") for p in pathways[:3] if isinstance(p, dict)]
                    lines.append(f"  富集通路: {', '.join(top_paths)}")
                clusters = analysis.get("clusters") or summary.get("clusters") or []
                if clusters:
                    lines.append(f"  细胞亚群: {len(clusters)} 个")
        lines.append("")

    if hypotheses:
        lines.append("## 已有研究假设")
        for h in hypotheses[:10]:
            lines.append(f"- {h.name}: {h.description[:100] if h.description else ''}")
        lines.append("")

    if not lines:
        return ""

    evidence_text = "# 项目前期分析数据汇总\n\n" + "\n".join(lines)
    logger.info(
        "[coscientist] 收集项目 %s 证据: %d 靶点 / %d 分子 / %d 治疗 / %d 实验 / %d 数据集 / %d 假设",
        project_id, len(targets), len(molecules), len(treatments),
        len(experiments), len(datasets), len(hypotheses),
    )
    return evidence_text


async def _run_supervisor(
    run_id: str,
    research_goal: str,
    max_rounds: int,
    initial_count: int,
    case_type: Optional[str],
    llm_client: Any,
    project_id: Optional[str] = None,
):
    """后台运行 Supervisor（异步任务）

    修复 B1：运行结束后持久化假设到 Hypothesis 表，更新 CoScientistRun 状态。
    重构：收集项目前期分析数据作为推理证据，替代针对未知内容的推理模式。
    """
    tracker = ProgressTracker(
        run_id=run_id,
        callback=lambda event: _ws_broadcast(run_id, event.type, event.payload),
    )
    _active_trackers[run_id] = tracker

    # 获取案例适配器（若指定 case_type）
    case_adapter = get_case_adapter(case_type) if case_type else None
    generation_context = case_adapter.get_generation_context() if case_adapter else None
    initial_seeds = case_adapter.get_initial_seeds() if case_adapter else None

    # 收集项目前期分析数据作为推理证据
    project_evidence = ""
    if project_id:
        try:
            project_evidence = await _collect_project_evidence(project_id)
            if project_evidence:
                await _ws_broadcast(run_id, "evidence_collected", {
                    "project_id": project_id,
                    "evidence_length": len(project_evidence),
                })
        except Exception as e:
            logger.warning("[coscientist] 收集项目证据失败（将使用空证据）: %s", e)

    supervisor = Supervisor(
        llm_client=llm_client,
        tracker=tracker,
        max_cost_usd=None,
        max_duration_sec=None,
        generation_context=generation_context,
        initial_seeds=initial_seeds,
    )
    _active_supervisors[run_id] = supervisor

    try:
        result = await supervisor.run(
            research_goal=research_goal,
            max_rounds=max_rounds,
            initial_count=initial_count,
            case_type=case_type,
            evidence=project_evidence,
            feedback_mode="auto",
        )
        # 持久化假设和运行结果到 DB
        await _persist_run_result(run_id, result, project_id)
        return result
    except Exception as e:
        logger.exception("[coscientist] 运行 %s 失败: %s", run_id, e)
        await _mark_run_failed(run_id, str(e))
    finally:
        # 清理活跃引用（保留 tracker 供查询历史）
        _active_supervisors.pop(run_id, None)


async def _persist_run_result(
    run_id: str,
    result: Any,
    project_id: Optional[str],
):
    """持久化 Co-Scientist 运行结果到数据库

    - 将假设写入 Hypothesis 表（设置 coscientist_run_id）— 仅当有 project_id 时
    - 更新 CoScientistRun 的 final_rankings、meta_review、status、计量字段
    """
    import json as _json
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        try:
            # 更新运行状态
            run = await db.get(CoScientistRun, uuid.UUID(run_id))
            if run:
                run.status = RunStatus.COMPLETED
                run.completed_at = datetime.now(timezone.utc)
                run.final_rankings = result.final_rankings
                # meta_review 模型字段为 Text，存 JSON 字符串
                run.meta_review = (
                    _json.dumps(result.meta_review, ensure_ascii=False, default=str)
                    if result.meta_review
                    else None
                )
                run.total_cost_usd = result.total_cost_usd
                run.duration_sec = result.duration_sec
                run.current_round = result.total_rounds

            # 持久化假设到 Hypothesis 表（仅当有 project_id，因 Hypothesis.project_id 不可空）
            if project_id and result.all_hypotheses:
                # 查询已存在的假设 ID，避免重复插入
                existing_result = await db.execute(
                    select(Hypothesis.id).where(
                        Hypothesis.coscientist_run_id == uuid.UUID(run_id)
                    )
                )
                existing_ids = {str(r[0]) for r in existing_result.fetchall()}

                for hyp_dict in result.all_hypotheses:
                    hyp_id = hyp_dict.get("id")
                    if hyp_id and str(hyp_id) in existing_ids:
                        continue

                    hyp = Hypothesis(
                        project_id=uuid.UUID(project_id),
                        name=str(hyp_dict.get("name", "未命名假设"))[:200],
                        description=hyp_dict.get("description", ""),
                        mechanism=hyp_dict.get("mechanism", ""),
                        strategy=hyp_dict.get("strategy", ""),
                        status=HypothesisStatus.COMPLETED,
                        target_list=hyp_dict.get("target_list", []),
                        elo_score=hyp_dict.get("elo_score", 1000.0),
                        novelty_score=hyp_dict.get("novelty_score"),
                        plausibility_score=hyp_dict.get("plausibility_score"),
                        testability_score=hyp_dict.get("testability_score"),
                        safety_score=hyp_dict.get("safety_score"),
                        parent_ids=hyp_dict.get("parent_ids", []),
                        evolution_strategy=hyp_dict.get("evolution_strategy", "initial"),
                        evolution_history=hyp_dict.get("evolution_history", []),
                        debate_log=hyp_dict.get("debate_log", []),
                        critique_summary=hyp_dict.get("critique_summary"),
                        coscientist_run_id=uuid.UUID(run_id),
                        rank=hyp_dict.get("rank"),
                    )
                    db.add(hyp)

            await db.commit()
            logger.info(
                "[coscientist] 运行 %s 持久化完成: %d 个假设",
                run_id,
                len(result.all_hypotheses) if result.all_hypotheses else 0,
            )
        except Exception as e:
            await db.rollback()
            logger.exception("[coscientist] 持久化运行 %s 结果失败: %s", run_id, e)


async def _mark_run_failed(run_id: str, error_msg: str):
    """标记运行失败"""
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        try:
            run = await db.get(CoScientistRun, uuid.UUID(run_id))
            if run:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = error_msg[:500]
                await db.commit()
        except Exception as e:
            await db.rollback()
            logger.exception("[coscientist] 标记运行失败状态时出错: %s", e)


# ========== 权限校验 ==========

async def _verify_run_owner(run: CoScientistRun, user: User):
    """验证运行归属"""
    if run.user_id != user.id and user.role != UserRole.FOUNDER:
        raise HTTPException(status_code=403, detail="无权访问此运行")


async def _get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> CoScientistRun:
    result = await db.execute(
        select(CoScientistRun).where(CoScientistRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    return run


# ========== 1. 创建运行 ==========

@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(
    body: RunCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建 Co-Scientist 运行

    同步创建运行记录，异步启动 Supervisor。
    运行状态通过 WebSocket 实时推送。
    """
    run = CoScientistRun(
        user_id=user.id,
        project_id=body.project_id,
        research_goal=body.research_goal,
        case_type=body.case_type or CaseType.CUSTOM,
        max_rounds=body.max_rounds,
        status=RunStatus.PENDING,
        config={
            "initial_hypothesis_count": body.initial_hypothesis_count,
            **(body.config or {}),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # 异步启动 Supervisor
    # 修复 B1：传递 project_id 给 _run_supervisor，确保运行结束后假设能持久化到 Hypothesis 表
    llm_client = await get_llm_client_with_fallback(db)
    asyncio.create_task(_run_supervisor(
        run_id=str(run.id),
        research_goal=body.research_goal,
        max_rounds=body.max_rounds,
        initial_count=body.initial_hypothesis_count,
        case_type=body.case_type,
        llm_client=llm_client,
        project_id=str(run.project_id) if run.project_id else None,
    ))

    # 更新状态为 RUNNING
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)

    return RunResponse.model_validate(run)


# ========== 2. 列出运行 ==========

@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户的 Co-Scientist 运行"""
    query = select(CoScientistRun).where(CoScientistRun.user_id == user.id)
    if status_filter:
        query = query.where(CoScientistRun.status == status_filter)

    # 总数
    count_query = select(func.count()).select_from(CoScientistRun).where(
        CoScientistRun.user_id == user.id
    )
    if status_filter:
        count_query = count_query.where(CoScientistRun.status == status_filter)
    total = (await db.execute(count_query)).scalar() or 0

    # 分页
    offset = (page - 1) * page_size
    query = query.order_by(CoScientistRun.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    runs = result.scalars().all()

    return RunListResponse(
        items=[RunResponse.model_validate(r) for r in runs],
        total=total,
        page=page,
        page_size=page_size,
    )


# ========== 3. 运行详情 ==========

@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取运行详情"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    # 合并活跃 tracker 的实时数据
    resp = RunResponse.model_validate(run)
    tracker = _get_tracker(str(run_id))
    if tracker and run.status == RunStatus.RUNNING:
        resp.current_round = tracker.current_round
        resp.current_phase = tracker.current_phase
        resp.total_cost_usd = tracker.total_cost_usd

    return resp


# ========== 4. 取消运行 ==========

@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """取消运行"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    if run.status in (RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED):
        raise HTTPException(status_code=400, detail=f"运行已结束（状态: {run.status}）")

    run.status = RunStatus.CANCELLED
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)

    # 清理活跃引用
    _active_supervisors.pop(str(run_id), None)

    return RunResponse.model_validate(run)


@router.delete("/runs/{run_id}", summary="删除运行")
async def delete_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除 Co-Scientist 运行记录

    - 清理活跃的 supervisor / tracker / WS 客户端
    - 级联删除辩论日志（debate_logs 配置了 cascade=all,delete-orphan）
    - 关联的假设（Hypothesis）保留，仅解除关联（coscientist_run_id 置 NULL），
      避免删除已沉淀的研究成果
    """
    from app.models.hypothesis import Hypothesis

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    # 若运行中，先清理活跃引用（避免后台任务继续写入已删除的记录）
    _active_supervisors.pop(str(run_id), None)
    _active_trackers.pop(str(run_id), None)
    _ws_clients.pop(str(run_id), None)

    # 解除关联假设（保留假设，仅置空 coscientist_run_id）
    await db.execute(
        Hypothesis.__table__.update()
        .where(Hypothesis.coscientist_run_id == run_id)
        .values(coscientist_run_id=None)
    )

    # 删除运行（debate_logs 级联删除）
    await db.delete(run)
    await db.commit()

    return {"message": f"运行 {run_id} 已删除"}


# ========== 5. 提交专家反馈 ==========

@router.post("/runs/{run_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    run_id: uuid.UUID,
    body: FeedbackPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交专家反馈（用于 interactive 模式）"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    if run.status != RunStatus.AWAITING_FEEDBACK and run.status != RunStatus.RUNNING:
        raise HTTPException(status_code=400, detail="运行未在等待反馈状态")

    # 注入反馈到 Supervisor
    supervisor = _get_supervisor(str(run_id))
    if supervisor:
        supervisor.inject_feedback(body.feedback_text)
    else:
        logger.warning("[coscientist] 运行 %s 的 Supervisor 不在活跃列表中", run_id)

    # 持久化反馈记录
    feedback_list = run.expert_feedback or []
    feedback_list.append({
        "round": run.current_round,
        "feedback_text": body.feedback_text,
        "feedback_type": body.feedback_type,
        "target_hypothesis_id": str(body.target_hypothesis_id) if body.target_hypothesis_id else None,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": str(user.id),
    })
    run.expert_feedback = feedback_list
    await db.commit()

    return FeedbackResponse(
        accepted=True,
        message="反馈已接收，将在下一轮迭代中应用",
        applied_round=run.current_round + 1,
    )

# ========== 6. 假设列表 ==========

@router.get("/runs/{run_id}/hypotheses", response_model=List[RankedHypothesisView])
async def list_hypotheses(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取运行的所有假设（按 Elo 排序）"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    result = await db.execute(
        select(Hypothesis)
        .where(Hypothesis.coscientist_run_id == run_id)
        .order_by(Hypothesis.elo_score.desc().nullslast())
    )
    hyps = result.scalars().all()
    return [RankedHypothesisView.model_validate(h) for h in hyps]


# ========== 7. 假设详情 ==========

@router.get("/runs/{run_id}/hypotheses/{hyp_id}", response_model=RankedHypothesisView)
async def get_hypothesis(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取假设详情"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    result = await db.execute(
        select(Hypothesis).where(
            and_(Hypothesis.id == hyp_id, Hypothesis.coscientist_run_id == run_id)
        )
    )
    hyp = result.scalar_one_or_none()
    if not hyp:
        raise HTTPException(status_code=404, detail="假设不存在")
    return RankedHypothesisView.model_validate(hyp)


# ========== 8. 排名 ==========

@router.get("/runs/{run_id}/rankings", response_model=RankingsResponse)
async def get_rankings(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前排名"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    result = await db.execute(
        select(Hypothesis)
        .where(Hypothesis.coscientist_run_id == run_id)
        .order_by(Hypothesis.elo_score.desc().nullslast())
    )
    hyps = result.scalars().all()
    rankings = []
    for idx, h in enumerate(hyps, 1):
        view = RankedHypothesisView.model_validate(h)
        view.rank = idx
        rankings.append(view)

    return RankingsResponse(
        run_id=run_id,
        round_num=run.current_round,
        rankings=rankings,
        total_hypotheses=len(rankings),
    )


# ========== 9. 辩论日志 ==========

@router.get("/runs/{run_id}/debates", response_model=DebateListResponse)
async def list_debates(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取辩论日志"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    result = await db.execute(
        select(CoScientistDebateLog)
        .where(CoScientistDebateLog.run_id == run_id)
        .order_by(CoScientistDebateLog.round_num, CoScientistDebateLog.created_at)
    )
    logs = result.scalars().all()
    return DebateListResponse(
        run_id=run_id,
        debates=[DebateLogView.model_validate(l) for l in logs],
        total=len(logs),
    )


# ========== 10. 进度 ==========

@router.get("/runs/{run_id}/progress")
async def get_progress(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取实时进度"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    tracker = _get_tracker(str(run_id))
    if tracker:
        return {
            "run_id": str(run_id),
            "status": run.status,
            **tracker.get_progress(),
            "recent_events": tracker.get_recent_events(20),
        }
    return {
        "run_id": str(run_id),
        "status": run.status,
        "current_round": run.current_round,
        "current_phase": run.current_phase,
        "recent_events": [],
    }


# ========== 11. 元评审 ==========

@router.get("/runs/{run_id}/meta-review", response_model=MetaReviewResponse)
async def get_meta_review(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取 Meta-review 报告"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    if not run.meta_review:
        raise HTTPException(status_code=404, detail="Meta-review 尚未生成")

    return MetaReviewResponse(
        run_id=run_id,
        meta_review=run.meta_review,
        final_rankings=run.final_rankings,
        total_cost_usd=run.total_cost_usd,
        duration_sec=run.duration_sec,
        completed_at=run.completed_at,
    )


# ========== 12. 统计 + Agent 活动 ==========

@router.get("/runs/{run_id}/stats", response_model=AgentActivityFeedResponse)
async def get_stats(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取运行统计和 Agent 活动状态"""
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)

    supervisor = _get_supervisor(str(run_id))
    agents = []
    if supervisor:
        stats = supervisor.get_agent_stats()
        for name, s in stats.items():
            agents.append(AgentActivity(
                agent_name=name,
                status="running" if s["call_count"] > 0 else "idle",
                token_usage={"total": s["total_tokens"]},
                cost_usd=s["total_cost_usd"],
            ))

    return AgentActivityFeedResponse(
        run_id=run_id,
        agents=agents,
        current_phase=run.current_phase,
        current_round=run.current_round,
    )


# ========== 13. 案例列表 ==========

@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    user: User = Depends(get_current_user),
):
    """获取可用案例列表

    返回三个验证案例（AML/肝纤维化/AMR）的元数据，
    包括研究目标模板和预期基准。案例适配器位于 app.services.coscientist.cases。
    """
    cases = [CaseInfo(**info) for info in get_all_case_info()]
    return CaseListResponse(cases=cases)


# ========== 13b. 进化树 ==========

@router.get("/runs/{run_id}/evolution-tree", response_model=EvolutionTreeResponse)
async def get_evolution_tree(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取假设进化树

    返回节点（假设）和边（父子关系），用于前端可视化进化树。
    """
    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    result = await db.execute(
        select(Hypothesis)
        .where(Hypothesis.coscientist_run_id == run.id)
        .order_by(Hypothesis.elo_score.desc())
    )
    hypotheses = result.scalars().all()

    nodes = []
    edges = []
    for hyp in hypotheses:
        parent_ids = hyp.parent_ids or []
        strategy = hyp.evolution_strategy or "initial"
        # round_num 从 evolution_history 推断
        round_num = 0
        if hyp.evolution_history:
            for entry in hyp.evolution_history:
                if isinstance(entry, dict) and "round" in entry:
                    round_num = max(round_num, entry.get("round", 0))

        nodes.append(EvolutionNode(
            hypothesis_id=str(hyp.id),
            name=hyp.name,
            evolution_strategy=strategy,
            parent_ids=[str(p) for p in parent_ids],
            elo_score=float(hyp.elo_score or 1000.0),
            round_num=round_num,
            rank=hyp.rank,
        ))

        for pid in parent_ids:
            edges.append(EvolutionEdge(
                from_id=str(pid),
                to_id=str(hyp.id),
                strategy=strategy,
            ))

    return EvolutionTreeResponse(
        run_id=run.id,
        nodes=nodes,
        edges=edges,
        total_rounds=run.current_round,
    )



# ========== 13c. AI 智能生成研究目标 ==========

@router.post("/generate-goal", response_model=StandardResponse)
async def generate_research_goal(
    body: GenerateGoalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI 智能生成研究目标和框架

    基于用户输入的研究主题，调用 LLM 生成：
    - 结构化的研究目标文本（可直接用于创建 Co-Scientist 运行）
    - 研究框架要点
    - 关键科学问题
    - 内容建议和推荐参数

    若关联了项目，会收集项目前期数据作为上下文，使生成更具针对性。
    """
    import json as _json

    llm_client = await get_llm_client_with_fallback(db)

    # 收集项目上下文（若有关联项目）
    project_context = ""
    if body.project_id:
        try:
            project_context = await _collect_project_evidence(str(body.project_id))
        except Exception as e:
            logger.warning("[coscientist] 生成目标时收集项目上下文失败: %s", e)

    # 构建提示词
    system_prompt = """你是一位资深的药物研发科学顾问。根据用户的研究主题，生成结构化的研究目标和框架。

请严格按照以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{
  "research_goal": "一段 100-300 字的详细研究目标描述",
  "suggested_case_type": "建议的案例类型: aml/liver_fibrosis/amr/custom 之一",
  "suggested_max_rounds": 3,
  "suggested_initial_count": 5,
  "framework": ["研究框架要点1", "要点2", "要点3"],
  "key_questions": ["关键科学问题1", "问题2", "问题3"],
  "content_suggestions": ["内容建议1", "建议2", "建议3"]
}

要求：
1. research_goal 必须是具体、可操作的科学假设目标，包含疾病/靶点/机制等关键信息
2. framework 列出 3-5 个研究方向或方法要点
3. key_questions 列出 2-4 个核心科学问题
4. content_suggestions 列出 2-4 个具体建议（如数据库、方法、验证策略）
5. suggested_max_rounds 范围 1-10，suggested_initial_count 范围 3-10
"""

    user_prompt = f"研究主题：{body.topic}\n"
    if body.case_type:
        user_prompt += f"\n参考案例风格：{body.case_type}\n"
    if project_context:
        user_prompt += f"\n--- 项目前期数据 ---\n{project_context[:3000]}\n"
        user_prompt += "\n请基于上述项目数据生成更有针对性的研究目标。\n"

    try:
        result = await llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        content = result.get("content", "").strip()

        # 清理可能的 markdown 代码块标记
        if content.startswith("```"):
            content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        elif content.endswith("```"):
            content = content[:-3].strip()

        # 尝试解析 JSON
        try:
            parsed = _json.loads(content)
        except _json.JSONDecodeError:
            # 尝试提取 JSON 部分
            import re
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                parsed = _json.loads(json_match.group())
            else:
                # 降级：直接使用原始文本作为研究目标
                logger.warning("[coscientist] AI 生成目标 JSON 解析失败，使用原始文本")
                parsed = {"research_goal": content[:500] if content else body.topic}

        # 确保必填字段存在
        if not parsed.get("research_goal") or len(parsed["research_goal"]) < 10:
            parsed["research_goal"] = f"针对「{body.topic}」的研究：探索相关分子机制、发现潜在靶点和候选药物，并评估其疗效与安全性。"

        # 规范化参数范围
        parsed["suggested_max_rounds"] = max(1, min(10, int(parsed.get("suggested_max_rounds", 3))))
        parsed["suggested_initial_count"] = max(3, min(10, int(parsed.get("suggested_initial_count", 5))))

        response = GenerateGoalResponse(
            research_goal=parsed["research_goal"],
            suggested_case_type=parsed.get("suggested_case_type"),
            suggested_max_rounds=parsed["suggested_max_rounds"],
            suggested_initial_count=parsed["suggested_initial_count"],
            framework=parsed.get("framework", []),
            key_questions=parsed.get("key_questions", []),
            content_suggestions=parsed.get("content_suggestions", []),
        )

        return StandardResponse(data=response, message="AI 研究目标生成成功")

    except Exception as e:
        logger.exception("[coscientist] AI 生成研究目标失败: %s", e)
        # 降级：返回基于模板的简单目标
        fallback_goal = f"针对「{body.topic}」的研究：基于多组学数据分析发现潜在靶点，设计候选分子，并通过实验验证其疗效与安全性机制。"
        response = GenerateGoalResponse(
            research_goal=fallback_goal,
            suggested_case_type="custom",
            suggested_max_rounds=3,
            suggested_initial_count=5,
            framework=["靶点发现与验证", "候选分子设计", "疗效与安全性评估"],
            key_questions=[f"{body.topic} 的核心分子机制是什么？"],
            content_suggestions=["结合多组学数据进行综合分析"],
        )
        return StandardResponse(data=response, message="AI 生成失败，已使用降级模板")


# ========== 13d. 综合性研究模板 ==========

@router.get("/comprehensive-template", response_model=StandardResponse)
async def get_comprehensive_template(
    user: User = Depends(get_current_user),
):
    """获取综合性研究模板

    整合 AML 药物重定位、肝纤维化靶点发现、AMR 基因转移机制三个验证模板的核心特性，
    形成一个统一的综合性模板，保留各模板的核心功能特性。
    """
    all_cases = get_all_case_info()

    # 合并所有模板的关键特性
    merged_framework = []
    merged_questions = []
    merged_benchmarks = {}
    for info in all_cases:
        name = info.get("name", "")
        desc = info.get("description", "")
        ct = info.get("case_type", "")
        merged_framework.append(f"[{name}] {desc}")
        merged_benchmarks[ct] = info.get("expected_benchmarks", {})
    comprehensive = {
        "case_type": "comprehensive",
        "name": "综合性药物研发研究模板",
        "description": "整合药物重定位、靶点发现、机制研究三大方向的综合性研究模板，适用于从靶点发现到药物设计的全流程研究。",
        "research_goal_template": (
            "开展综合性药物研发研究：1) 基于多组学数据（转录组/蛋白组/代谢组）识别疾病相关靶点和信号通路；"
            "2) 针对关键靶点设计或重定位候选药物分子，评估其药代动力学特性和成药性；"
            "3) 通过分子对接、实验验证等手段评估候选分子的疗效与安全性；"
            "4) 综合分析机制、疗效、安全性数据，形成完整的研究假设和治疗方案建议。"
        ),
        "expected_benchmarks": merged_benchmarks,
        "sub_templates": [
            {"case_type": c.get("case_type"), "name": c.get("name"), "description": c.get("description")}
            for c in all_cases
        ],
        "framework": [
            "多组学数据分析与靶点发现",
            "候选分子设计与药物重定位",
            "分子对接与成药性评估",
            "实验验证与疗效评估",
            "综合机制分析与假设生成",
        ],
        "config_presets": {
            "quick": {"max_rounds": 2, "initial_count": 5, "description": "快速探索"},
            "standard": {"max_rounds": 3, "initial_count": 5, "description": "标准研究"},
            "deep": {"max_rounds": 5, "initial_count": 8, "description": "深度研究"},
        },
    }

    return StandardResponse(data=comprehensive, message="综合性模板获取成功")


# ========== 14. WebSocket 实时进度 ==========

@router.websocket("/runs/{run_id}/ws")
async def run_websocket(
    websocket: WebSocket,
    run_id: str,
):
    """WebSocket 实时推送运行进度

    客户端连接后自动订阅指定 run 的事件。
    可发送 feedback 消息提交专家反馈。
    """
    await websocket.accept()

    # 注册客户端
    if run_id not in _ws_clients:
        _ws_clients[run_id] = set()
    _ws_clients[run_id].add(websocket)

    try:
        # 推送当前进度快照
        tracker = _get_tracker(run_id)
        if tracker:
            import json
            snapshot = {
                "type": "progress_snapshot",
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    **tracker.get_progress(),
                    "recent_events": tracker.get_recent_events(10),
                },
            }
            await websocket.send_text(json.dumps(snapshot, ensure_ascii=False, default=str))

        # 监听客户端消息
        while True:
            data = await websocket.receive_text()
            import json
            try:
                msg = json.loads(data)
                if msg.get("type") == "feedback":
                    supervisor = _get_supervisor(run_id)
                    if supervisor:
                        supervisor.inject_feedback(msg.get("payload", {}).get("feedback_text", ""))
                        await websocket.send_text(json.dumps({
                            "type": "feedback_accepted",
                            "run_id": run_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False))
                    else:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "run_id": run_id,
                            "payload": {"error": "运行未在活跃状态"},
                        }, ensure_ascii=False))
                elif msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "run_id": run_id,
                    }, ensure_ascii=False))
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "payload": {"error": "无效的 JSON"},
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("[coscientist] WebSocket 断开: run %s", run_id)
    except Exception as e:
        logger.exception("[coscientist] WebSocket 错误: %s", e)
    finally:
        _ws_clients.get(run_id, set()).discard(websocket)

# ========== Phase B3: 下游集成 — 假设→实体 promote 端点 ==========
# 将 Co-Scientist 产出的高排名假设转化为可执行的下游实体（靶点/分子/实验/治疗），
# 形成「假设→验证→反馈」的完整闭环。


class PromoteTargetRequest(BaseModel):
    """假设→靶点 promote 请求"""
    gene_symbol: Optional[str] = Field(None, description="靶点基因符号（默认取假设 target_list 首项）")
    name: Optional[str] = Field(None, description="靶点名称（默认由基因符号生成）")
    confidence_override: Optional[float] = Field(None, ge=0, le=1, description="置信度覆盖（默认由 Elo 评分映射）")


class PromoteMoleculeRequest(BaseModel):
    """假设→分子 promote 请求"""
    target_id: UUID = Field(..., description="关联靶点 ID（分子必须挂载到靶点）")
    smiles: Optional[str] = Field(None, description="种子分子 SMILES（默认留空由设计引擎生成）")
    name: Optional[str] = Field(None, description="分子名称")


class PromoteExperimentRequest(BaseModel):
    """假设→实验 promote 请求（Phase B4 反馈闭环核心）"""
    name: str = Field(..., min_length=1, max_length=200, description="实验名称")
    exp_type: str = Field(..., description="实验类型: cytotoxicity/apoptosis/pdx/in_vivo 等")
    target_id: Optional[UUID] = Field(None, description="关联靶点 ID")
    molecule_id: Optional[UUID] = Field(None, description="关联分子 ID")
    treatment_id: Optional[UUID] = Field(None, description="关联治疗方案 ID")
    config: Optional[Dict[str, Any]] = Field(None, description="实验配置")
    notes: Optional[str] = Field(None, description="实验备注")


class PromoteTreatmentRequest(BaseModel):
    """假设→治疗 promote 请求"""
    name: Optional[str] = Field(None, description="治疗方案名称（默认由假设策略生成）")
    therapy_type: str = Field(..., description="治疗类型: targeted_therapy/immunotherapy/chemotherapy 等")
    description: Optional[str] = Field(None, description="治疗描述（默认取假设 mechanism）")


async def _get_hypothesis_or_404(
    db: AsyncSession, run_id: uuid.UUID, hyp_id: uuid.UUID
) -> Hypothesis:
    """获取假设并校验归属运行"""
    result = await db.execute(
        select(Hypothesis).where(
            and_(Hypothesis.id == hyp_id, Hypothesis.coscientist_run_id == run_id)
        )
    )
    hyp = result.scalar_one_or_none()
    if not hyp:
        raise HTTPException(status_code=404, detail="假设不存在或不属于该运行")
    return hyp


@router.post("/runs/{run_id}/hypotheses/{hyp_id}/promote-target", summary="假设→靶点转化")
async def promote_hypothesis_to_target(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    body: PromoteTargetRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将 Co-Scientist 假设转化为药物靶点

    从假设的 target_list 提取候选基因，创建 Target 实体。
    置信度由 Elo 评分映射：confidence = min(0.99, 0.5 + (elo - 1000) / 2000)。
    """
    from app.models.target import Target

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    hyp = await _get_hypothesis_or_404(db, run_id, hyp_id)

    if not hyp.project_id:
        raise HTTPException(status_code=400, detail="假设未关联项目，无法 promote（请创建运行时指定 project_id）")

    target_list = hyp.target_list or []
    gene_symbol = body.gene_symbol
    if not gene_symbol:
        if not target_list:
            raise HTTPException(status_code=400, detail="假设无候选靶点，请手动指定 gene_symbol")
        first = target_list[0]
        gene_symbol = first if isinstance(first, str) else first.get("gene_symbol") or first.get("name")
        if not gene_symbol:
            raise HTTPException(status_code=400, detail="假设 target_list 无有效基因符号")

    # Elo → 置信度映射
    confidence = body.confidence_override
    if confidence is None:
        elo = float(hyp.elo_score or 1000.0)
        confidence = max(0.1, min(0.99, 0.5 + (elo - 1000.0) / 2000.0))

    target = Target(
        project_id=hyp.project_id,
        gene_symbol=str(gene_symbol)[:50],
        gene_name=body.name or f"{gene_symbol} (Co-Sci 假设来源)",
        confidence_score=confidence,
        source="coscientist",
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)

    # 记录到假设的 evolution_history
    history = hyp.evolution_history or []
    history.append({
        "action": "promote_target",
        "target_id": str(target.id),
        "gene_symbol": gene_symbol,
        "confidence": confidence,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by": str(user.id),
    })
    hyp.evolution_history = history
    await db.commit()

    return {
        "message": "假设已转化为靶点",
        "hypothesis_id": str(hyp.id),
        "target_id": str(target.id),
        "gene_symbol": target.gene_symbol,
        "confidence_score": confidence,
    }


@router.post("/runs/{run_id}/hypotheses/{hyp_id}/promote-molecule", summary="假设→分子转化")
async def promote_hypothesis_to_molecule(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    body: PromoteMoleculeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将 Co-Scientist 假设转化为候选分子

    创建 Molecule 实体并关联到指定靶点。
    若提供 smiles 则直接存储，否则标记为待设计（design_strategy=coscientist）。
    """
    from app.models.molecule import Molecule
    from app.models.target import Target

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    hyp = await _get_hypothesis_or_404(db, run_id, hyp_id)

    # 校验靶点归属
    target = await db.get(Target, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="靶点不存在")
    if target.project_id != hyp.project_id and user.role != UserRole.FOUNDER:
        raise HTTPException(status_code=403, detail="靶点与假设不属于同一项目")

    smiles = body.smiles or ""
    mol = Molecule(
        target_id=target.id,
        smiles=smiles,
        name=body.name or f"Co-Sci候选-{str(hyp.id)[:8]}",
        properties={
            "source": "coscientist",
            "hypothesis_id": str(hyp.id),
            "hypothesis_name": hyp.name,
            "elo_score": float(hyp.elo_score or 1000.0),
            "mechanism": hyp.mechanism,
            "needs_design": not bool(smiles),
        },
        designed_by="coscientist_promote",
        source="coscientist",
    )
    db.add(mol)
    await db.commit()
    await db.refresh(mol)

    history = hyp.evolution_history or []
    history.append({
        "action": "promote_molecule",
        "molecule_id": str(mol.id),
        "target_id": str(target.id),
        "smiles": smiles,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by": str(user.id),
    })
    hyp.evolution_history = history
    await db.commit()

    return {
        "message": "假设已转化为分子",
        "hypothesis_id": str(hyp.id),
        "molecule_id": str(mol.id),
        "target_id": str(target.id),
        "smiles": smiles,
        "needs_design": not bool(smiles),
    }


@router.post("/runs/{run_id}/hypotheses/{hyp_id}/promote-experiment", summary="假设→实验转化（反馈闭环）")
async def promote_hypothesis_to_experiment(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    body: PromoteExperimentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将 Co-Scientist 假设转化为湿实验任务（Phase B4 反馈闭环核心）

    创建 Experiment 实体并设置 hypothesis_id 关联，
    实验完成后可通过 /hypotheses/{hyp_id}/feedback 端点将结果反馈到假设评估。
    """
    from app.models.experiment import Experiment, ExperimentStatus

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    hyp = await _get_hypothesis_or_404(db, run_id, hyp_id)

    if not hyp.project_id:
        raise HTTPException(status_code=400, detail="假设未关联项目，无法 promote")

    exp = Experiment(
        project_id=hyp.project_id,
        name=body.name,
        exp_type=body.exp_type,
        status=ExperimentStatus.PLANNED,
        target_id=body.target_id,
        molecule_id=body.molecule_id,
        treatment_id=body.treatment_id,
        hypothesis_id=hyp.id,  # Phase B4 反馈闭环关键字段
        config=body.config or {
            "source": "coscientist",
            "hypothesis_name": hyp.name,
            "elo_score": float(hyp.elo_score or 1000.0),
        },
        notes=body.notes or f"源于 Co-Scientist 假设: {hyp.name}",
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)

    history = hyp.evolution_history or []
    history.append({
        "action": "promote_experiment",
        "experiment_id": str(exp.id),
        "exp_type": body.exp_type,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by": str(user.id),
    })
    hyp.evolution_history = history
    await db.commit()

    return {
        "message": "假设已转化为实验任务（反馈闭环已建立）",
        "hypothesis_id": str(hyp.id),
        "experiment_id": str(exp.id),
        "exp_type": body.exp_type,
        "feedback_endpoint": f"POST /api/v1/coscientist/runs/{run_id}/hypotheses/{hyp_id}/experiment-feedback",
    }


@router.post("/runs/{run_id}/hypotheses/{hyp_id}/promote-treatment", summary="假设→治疗方案转化")
async def promote_hypothesis_to_treatment(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    body: PromoteTreatmentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将 Co-Scientist 假设转化为治疗方案

    从假设的 strategy/mechanism 提取治疗方向，创建 Treatment 实体。
    """
    from app.models.treatment import Treatment

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    hyp = await _get_hypothesis_or_404(db, run_id, hyp_id)

    if not hyp.project_id:
        raise HTTPException(status_code=400, detail="假设未关联项目，无法 promote")

    treatment = Treatment(
        project_id=hyp.project_id,
        name=body.name or f"Co-Sci治疗方案-{str(hyp.id)[:8]}",
        therapy_type=body.therapy_type,
        hypothesis_id=hyp.id,
        notes=body.description or hyp.mechanism or hyp.description,
    )
    db.add(treatment)
    await db.commit()
    await db.refresh(treatment)

    history = hyp.evolution_history or []
    history.append({
        "action": "promote_treatment",
        "treatment_id": str(treatment.id),
        "therapy_type": body.therapy_type,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by": str(user.id),
    })
    hyp.evolution_history = history
    await db.commit()

    return {
        "message": "假设已转化为治疗方案",
        "hypothesis_id": str(hyp.id),
        "treatment_id": str(treatment.id),
        "therapy_type": body.therapy_type,
    }


# ========== Phase B4: 反馈闭环 — 实验结果→假设评估 ==========

class ExperimentFeedbackRequest(BaseModel):
    """实验结果反馈到假设评估"""
    experiment_id: UUID = Field(..., description="已完成的实验 ID")
    success: bool = Field(..., description="实验是否验证了假设")
    result_summary: str = Field(..., min_length=1, max_length=5000, description="实验结果摘要")
    elo_delta: Optional[float] = Field(None, description="手动指定 Elo 增量（默认自动计算）")


@router.post("/runs/{run_id}/hypotheses/{hyp_id}/experiment-feedback", summary="实验结果→假设反馈")
async def submit_experiment_feedback(
    run_id: uuid.UUID,
    hyp_id: uuid.UUID,
    body: ExperimentFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将湿实验结果反馈到 Co-Scientist 假设评估（Phase B4 反馈闭环）

    实验成功 → Elo +50~100（基于当前评分动态调整）
    实验失败 → Elo -30~80
    反馈记录到 hypothesis.evolution_history 和 critique_summary。
    """
    from app.models.experiment import Experiment, ExperimentStatus

    run = await _get_run_or_404(db, run_id)
    await _verify_run_owner(run, user)
    hyp = await _get_hypothesis_or_404(db, run_id, hyp_id)

    exp = await db.get(Experiment, body.experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="实验不存在")
    if exp.hypothesis_id != hyp.id:
        raise HTTPException(status_code=400, detail="实验与假设无关联")
    if exp.status != ExperimentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"实验未完成（当前状态: {exp.status}），无法反馈")

    # 计算 Elo 增量
    if body.elo_delta is not None:
        delta = body.elo_delta
    else:
        current_elo = float(hyp.elo_score or 1000.0)
        # 动态 K 因子：低分假设变化大，高分假设变化小
        k_factor = 64.0 if current_elo < 1200 else 32.0
        if body.success:
            delta = k_factor * (1.0 - 0.3)  # 验证成功，正向反馈
        else:
            delta = -k_factor * 0.6  # 验证失败，负向反馈

    old_elo = float(hyp.elo_score or 1000.0)
    new_elo = max(0.0, old_elo + delta)
    hyp.elo_score = new_elo

    # 调整可信度评分
    if body.success:
        hyp.plausibility_score = min(10.0, float(hyp.plausibility_score or 5.0) + 1.0)
    else:
        hyp.plausibility_score = max(0.0, float(hyp.plausibility_score or 5.0) - 1.5)

    # 记录到 evolution_history
    history = hyp.evolution_history or []
    history.append({
        "action": "experiment_feedback",
        "experiment_id": str(exp.id),
        "success": body.success,
        "result_summary": body.result_summary,
        "elo_before": old_elo,
        "elo_after": new_elo,
        "elo_delta": delta,
        "feedback_at": datetime.now(timezone.utc).isoformat(),
        "feedback_by": str(user.id),
    })
    hyp.evolution_history = history

    # 更新批判摘要
    feedback_line = f"\n[实验反馈 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {'✓ 验证成功' if body.success else '✗ 验证失败'}: {body.result_summary}"
    hyp.critique_summary = (hyp.critique_summary or "") + feedback_line

    # 标记实验已反馈
    exp.feedback_applied = True

    await db.commit()

    return {
        "message": "实验结果已反馈到假设评估",
        "hypothesis_id": str(hyp.id),
        "experiment_id": str(exp.id),
        "elo_before": round(old_elo, 2),
        "elo_after": round(new_elo, 2),
        "elo_delta": round(delta, 2),
        "plausibility_score": float(hyp.plausibility_score or 0),
        "success": body.success,
    }


# ========== Phase D: 根路由 + 健康检查 ==========

@router.get("/evidence-preview", summary="预览项目推理证据")
async def preview_project_evidence(
    project_id: UUID = Query(..., description="项目 ID"),
    user: User = Depends(get_current_user),
):
    """预览将用于 Co-Scientist 推理的项目前期数据

    让用户在创建运行前查看哪些分析结果会被整合到推理引擎中，
    确保推理过程可追溯、结果可解释。
    """
    evidence_text = await _collect_project_evidence(str(project_id))
    return {
        "project_id": str(project_id),
        "evidence_text": evidence_text,
        "evidence_length": len(evidence_text),
        "has_evidence": bool(evidence_text),
    }


@router.get("", summary="Co-Scientist 模块概览")
async def coscientist_overview(
    user: User = Depends(get_current_user),
):
    """Co-Scientist 模块根路由 — 返回模块信息和可用端点

    提供 API 导航，方便前端和开发者快速了解 Co-Scientist 模块的能力。
    """
    return {
        "module": "Co-Scientist",
        "version": "1.0",
        "description": "多智能体科学推理引擎 — 基于 Nature 论文的结构化科学思维，整合项目前期所有分析数据进行综合推理",
        "capabilities": [
            "多假设并行生成与进化",
            "科学辩论机制（正方/反方/裁判）",
            "Elo 锦标赛排名",
            "专家反馈循环",
            "假设→实体 promote（靶点/分子/实验/治疗）",
            "实验结果→假设 Elo 反馈闭环",
            "WebSocket 实时进度推送",
            "项目前期数据整合推理（靶点/分子/DE基因/通路/治疗/实验）",
        ],
        "endpoints": {
            "runs": "POST/GET /runs, GET/POST /runs/{id}, /runs/{id}/cancel",
            "hypotheses": "GET /runs/{id}/hypotheses, /runs/{id}/hypotheses/{hid}",
            "rankings": "GET /runs/{id}/rankings",
            "debates": "GET /runs/{id}/debates",
            "progress": "GET /runs/{id}/progress",
            "meta_review": "GET /runs/{id}/meta-review",
            "evolution_tree": "GET /runs/{id}/evolution-tree",
            "promote": "POST /runs/{id}/hypotheses/{hid}/promote-{target|molecule|experiment|treatment}",
            "feedback": "POST /runs/{id}/hypotheses/{hid}/experiment-feedback",
            "websocket": "WS /runs/{id}/ws",
            "cases": "GET /cases",
            "evidence_preview": "GET /evidence-preview?project_id=...",
        },
        "cases": ["aml", "liver_fibrosis", "amr", "custom"],
    }


@router.get("/health", summary="Co-Scientist 健康检查")
async def coscientist_health():
    """Co-Scientist 模块健康检查

    返回模块运行状态、活跃运行数、缓存统计等。
    """
    from app.core.llm.cache import llm_cache

    return {
        "status": "healthy",
        "active_supervisors": len(_active_supervisors),
        "active_trackers": len(_active_trackers),
        "websocket_clients": sum(len(clients) for clients in _ws_clients.values()),
        "llm_cache": llm_cache.stats(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ========== Phase B5: 报告导出端点（SDTM HO 域 / FHIR ResearchStudy / Markdown） ==========


@router.post("/runs/{run_id}/export/sdtm", summary="导出运行结果为 SDTM（HO/TS/DL 域）")
async def export_run_sdtm(
    run_id: UUID,
    format: str = Query(
        "json",
        description="输出格式: json(默认,含域预览) 或 csv(纯 CSV 下载)",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 Co-Scientist 运行结果为 CDISC SDTM 格式

    自定义域：
    - HO（Hypothesis Outcomes）: 假设及评分、排名
    - TS（Trial Summary）: 运行元数据
    - DL（Debate Logs）: 辩论记录

    - format=json（默认）：返回 JSON 包含 CSV 文本 + 结构化域数据
    - format=csv：直接返回 text/csv 文件（前端触发下载）
    """
    from app.services.coscientist.exporters import CoScientistSDTMExporter
    from fastapi.responses import PlainTextResponse

    try:
        exporter = CoScientistSDTMExporter(db)
        sdtm_data = await exporter.export(run_id)
        csv_content = exporter.to_csv(sdtm_data)
    except Exception as e:
        logger.error("Co-Scientist SDTM 导出失败 (run=%s): %s", run_id, e, exc_info=True)
        return StandardResponse(
            success=False,
            message=f"SDTM 导出失败: {str(e)}",
            data={"run_id": str(run_id), "error": str(e)},
        )

    if format.lower() == "csv":
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=coscientist_sdtm_{run_id}.csv"
            },
        )

    return StandardResponse(
        message="Co-Scientist SDTM 导出完成",
        data={
            "csv": csv_content,
            "domains": sdtm_data.get("domains", {}),
            "metadata": sdtm_data.get("metadata", {}),
            "record_counts": sdtm_data.get("metadata", {}).get("record_counts", {}),
        },
    )


@router.post("/runs/{run_id}/export/fhir", summary="导出运行结果为 FHIR ResearchStudy Bundle")
async def export_run_fhir(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 Co-Scientist 运行结果为 HL7 FHIR R4 Bundle

    映射关系：
    - CoScientistRun → ResearchStudy
    - Hypothesis → ResearchSubject（每个假设一个）
    - 辩论日志 → ResearchStudy.note
    - 元评审 → ResearchStudy.objective
    """
    from app.services.coscientist.exporters import CoScientistFHIRExporter

    try:
        exporter = CoScientistFHIRExporter(db)
        bundle = await exporter.export_research_study(run_id)
    except Exception as e:
        logger.error("Co-Scientist FHIR 导出失败 (run=%s): %s", run_id, e, exc_info=True)
        return StandardResponse(
            success=False,
            message=f"FHIR 导出失败: {str(e)}",
            data={"run_id": str(run_id), "error": str(e)},
        )

    return StandardResponse(
        message="Co-Scientist FHIR ResearchStudy 导出完成",
        data=bundle,
    )


@router.get("/runs/{run_id}/export/markdown", summary="导出运行结果为 Markdown 报告")
async def export_run_markdown(
    run_id: UUID,
    top_n: int = Query(10, ge=1, le=100, description="显示前 N 个假设"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出 Co-Scientist 运行结果为 Markdown 综合报告

    生成人类可读的报告，包含：
    1. 基本信息（运行 ID、状态、案例类型）
    2. 假设排名表（Top N）
    3. 辩论摘要
    4. 元评审报告
    5. 资源消耗
    """
    from app.services.coscientist.exporters import CoScientistMarkdownExporter
    from fastapi.responses import PlainTextResponse

    try:
        exporter = CoScientistMarkdownExporter(db)
        markdown = await exporter.export_markdown(run_id, top_n=top_n)
    except Exception as e:
        logger.error("Co-Scientist Markdown 导出失败 (run=%s): %s", run_id, e, exc_info=True)
        return StandardResponse(
            success=False,
            message=f"Markdown 导出失败: {str(e)}",
            data={"run_id": str(run_id), "error": str(e)},
        )

    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=coscientist_report_{run_id}.md"
        },
    )
