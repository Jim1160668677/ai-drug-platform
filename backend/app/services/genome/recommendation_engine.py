"""生活建议生成服务

按性状类别映射推荐模板，根据风险等级调整优先级。
不调 LLM — 纯规则驱动，与 LLM 解读并行使用。

性状类别映射：
  allergy    → 过敏原规避 + 抗组胺饮食
  metabolism → 代谢平衡 + 运动强度
  cardio     → 心血管监测 + 饮食结构
  athletic   → 训练强度 + 营养补充
  sleep      → 睡眠卫生 + 褪黑素
  skin_hair  → 防晒 + 护理
  cognition  → 认知训练 + 营养
  altitude   → 高原适应
  drug_response → 用药剂量调整
"""
import logging
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_genome import (
    LifestyleRecommendation,
    RecommendationCategory,
    RiskAssessment,
    RiskLevel,
)
from app.models.trait import Trait, TraitCategory
from app.services.genome.risk_scorer import RISK_THRESHOLDS

logger = logging.getLogger(__name__)


# 风险等级 → 优先级映射
RISK_TO_PRIORITY = {
    "very_high": "urgent",
    "high": "high",
    "moderate": "medium",
    "low": "low",
}


# 性状类别 → 建议模板（每类 3-5 条）
CATEGORY_TEMPLATES = {
    TraitCategory.ALLERGY: [
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "定期清洁居住环境，减少尘螨、花粉等常见过敏原暴露",
            "evidence": "GSTM1 基因多态性与过敏易感性相关",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "增加富含 omega-3 脂肪酸的食物（深海鱼、亚麻籽），有助抗炎",
            "evidence": "IL13 rs20541 增加过敏风险，omega-3 可调节免疫",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "如出现持续过敏症状，建议咨询过敏专科进行皮肤点刺试验",
            "evidence": "建议每年随访一次",
        },
    ],
    TraitCategory.METABOLISM: [
        {
            "category": RecommendationCategory.DIET,
            "content": "控制咖啡因摄入（每日 ≤ 200mg），CYP1A2 慢代谢者咖啡因半衰期延长 2 倍",
            "evidence": "CYP1A2 rs762551 慢代谢型咖啡因心血管风险升高",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "酒精代谢能力较弱者建议严格限酒或戒酒",
            "evidence": "ALDH2 rs671 突变携带者乙醛蓄积显著升高食管癌风险",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "乳糖不耐受者选择无乳糖奶制品或植物奶替代",
            "evidence": "LCT rs4988235 CC 型乳糖酶活性降低",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "补充叶酸建议优先选择 5-MTHF 形式",
            "evidence": "MTHFR C677T 突变降低叶酸代谢效率",
        },
    ],
    TraitCategory.CARDIO: [
        {
            "category": RecommendationCategory.DIET,
            "content": "采用地中海饮食模式，增加橄榄油、坚果、深海鱼摄入",
            "evidence": "ACE I/D 多态性携带者获益更显著",
        },
        {
            "category": RecommendationCategory.EXERCISE,
            "content": "每周 ≥ 150 分钟中等强度有氧运动（快走、游泳、骑行）",
            "evidence": "可降低 LDL 与血压",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "建议每年监测血压、血脂、心电图",
            "evidence": "高风险基因型人群监测频率应加倍",
        },
    ],
    TraitCategory.ATHLETIC: [
        {
            "category": RecommendationCategory.EXERCISE,
            "content": "ACTN3 R577X 携带者适合耐力运动（长跑、游泳）",
            "evidence": "X 等位基因降低快肌纤维比例",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "运动后 30 分钟内补充碳水+蛋白质（比例 3:1）促进恢复",
            "evidence": "提升糖原合成效率",
        },
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "保证每日 7-9 小时睡眠，深度睡眠期生长激素分泌促进肌肉修复",
            "evidence": "睡眠不足显著影响运动表现",
        },
    ],
    TraitCategory.SLEEP: [
        {
            "category": RecommendationCategory.SLEEP,
            "content": "固定就寝时间，避免周末作息大漂移",
            "evidence": "CLOCK 基因变异者更易受作息漂移影响",
        },
        {
            "category": RecommendationCategory.SLEEP,
            "content": "睡前 1 小时避免蓝光，必要时补充 0.3-0.5mg 褪黑素",
            "evidence": "MTNR1B 携带者褪黑素信号减弱",
        },
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "上午晒 15-30 分钟日光，强化昼夜节律",
            "evidence": "光照是生物钟最强同步信号",
        },
    ],
    TraitCategory.SKIN_HAIR: [
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "每日 SPF30+ 防晒，MC1R 突变携带者黑色素瘤风险升高",
            "evidence": "MC1R rs1805007 与红发/晒伤易感性相关",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "补充维生素 C、E 抗氧化",
            "evidence": "减少紫外线诱导的氧化损伤",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "每年皮肤科体检，关注痣的变化",
            "evidence": "高风险人群筛查频率应增加",
        },
    ],
    TraitCategory.COGNITION: [
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "学习新技能（外语、乐器）激活多脑区网络",
            "evidence": "BDNF Val66Met 影响神经可塑性",
        },
        {
            "category": RecommendationCategory.DIET,
            "content": "补充 omega-3 DHA（深海鱼或藻油）",
            "evidence": "APOE ε4 携带者认知下降风险升高，DHA 有保护作用",
        },
        {
            "category": RecommendationCategory.EXERCISE,
            "content": "每周 3 次有氧运动，提升脑源性神经营养因子",
            "evidence": "BDNF 表达受运动诱导",
        },
    ],
    TraitCategory.ALTITUDE: [
        {
            "category": RecommendationCategory.LIFESTYLE,
            "content": "高海拔活动前 3 天开始阶梯式上升（每日 ≤ 300m）",
            "evidence": "EPAS1 藏族变异低氧适应优势",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "携带 ACE I 等位基因者高原反应风险较低，仍建议备用乙酰唑胺",
            "evidence": "ACE I/D 影响肾素-血管紧张素系统",
        },
    ],
    TraitCategory.DRUG_RESPONSE: [
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "CYP2D6 慢代谢者避免可待因（转化率低，镇痛不足）",
            "evidence": "CYP2D6 多态性影响 25% 临床药物代谢",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "CYP2C19 慢代谢者氯吡格雷疗效降低，建议替代替格瑞洛",
            "evidence": "FDA 已标注黑框警告",
        },
        {
            "category": RecommendationCategory.MEDICAL,
            "content": "华法林剂量需结合 CYP2C9 和 VKORC1 基因型调整",
            "evidence": "CYP2C9 *2/*3 携带者剂量减少 30-70%",
        },
    ],
}


async def generate_recommendations(
    db: AsyncSession, risk_assessment_id: UUID
) -> List[LifestyleRecommendation]:
    """生成生活建议

    Args:
        db: 数据库会话
        risk_assessment_id: 风险评估 ID

    Returns:
        LifestyleRecommendation 列表（已 flush 到 DB）
    """
    # 1. 加载 RiskAssessment
    assessment = await db.get(RiskAssessment, risk_assessment_id)
    if not assessment:
        raise ValueError(f"RiskAssessment 不存在: {risk_assessment_id}")

    # 2. 加载 Trait
    trait = await db.get(Trait, assessment.trait_id)
    if not trait:
        raise ValueError(f"Trait 不存在: {assessment.trait_id}")

    # 3. 取模板
    templates = CATEGORY_TEMPLATES.get(trait.category, [])
    if not templates:
        logger.warning(f"性状类别 {trait.category} 无预设建议模板，使用通用模板")
        templates = [
            {
                "category": RecommendationCategory.LIFESTYLE,
                "content": "保持健康生活方式，定期体检",
                "evidence": "通用建议",
            }
        ]

    # 4. 按风险等级调整优先级
    priority = RISK_TO_PRIORITY.get(assessment.risk_level, "medium")

    # 5. 批量插入
    recommendations = []
    for tpl in templates:
        rec = LifestyleRecommendation(
            risk_assessment_id=risk_assessment_id,
            category=tpl["category"],
            content=tpl["content"],
            priority=priority,
            evidence=tpl.get("evidence"),
        )
        recommendations.append(rec)
        db.add(rec)

    if recommendations:
        await db.flush()

    logger.info(
        f"生成 {len(recommendations)} 条建议：assessment={risk_assessment_id} "
        f"category={trait.category} priority={priority}"
    )
    return recommendations


async def list_recommendations(
    db: AsyncSession, risk_assessment_id: UUID
) -> List[dict]:
    """查询建议列表"""
    from sqlalchemy import select

    stmt = (
        select(LifestyleRecommendation)
        .where(LifestyleRecommendation.risk_assessment_id == risk_assessment_id)
        .order_by(
            # urgent > high > medium > low
            LifestyleRecommendation.priority.asc(),
            LifestyleRecommendation.created_at.desc(),
        )
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(r.id),
            "risk_assessment_id": str(r.risk_assessment_id),
            "category": r.category,
            "content": r.content,
            "priority": r.priority,
            "evidence": r.evidence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in result.scalars().all()
    ]


__all__ = ["generate_recommendations", "list_recommendations", "CATEGORY_TEMPLATES"]
