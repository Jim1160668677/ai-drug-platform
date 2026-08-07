"""种子数据脚本 — 灌入演示数据

用法:
    python -m app.db.seed
    或在 Makefile 中: make seed
"""
import asyncio
import sys
import os

# 确保导入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, UserRole
from app.core.config import settings
from app.core.encryption import encrypt
from app.db.session import AsyncSessionLocal, init_db
from app.models.user import User
from app.models.project import Project, ProjectStatus
from app.models.dataset import Dataset, DataType, ParseStatus
from app.models.target import Target, EvidenceGrade
from app.models.hypothesis import Hypothesis, HypothesisStatus
from app.models.experiment import Experiment, ExperimentStatus, ExperimentType
from app.models.treatment import Treatment, TreatmentStatus, TreatmentType
from app.models.llm_config import LLMConfig, AccessMode, UpstreamProtocol
from app.models.trait import Trait, TraitCategory
from app.models.snp_locus import (
    SnpLocus, LocusTier, Population as LocusPopulation,
    EvidenceSource, EvidenceLevel,
)
from app.models.prompt_template import PromptTemplate, TemplateType


DEMO_PASSWORD = "demo123456"

# Agnes LLM 配置 — 从环境变量读取真实 Key，未配置时使用占位符
# 比赛/API Key 安全要求：源码中不得明文写入真实 API Key
# 评审如需实测，请在管理后台「LLM 配置」中填入专用测试 Key
AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "sk-agnes-api-key-placeholder-fill-in-real-key-via-admin-ui")
AGNES_BASE_URL = os.environ.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
AGNES_MODEL = os.environ.get("AGNES_MODEL", "agnes-2.0-flash")


async def seed_llm_config(db: AsyncSession) -> int:
    """灌入 Agnes LLM 配置"""
    existing = await db.execute(select(LLMConfig).where(LLMConfig.name == "Agnes"))
    if existing.scalar_one_or_none():
        return 0

    # 先清除其他 active 配置
    other_active = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True))  # noqa: E712
    for cfg in other_active.scalars().all():
        cfg.is_active = False

    config = LLMConfig(
        name="Agnes",
        provider="agnes",
        access_mode=AccessMode.API_ONLY,
        upstream_protocol=UpstreamProtocol.CHAT_COMPLETIONS,
        base_url=AGNES_BASE_URL,
        api_key=encrypt(AGNES_API_KEY),
        test_model=AGNES_MODEL,
        fast_model=AGNES_MODEL,
        deep_model=AGNES_MODEL,
        version="1.0.0",
        temperature=0.7,
        max_tokens=2000,
        timeout_sec=60,
        is_active=True,
        description="Agnes AI 大模型 API（API Only / Chat Completions）",
    )
    db.add(config)
    await db.flush()
    return 1


# ========== 个人基因组解读模块种子数据 ==========

# 9 大性状标准模板
DEMO_TRAITS = [
    {
        "name": "过敏易感性",
        "category": TraitCategory.ALLERGY,
        "description": "由 IL13/IL4/FcεRIα 等免疫调控基因变异影响的过敏体质",
        "icon": "ShieldAlert",
    },
    {
        "name": "乳糖代谢能力",
        "category": TraitCategory.METABOLISM,
        "description": "LCT 基因调控区变异决定成年期乳糖酶持续表达",
        "icon": "Milk",
    },
    {
        "name": "酒精代谢能力",
        "category": TraitCategory.METABOLISM,
        "description": "ALDH2 rs671 变异影响乙醛代谢，亚洲人群携带率高",
        "icon": "Wine",
    },
    {
        "name": "咖啡因代谢速度",
        "category": TraitCategory.METABOLISM,
        "description": "CYP1A2 rs762551 决定咖啡因代谢快慢",
        "icon": "Coffee",
    },
    {
        "name": "叶酸代谢效率",
        "category": TraitCategory.METABOLISM,
        "description": "MTHFR C677T 变异降低叶酸代谢效率",
        "icon": "Pill",
    },
    {
        "name": "心血管疾病风险",
        "category": TraitCategory.CARDIO,
        "description": "ACE/AGT/NOS3 等多基因变异影响心血管风险",
        "icon": "Heart",
    },
    {
        "name": "耐力运动潜能",
        "category": TraitCategory.ATHLETIC,
        "description": "ACTN3 R577X 决定快/慢肌纤维比例",
        "icon": "Activity",
    },
    {
        "name": "睡眠节律倾向",
        "category": TraitCategory.SLEEP,
        "description": "CLOCK/MTNR1B 变异影响昼夜节律",
        "icon": "Moon",
    },
    {
        "name": "药物代谢能力",
        "category": TraitCategory.DRUG_RESPONSE,
        "description": "CYP2D6/CYP2C19/CYP2C9 多态性影响临床药物代谢",
        "icon": "Pill",
    },
]

# 标准位点库 — 含真实东亚人群验证位点
DEMO_LOCI = [
    # IL13 过敏
    {"rsid": "rs20541", "chrom": "5", "pos37": 132562611, "gene": "IL13",
     "trait_name": "过敏易感性", "effect_allele": "A", "risk_genotype": "AA|AG",
     "effect_size": 1.4, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_II, "pmid": "18604357"},
    {"rsid": "rs1800925", "chrom": "5", "pos37": 132558294, "gene": "IL13",
     "trait_name": "过敏易感性", "effect_allele": "C", "risk_genotype": "CC|CT",
     "effect_size": 1.3, "weight": 0.3, "tier": LocusTier.AUXILIARY, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_III, "pmid": "18604357"},
    # LCT 乳糖代谢
    {"rsid": "rs4988235", "chrom": "2", "pos37": 136608646, "gene": "LCT",
     "trait_name": "乳糖代谢能力", "effect_allele": "G", "risk_genotype": "GG",
     "effect_size": 2.5, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_I, "pmid": "11788828"},
    {"rsid": "rs182549", "chrom": "2", "pos37": 136602919, "gene": "MCM6",
     "trait_name": "乳糖代谢能力", "effect_allele": "T", "risk_genotype": "TT",
     "effect_size": 2.0, "weight": 0.3, "tier": LocusTier.AUXILIARY, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_II, "pmid": "11788828"},
    # ALDH2 酒精代谢
    {"rsid": "rs671", "chrom": "12", "pos37": 111803962, "gene": "ALDH2",
     "trait_name": "酒精代谢能力", "effect_allele": "A", "risk_genotype": "AA|AG",
     "effect_size": 3.5, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_I, "pmid": "16358213"},
    # CYP1A2 咖啡因
    {"rsid": "rs762551", "chrom": "15", "pos37": 74749576, "gene": "CYP1A2",
     "trait_name": "咖啡因代谢速度", "effect_allele": "C", "risk_genotype": "CC|AC",
     "effect_size": 1.8, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.EAST_ASIAN,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_II, "pmid": "16906654"},
    # MTHFR 叶酸
    {"rsid": "rs1801133", "chrom": "1", "pos37": 11796321, "gene": "MTHFR",
     "trait_name": "叶酸代谢效率", "effect_allele": "T", "risk_genotype": "TT|CT",
     "effect_size": 2.0, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_I, "pmid": "11591650"},
    # ACE 心血管
    {"rsid": "rs4646994", "chrom": "17", "pos37": 63477061, "gene": "ACE",
     "trait_name": "心血管疾病风险", "effect_allele": "D", "risk_genotype": "DD",
     "effect_size": 1.3, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_II, "pmid": "9324229"},
    {"rsid": "rs699", "chrom": "1", "pos37": 230710048, "gene": "AGT",
     "trait_name": "心血管疾病风险", "effect_allele": "C", "risk_genotype": "CC|AC",
     "effect_size": 1.2, "weight": 0.3, "tier": LocusTier.AUXILIARY, "pop": LocusPopulation.EAST_ASIAN,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_III, "pmid": "10924993"},
    # ACTN3 运动
    {"rsid": "rs1815739", "chrom": "11", "pos37": 66560624, "gene": "ACTN3",
     "trait_name": "耐力运动潜能", "effect_allele": "X", "risk_genotype": "XX",
     "effect_size": 0.7, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_II, "pmid": "12676577"},
    # CLOCK 睡眠
    {"rsid": "rs1801260", "chrom": "4", "pos37": 55417555, "gene": "CLOCK",
     "trait_name": "睡眠节律倾向", "effect_allele": "A", "risk_genotype": "AA",
     "effect_size": 1.5, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.EAST_ASIAN,
     "src": EvidenceSource.GWAS_CATALOG, "level": EvidenceLevel.LEVEL_III, "pmid": "10480947"},
    # CYP2D6 药物
    {"rsid": "rs3892097", "chrom": "22", "pos37": 42128945, "gene": "CYP2D6",
     "trait_name": "药物代谢能力", "effect_allele": "A", "risk_genotype": "AA|AG",
     "effect_size": 2.5, "weight": 0.7, "tier": LocusTier.CORE, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.CLINVAR, "level": EvidenceLevel.LEVEL_I, "pmid": "1990404"},
    # CYP2C19 药物
    {"rsid": "rs4244285", "chrom": "10", "pos37": 94781859, "gene": "CYP2C19",
     "trait_name": "药物代谢能力", "effect_allele": "A", "risk_genotype": "AA|AG",
     "effect_size": 2.0, "weight": 0.3, "tier": LocusTier.AUXILIARY, "pop": LocusPopulation.HAN_CHINESE,
     "src": EvidenceSource.CLINVAR, "level": EvidenceLevel.LEVEL_I, "pmid": "16584126"},
]

# Prompt 模板
DEMO_PROMPT_TEMPLATES = [
    {
        "name": "默认性状检索模板",
        "template_type": TemplateType.TRAIT_SEARCH,
        "genome_build": None,
        "trait_category": None,
        "content": "针对性状「{trait}」（分类：{category}），列出 3 个最值得纳入知识库的 SNP 位点研究方向。严格输出 JSON 数组。",
        "description": "通用性状检索 Prompt — 含 {trait} {category} 占位符",
        "is_active": True,
    },
    {
        "name": "过敏性状解读模板",
        "template_type": TemplateType.INTERPRETATION,
        "genome_build": "GRCh37",
        "trait_category": TraitCategory.ALLERGY,
        "content": "你是临床免疫学专家。基于过敏易感性检测结果生成结构化解读：\n性状：{trait}\n风险等级：{risk_level}\n评分：{risk_score}\n\n输出 JSON：{{summary, mechanism, action_items, disclaimer}}",
        "description": "过敏易感性专用解读模板",
        "is_active": True,
    },
    {
        "name": "代谢性状解读模板",
        "template_type": TemplateType.INTERPRETATION,
        "genome_build": "GRCh37",
        "trait_category": TraitCategory.METABOLISM,
        "content": "你是营养遗传学专家。基于代谢能力检测结果生成结构化解读：\n性状：{trait}\n风险等级：{risk_level}\n评分：{risk_score}\n\n输出 JSON：{{summary, mechanism, action_items, disclaimer}}",
        "description": "代谢能力（乳糖/酒精/咖啡因/叶酸）专用解读模板",
        "is_active": True,
    },
    {
        "name": "通用解读模板",
        "template_type": TemplateType.INTERPRETATION,
        "genome_build": None,
        "trait_category": None,
        "content": "你是临床遗传学专家。基于基因检测结果生成结构化解读：\n性状：{trait}\n风险等级：{risk_level}\n评分：{risk_score}\n\n输出 JSON：{{summary, mechanism, action_items, disclaimer}}",
        "description": "通用解读模板 — 含 {trait} {risk_level} {risk_score} 占位符",
        "is_active": True,
    },
]


async def seed_genome_data(db: AsyncSession) -> dict:
    """灌入个人基因组解读模块种子数据

    Returns:
        {traits, loci, prompt_templates} 计数
    """
    stats = {"traits": 0, "loci": 0, "prompt_templates": 0}

    # 1. 性状
    trait_name_to_id = {}
    for trait_data in DEMO_TRAITS:
        existing = await db.execute(select(Trait).where(Trait.name == trait_data["name"]))
        if existing.scalar_one_or_none():
            continue
        trait = Trait(
            name=trait_data["name"],
            category=trait_data["category"],
            description=trait_data["description"],
            icon=trait_data["icon"],
        )
        db.add(trait)
        await db.flush()
        trait_name_to_id[trait_data["name"]] = trait.id
        stats["traits"] += 1

    # 加载所有性状 ID（含已存在的）
    for trait_data in DEMO_TRAITS:
        if trait_data["name"] not in trait_name_to_id:
            result = await db.execute(select(Trait).where(Trait.name == trait_data["name"]))
            t = result.scalar_one_or_none()
            if t:
                trait_name_to_id[t.name] = t.id

    # 2. SNP 位点
    for locus_data in DEMO_LOCI:
        existing = await db.execute(
            select(SnpLocus).where(SnpLocus.rsid == locus_data["rsid"])
        )
        if existing.scalar_one_or_none():
            continue
        trait_id = trait_name_to_id.get(locus_data["trait_name"])
        if not trait_id:
            continue
        locus = SnpLocus(
            rsid=locus_data["rsid"],
            chromosome=locus_data["chrom"],
            position_grch37=locus_data["pos37"],
            position_grch38=None,
            gene_symbol=locus_data["gene"],
            trait_id=trait_id,
            effect_allele=locus_data["effect_allele"],
            risk_genotype=locus_data["risk_genotype"],
            effect_size=locus_data["effect_size"],
            weight=locus_data["weight"],
            locus_tier=locus_data["tier"],
            population=locus_data["pop"],
            evidence_source=locus_data["src"],
            evidence_level=locus_data["level"],
            pmid=locus_data["pmid"],
            is_approved=True,
        )
        db.add(locus)
        stats["loci"] += 1

    if stats["loci"]:
        await db.flush()

    # 3. Prompt 模板
    for tpl_data in DEMO_PROMPT_TEMPLATES:
        existing = await db.execute(select(PromptTemplate).where(PromptTemplate.name == tpl_data["name"]))
        if existing.scalar_one_or_none():
            continue
        tpl = PromptTemplate(
            name=tpl_data["name"],
            template_type=tpl_data["template_type"],
            genome_build=tpl_data["genome_build"],
            trait_category=tpl_data["trait_category"],
            content=tpl_data["content"],
            description=tpl_data["description"],
            is_active=tpl_data["is_active"],
        )
        db.add(tpl)
        stats["prompt_templates"] += 1

    if stats["prompt_templates"]:
        await db.flush()

    return stats

DEMO_USERS = [
    {
        "email": "sid@ai-drug.com",
        "name": "Sid Sijbrandij",
        "role": UserRole.FOUNDER,
        "organization": "AI Drug Inc.",
        "bio": "GitLab 联合创始人，个性化癌症治疗倡导者",
    },
    {
        "email": "chief@ai-drug.com",
        "name": "Dr. Sarah Chen",
        "role": UserRole.CHIEF_RESEARCHER,
        "organization": "AI Drug Inc.",
        "bio": "首席科学家，专注精准医学与 AI 药物设计",
    },
    {
        "email": "researcher@ai-drug.com",
        "name": "Dr. Li Wei",
        "role": UserRole.RESEARCHER,
        "organization": "AI Drug Inc.",
        "bio": "研究员，负责多组学数据分析",
    },
    {
        "email": "doctor@ai-drug.com",
        "name": "Dr. Maria Garcia",
        "role": UserRole.DOCTOR,
        "organization": "Central Hospital",
        "bio": "临床医生，负责治疗方案评估",
    },
    {
        "email": "engineer@ai-drug.com",
        "name": "Alex Kumar",
        "role": UserRole.DATA_ENGINEER,
        "organization": "AI Drug Inc.",
        "bio": "数据工程师，负责系统运维与数据质量",
    },
]


async def seed_database(db: AsyncSession) -> dict:
    """灌入种子数据"""
    stats = {"users": 0, "projects": 0, "datasets": 0, "targets": 0, "hypotheses": 0, "experiments": 0, "llm_configs": 0,
             "genome_traits": 0, "genome_loci": 0, "genome_prompt_templates": 0}

    # 1. 创建用户
    users = {}
    for user_data in DEMO_USERS:
        existing = await db.execute(select(User).where(User.email == user_data["email"]))
        if existing.scalar_one_or_none():
            continue
        user = User(
            email=user_data["email"],
            name=user_data["name"],
            hashed_password=hash_password(DEMO_PASSWORD),
            role=user_data["role"],
            organization=user_data.get("organization"),
            bio=user_data.get("bio"),
        )
        db.add(user)
        await db.flush()
        users[user_data["email"]] = user
        stats["users"] += 1

    founder = users.get("sid@ai-drug.com")
    if not founder:
        result = await db.execute(select(User).where(User.email == "sid@ai-drug.com"))
        founder = result.scalar_one_or_none()
    if not founder:
        print("无法获取 founder 用户，终止种子数据")
        return stats

    # 2. 创建示例项目 — Sid 的 NSCLC 个性化治疗
    existing_proj = await db.execute(select(Project).where(Project.name == "Sid NSCLC 个性化治疗"))
    project = existing_proj.scalar_one_or_none()
    if not project:
        project = Project(
            name="Sid NSCLC 个性化治疗",
            patient_pseudonym="SID-001",
            cancer_type="NSCLC",
            stage="IV",
            description="基于 GitLab 联合创始人 Sid 经历的 NSCLC 个性化精准治疗项目。通过多组学数据整合、AI 靶点发现和干湿闭环优化治疗方案。",
            status=ProjectStatus.ACTIVE,
            owner_id=founder.id,
            metadata_={"source": "demo_seed", "inspiration": "Sid Sijbrandij case"},
        )
        db.add(project)
        await db.flush()
        stats["projects"] += 1

    # 3. 创建示例数据集
    existing_ds = await db.execute(select(Dataset).where(Dataset.project_id == project.id))
    if not existing_ds.scalars().first():
        # RNA-seq 数据集
        rna_dataset = Dataset(
            project_id=project.id,
            name="Sid 肿瘤组织 RNA-seq",
            data_type=DataType.RNA_SEQ,
            source="tumor_biopsy",
            storage_path="tests/fixtures/sample_rna_seq.csv",
            file_format="csv",
            file_size=1024,
            parse_status=ParseStatus.COMPLETED,
            quality_metrics={
                "missing_rate": 0.02,
                "low_expression_ratio": 0.15,
                "total_genes": 10,
                "total_samples": 5,
            },
            parsed_summary={
                "genes": 10,
                "samples": 5,
                "top_genes": [
                    {"symbol": "EGFR", "mean_expr": 25.5},
                    {"symbol": "TP53", "mean_expr": 30.1},
                    {"symbol": "KRAS", "mean_expr": 15.2},
                    {"symbol": "B7H3", "mean_expr": 12.3},
                ],
            },
            uploaded_by=founder.id,
        )
        db.add(rna_dataset)

        # VCF 数据集
        vcf_dataset = Dataset(
            project_id=project.id,
            name="Sid WES 变异检测 VCF",
            data_type=DataType.WES,
            source="whole_exome_sequencing",
            storage_path="tests/fixtures/sample_vcf.vcf",
            file_format="vcf",
            file_size=2048,
            parse_status=ParseStatus.COMPLETED,
            quality_metrics={
                "total_variants": 2,
                "pass_rate": 1.0,
                "ts_tv_ratio": 2.0,
            },
            parsed_summary={
                "total_variants": 2,
                "variants": [
                    {"query": "chr7:55259515:T>A", "gene": "EGFR", "hgvs_p": "p.Thr790Met"},
                    {"query": "chr7:55259513:G>A", "gene": "EGFR", "hgvs_p": "p.Leu858Arg"},
                ],
            },
            uploaded_by=founder.id,
        )
        db.add(vcf_dataset)
        await db.flush()
        stats["datasets"] += 2

    # 4. 创建示例靶点
    existing_targets = await db.execute(select(Target).where(Target.project_id == project.id))
    if not existing_targets.scalars().first():
        egfr_target = Target(
            project_id=project.id,
            gene_symbol="EGFR",
            gene_name="Epidermal Growth Factor Receptor",
            evidence_grade=EvidenceGrade.LEVEL_I,
            confidence_score=0.85,
            source="multi_omics_integration",
            variant_info=[
                {"query": "chr7:55259515:T>A", "hgvs_p": "p.Thr790Met", "clinvar": {"clnsig": "Pathogenic"}},
                {"query": "chr7:55259513:G>A", "hgvs_p": "p.Leu858Arg", "clinvar": {"clnsig": "Pathogenic"}},
            ],
            annotation={
                "entrez_id": 1956,
                "uniprot_id": "P00533",
                "summary": "EGFR 是跨膜酪氨酸激酶受体，NSCLC 中常发生激活突变",
            },
            pathway={"pathways": ["MAPK signaling", "ErbB signaling", "PI3K-Akt signaling"]},
            approved_drugs=[
                {"name": "Osimertinib", "chembl_id": "CHEMBL2114657", "max_phase": 4},
                {"name": "Gefitinib", "chembl_id": "CHEMBL537", "max_phase": 4},
            ],
            analysis_tier="deep_insight",
        )
        b7h3_target = Target(
            project_id=project.id,
            gene_symbol="B7H3",
            gene_name="CD276 Molecule",
            evidence_grade=EvidenceGrade.LEVEL_III,
            confidence_score=0.62,
            source="scrna_analysis",
            annotation={
                "entrez_id": 80381,
                "summary": "B7-H3 是免疫检查点分子，在多种实体瘤中高表达",
            },
            pathway={"pathways": ["immune_checkpoint"], "ppi_neighbors": [{"gene": "CD28"}, {"gene": "PD-L1"}]},
            approved_drugs=[],
            analysis_tier="fast_screen",
        )
        db.add_all([egfr_target, b7h3_target])
        await db.flush()
        stats["targets"] += 2

    # 5. 创建示例假设
    existing_hyps = await db.execute(select(Hypothesis).where(Hypothesis.project_id == project.id))
    if not existing_hyps.scalars().first():
        h1 = Hypothesis(
            project_id=project.id,
            name="H1: EGFR 通路抑制策略",
            description="通过三代 TKI Osimertinib 抑制 EGFR 通路，克服 T790M 耐药",
            mechanism="EGFR T790M 突变导致一代 TKI 耐药，三代 TKI 可克服",
            strategy="Osimertinib 80mg qd 单药治疗",
            status=HypothesisStatus.COMPLETED,
            analysis_config={"tier": "deep_insight"},
            analysis_result={"targets": [{"gene_symbol": "EGFR", "evidence_grade": "I"}]},
            target_list=["EGFR"],
            created_by=founder.id,
        )
        h2 = Hypothesis(
            project_id=project.id,
            name="H2: B7H3 免疫治疗策略",
            description="针对 B7H3 高表达，探索免疫检查点抑制联合治疗",
            mechanism="B7H3 在肿瘤微环境中高表达，导致免疫抑制",
            strategy="B7H3 靶向 ADC + anti-PD-1 联合",
            status=HypothesisStatus.DRAFT,
            target_list=["B7H3", "PD-L1"],
            created_by=founder.id,
        )
        db.add_all([h1, h2])
        await db.flush()
        stats["hypotheses"] += 2

    # 6. 创建示例实验
    existing_exps = await db.execute(select(Experiment).where(Experiment.project_id == project.id))
    if not existing_exps.scalars().first():
        exp = Experiment(
            project_id=project.id,
            name="Osimertinib 细胞毒性测试",
            exp_type=ExperimentType.CYTOTOXICITY,
            status=ExperimentStatus.COMPLETED,
            config={
                "predicted": {"ic50": 0.05, "inhibition_rate": 85},
                "drug": "Osimertinib",
                "cell_line": "H1975 (EGFR T790M)",
            },
            result={
                "measured": {"ic50": 0.08, "inhibition_rate": 78},
                "adverse_events": [],
            },
            success=True,
            iteration=1,
            lab_source="AI Drug Lab",
            notes="Osimertinib 对 H1975 细胞系显示良好抑制活性",
        )
        db.add(exp)
        await db.flush()
        stats["experiments"] += 1

    # 7. 灌入 Agnes LLM 配置
    stats["llm_configs"] += await seed_llm_config(db)

    # 8. 灌入个人基因组解读模块种子数据
    try:
        genome_stats = await seed_genome_data(db)
        stats["genome_traits"] = genome_stats["traits"]
        stats["genome_loci"] = genome_stats["loci"]
        stats["genome_prompt_templates"] = genome_stats["prompt_templates"]
    except Exception as e:
        print(f"[WARN] 个人基因组种子数据灌入失败（不影响主流程）: {e}")

    await db.commit()
    return stats


async def main():
    """主入口"""
    print("=" * 60)
    print("AI模式精准药物设计系统 — 种子数据灌入")
    print(f"  数据库: {settings.DATABASE_URL.split('@')[-1]}")
    print("=" * 60)

    # 初始化表
    await init_db()

    async with AsyncSessionLocal() as db:
        stats = await seed_database(db)

    print("\n种子数据灌入完成：")
    for k, v in stats.items():
        print(f"  {k}: {v} 条新增")
    print(f"\n演示账号（密码统一为 {DEMO_PASSWORD}）：")
    for user_data in DEMO_USERS:
        print(f"  {user_data['email']:<30} ({user_data['role'].value}) — {user_data['name']}")


if __name__ == "__main__":
    asyncio.run(main())
