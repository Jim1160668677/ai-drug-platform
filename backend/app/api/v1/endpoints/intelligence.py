"""统一智能系统 API 端点 — 22 个 REST 接口

融合 AI 问答 / 科学推理 / Agent 工作台 / 多模态 / 规则引擎的统一入口。

五大功能域（22 端点）：
1. 会话管理（4）：POST 创建 / GET 列表 / GET 详情 / PATCH 归档
2. 统一对话（3）：POST 对话 / POST 流式 / POST 强制模式
3. 上下文与追溯（5）：GET 上下文 / GET 追溯 / GET 步骤树 / GET 成本 / GET 决策链
4. 证据收集与分析（4）：POST 项目证据 / POST 实体上下文 / POST 解读 / POST 数据集解读
5. 多模态与规则引擎（6）：POST 标准化 / POST 视觉解析 / GET 规则列表 / GET 规则详情 / POST 执行 / POST 验证

设计规范：RESTful + 幂等 + 所有权校验 + 统一错误处理 + StandardResponse 信封。
"""
import logging
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import StandardResponse
from app.core.deps import get_current_user, get_llm_client_with_fallback
from app.core.config import settings
from app.core.security import UserRole
from app.db.session import get_db
from app.models.coscientist_run import CoScientistRun
from app.models.unified_session import PrimaryMode, UnifiedSession, UnifiedSessionStatus
from app.models.user import User
from app.schemas.intelligence import (
    AnalysisInterpretRequest, AnalysisInterpretResponse, ChatRequest, ChatResponse,
    ContextResponse, ContextMemoryItem, CostBreakdownResponse, DatasetInterpretRequest,
    DecisionChainResponse, EvidenceCollectRequest, EvidenceResponse, EvidenceSourceItem,
    ForceModeRequest, MultimodalNormalizeRequest, MultimodalNormalizeResponse,
    RuleExecuteRequest, RuleExecuteResponse, RuleExecutionResultItem, RuleListResponse,
    RuleResponse, RuleSetResponse, RuleValidateRequest, RuleValidateResponse,
    SessionArchive, SessionCreate,
    SessionListResponse, SessionResponse, TierSuggestRequest, TierSuggestResponse,
    TraceResponse, TraceStep, TraceTreeResponse,
    VisionAnalyzeRequest, VisionAnalyzeResponse,
)
from app.services.intelligence.analysis_service import AnalysisService
from app.services.intelligence.evidence_collector import EvidenceCollector
from app.services.intelligence.intent_router import IntentRouter
from app.services.intelligence.multimodal_normalizer import MultimodalNormalizer
from app.services.intelligence.orchestrator import UnifiedOrchestrator
from app.services.intelligence.rule_engine.engine import RuleEngine
from app.services.intelligence.rule_engine.loader import RuleLoader
from app.services.intelligence.vision_llm_client import VisionLLMClient

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 所有权校验 ==========

async def _get_session_or_404(db: AsyncSession, session_id: UUID, user: User) -> UnifiedSession:
    """获取会话并校验所有权"""
    result = await db.execute(
        select(UnifiedSession).where(UnifiedSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != user.id and user.role != "founder":
        raise HTTPException(status_code=403, detail="无权访问此会话")
    return session


async def _verify_trace_run_or_404(db: AsyncSession, run_id: UUID, user: User) -> None:
    """校验推理追溯 run_id 归属（CoScientistRun 或 UnifiedSession）"""
    result = await db.execute(
        select(CoScientistRun).where(CoScientistRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is not None:
        if run.user_id != user.id and user.role != UserRole.FOUNDER:
            raise HTTPException(status_code=403, detail="无权访问此运行")
        return

    result = await db.execute(
        select(UnifiedSession).where(UnifiedSession.id == run_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    if session.user_id != user.id and user.role != UserRole.FOUNDER:
        raise HTTPException(status_code=403, detail="无权访问此运行")


def _session_to_response(session: UnifiedSession) -> SessionResponse:
    return SessionResponse(
        id=session.id, user_id=session.user_id, project_id=session.project_id,
        title=session.title, status=session.status, primary_mode=session.primary_mode,
        context=session.context, last_message_at=session.last_message_at,
        message_count=session.message_count, created_at=session.created_at,
        updated_at=session.updated_at,
    )


# ========== 1. 会话管理（4 端点） ==========

@router.post("/sessions", response_model=StandardResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """1. 创建统一智能会话"""
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    session = await orchestrator.create_session(
        user=user, project_id=str(body.project_id) if body.project_id else None,
        title=body.title, primary_mode=body.primary_mode,
    )
    return StandardResponse(success=True, message="会话已创建", data=_session_to_response(session).model_dump(mode="json"))


@router.get("/sessions", response_model=StandardResponse)
async def list_sessions(
    project_id: Optional[UUID] = Query(None, description="按项目过滤"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """2. 列出当前用户的会话"""
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    sessions = await orchestrator.list_sessions(
        user=user, project_id=str(project_id) if project_id else None, limit=limit,
    )
    items = [_session_to_response(s) for s in sessions]
    return StandardResponse(
        success=True, data=SessionListResponse(items=items, total=len(items)).model_dump(mode="json"),
    )


@router.get("/sessions/{session_id}", response_model=StandardResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """3. 获取会话详情"""
    session = await _get_session_or_404(db, session_id, user)
    return StandardResponse(success=True, data=_session_to_response(session).model_dump(mode="json"))


@router.patch("/sessions/{session_id}", response_model=StandardResponse)
async def archive_session(
    session_id: UUID,
    body: SessionArchive,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """4. 归档/删除会话（幂等）"""
    session = await _get_session_or_404(db, session_id, user)
    if body.status not in (UnifiedSessionStatus.ARCHIVED, UnifiedSessionStatus.DELETED):
        raise HTTPException(status_code=422, detail="status 仅支持 archived/deleted")
    session.status = body.status
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return StandardResponse(success=True, message="会话状态已更新", data=_session_to_response(session).model_dump(mode="json"))


# ========== 2. 统一对话（3 端点） ==========

@router.post("/sessions/{session_id}/chat", response_model=StandardResponse)
async def chat(
    session_id: UUID,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """5. 统一对话入口（意图路由 → 分流 channel）"""
    session = await _get_session_or_404(db, session_id, user)
    llm_client = await get_llm_client_with_fallback(db)
    orchestrator = UnifiedOrchestrator(db, llm_client=llm_client)
    try:
        result = await orchestrator.chat(
            session_id=session.id, message=body.message, user=user,
            project_id=str(body.project_id) if body.project_id else None,
            force_mode=body.force_mode, tier=body.tier,
        )
    except Exception as e:
        logger.exception("[intelligence] 对话失败: %s", e)
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return StandardResponse(success=True, data=result)


@router.post("/sessions/{session_id}/stream")
async def chat_stream(
    session_id: UUID,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """6. 流式对话（SSE）

    返回 text/event-stream，每帧为一段流式回复。
    """
    session = await _get_session_or_404(db, session_id, user)
    llm_client = await get_llm_client_with_fallback(db)
    orchestrator = UnifiedOrchestrator(db, llm_client=llm_client)

    async def event_generator():
        try:
            # 使用 ChatChannel 的 stream_chat
            from app.services.intelligence.context_store import ContextMemoryStore
            ctx_store = ContextMemoryStore(db=db)
            from app.services.intelligence.trace_store import ReasoningTraceStore
            trace_store = ReasoningTraceStore(db=db)
            from app.services.intelligence.channels.chat import ChatChannel
            channel = ChatChannel(llm_client=llm_client, context_store=ctx_store, trace_store=trace_store)
            async for chunk in channel.stream_chat(
                session_id=session.id, message=body.message, user=user,
                project_id=str(body.project_id) if body.project_id else None,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("[intelligence] 流式对话失败: %s", e)
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/force-mode", response_model=StandardResponse)
async def force_mode(
    session_id: UUID,
    body: ForceModeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """7. 强制切换会话主模式（幂等）"""
    if body.mode not in (PrimaryMode.CHAT, PrimaryMode.REASONING, PrimaryMode.AGENT, "hybrid"):
        raise HTTPException(status_code=422, detail="mode 仅支持 chat/reasoning/agent/hybrid")
    session = await _get_session_or_404(db, session_id, user)
    session.primary_mode = body.mode
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return StandardResponse(success=True, message="主模式已切换", data={"primary_mode": session.primary_mode})


@router.post("/sessions/{session_id}/suggest-tier", response_model=StandardResponse)
async def suggest_tier(
    session_id: UUID,
    body: TierSuggestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """推荐档位 (零成本，仅 keyword 路由)"""
    _get_session_or_404(db, session_id, user)
    router = IntentRouter(llm_client=None)
    detail = router.suggest_tier_detail(body.message)
    tier = detail["tier"]
    tier_config = settings.LLM_TIERS.get(tier, settings.LLM_TIERS.get(settings.DEFAULT_LLM_TIER, {}))
    resp = TierSuggestResponse(
        tier=tier,
        reason=detail["reason"],
        confidence=detail["confidence"],
        tier_config=tier_config,
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


# ========== 3. 上下文与追溯（5 端点） ==========

@router.get("/sessions/{session_id}/context", response_model=StandardResponse)
async def get_context(
    session_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """8. 获取会话上下文记忆"""
    session = await _get_session_or_404(db, session_id, user)
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    ctx = await orchestrator.get_session_context(session.id)
    memories = [
        ContextMemoryItem(id=m["id"], type=m["type"], content=m["content"],
                          importance=m["importance"], created_at=m["created_at"])
        for m in ctx.get("memories", [])[:limit]
    ]
    resp = ContextResponse(session_id=str(session.id), memories=memories, context_prompt=ctx.get("context_prompt", ""))
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/sessions/{session_id}/trace", response_model=StandardResponse)
async def get_trace(
    session_id: UUID,
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """9. 获取会话推理追溯"""
    session = await _get_session_or_404(db, session_id, user)
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    trace_data = await orchestrator.get_session_trace(session.id)
    traces = [
        TraceStep(id=t["id"], step_type=t["step_type"], agent_name=t["agent_name"],
                  phase=t["phase"], round_num=t["round_num"], decision_basis=t["decision_basis"],
                  cost_usd=t["cost_usd"], duration_sec=t["duration_sec"],
                  status=t["status"], created_at=t["created_at"],
                  evidence=t.get("evidence"))
        for t in trace_data.get("traces", [])[:limit]
    ]
    resp = TraceResponse(session_id=str(session.id), total_steps=trace_data.get("total_steps", 0), traces=traces)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/runs/{run_id}/trace-tree", response_model=StandardResponse)
async def get_trace_tree(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """10. 获取推理运行的步骤树"""
    await _verify_trace_run_or_404(db, run_id, user)
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    tree = await orchestrator.get_run_trace_tree(run_id)
    resp = TraceTreeResponse(
        roots=tree.get("roots", []), total_steps=tree.get("total_steps", 0),
        total_cost=tree.get("total_cost", 0.0),
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/runs/{run_id}/cost", response_model=StandardResponse)
async def get_cost_breakdown(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """11. 获取推理运行的成本分解"""
    await _verify_trace_run_or_404(db, run_id, user)
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    cost = await orchestrator.get_run_cost_breakdown(run_id)
    resp = CostBreakdownResponse(
        total_cost=cost.get("total_cost", 0.0), total_tokens=cost.get("total_tokens", 0),
        by_agent=cost.get("by_agent", {}), by_phase=cost.get("by_phase", {}),
        by_step_type=cost.get("by_step_type", {}),
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/runs/{run_id}/decisions", response_model=StandardResponse)
async def get_decision_chain(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """12. 获取推理运行的决策链"""
    await _verify_trace_run_or_404(db, run_id, user)
    orchestrator = UnifiedOrchestrator(db, llm_client=None)
    decisions = await orchestrator.get_run_decision_chain(run_id)
    resp = DecisionChainResponse(decisions=decisions)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


# ========== 4. 证据收集与分析（4 端点） ==========

@router.post("/evidence/collect", response_model=StandardResponse)
async def collect_evidence(
    body: EvidenceCollectRequest,
    user: User = Depends(get_current_user),
):
    """13. 收集项目证据（EvidenceCollector 管道嵌入入口）"""
    if not body.project_id:
        raise HTTPException(status_code=422, detail="project_id 不能为空")
    collector = EvidenceCollector()
    bundle = await collector.collect_evidence_bundle(
        trigger_event=body.trigger_event,
        project_id=str(body.project_id),
        entity_id=str(body.entity_id) if body.entity_id else None,
        extra_evidence=body.extra_evidence,
    )
    resp = EvidenceResponse(
        text=bundle.text,
        sources=[EvidenceSourceItem(**s.__dict__) for s in bundle.sources],
        total_items=bundle.total_items,
        project_id=bundle.project_id, entity_id=bundle.entity_id, trigger_event=bundle.trigger_event,
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/evidence/collect-entity", response_model=StandardResponse)
async def collect_entity_context(
    body: EvidenceCollectRequest,
    user: User = Depends(get_current_user),
):
    """14. 收集触发实体的上下文证据"""
    if not body.trigger_event or not body.entity_id:
        raise HTTPException(status_code=422, detail="trigger_event 与 entity_id 不能为空")
    collector = EvidenceCollector()
    bundle = await collector.collect_entity_context_bundle(
        trigger_event=body.trigger_event,
        entity_id=str(body.entity_id),
        project_id=str(body.project_id) if body.project_id else None,
    )
    resp = EvidenceResponse(
        text=bundle.text,
        sources=[EvidenceSourceItem(**s.__dict__) for s in bundle.sources],
        total_items=bundle.total_items,
        project_id=bundle.project_id, entity_id=bundle.entity_id, trigger_event=bundle.trigger_event,
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/analysis/interpret", response_model=StandardResponse)
async def interpret_analysis(
    body: AnalysisInterpretRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """15. 统一解读分析（AnalysisService）"""
    llm_client = await get_llm_client_with_fallback(db)
    svc = AnalysisService(db=db, llm_client=llm_client)
    try:
        result = await svc.interpret(
            message=body.message,
            analysis_data=body.analysis_data,
            project_id=str(body.project_id) if body.project_id else None,
            intent=body.intent,
        )
    except Exception as e:
        logger.exception("[intelligence] 解读失败: %s", e)
        raise HTTPException(status_code=500, detail=f"解读失败: {str(e)}")
    resp = AnalysisInterpretResponse(**result)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/analysis/datasets/{dataset_id}/interpret", response_model=StandardResponse)
async def interpret_dataset(
    dataset_id: UUID,
    body: DatasetInterpretRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """16. 数据集解读（从 Dataset.parsed_summary 提取分析结果并解读）"""
    llm_client = await get_llm_client_with_fallback(db)
    svc = AnalysisService(db=db, llm_client=llm_client)
    try:
        result = await svc.analyze_dataset(
            dataset_id=str(dataset_id),
            message=body.message,
            project_id=str(body.project_id) if body.project_id else None,
        )
    except Exception as e:
        logger.exception("[intelligence] 数据集解读失败: %s", e)
        raise HTTPException(status_code=500, detail=f"数据集解读失败: {str(e)}")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    resp = AnalysisInterpretResponse(**result)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


# ========== 5. 多模态与规则引擎（6 端点） ==========

@router.post("/multimodal/normalize", response_model=StandardResponse)
async def normalize_multimodal(
    body: MultimodalNormalizeRequest,
    user: User = Depends(get_current_user),
):
    """17. 多模态数据标准化（MultimodalNormalizer）"""
    normalizer = MultimodalNormalizer()
    content = normalizer.normalize(
        text=body.text, image_paths=body.image_paths, image_urls=body.image_urls,
        image_base64=body.image_base64, file_paths=body.file_paths, structured_data=body.structured_data,
    )
    resp = MultimodalNormalizeResponse(
        items=[i.to_dict() for i in content.items],
        primary_text=content.primary_text, has_image=content.has_image,
        modalities=content.modalities, textualized=normalizer.textualize(content),
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/vision/analyze", response_model=StandardResponse)
async def analyze_vision(
    body: VisionAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """18. 视觉内容解析（VisionLLMClient — agnes-2.0-vision）"""
    llm_client = await get_llm_client_with_fallback(db)
    vision_client = VisionLLMClient(llm_client=llm_client)
    try:
        analysis_map = {
            "pathology": vision_client.analyze_pathology_image,
            "protein_structure": vision_client.analyze_protein_structure,
            "molecule_structure": vision_client.analyze_molecule_structure,
            "chart": vision_client.analyze_chart,
        }
        if body.analysis_type and body.analysis_type in analysis_map:
            result = await analysis_map[body.analysis_type](body.image_data_uri, body.focus or body.prompt)
        else:
            result = await vision_client.analyze_image(body.image_data_uri, body.prompt)
    except Exception as e:
        logger.exception("[intelligence] 视觉解析失败: %s", e)
        raise HTTPException(status_code=500, detail=f"视觉解析失败: {str(e)}")
    resp = VisionAnalyzeResponse(**result)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/rules", response_model=StandardResponse)
async def list_rules(
    user: User = Depends(get_current_user),
):
    """19. 列出所有可用规则集与内置 preset"""
    loader = RuleLoader()
    presets = loader.list_presets()
    rulesets: List[RuleSetResponse] = []
    total_rules = 0
    for name in presets:
        try:
            rs = loader.load_preset(name)
            rules = [
                RuleResponse(
                    id=r.id, name=r.name, when=r.when.model_dump(mode="json"),
                    then=[a.model_dump(mode="json") for a in r.then], priority=r.priority,
                    enabled=r.enabled, description=r.description, tags=r.tags,
                )
                for r in rs.rules
            ]
            total_rules += len(rules)
            rulesets.append(RuleSetResponse(
                name=rs.name, version=rs.version, description=rs.description, rules=rules,
            ))
        except Exception as e:
            logger.warning("[intelligence] 加载 preset %s 失败: %s", name, e)
    resp = RuleListResponse(presets=presets, rulesets=rulesets, total_rules=total_rules)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.get("/rules/{preset}", response_model=StandardResponse)
async def get_rule_preset(
    preset: str,
    user: User = Depends(get_current_user),
):
    """20. 获取指定 preset 的规则详情"""
    loader = RuleLoader()
    try:
        rs = loader.load_preset(preset)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"规则集不存在: {preset}")
    rules = [
        RuleResponse(
            id=r.id, name=r.name, when=r.when.model_dump(mode="json"),
            then=[a.model_dump(mode="json") for a in r.then], priority=r.priority,
            enabled=r.enabled, description=r.description, tags=r.tags,
        )
        for r in rs.rules
    ]
    resp = RuleSetResponse(name=rs.name, version=rs.version, description=rs.description, rules=rules)
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/rules/execute", response_model=StandardResponse)
async def execute_rules(
    body: RuleExecuteRequest,
    user: User = Depends(get_current_user),
):
    """21. 执行规则集（对上下文求值并执行匹配规则的动作）"""
    engine = RuleEngine()
    loader = RuleLoader()
    try:
        if body.yaml_content:
            ruleset = loader.load_string(body.yaml_content, source="<api>")
            engine.load_ruleset(ruleset)
        elif body.preset:
            engine.load_preset(body.preset)
        else:
            raise HTTPException(status_code=422, detail="需提供 preset 或 yaml_content")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"规则加载失败: {str(e)}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    ctx = dict(body.context)
    report = await engine.execute(ctx, tags=body.tags)
    resp = RuleExecuteResponse(
        ruleset_name=report.ruleset_name, total_rules=report.total_rules,
        matched_rules=report.matched_rules, executed_actions=report.executed_actions,
        results=[
            RuleExecutionResultItem(
                rule_id=r.rule_id, rule_name=r.rule_name, matched=r.matched,
                actions_executed=r.actions_executed, outputs=r.outputs, error=r.error,
            )
            for r in report.results
        ],
        context_changes=report.context_changes, duration_sec=report.duration_sec,
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


@router.post("/rules/validate", response_model=StandardResponse)
async def validate_rules(
    body: RuleValidateRequest,
    user: User = Depends(get_current_user),
):
    """22. 验证 YAML 规则文件（校验 schema，不执行）"""
    loader = RuleLoader()
    errors: List[str] = []
    ruleset_name = None
    rules_count = 0
    valid = True
    try:
        rs = loader.load_string(body.yaml_content, source="<validate>")
        ruleset_name = rs.name
        rules_count = len(rs.rules)
    except ValueError as e:
        valid = False
        errors.append(str(e))
    except Exception as e:
        valid = False
        errors.append(f"解析失败: {str(e)}")
    resp = RuleValidateResponse(
        valid=valid, errors=errors, rules_count=rules_count, ruleset_name=ruleset_name,
    )
    return StandardResponse(success=True, data=resp.model_dump(mode="json"))


# ========== 6. 统一智能Agent网关（新端点） ==========

@router.post("/agent/chat", response_model=StandardResponse)
async def unified_agent_chat(
    session_id: UUID,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """统一智能Agent对话入口
    
    自动路由到最合适的能力类型：
    - qa: 简单问答 (快速响应)
    - reasoning: 科学推理 (深度分析)
    - agent: 工具执行 (Agent工作台)
    - auto: 自动判断 (默认)
    
    响应包含:
    - response: 对话响应
    - capability: 使用的能力类型
    - suggestions: 建议的下一步操作
    - metadata: 执行元数据
    """
    from app.services.intelligence.unified_agent_gateway import UnifiedAgentGateway
    from app.core.deps import get_llm_client_with_fallback
    
    session = await _get_session_or_404(db, session_id, user)
    llm_client = await get_llm_client_with_fallback(db)
    
    gateway = UnifiedAgentGateway(db=db, llm_client=llm_client)
    
    try:
        result = await gateway.chat(
            session_id=session.id,
            message=body.message,
            user=user,
            project_id=str(body.project_id) if body.project_id else None,
            capability_hint=body.capability_hint,
            force_mode=body.force_mode,
            tier=body.tier,
        )

        capability_used = result.get("capability", "qa")
        workflow_map = {
            "qa": {"brain": "知识库问答", "hands": ["knowledge_base", "document_search"]},
            "reasoning": {"brain": "科学推理引擎", "hands": ["hypothesis_engine", "pathway_analyzer", "literature_search"]},
            "agent": {"brain": "Agent调度中心", "hands": ["tool_registry", "task_planner", "executor"]},
        }
        result["workflow_status"] = {
            "step": capability_used,
            "brain": workflow_map.get(capability_used, {}).get("brain", "智能Agent"),
            "hands": workflow_map.get(capability_used, {}).get("hands", []),
            "status": "completed",
        }

        return StandardResponse(success=True, data=result)
    except Exception as e:
        logger.exception("[UnifiedAgent] 对话失败: %s", e)
        raise HTTPException(status_code=500, detail=f"统一Agent对话失败: {str(e)}")


@router.get("/agent/capabilities", response_model=StandardResponse)
async def get_agent_capabilities(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取统一Agent可用的能力列表"""
    from app.services.intelligence.unified_agent_gateway import UnifiedAgentGateway
    
    gateway = UnifiedAgentGateway(db=db)
    capabilities = await gateway.get_capabilities()
    return StandardResponse(success=True, data=capabilities)


@router.get("/agent/sessions/{session_id}/suggestions", response_model=StandardResponse)
async def get_session_suggestions(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取会话的下一步建议"""
    from app.services.intelligence.unified_agent_gateway import UnifiedAgentGateway
    
    session = await _get_session_or_404(db, session_id, user)
    gateway = UnifiedAgentGateway(db=db)
    suggestions = await gateway.get_session_suggestions(session.id)
    return StandardResponse(success=True, data={"suggestions": suggestions})


@router.get("/reasoning/runs/{run_id}/traces", response_model=StandardResponse)
async def get_reasoning_traces(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取推理轨迹（步骤树 + 成本分解 + 决策链）

    用于前端可视化展示 Agent 推理全过程：
    - 时间轴：按步骤类型展示 Agent 调用、LLM 调用、决策点
    - 流程图：展示步骤间的父子关系（树形结构）
    - 成本分解：按 agent/phase/step_type 统计成本
    - 决策链：展示所有决策点及决策依据
    """
    from app.services.intelligence.trace_store import ReasoningTraceStore

    store = ReasoningTraceStore(db=db)
    tree = await store.get_trace_tree(run_id)
    cost = await store.get_cost_breakdown(run_id)
    decisions = await store.get_decision_chain(run_id)

    return StandardResponse(success=True, data={
        "run_id": str(run_id),
        "tree": tree,
        "cost_breakdown": cost,
        "decision_chain": decisions,
    })
