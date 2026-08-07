"""LLM 解读 + 知识库扩充服务

两个职责：
1. interpret(): 调用 UserLLMRouter 生成单个风险评估的解读文本
2. expand_kb(): 调用 UserLLMRouter 批量扩充性状/位点/Prompt 模板

LLM 调用必须走 UserLLMRouter（用户级配置优先，自动降级到系统默认）。
失败时返回规则生成的 fallback 解读，标注 llm_model="rule_fallback"。
"""
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_genome import (
    GenotypeMatch,
    LifestyleRecommendation,
    RiskAssessment,
)
from app.models.prompt_template import PromptTemplate, TemplateType
from app.models.snp_locus import SnpLocus
from app.models.trait import Trait
from app.services.llm.user_router import UserLLMRouter

logger = logging.getLogger(__name__)


# 默认解读 Prompt 模板（当 DB 无激活模板时使用）
_DEFAULT_INTERPRET_PROMPT = """你是临床遗传学专家。基于以下个人基因检测结果，生成结构化解读。

## 性状
{name}（分类：{category}）
{description}

## 风险评分
- 整体风险评分：{overall_score}（{risk_level}）
- 核心位点命中：{core_matched} 个
- 辅助位点命中：{aux_matched} 个

## 命中位点详情
{loci_details}

## 任务
请用中文输出严格的 JSON：
{{
  "summary": "一句话总结风险评估结果",
  "mechanism": "相关基因和通路的生物学机制说明",
  "action_items": ["可执行建议1", "可执行建议2", "可执行建议3"],
  "disclaimer": "本结果仅供健康参考，不构成临床诊断"
}}

注意：必须输出有效 JSON，不要包含额外文字或代码块标记。
"""


async def interpret(
    db: AsyncSession,
    risk_assessment_id: UUID,
    user,
    use_llm: bool = True,
    user_llm_config_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """生成风险评估的 LLM 解读

    Args:
        db: 数据库会话
        risk_assessment_id: 风险评估 ID
        user: 当前用户
        use_llm: 是否调用 LLM（False 则纯规则生成）
        user_llm_config_id: 用户 LLM 配置 ID（不传则用激活的）

    Returns:
        {summary, mechanism, action_items, disclaimer, llm_model, duration_sec}
    """
    # 1. 加载 RiskAssessment
    assessment = await db.get(RiskAssessment, risk_assessment_id)
    if not assessment:
        raise ValueError(f"RiskAssessment 不存在: {risk_assessment_id}")

    # 2. 加载 Trait
    trait = await db.get(Trait, assessment.trait_id)
    if not trait:
        raise ValueError(f"Trait 不存在: {assessment.trait_id}")

    # 3. 加载命中位点详情
    loci_details = await _load_matched_loci_details(db, assessment)

    # 4. 构造 prompt
    prompt = _build_interpret_prompt(assessment, trait, loci_details)

    # 5. 调 LLM（或降级）
    if not use_llm:
        result = _rule_fallback_interpret(assessment, trait, loci_details)
    else:
        try:
            router = await UserLLMRouter.create(db, user, user_llm_config_id)
            response = await router.complete(
                prompt,
                tier="deep_insight",
                system="你是临床遗传学专家，擅长用通俗易懂的语言解释基因检测结果。",
            )

            content = response.get("content", "")
            result = _parse_llm_response(content)
            result["llm_model"] = response.get("model", "unknown")
            result["provider"] = response.get("provider", "unknown")
        except Exception as e:
            logger.error(f"LLM 解读失败，降级到规则生成: {e}", exc_info=True)
            result = _rule_fallback_interpret(assessment, trait, loci_details)

    # 6. 写回 RiskAssessment
    assessment.interpretation = result
    assessment.llm_model = result.get("llm_model")
    await db.flush()

    return result


async def expand_kb(
    db: AsyncSession,
    user,
    trait_ids: Optional[List[UUID]] = None,
    user_llm_config_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """扩充知识库 — 批量调用 LLM 生成位点研究方向 + 新 Prompt 模板

    Args:
        db: 数据库会话
        user: 当前用户
        trait_ids: 指定性状 ID 列表（不传则全部）
        user_llm_config_id: 用户 LLM 配置 ID

    Returns:
        {traits_processed, loci_added, prompts_added, errors}
    """
    # 1. 加载性状列表
    stmt = select(Trait)
    if trait_ids:
        stmt = stmt.where(Trait.id.in_(trait_ids))
    result = await db.execute(stmt)
    traits = list(result.scalars().all())

    if not traits:
        return {"traits_processed": 0, "loci_added": 0, "prompts_added": 0, "errors": []}

    router = await UserLLMRouter.create(db, user, user_llm_config_id)

    loci_added = 0
    prompts_added = 0
    errors: List[str] = []

    for trait in traits:
        try:
            # 2. 生成位点研究方向
            prompt = (
                f"针对性状「{trait.name}」（分类：{trait.category}），"
                f"列出 3 个最值得纳入知识库的 SNP 位点研究方向，"
                f"严格输出 JSON 数组：[{{'rsid': 'rs1234', 'gene': 'IL13', 'rationale': '理由'}}]"
            )
            response = await router.complete(prompt, tier="fast_screen")
            new_loci = _parse_loci_suggestions(response.get("content", ""), trait.id)
            for loc_data in new_loci:
                locus = SnpLocus(
                    rsid=loc_data["rsid"],
                    chromosome=loc_data.get("chromosome", ""),
                    gene_symbol=loc_data.get("gene"),
                    trait_id=trait.id,
                    effect_allele=loc_data.get("effect_allele"),
                    effect_size=loc_data.get("effect_size"),
                    weight=0.5,
                    evidence_source="llm",
                    evidence_level="IV",
                    is_approved=False,
                )
                db.add(locus)
                loci_added += 1

            # 3. 生成 Prompt 模板候选
            tpl_prompt = (
                f"为性状「{trait.name}」（分类：{trait.category}）写一个解读模板，"
                f"包含 {{trait}} 和 {{risk_level}} 占位符。"
                f"输出纯文本模板内容，不要解释。"
            )
            tpl_response = await router.complete(tpl_prompt, tier="fast_screen")
            tpl_content = tpl_response.get("content", "").strip()
            if tpl_content:
                tpl = PromptTemplate(
                    name=f"auto_{trait.category}_{trait.name[:20]}",
                    template_type=TemplateType.INTERPRETATION,
                    genome_build=None,
                    trait_category=trait.category,
                    content=tpl_content[:5000],
                    description=f"自动生成 — 性状 {trait.name}",
                    is_active=False,  # 自动生成默认不启用
                )
                db.add(tpl)
                prompts_added += 1

        except Exception as e:
            logger.warning(f"扩充 trait {trait.name} 失败: {e}")
            errors.append(f"{trait.name}: {str(e)}")

    if loci_added or prompts_added:
        await db.flush()

    return {
        "traits_processed": len(traits),
        "loci_added": loci_added,
        "prompts_added": prompts_added,
        "errors": errors,
    }


# ===== 内部辅助 =====


async def _load_matched_loci_details(
    db: AsyncSession, assessment: RiskAssessment
) -> List[Dict[str, Any]]:
    """加载风险评估命中的位点详情"""
    if not assessment.matched_loci_ids:
        return []
    locus_ids = [UUID(lid) if isinstance(lid, str) else lid for lid in assessment.matched_loci_ids]
    stmt = select(SnpLocus).where(SnpLocus.id.in_(locus_ids))
    result = await db.execute(stmt)
    return [
        {
            "rsid": loc.rsid,
            "gene": loc.gene_symbol or "未知",
            "effect_allele": loc.effect_allele or "-",
            "risk_genotype": loc.risk_genotype or "-",
            "effect_size": loc.effect_size,
            "tier": loc.locus_tier,
            "population": loc.population,
        }
        for loc in result.scalars().all()
    ]


def _build_interpret_prompt(
    assessment: RiskAssessment, trait: Trait, loci_details: List[Dict]
) -> str:
    """构造解读 prompt"""
    # 优先用 DB 模板（已实现 → 暂时简化为默认模板）
    loci_str = "\n".join(
        f"- {l['rsid']}（{l['gene']}）：风险等位={l['effect_allele']}，"
        f"效应量={l['effect_size']}，分级={l['tier']}"
        for l in loci_details
    ) or "（无命中位点详情）"

    return _DEFAULT_INTERPRET_PROMPT.format(
        name=trait.name,
        category=trait.category,
        description=trait.description or "",
        overall_score=assessment.overall_risk_score,
        risk_level=assessment.risk_level,
        core_matched=assessment.core_loci_matched,
        aux_matched=assessment.auxiliary_loci_matched,
        loci_details=loci_str,
    )


def _parse_llm_response(content: str) -> Dict[str, Any]:
    """解析 LLM 输出为结构化 JSON

    失败时返回降级结构。
    """
    if not content:
        return _empty_interpretation("llm_empty_response")

    # 去除 markdown 代码块
    text = content.strip()
    if text.startswith("```"):
        # 去掉 ```json 或 ``` 标记
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
        return {
            "summary": data.get("summary", ""),
            "mechanism": data.get("mechanism", ""),
            "action_items": data.get("action_items", []),
            "disclaimer": data.get("disclaimer", "本结果仅供健康参考，不构成临床诊断"),
        }
    except json.JSONDecodeError as e:
        logger.warning(f"LLM 输出非合法 JSON: {e}\n原始内容: {content[:300]}")
        # 降级：把原文作为 summary
        return {
            "summary": content[:500],
            "mechanism": "",
            "action_items": [],
            "disclaimer": "LLM 输出解析失败，已展示原始内容",
            "parse_error": str(e),
        }


def _rule_fallback_interpret(
    assessment: RiskAssessment, trait: Trait, loci_details: List[Dict]
) -> Dict[str, Any]:
    """规则生成降级解读（LLM 不可用时）"""
    level_text = {
        "very_high": "非常高",
        "high": "较高",
        "moderate": "中等",
        "low": "较低",
    }.get(assessment.risk_level, assessment.risk_level)

    summary = (
        f"您的「{trait.name}」性状风险等级为{level_text}"
        f"（评分 {assessment.overall_risk_score:.2f}）。"
    )

    mechanism = f"涉及 {assessment.core_loci_matched} 个核心位点和 "
    f"{assessment.auxiliary_loci_matched} 个辅助位点。"
    if loci_details:
        genes = list({l["gene"] for l in loci_details if l["gene"] != "未知"})[:5]
        if genes:
            mechanism += f"主要关联基因：{', '.join(genes)}。"

    return {
        "summary": summary,
        "mechanism": mechanism,
        "action_items": [
            "请结合生活建议执行相关干预",
            "建议定期体检监测相关指标",
            "如需进一步诊疗请咨询临床遗传学专家",
        ],
        "disclaimer": "本结果由规则引擎生成（LLM 不可用），仅供健康参考，不构成临床诊断",
        "llm_model": "rule_fallback",
    }


def _empty_interpretation(reason: str) -> Dict[str, Any]:
    return {
        "summary": "解读生成失败",
        "mechanism": "",
        "action_items": [],
        "disclaimer": "本结果仅供健康参考，不构成临床诊断",
        "error": reason,
    }


def _parse_loci_suggestions(content: str, trait_id: UUID) -> List[Dict[str, Any]]:
    """解析 LLM 输出的位点建议列表"""
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        valid = []
        for item in data[:10]:  # 限制 10 条
            rsid = item.get("rsid", "").strip()
            if not rsid or not rsid.startswith("rs"):
                continue
            valid.append({
                "rsid": rsid,
                "gene": item.get("gene"),
                "chromosome": item.get("chromosome", ""),
                "effect_allele": item.get("effect_allele"),
                "effect_size": item.get("effect_size"),
            })
        return valid
    except json.JSONDecodeError:
        return []


__all__ = ["interpret", "expand_kb"]
