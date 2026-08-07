"""个人基因组解读端点 — /api/v1/genome

设计来源：参照 Trae 论坛「个人基因组定制解密」方案核心闭环
上传 SNP 文件 → 性状选择 → AI 检索位点 → 基因型匹配 → 风险评分 → LLM 解读 → 生活建议

路径前缀：/api/v1/genome
权限：所有用户可读；创建/删除性状与 Prompt 模板需 FOUNDER 角色；
      基因组文件级操作需 owner 校验（personal_genome.owner_id == current_user.id）
"""
import asyncio
import logging
import os
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    KbExpandRequest,
    InterpretRequest,
    PersonalizedTreatmentRequest,
    PromptTemplateCreate,
    TraitCreate,
)
from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.security import UserRole
from app.db.session import get_db
from app.models.personal_genome import (
    PersonalGenome,
    GenomeBuild,
    SourceFormat,
)
from app.models.prompt_template import PromptTemplate
from app.models.trait import Trait
from app.models.user import User
from app.schemas.common import (
    ApiResponse,
    PagedResponse,
    paged_response,
    success_response,
)
from app.services.genome import (
    genotype_matcher,
    kb_expander,
    recommendation_engine,
    risk_scorer,
    trait_search,
)
from app.services.parser.snp_chip import SnpChipParser
from app.services.coscientist.hooks import on_genome_interpreted

logger = logging.getLogger(__name__)
router = APIRouter()

# 上传文件大小上限（50MB — SNP 芯片数据通常 5-30MB）
MAX_GENOME_UPLOAD_BYTES = 50 * 1024 * 1024

# 允许的扩展名
ALLOWED_GENOME_EXTENSIONS = {"txt", "csv", "tsv", "zip"}


# ========== 性状管理 ==========


@router.get("/traits", response_model=PagedResponse, summary="性状列表")
async def list_traits(
    category: Optional[str] = Query(None, description="按分类过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取性状列表（分页）"""
    result = await trait_search.list_traits(db, category=category, page=page, page_size=page_size)
    return paged_response(
        data=result["items"], page=result["page"], page_size=result["page_size"], total=result["total"]
    )


@router.post("/traits", summary="创建性状（创始人权限）")
async def create_trait(
    payload: TraitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """创建新性状（仅创始人）"""
    trait = Trait(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        icon=payload.icon,
    )
    db.add(trait)
    await db.flush()
    await db.refresh(trait)
    return success_response({
        "id": str(trait.id),
        "name": trait.name,
        "category": trait.category,
        "description": trait.description,
        "icon": trait.icon,
    })


@router.get("/traits/{trait_id}", summary="性状详情")
async def get_trait(
    trait_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trait = await db.get(Trait, trait_id)
    if not trait:
        raise NotFoundError("性状不存在")
    return success_response({
        "id": str(trait.id),
        "name": trait.name,
        "category": trait.category,
        "description": trait.description,
        "icon": trait.icon,
    })


@router.get("/traits/{trait_id}/loci", summary="性状关联位点")
async def list_trait_loci(
    trait_id: UUID,
    approved_only: bool = Query(True, description="仅返回审核通过位点"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取性状关联的所有 SNP 位点"""
    trait = await db.get(Trait, trait_id)
    if not trait:
        raise NotFoundError("性状不存在")
    loci = await trait_search.get_trait_loci(db, trait_id, approved_only=approved_only)
    return success_response({"trait_id": str(trait_id), "loci": loci, "total": len(loci)})


@router.post("/traits/{trait_id}/search-loci", summary="AI 检索位点")
async def search_loci(
    trait_id: UUID,
    use_external: bool = Query(True, description="是否调外部 GWAS/ClinVar/OMIM"),
    user_llm_config_id: Optional[UUID] = Query(None, description="用户 LLM 配置 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 检索性状关联位点 — 本地 + 外部数据源交叉验证

    安全约束：外部 API 调用使用 asyncio.to_thread 包装，避免阻塞事件循环
    """
    try:
        result = await trait_search.search_loci(
            db,
            trait_id=trait_id,
            user=current_user,
            user_llm_config_id=user_llm_config_id,
            use_external=use_external,
        )
        return success_response(result)
    except ValueError as e:
        raise NotFoundError(str(e))


# ========== 个人基因组文件管理 ==========


@router.post("/upload", summary="上传 SNP 芯片文件")
async def upload_genome(
    file: UploadFile = File(...),
    genome_build: str = Form("GRCh37"),
    project_id: Optional[UUID] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传 SNP 芯片文件

    支持 4 种格式自动识别：23andme / ancestry / wechat_gene / generic
    安全策略：
    - 文件大小上限 50MB
    - 扩展名白名单
    - 文件名 basename 防路径遍历
    - 解析使用 asyncio.to_thread 避免阻塞事件循环
    """
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_GENOME_UPLOAD_BYTES:
        raise ValidationError(
            f"文件大小 {file_size} 字节超过上限 {MAX_GENOME_UPLOAD_BYTES} 字节（50MB）"
        )
    if file_size == 0:
        raise ValidationError("文件为空")

    ext = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    if ext not in ALLOWED_GENOME_EXTENSIONS:
        raise ValidationError(
            f"不支持的文件类型: .{ext}，允许: {', '.join(sorted(ALLOWED_GENOME_EXTENSIONS))}"
        )

    # 安全文件名
    safe_name = os.path.basename(file.filename or "") or f"{uuid.uuid4().hex}.txt"
    safe_name = safe_name.replace("\\", "/").split("/")[-1]
    if not safe_name or safe_name.startswith("."):
        safe_name = f"{uuid.uuid4().hex}.txt"

    upload_root = os.path.abspath(getattr(settings, "UPLOAD_DIR", "uploads") or "uploads")
    local_dir = os.path.join(upload_root, "genome", str(current_user.id))
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.abspath(os.path.join(local_dir, safe_name))
    if not local_path.startswith(local_dir + os.sep):
        raise ValidationError("非法文件名")

    # 异步写入
    await asyncio.to_thread(_write_file_sync, local_path, content)

    # 构造 PersonalGenome 记录
    genome = PersonalGenome(
        owner_id=current_user.id,
        project_id=project_id,
        file_name=file.filename or safe_name,
        storage_path=local_path,
        genome_build=genome_build,
        source_format=SourceFormat.GENERIC,
        total_variants=None,
        parsed_summary=None,
        quality_metrics=None,
    )
    db.add(genome)
    await db.flush()

    # 触发解析
    try:
        parsed = await _parse_genome_file(genome)
        genome.source_format = parsed.get("summary", {}).get("source_format", SourceFormat.GENERIC)
        genome.total_variants = parsed.get("summary", {}).get("total_variants")
        genome.parsed_summary = parsed.get("summary")
        genome.quality_metrics = parsed.get("quality_metrics")
        await db.flush()
    except Exception as e:
        logger.error(f"基因组文件解析失败: {e}", exc_info=True)
        genome.parsed_summary = {"error": str(e)[:500]}

    return success_response({
        "id": str(genome.id),
        "file_name": genome.file_name,
        "genome_build": genome.genome_build,
        "source_format": genome.source_format,
        "total_variants": genome.total_variants,
        "parsed_summary": genome.parsed_summary,
        "quality_metrics": genome.quality_metrics,
    })


def _write_file_sync(path: str, content: bytes) -> None:
    """同步文件写入"""
    with open(path, "wb") as f:
        f.write(content)


async def _parse_genome_file(genome: PersonalGenome) -> dict:
    """调 SnpChipParser 解析上传的文件"""
    # 包装一个最小 dataset 对象供 parser 使用
    class _DatasetStub:
        def __init__(self, storage_path):
            self.storage_path = storage_path

    parser = SnpChipParser()
    # CPU 密集解析用 to_thread 包装
    return await asyncio.to_thread(
        lambda: asyncio.run(parser.parse(_DatasetStub(genome.storage_path), None))
    )


@router.get("/genomes", summary="当前用户的基因组文件列表")
async def list_genomes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户上传的基因组文件列表"""
    skip = (page - 1) * page_size
    stmt = (
        select(PersonalGenome)
        .where(PersonalGenome.owner_id == current_user.id)
        .order_by(PersonalGenome.created_at.desc())
        .offset(skip)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    items = [_genome_to_dict(g) for g in result.scalars().all()]

    count_stmt = (
        select(func.count())
        .select_from(PersonalGenome)
        .where(PersonalGenome.owner_id == current_user.id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.get("/genomes/{genome_id}", summary="基因组文件详情")
async def get_genome(
    genome_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    genome = await _get_owned_genome(db, genome_id, current_user)
    return success_response(_genome_to_dict(genome))


@router.delete("/genomes/{genome_id}", summary="删除基因组文件")
async def delete_genome(
    genome_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除基因组文件（级联删 GenotypeMatch / RiskAssessment / LifestyleRecommendation）

    安全约束：硬约束「删除操作不影响核心系统功能」— 仅删除用户自有数据
    """
    genome = await _get_owned_genome(db, genome_id, current_user)
    # 删除物理文件（不抛错，文件可能已被外部清理）
    try:
        if genome.storage_path and os.path.exists(genome.storage_path):
            await asyncio.to_thread(os.remove, genome.storage_path)
    except OSError as e:
        logger.warning(f"删除物理文件失败（DB 记录仍将删除）: {e}")

    await db.delete(genome)
    return success_response({"message": f"基因组文件 '{genome.file_name}' 已删除"})


# ========== 基因型匹配 ==========


@router.post("/genomes/{genome_id}/match", summary="触发基因型匹配")
async def match_genotype_endpoint(
    genome_id: UUID,
    trait_id: UUID = Query(..., description="按性状过滤位点"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对指定性状的所有 SnpLocus 执行基因型匹配"""
    genome = await _get_owned_genome(db, genome_id, current_user)

    # 加载该性状的位点
    from app.models.snp_locus import SnpLocus
    loci_stmt = (
        select(SnpLocus)
        .where(SnpLocus.trait_id == trait_id)
        .where(SnpLocus.is_approved == True)  # noqa: E712
    )
    loci_result = await db.execute(loci_stmt)
    loci = list(loci_result.scalars().all())

    if not loci:
        raise ValidationError("该性状暂无可用位点，请先调用 AI 检索位点")

    matches = await genotype_matcher.match_genotype(db, genome_id, loci)
    return success_response({
        "personal_genome_id": str(genome_id),
        "trait_id": str(trait_id),
        "matched_loci": len(matches),
        "risk_loci": sum(1 for m in matches if m.is_risk),
        "matches": [
            {
                "id": str(m.id),
                "snp_locus_id": str(m.snp_locus_id),
                "user_genotype": m.user_genotype,
                "is_risk": m.is_risk,
                "risk_score": m.risk_score,
                "note": m.note,
            }
            for m in matches
        ],
    })


@router.get("/genomes/{genome_id}/matches", summary="查询匹配结果")
async def list_matches(
    genome_id: UUID,
    risk_only: bool = Query(False, description="仅返回风险位点匹配"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询基因型匹配结果"""
    await _get_owned_genome(db, genome_id, current_user)
    matches = await genotype_matcher.list_matches(db, genome_id, risk_only=risk_only)
    return success_response({"matches": matches, "total": len(matches)})


# ========== 风险评估 ==========


@router.post("/genomes/{genome_id}/risk/{trait_id}", summary="触发风险评估")
async def score_risk_endpoint(
    genome_id: UUID,
    trait_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对指定性状触发风险评估（基于已有匹配记录）"""
    genome = await _get_owned_genome(db, genome_id, current_user)

    # 校验性状存在
    trait = await db.get(Trait, trait_id)
    if not trait:
        raise NotFoundError("性状不存在")

    assessment = await risk_scorer.score_risk(db, genome_id, trait_id, matches=None)
    return success_response({
        "id": str(assessment.id),
        "personal_genome_id": str(assessment.personal_genome_id),
        "trait_id": str(assessment.trait_id),
        "overall_risk_score": assessment.overall_risk_score,
        "risk_level": assessment.risk_level,
        "core_loci_matched": assessment.core_loci_matched,
        "auxiliary_loci_matched": assessment.auxiliary_loci_matched,
        "matched_loci_ids": assessment.matched_loci_ids or [],
        "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
    })


@router.get("/genomes/{genome_id}/assessments", summary="风险评估列表")
async def list_assessments(
    genome_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询个人基因组文件的所有风险评估"""
    await _get_owned_genome(db, genome_id, current_user)
    assessments = await risk_scorer.list_assessments(db, genome_id)
    return success_response({"assessments": assessments, "total": len(assessments)})


# ========== LLM 解读 ==========


@router.post("/assessments/{assessment_id}/interpret", summary="生成 LLM 解读")
async def interpret_assessment(
    assessment_id: UUID,
    payload: InterpretRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调用 LLM 生成风险评估的解读报告

    优先用用户级 LLM 配置（BYO Key），失败自动降级到系统默认
    """
    from app.models.personal_genome import RiskAssessment
    assessment = await db.get(RiskAssessment, assessment_id)
    if not assessment:
        raise NotFoundError("风险评估不存在")

    # 级联 owner 校验：assessment → personal_genome → owner
    genome = await db.get(PersonalGenome, assessment.personal_genome_id)
    if not genome or genome.owner_id != current_user.id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此风险评估")

    result = await kb_expander.interpret(
        db,
        risk_assessment_id=assessment_id,
        user=current_user,
        use_llm=payload.use_llm,
        user_llm_config_id=payload.user_llm_config_id,
    )
    # Co-Scientist auto-trigger: genome interpreted
    await on_genome_interpreted(
        db=db, user=current_user,
        project_id=str(genome.project_id) if genome and genome.project_id else None,
        assessment_id=str(assessment_id), trait_name=None,
    )
    return success_response(result)


# ========== 整合解读：基因解读 + 项目疾病分析 ==========


class IntegratedInterpretRequest(BaseModel):
    """整合解读请求体 — 结合项目前期疾病分析结果"""

    use_llm: bool = True
    user_llm_config_id: Optional[UUID] = None


@router.post("/genomes/{genome_id}/integrated-interpretation", summary="整合解读：基因+疾病分析")
async def integrated_interpretation(
    genome_id: UUID,
    payload: IntegratedInterpretRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """整合个人基因解读与项目前期疾病分析结果

    建立数据分析结果与个人基因解读的关联机制：
    1. 加载个人基因组的风险评估结果（SNP 位点匹配、风险评分）
    2. 若基因组关联了项目（project_id），收集项目前期的疾病分析结果：
       - 差异表达基因（DE genes）
       - 已发现靶点
       - 富集通路
       - 治疗方案与疗效
       - 实验结果
    3. 调用 LLM 生成整合解读报告，基于完整上下文提供针对性解读

    确保解读结果：
    - 关联个人基因型风险与项目发现的疾病靶点
    - 基于前期分析结果提供针对性用药和生活建议
    - 逻辑清晰，易于理解
    """
    import json
    from app.core.deps import get_llm_client_with_fallback
    from app.models.personal_genome import RiskAssessment, GenotypeMatch
    from app.models.snp_locus import SnpLocus
    from app.models.target import Target
    from app.models.dataset import Dataset
    from app.models.treatment import Treatment

    genome = await _get_owned_genome(db, genome_id, current_user)

    # 1. 加载风险评估
    assessments = await risk_scorer.list_assessments(db, genome_id)

    # 2. 加载基因型匹配明细
    match_stmt = (
        select(GenotypeMatch, SnpLocus)
        .join(SnpLocus, GenotypeMatch.snp_locus_id == SnpLocus.id)
        .where(GenotypeMatch.personal_genome_id == genome_id)
        .order_by(GenotypeMatch.is_risk.desc())
        .limit(30)
    )
    match_rows = (await db.execute(match_stmt)).all()
    genotype_matches = [
        {
            "rsid": locus.rsid,
            "gene_symbol": locus.gene_symbol,
            "user_genotype": match.user_genotype,
            "is_risk": match.is_risk,
            "risk_score": match.risk_score,
        }
        for match, locus in match_rows
    ]

    # 3. 收集项目前期疾病分析结果（若基因组关联了项目）
    project_analysis = {}
    project_id = genome.project_id
    if project_id:
        # 并行查询项目数据
        targets_task = db.execute(
            select(Target).where(Target.project_id == project_id).limit(15)
        )
        datasets_task = db.execute(
            select(Dataset).where(Dataset.project_id == project_id)
            .where(Dataset.parse_status == "completed").limit(5)
        )
        treatments_task = db.execute(
            select(Treatment).where(Treatment.project_id == project_id).limit(10)
        )

        targets_r, datasets_r, treatments_r = await asyncio.gather(
            targets_task, datasets_task, treatments_task
        )

        targets = targets_r.scalars().all()
        datasets = datasets_r.scalars().all()
        treatments = treatments_r.scalars().all()

        project_analysis = {
            "has_project_data": True,
            "project_id": str(project_id),
            "targets": [
                {
                    "gene_symbol": t.gene_symbol,
                    "confidence_score": float(t.confidence_score) if t.confidence_score else None,
                }
                for t in targets
            ],
            "treatments": [
                {
                    "name": t.name,
                    "therapy_type": t.therapy_type,
                    "efficacy_score": float(t.efficacy_score) if t.efficacy_score else None,
                }
                for t in treatments
            ],
            "de_genes": [],
            "pathways": [],
        }

        # 从数据集提取 DE 基因和通路
        for ds in datasets:
            summary = ds.parsed_summary or {}
            analysis = summary.get("analysis_results") or {}
            if isinstance(analysis, dict):
                de = analysis.get("de") or {}
                if isinstance(de, dict):
                    genes = de.get("genes") or []
                    if isinstance(genes, list):
                        project_analysis["de_genes"].extend(
                            [g.get("gene", g.get("gene_id", "")) for g in genes[:10] if isinstance(g, dict)]
                        )
                pathways = analysis.get("pathways") or summary.get("pathways") or []
                if isinstance(pathways, list):
                    project_analysis["pathways"].extend(
                        [p.get("name", "") for p in pathways[:5] if isinstance(p, dict)]
                    )

    # 4. 构造整合解读 prompt
    genome_info = {
        "file_name": genome.file_name,
        "genome_build": genome.genome_build,
        "total_variants": genome.total_variants,
    }
    risk_summary = [
        {
            "trait_id": str(a.get("trait_id", "")),
            "risk_level": a.get("risk_level"),
            "overall_risk_score": a.get("overall_risk_score"),
            "core_loci_matched": a.get("core_loci_matched"),
        }
        for a in (assessments or [])[:5]
    ]

    prompt = _build_integrated_interpretation_prompt(
        genome_info, risk_summary, genotype_matches, project_analysis
    )

    # 5. 调用 LLM 生成整合解读
    interpretation = ""
    llm_model = "none"
    if payload.use_llm:
        try:
            if payload.user_llm_config_id:
                from app.services.llm.user_router import UserLLMRouter
                router_llm = await UserLLMRouter.create(
                    db, current_user, payload.user_llm_config_id
                )
                llm_model = router_llm.active_model_name
                response = await router_llm.complete(prompt)
            else:
                llm_client = await get_llm_client_with_fallback(db)
                llm_model = getattr(llm_client, "default_model", "agnes-2.5-flash")
                response = await llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                )

            # 解析 LLM 响应
            if isinstance(response, dict):
                interpretation = response.get("content", "")
            else:
                interpretation = str(response)
        except Exception as e:
            logger.warning(f"整合解读 LLM 调用失败: {e}")
            interpretation = f"LLM 解读生成失败（{type(e).__name__}），请稍后重试。已收集的数据摘要见下方。"

    return success_response({
        "personal_genome_id": str(genome_id),
        "project_id": str(project_id) if project_id else None,
        "genome_info": genome_info,
        "risk_assessments": risk_summary,
        "genotype_matches": genotype_matches[:20],
        "project_analysis": project_analysis,
        "interpretation": interpretation,
        "llm_model": llm_model,
        "data_integration": {
            "genome_linked_to_project": project_id is not None,
            "risk_assessments_count": len(assessments),
            "genotype_matches_count": len(genotype_matches),
            "project_targets_count": len(project_analysis.get("targets", [])),
            "project_treatments_count": len(project_analysis.get("treatments", [])),
            "project_de_genes_count": len(project_analysis.get("de_genes", [])),
            "project_pathways_count": len(project_analysis.get("pathways", [])),
        },
    })


def _build_integrated_interpretation_prompt(
    genome_info: dict,
    risk_assessments: list,
    genotype_matches: list,
    project_analysis: dict,
) -> str:
    """构造整合解读 prompt — 结合个人基因型与项目疾病分析"""
    import json

    parts = [
        "你是一名资深遗传学专家和临床药理学家。请基于以下个人基因组数据与项目疾病分析结果，生成一份整合解读报告。",
        "",
        "## 个人基因组信息",
        json.dumps(genome_info, ensure_ascii=False, indent=2),
        "",
        "## 风险评估摘要",
        json.dumps(risk_assessments, ensure_ascii=False, indent=2, default=str),
        "",
        "## 关键基因型匹配（风险位点）",
        json.dumps(genotype_matches[:15], ensure_ascii=False, indent=2, default=str),
        "",
    ]

    if project_analysis.get("has_project_data"):
        parts.extend([
            "## 项目前期疾病分析结果",
            json.dumps({
                "targets": project_analysis.get("targets", []),
                "de_genes": project_analysis.get("de_genes", [])[:10],
                "pathways": project_analysis.get("pathways", [])[:5],
                "treatments": project_analysis.get("treatments", []),
            }, ensure_ascii=False, indent=2, default=str),
            "",
        ])

    parts.extend([
        "## 任务",
        "请生成一份结构化的整合解读报告，包含以下部分：",
        "1. **基因风险概述**：总结个人基因组中的关键风险位点及其临床意义",
        "2. **与疾病分析的关联**：" + (
            "将个人基因型风险与项目前期发现的靶点、DE基因、通路进行关联分析，"
            "指出个人基因型是否与项目研究的疾病靶点存在重叠或相互作用"
            if project_analysis.get("has_project_data")
            else "（未关联项目，仅基于基因型进行解读）"
        ),
        "3. **针对性建议**：基于基因型和疾病分析结果，提供个性化的用药和生活建议",
        "4. **数据局限性说明**：说明解读的局限性和需要进一步验证的内容",
        "",
        "请使用中文，以 Markdown 格式返回报告。",
    ])

    return "\n".join(parts)


# ========== 生活建议 ==========


@router.post("/assessments/{assessment_id}/recommendations", summary="生成生活建议")
async def generate_recommendations(
    assessment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成个性化生活建议（规则引擎，不调 LLM）"""
    from app.models.personal_genome import RiskAssessment
    assessment = await db.get(RiskAssessment, assessment_id)
    if not assessment:
        raise NotFoundError("风险评估不存在")

    genome = await db.get(PersonalGenome, assessment.personal_genome_id)
    if not genome or genome.owner_id != current_user.id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此风险评估")

    recs = await recommendation_engine.generate_recommendations(db, assessment_id)
    return success_response({
        "recommendations": [
            {
                "id": str(r.id),
                "category": r.category,
                "content": r.content,
                "priority": r.priority,
                "evidence": r.evidence,
            }
            for r in recs
        ],
        "total": len(recs),
    })


@router.get("/assessments/{assessment_id}/recommendations", summary="查询生活建议")
async def list_recommendations(
    assessment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询指定风险评估的生活建议列表"""
    from app.models.personal_genome import RiskAssessment
    assessment = await db.get(RiskAssessment, assessment_id)
    if not assessment:
        raise NotFoundError("风险评估不存在")

    genome = await db.get(PersonalGenome, assessment.personal_genome_id)
    if not genome or genome.owner_id != current_user.id:
        if current_user.role != UserRole.FOUNDER:
            raise ForbiddenError("无权访问此风险评估")

    recs = await recommendation_engine.list_recommendations(db, assessment_id)
    return success_response({"recommendations": recs, "total": len(recs)})


# ========== 知识库扩充 ==========


@router.post("/kb/expand", summary="扩充知识库")
async def expand_kb(
    payload: KbExpandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调用 LLM 批量扩充性状/位点/Prompt 模板

    仅创始人可调用（避免普通用户污染知识库）
    """
    if current_user.role != UserRole.FOUNDER:
        raise ForbiddenError("仅创始人可扩充知识库")

    result = await kb_expander.expand_kb(
        db,
        user=current_user,
        trait_ids=payload.trait_ids,
        user_llm_config_id=payload.user_llm_config_id,
    )
    return success_response(result)


# ========== Prompt 模板 ==========


@router.get("/prompt-templates", summary="Prompt 模板列表")
async def list_prompt_templates(
    template_type: Optional[str] = Query(None),
    trait_category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询 Prompt 模板"""
    skip = (page - 1) * page_size
    stmt = select(PromptTemplate).offset(skip).limit(page_size).order_by(PromptTemplate.created_at.desc())
    if template_type:
        stmt = stmt.where(PromptTemplate.template_type == template_type)
    if trait_category:
        stmt = stmt.where(PromptTemplate.trait_category == trait_category)
    result = await db.execute(stmt)
    items = [_tpl_to_dict(t) for t in result.scalars().all()]

    count_stmt = select(func.count()).select_from(PromptTemplate)
    if template_type:
        count_stmt = count_stmt.where(PromptTemplate.template_type == template_type)
    if trait_category:
        count_stmt = count_stmt.where(PromptTemplate.trait_category == trait_category)
    total = (await db.execute(count_stmt)).scalar() or 0

    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("/prompt-templates", summary="创建 Prompt 模板（创始人）")
async def create_prompt_template(
    payload: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FOUNDER)),
):
    """创建新的 Prompt 模板（仅创始人）"""
    tpl = PromptTemplate(
        name=payload.name,
        template_type=payload.template_type,
        genome_build=payload.genome_build,
        trait_category=payload.trait_category,
        content=payload.content,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return success_response(_tpl_to_dict(tpl))


# ========== 个性化治疗推荐 ==========


@router.post("/personalized-treatment", summary="个性化治疗推荐")
async def personalized_treatment(
    payload: PersonalizedTreatmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于个人基因组的治疗推荐（集成 treatments 模块 + LLM）

    流程：
    1. 校验 genome 归属
    2. 加载该基因组的风险评估
    3. 若 disease 提供 → 查询匹配的现有治疗方案（按 name/notes ilike）
    4. 调用 UserLLMRouter 生成个性化用药建议（含基因型 + 候选药物）
    5. 解析 LLM 输出（结构化 JSON，失败降级到原文）
    """
    genome = await _get_owned_genome(db, payload.personal_genome_id, current_user)

    # 1. 加载风险评估
    assessments = await risk_scorer.list_assessments(db, payload.personal_genome_id)

    # 2. 查询候选药物（按 disease 关键字模糊匹配 Treatment.name 或 notes）
    drug_candidates: list = []
    if payload.disease:
        try:
            from app.models.treatment import Treatment
            keyword = f"%{payload.disease}%"
            drug_stmt = (
                select(Treatment)
                .where(
                    (Treatment.name.ilike(keyword))
                    | (Treatment.notes.ilike(keyword))
                )
                .limit(20)
            )
            drug_result = await db.execute(drug_stmt)
            for t in drug_result.scalars().all():
                drug_candidates.append({
                    "id": str(t.id),
                    "name": t.name,
                    "therapy_type": t.therapy_type,
                    "status": t.status,
                    "efficacy_score": t.efficacy_score,
                    "risk_score": t.risk_score,
                    "notes": t.notes,
                })
        except Exception as e:
            logger.warning(f"查询候选药物失败（不影响主流程）: {e}")

    # 3. 调用 UserLLMRouter 生成个性化建议
    llm_model_name = "system_default"
    parsed = {"recommendations": [], "gene_drug_interactions": [], "dosage_adjustments": []}
    try:
        from app.services.llm.user_router import UserLLMRouter
        router_llm = await UserLLMRouter.create(
            db, current_user, payload.user_llm_config_id
        )
        llm_model_name = router_llm.active_model_name
        prompt = _build_personalized_treatment_prompt(
            genome, assessments, drug_candidates, payload.disease
        )
        llm_response = await router_llm.complete(prompt)
        # LLM 返回 dict（含 content 字段）或纯字符串
        response_text = (
            llm_response.get("content") if isinstance(llm_response, dict) else str(llm_response)
        )
        parsed = _parse_treatment_response(response_text, parsed)
    except Exception as e:
        logger.warning(f"LLM 个性化治疗推荐失败（降级到空推荐）: {e}")
        parsed = {
            **parsed,
            "recommendations": [
                f"LLM 调用失败（{type(e).__name__}: {str(e)[:200]}），请稍后重试或检查 LLM 配置"
            ],
        }

    return success_response({
        "personal_genome_id": str(payload.personal_genome_id),
        "project_id": str(payload.project_id) if payload.project_id else None,
        "disease": payload.disease,
        "risk_assessments": assessments,
        "drug_candidates": drug_candidates,
        "recommendations": parsed.get("recommendations", []),
        "gene_drug_interactions": parsed.get("gene_drug_interactions", []),
        "dosage_adjustments": parsed.get("dosage_adjustments", []),
        "llm_model": llm_model_name,
    })


def _build_personalized_treatment_prompt(
    genome: PersonalGenome,
    assessments: list,
    drug_candidates: list,
    disease: Optional[str],
) -> str:
    """构造个性化治疗推荐 prompt"""
    import json

    genome_summary = {
        "file_name": genome.file_name,
        "genome_build": genome.genome_build,
        "total_variants": genome.total_variants,
    }
    assessment_summary = [
        {
            "trait_id": a.get("trait_id"),
            "risk_level": a.get("risk_level"),
            "overall_risk_score": a.get("overall_risk_score"),
            "core_loci_matched": a.get("core_loci_matched"),
            "auxiliary_loci_matched": a.get("auxiliary_loci_matched"),
        }
        for a in (assessments or [])[:5]
    ]
    return (
        "你是一名临床药理学家。基于以下个人基因组风险评估结果，生成个性化用药建议。\n\n"
        f"## 目标疾病\n{disease or '未指定'}\n\n"
        f"## 个人基因组信息\n{json.dumps(genome_summary, ensure_ascii=False, indent=2)}\n\n"
        f"## 风险评估摘要（前 5 项）\n"
        f"{json.dumps(assessment_summary, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"## 候选药物（来自现有治疗方案库）\n"
        f"{json.dumps(drug_candidates[:10], ensure_ascii=False, indent=2, default=str)}\n\n"
        "## 任务\n"
        "请生成以下 JSON 结构（仅返回 JSON，不要包含 markdown 代码块标记）：\n"
        "{\n"
        '  "recommendations": ["针对基因型的具体用药建议1", "建议2", ...],\n'
        '  "gene_drug_interactions": [\n'
        '    {"description": "rsID 与某药物的相互作用警示"}\n'
        '  ],\n'
        '  "dosage_adjustments": [\n'
        '    {"description": "根据基因型代谢能力调整剂量"}\n'
        '  ]\n'
        "}\n"
    )


def _parse_treatment_response(response_text: str, fallback: dict) -> dict:
    """解析 LLM 治疗推荐响应（支持纯 JSON / 含 markdown 代码块 / 纯文本降级）"""
    import json
    import re

    if not response_text:
        return fallback

    # 1. 尝试提取 ```json ... ``` 代码块
    md_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", response_text)
    candidate = md_match.group(1) if md_match else response_text

    # 2. 尝试找到第一个 { ... } JSON 对象
    brace_start = candidate.find("{")
    brace_end = candidate.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidate = candidate[brace_start : brace_end + 1]

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return {
                "recommendations": parsed.get("recommendations", []) or [],
                "gene_drug_interactions": parsed.get("gene_drug_interactions", []) or [],
                "dosage_adjustments": parsed.get("dosage_adjustments", []) or [],
            }
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"解析 LLM 治疗推荐 JSON 失败，降级为原文: {e}")

    # 3. 降级：把原文作为单条 recommendation
    return {
        **fallback,
        "recommendations": [response_text[:2000]] if response_text else [],
    }


# ========== 知识图谱同步 ==========


@router.post("/genomes/{genome_id}/graph-sync", summary="将基因型同步到知识图谱")
async def sync_to_graph(
    genome_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将个人基因型匹配结果同步到知识图谱节点

    不污染公共图谱：用户级节点用前缀 user:{owner_id}:{rsid} 区分。
    Mock 模式下写入内存 MOCK_USER_GENOTYPES 字典；Neo4j 模式下写入 user_genotype 标签节点。
    """
    genome = await _get_owned_genome(db, genome_id, current_user)
    from app.services.knowledge.graph import get_knowledge_graph

    kg = get_knowledge_graph()
    result = await kg.add_genome_context(genome_id, db)
    return success_response(result)


# ========== 报告导出 ==========


@router.post("/genomes/{genome_id}/export", summary="导出基因组解读报告")
async def export_genome_report(
    genome_id: UUID,
    format: str = Query("both", description="导出格式：markdown / json / both"),
    user_llm_config_id: Optional[UUID] = Query(None, description="用户级 LLM 配置 ID（保留参数，未在当前实现中使用）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出个人基因组解读报告（Markdown / JSON / 同时）

    报告内容包含：
    - 基本信息（文件名、基因组版本、变异数量、上传时间）
    - 风险评估列表（按性状分组）
    - 基因型匹配明细（含 rsID、基因、风险等级）
    - 生活建议（按优先级排序）
    """
    from app.models.personal_genome import GenotypeMatch, LifestyleRecommendation, RiskAssessment
    from app.models.snp_locus import SnpLocus

    fmt = format.lower().strip()
    if fmt not in ("markdown", "json", "both"):
        raise ValidationError(
            f"不支持的格式：{format}（支持 markdown / json / both）"
        )

    genome = await _get_owned_genome(db, genome_id, current_user)

    # 1. 加载风险评估（复用 risk_scorer 服务返回 dict 列表）
    assessments = await risk_scorer.list_assessments(db, genome_id)

    # 2. 加载基因型匹配（含 SnpLocus 详情）
    match_stmt = (
        select(GenotypeMatch, SnpLocus)
        .join(SnpLocus, GenotypeMatch.snp_locus_id == SnpLocus.id)
        .where(GenotypeMatch.personal_genome_id == genome_id)
        .order_by(GenotypeMatch.is_risk.desc(), SnpLocus.rsid)
    )
    match_rows = (await db.execute(match_stmt)).all()
    matches_detail = [
        {
            "rsid": locus.rsid,
            "gene_symbol": locus.gene_symbol,
            "chromosome": locus.chromosome,
            "user_genotype": match.user_genotype,
            "is_risk": match.is_risk,
            "risk_score": match.risk_score,
            "effect_allele": locus.effect_allele,
            "risk_genotype": locus.risk_genotype,
            "effect_size": locus.effect_size,
            "note": match.note,
        }
        for match, locus in match_rows
    ]

    # 3. 加载生活建议（通过 RiskAssessment 反查）
    rec_stmt = (
        select(LifestyleRecommendation)
        .join(
            RiskAssessment,
            LifestyleRecommendation.risk_assessment_id == RiskAssessment.id,
        )
        .where(RiskAssessment.personal_genome_id == genome_id)
        .order_by(LifestyleRecommendation.priority)
    )
    recommendations = (await db.execute(rec_stmt)).scalars().all()
    recommendations_detail = [
        {
            "category": r.category,
            "content": r.content,
            "priority": r.priority,
            "evidence": r.evidence,
        }
        for r in recommendations
    ]

    # 4. 构建结构化 JSON
    report_json = {
        "personal_genome_id": str(genome_id),
        "file_name": genome.file_name,
        "genome_build": genome.genome_build,
        "total_variants": genome.total_variants,
        "uploaded_at": genome.created_at.isoformat() if genome.created_at else None,
        "risk_assessments": assessments,
        "genotype_matches": matches_detail,
        "recommendations": recommendations_detail,
    }

    # 5. 构建 Markdown（仅 format in {markdown, both}）
    markdown_text = ""
    if fmt in ("markdown", "both"):
        markdown_text = _build_genome_markdown(genome, report_json)

    # 6. 返回
    data: dict = {"personal_genome_id": str(genome_id)}
    if fmt in ("json", "both"):
        data["json"] = report_json
    if fmt in ("markdown", "both"):
        data["markdown"] = markdown_text

    return success_response(data)


def _build_genome_markdown(genome: PersonalGenome, report_json: dict) -> str:
    """构造基因组解读报告 Markdown 文本

    Args:
        genome: PersonalGenome ORM 实例
        report_json: 已构建的结构化报告 dict
    Returns:
        Markdown 字符串
    """
    lines: list = []
    lines.append("# 个人基因组解读报告")
    lines.append("")
    lines.append("> 本报告由 AI 药物研发平台自动生成，仅供参考，不构成医疗建议。")
    lines.append("")

    # 基本信息
    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"| 字段 | 值 |")
    lines.append(f"| --- | --- |")
    lines.append(f"| 文件名 | {genome.file_name} |")
    lines.append(f"| 基因组版本 | {genome.genome_build} |")
    lines.append(f"| 变异数量 | {genome.total_variants or '未知'} |")
    if genome.created_at:
        lines.append(f"| 上传时间 | {genome.created_at.isoformat()} |")
    lines.append("")

    # 风险评估
    assessments = report_json.get("risk_assessments") or []
    lines.append(f"## 风险评估（共 {len(assessments)} 项）")
    lines.append("")
    if assessments:
        lines.append("| 性状 | 风险等级 | 综合评分 | 核心位点 | 辅助位点 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for a in assessments:
            trait = a.get("trait_name") or a.get("trait_id") or "未知性状"
            level = a.get("risk_level", "unknown")
            score = a.get("overall_risk_score", 0)
            core = a.get("core_loci_matched", 0)
            aux = a.get("auxiliary_loci_matched", 0)
            lines.append(f"| {trait} | {level} | {score} | {core} | {aux} |")
    else:
        lines.append("_暂无风险评估数据_")
    lines.append("")

    # 基因型匹配明细
    matches = report_json.get("genotype_matches") or []
    lines.append(f"## 基因型匹配明细（共 {len(matches)} 条）")
    lines.append("")
    if matches:
        lines.append("| rsID | 基因 | 用户基因型 | 是否风险 | 风险基因型 | 风险评分 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for m in matches[:50]:  # 限制 Markdown 表格长度
            rsid = m.get("rsid", "")
            gene = m.get("gene_symbol") or "-"
            geno = m.get("user_genotype", "")
            is_risk = "是" if m.get("is_risk") else "否"
            risk_geno = m.get("risk_genotype") or "-"
            score = m.get("risk_score", 0)
            lines.append(f"| {rsid} | {gene} | {geno} | {is_risk} | {risk_geno} | {score} |")
        if len(matches) > 50:
            lines.append(f"\n_仅展示前 50 条，共 {len(matches)} 条_")
    else:
        lines.append("_暂无基因型匹配数据_")
    lines.append("")

    # 生活建议
    recs = report_json.get("recommendations") or []
    lines.append(f"## 生活建议（共 {len(recs)} 条）")
    lines.append("")
    if recs:
        priority_emoji = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
        for r in recs:
            p = r.get("priority", "medium")
            emoji = priority_emoji.get(p, "⚪")
            cat = r.get("category", "")
            content = r.get("content", "")
            evidence = r.get("evidence") or ""
            lines.append(f"- {emoji} **[{p.upper()}] {cat}**：{content}")
            if evidence:
                lines.append(f"  - 证据：{evidence}")
    else:
        lines.append("_暂无生活建议数据_")
    lines.append("")

    # 免责声明
    lines.append("## 免责声明")
    lines.append("")
    lines.append("本报告基于上传的个人基因组数据生成，仅用于科研与健康参考目的。")
    lines.append("风险评估结果受位点覆盖度、群体代表性、模型假设等限制，不代表临床诊断。")
    lines.append("任何医疗决策请咨询专业医师。")
    lines.append("")

    return "\n".join(lines)


# ========== 内部辅助 ==========


async def _get_owned_genome(
    db: AsyncSession, genome_id: UUID, current_user: User
) -> PersonalGenome:
    """加载基因组文件并校验 owner

    所有 genome 级端点必须调用此函数
    """
    genome = await db.get(PersonalGenome, genome_id)
    if not genome:
        raise NotFoundError("基因组文件不存在")
    if genome.owner_id != current_user.id and current_user.role != UserRole.FOUNDER:
        raise ForbiddenError("无权访问他人基因组文件")
    return genome


def _genome_to_dict(g: PersonalGenome) -> dict:
    return {
        "id": str(g.id),
        "owner_id": str(g.owner_id),
        "project_id": str(g.project_id) if g.project_id else None,
        "file_name": g.file_name,
        "genome_build": g.genome_build,
        "source_format": g.source_format,
        "total_variants": g.total_variants,
        "parsed_summary": g.parsed_summary,
        "quality_metrics": g.quality_metrics,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


def _tpl_to_dict(t: PromptTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "template_type": t.template_type,
        "genome_build": t.genome_build,
        "trait_category": t.trait_category,
        "content": t.content,
        "description": t.description,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


__all__ = ["router"]
