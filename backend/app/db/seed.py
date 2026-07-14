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


DEMO_PASSWORD = "demo123456"

AGNES_API_KEY = "sk-EGw4PNgeLncSdPDy09XZJK9DQHa4uUcQ15EEv8bousgPxo39"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
AGNES_MODEL = "agnes-2.0-flash"


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
    stats = {"users": 0, "projects": 0, "datasets": 0, "targets": 0, "hypotheses": 0, "experiments": 0, "llm_configs": 0}

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
