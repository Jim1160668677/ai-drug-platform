"""个人基因组模块服务层单元测试

覆盖：
- trait_search.list_traits / get_trait_loci / search_loci
- genotype_matcher.match_genotype / list_matches
- risk_scorer.score_risk / list_assessments / _calculate_tier_score / _determine_risk_level
- recommendation_engine.generate_recommendations / list_recommendations
- coordinate.chain_flip_allele / chain_flip_genotype / is_genotype_match / convert_position

设计原则：
- 每个测试自包含（在内存 SQLite 中构造数据）
- 外部 API（GWAS Catalog/ClinVar/OMIM）用 monkeypatch mock
- 不依赖 conftest.py 的 client 夹具（仅用 async_db_session）
"""
import os
import sys
import uuid as uuid_mod
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 确保测试环境
os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    personal_genome, snp_locus, trait, prompt_template, user_llm_config,
)
from app.core.security import hash_password, UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.personal_genome import (  # noqa: E402
    PersonalGenome, GenotypeMatch, RiskAssessment, LifestyleRecommendation,
    GenomeBuild, SourceFormat, RiskLevel,
)
from app.models.snp_locus import (  # noqa: E402
    SnpLocus, LocusTier, EvidenceSource, EvidenceLevel, Population,
)
from app.models.trait import Trait, TraitCategory  # noqa: E402

from app.services.genome import (  # noqa: E402
    trait_search, genotype_matcher, risk_scorer, recommendation_engine,
)
from app.services.genome import coordinate  # noqa: E402


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture
async def db_session():
    """SQLite 内存数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """测试用户"""
    user = User(
        id=uuid_mod.uuid4(),
        email="genome-test@ai-drug.com",
        name="Genome Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_trait(db_session: AsyncSession):
    """测试性状 — 过敏易感"""
    trait = Trait(
        name="过敏易感",
        category=TraitCategory.ALLERGY,
        description="过敏易感性状测试",
    )
    db_session.add(trait)
    await db_session.flush()
    return trait


@pytest_asyncio.fixture
async def test_loci(db_session: AsyncSession, test_trait):
    """测试 SNP 位点 — 2 core + 2 auxiliary"""
    loci_data = [
        # (rsid, chromosome, pos37, gene, effect_allele, risk_genotype, effect_size, weight, tier)
        ("rs1234", "1", 100000, "IL13", "A", "AA", 1.5, 0.8, LocusTier.CORE),
        ("rs5678", "5", 200000, "IL4", "T", "TT", 1.3, 0.7, LocusTier.CORE),
        ("rs9012", "11", 300000, "STAT6", "G", "GG", 1.1, 0.5, LocusTier.AUXILIARY),
        ("rs3456", "3", 400000, "IL33", "C", "CC", 1.2, 0.4, LocusTier.AUXILIARY),
    ]
    loci = []
    for rsid, chrom, pos, gene, ea, rg, es, w, tier in loci_data:
        locus = SnpLocus(
            rsid=rsid,
            chromosome=chrom,
            position_grch37=pos,
            position_grch38=pos + 1000,
            gene_symbol=gene,
            trait_id=test_trait.id,
            effect_allele=ea,
            risk_genotype=rg,
            effect_size=es,
            weight=w,
            locus_tier=tier,
            population=Population.EAST_ASIAN,
            evidence_source=EvidenceSource.GWAS_CATALOG,
            evidence_level=EvidenceLevel.LEVEL_III,
            pmid="12345678",
            is_approved=True,
        )
        db_session.add(locus)
        loci.append(locus)
    await db_session.flush()
    return loci


@pytest_asyncio.fixture
async def test_genome(db_session: AsyncSession, test_user):
    """测试个人基因组文件（含基因型样本）"""
    genome = PersonalGenome(
        owner_id=test_user.id,
        file_name="test_genome.txt",
        storage_path="/tmp/test_genome.txt",
        genome_build=GenomeBuild.GRCH37,
        source_format=SourceFormat.TWENTY_THREE_AND_ME,
        total_variants=4,
        parsed_summary={
            "genotype_sample": {
                "rs1234": "AA",  # 命中风险
                "rs5678": "TT",  # 命中风险
                "rs9012": "GG",  # 命中风险
                "rs3456": "CC",  # 命中风险
            }
        },
        quality_metrics={"parseable": True, "missing_rate": 0.0},
    )
    db_session.add(genome)
    await db_session.flush()
    return genome


# ============================================================
# coordinate.py 测试
# ============================================================

class TestCoordinate:
    """坐标转换 + 链翻转 + 基因型匹配"""

    def test_chain_flip_allele_basic(self):
        """链翻转 — 单碱基互补"""
        assert coordinate.chain_flip_allele("A") == "T"
        assert coordinate.chain_flip_allele("T") == "A"
        assert coordinate.chain_flip_allele("C") == "G"
        assert coordinate.chain_flip_allele("G") == "C"

    def test_chain_flip_allele_multi(self):
        """链翻转 — 多碱基"""
        assert coordinate.chain_flip_allele("AA") == "TT"
        assert coordinate.chain_flip_allele("AG") == "TC"
        assert coordinate.chain_flip_allele("GG") == "CC"

    def test_chain_flip_allele_empty(self):
        """链翻转 — 空值处理"""
        assert coordinate.chain_flip_allele("") == ""
        assert coordinate.chain_flip_allele(None) is None

    def test_chain_flip_genotype_basic(self):
        """基因型链翻转"""
        assert coordinate.chain_flip_genotype("AA") == "TT"
        assert coordinate.chain_flip_genotype("AG") == "TC"

    def test_chain_flip_genotype_no_data(self):
        """基因型链翻转 — 无数据保持原样"""
        assert coordinate.chain_flip_genotype("--") == "--"
        assert coordinate.chain_flip_genotype("") == ""
        assert coordinate.chain_flip_genotype("00") == "00"

    def test_is_genotype_match_direct(self):
        """直接相等匹配"""
        assert coordinate.is_genotype_match("AA", "AA") is True
        assert coordinate.is_genotype_match("AG", "AG") is True

    def test_is_genotype_match_chain_flip(self):
        """链翻转匹配（user=TT, risk=AA）"""
        assert coordinate.is_genotype_match("TT", "AA") is True
        assert coordinate.is_genotype_match("CC", "GG") is True

    def test_is_genotype_match_phase_insensitive(self):
        """不区分相位（AG == GA）"""
        assert coordinate.is_genotype_match("AG", "GA") is True
        assert coordinate.is_genotype_match("GA", "AG") is True

    def test_is_genotype_match_single_allele(self):
        """风险是单等位（A），用户基因型含此等位即命中"""
        assert coordinate.is_genotype_match("AA", "A") is True
        assert coordinate.is_genotype_match("AG", "A") is True
        assert coordinate.is_genotype_match("GG", "A") is False

    def test_is_genotype_match_or_mode(self):
        """OR 模式（risk=AA|AG，命中任一）"""
        assert coordinate.is_genotype_match("AA", "AA|AG") is True
        assert coordinate.is_genotype_match("AG", "AA|AG") is True
        assert coordinate.is_genotype_match("GG", "AA|AG") is False

    def test_is_genotype_match_no_data(self):
        """无数据不匹配"""
        assert coordinate.is_genotype_match("--", "AA") is False
        assert coordinate.is_genotype_match("", "AA") is False
        assert coordinate.is_genotype_match("AA", "") is False
        assert coordinate.is_genotype_match("AA", None) is False

    @pytest.mark.asyncio
    async def test_convert_position_same_build(self, db_session, test_loci):
        """同版本坐标转换 — 直接查表"""
        pos = await coordinate.convert_position(
            db_session, "rs1234", "GRCh37", "GRCh37"
        )
        assert pos == 100000

    @pytest.mark.asyncio
    async def test_convert_position_cross_build(self, db_session, test_loci):
        """跨版本坐标转换（37→38）"""
        pos = await coordinate.convert_position(
            db_session, "rs1234", "GRCh37", "GRCh38"
        )
        assert pos == 101000  # 100000 + 1000

    @pytest.mark.asyncio
    async def test_convert_position_not_found(self, db_session):
        """rsid 不存在返回 None"""
        pos = await coordinate.convert_position(
            db_session, "rs_not_exist", "GRCh37", "GRCh38"
        )
        assert pos is None

    @pytest.mark.asyncio
    async def test_liftover_with_fallback_local(self, db_session, test_loci):
        """liftover_with_fallback 本地命中"""
        pos, source = await coordinate.liftover_with_fallback(
            db_session, "rs1234", "GRCh37", "GRCh37"
        )
        assert pos == 100000
        assert source == "local"


# ============================================================
# trait_search 测试
# ============================================================

class TestTraitSearch:
    """性状检索服务"""

    @pytest.mark.asyncio
    async def test_list_traits_empty(self, db_session):
        """空列表"""
        result = await trait_search.list_traits(db_session)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_list_traits_with_data(self, db_session, test_trait):
        """有数据列表"""
        result = await trait_search.list_traits(db_session)
        assert result["total"] == 1
        assert result["items"][0]["name"] == "过敏易感"
        assert result["items"][0]["category"] == TraitCategory.ALLERGY

    @pytest.mark.asyncio
    async def test_list_traits_pagination(self, db_session):
        """分页"""
        # 创建 25 个性状
        for i in range(25):
            db_session.add(Trait(
                name=f"性状{i}",
                category=TraitCategory.METABOLISM,
            ))
        await db_session.flush()
        result = await trait_search.list_traits(db_session, page=2, page_size=10)
        assert result["page"] == 2
        assert result["page_size"] == 10
        assert len(result["items"]) == 10
        assert result["total"] == 25

    @pytest.mark.asyncio
    async def test_list_traits_category_filter(self, db_session, test_trait):
        """分类过滤"""
        # 添加另一个分类的性状
        db_session.add(Trait(name="代谢", category=TraitCategory.METABOLISM))
        await db_session.flush()
        result = await trait_search.list_traits(db_session, category=TraitCategory.ALLERGY)
        assert result["total"] == 1
        assert result["items"][0]["category"] == TraitCategory.ALLERGY

    @pytest.mark.asyncio
    async def test_get_trait_loci(self, db_session, test_trait, test_loci):
        """获取性状关联位点"""
        loci = await trait_search.get_trait_loci(db_session, test_trait.id)
        assert len(loci) == 4
        # 按 tier + rsid 排序
        assert loci[0]["rsid"] == "rs1234"  # CORE 在前

    @pytest.mark.asyncio
    async def test_get_trait_loci_approved_only(self, db_session, test_trait, test_loci):
        """仅获取已审核位点"""
        # 添加未审核位点
        db_session.add(SnpLocus(
            rsid="rs_unapproved",
            chromosome="1",
            position_grch37=999,
            trait_id=test_trait.id,
            weight=0.5,
            locus_tier=LocusTier.AUXILIARY,
            population=Population.UNKNOWN,
            evidence_source=EvidenceSource.LLM,
            evidence_level=EvidenceLevel.LEVEL_IV,
            is_approved=False,
        ))
        await db_session.flush()
        loci = await trait_search.get_trait_loci(db_session, test_trait.id, approved_only=True)
        assert len(loci) == 4  # 仅 4 个 approved
        loci_all = await trait_search.get_trait_loci(db_session, test_trait.id, approved_only=False)
        assert len(loci_all) == 5

    @pytest.mark.asyncio
    async def test_search_loci_local_only(
        self, db_session, test_trait, test_loci, test_user, monkeypatch
    ):
        """AI 检索位点 — 仅本地（不调外部）"""
        result = await trait_search.search_loci(
            db_session, test_trait.id, test_user, use_external=False
        )
        assert result["trait"]["name"] == "过敏易感"
        assert result["total_loci"] == 4
        assert result["new_loci_added"] == 0
        assert result["external_sources_queried"] == []

    @pytest.mark.asyncio
    async def test_search_loci_trait_not_found(self, db_session, test_user):
        """性状不存在抛 ValueError"""
        with pytest.raises(ValueError, match="性状不存在"):
            await trait_search.search_loci(
                db_session, uuid_mod.uuid4(), test_user, use_external=False
            )


# ============================================================
# genotype_matcher 测试
# ============================================================

class TestGenotypeMatcher:
    """基因型匹配服务"""

    @pytest.mark.asyncio
    async def test_match_genotype_all_risk(self, db_session, test_genome, test_loci):
        """全部命中风险基因型"""
        matches = await genotype_matcher.match_genotype(
            db_session, test_genome.id, test_loci
        )
        assert len(matches) == 4
        assert all(m.is_risk for m in matches)
        # 风险评分应等于 effect_size
        risk_scores = [m.risk_score for m in matches]
        assert risk_scores == [1.5, 1.3, 1.1, 1.2]

    @pytest.mark.asyncio
    async def test_match_genotype_no_coverage(self, db_session, test_user, test_loci, test_trait):
        """用户基因型未覆盖所有 rsid"""
        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="partial.txt",
            storage_path="/tmp/partial.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=2,
            parsed_summary={
                "genotype_sample": {
                    "rs1234": "AA",  # 命中
                    "rs5678": "--",  # 未检测
                }
            },
            quality_metrics={},
        )
        db_session.add(genome)
        await db_session.flush()
        matches = await genotype_matcher.match_genotype(
            db_session, genome.id, test_loci
        )
        assert len(matches) == 4
        risk_matches = [m for m in matches if m.is_risk]
        assert len(risk_matches) == 1  # 只有 rs1234 命中
        not_tested = [m for m in matches if m.note == "未检测"]
        assert len(not_tested) == 3  # rs5678/rs9012/rs3456 未检测

    @pytest.mark.asyncio
    async def test_match_genotype_chain_flip(self, db_session, test_user, test_loci):
        """链翻转匹配（用户=TT，风险=AA）"""
        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="flip.txt",
            storage_path="/tmp/flip.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=4,
            parsed_summary={
                "genotype_sample": {
                    "rs1234": "TT",  # AA 的互补
                    "rs5678": "TT",
                    "rs9012": "CC",  # GG 的互补
                    "rs3456": "GG",  # CC 的互补
                }
            },
            quality_metrics={},
        )
        db_session.add(genome)
        await db_session.flush()
        matches = await genotype_matcher.match_genotype(
            db_session, genome.id, test_loci
        )
        # 链翻转后应全部命中
        assert all(m.is_risk for m in matches)

    @pytest.mark.asyncio
    async def test_match_genotype_replace_existing(self, db_session, test_genome, test_loci):
        """覆盖已有匹配记录"""
        # 第一次匹配
        matches1 = await genotype_matcher.match_genotype(
            db_session, test_genome.id, test_loci
        )
        assert len(matches1) == 4
        # 第二次匹配（replace_existing=True，应覆盖）
        matches2 = await genotype_matcher.match_genotype(
            db_session, test_genome.id, test_loci, replace_existing=True
        )
        assert len(matches2) == 4
        # 验证不会重复（list_matches 应只返回 4 条）
        listed = await genotype_matcher.list_matches(db_session, test_genome.id)
        assert len(listed) == 4

    @pytest.mark.asyncio
    async def test_match_genome_not_found(self, db_session, test_loci):
        """基因组不存在抛 ValueError"""
        with pytest.raises(ValueError, match="PersonalGenome 不存在"):
            await genotype_matcher.match_genotype(
                db_session, uuid_mod.uuid4(), test_loci
            )

    @pytest.mark.asyncio
    async def test_list_matches_risk_only(self, db_session, test_genome, test_loci):
        """仅查风险匹配"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        risk_only = await genotype_matcher.list_matches(
            db_session, test_genome.id, risk_only=True
        )
        assert len(risk_only) == 4  # 全部命中


# ============================================================
# risk_scorer 测试
# ============================================================

class TestRiskScorer:
    """风险评分服务"""

    @pytest.mark.asyncio
    async def test_score_risk_all_high(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """全部命中高风险位点 → 评分较高"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        assert assessment.overall_risk_score > 0
        assert assessment.risk_level in ("low", "moderate", "high", "very_high")
        assert assessment.core_loci_matched == 2
        assert assessment.auxiliary_loci_matched == 2

    @pytest.mark.asyncio
    async def test_score_risk_no_matches(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """无匹配记录 → 评分为 0，等级 LOW"""
        # 不调 match_genotype，直接评分（matches 为空）
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        assert assessment.overall_risk_score == 0.0
        assert assessment.risk_level == "low"
        assert assessment.core_loci_matched == 0
        assert assessment.auxiliary_loci_matched == 0

    def test_determine_risk_level_thresholds(self):
        """风险等级阈值边界"""
        assert risk_scorer._determine_risk_level(0.0) == "low"
        assert risk_scorer._determine_risk_level(0.29) == "low"
        assert risk_scorer._determine_risk_level(0.30) == "moderate"
        assert risk_scorer._determine_risk_level(0.59) == "moderate"
        assert risk_scorer._determine_risk_level(0.60) == "high"
        assert risk_scorer._determine_risk_level(0.84) == "high"
        assert risk_scorer._determine_risk_level(0.85) == "very_high"
        assert risk_scorer._determine_risk_level(1.0) == "very_high"

    def test_calculate_tier_score_empty(self):
        """空列表评分为 0"""
        assert risk_scorer._calculate_tier_score([], 0.7) == 0.0

    @pytest.mark.asyncio
    async def test_list_assessments_empty(self, db_session, test_genome):
        """空评估列表"""
        items = await risk_scorer.list_assessments(db_session, test_genome.id)
        assert items == []

    @pytest.mark.asyncio
    async def test_list_assessments_with_data(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """有评估数据"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        await risk_scorer.score_risk(db_session, test_genome.id, test_trait.id)
        items = await risk_scorer.list_assessments(db_session, test_genome.id)
        assert len(items) == 1
        assert items[0]["trait_name"] == "过敏易感"
        assert items[0]["trait_category"] == TraitCategory.ALLERGY

    @pytest.mark.asyncio
    async def test_get_assessment_not_found(self, db_session):
        """不存在的评估返回 None"""
        result = await risk_scorer.get_assessment(db_session, uuid_mod.uuid4())
        assert result is None


# ============================================================
# recommendation_engine 测试
# ============================================================

class TestRecommendationEngine:
    """生活建议生成服务"""

    @pytest.mark.asyncio
    async def test_generate_recommendations_allergy(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """过敏类性状生成建议"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        recs = await recommendation_engine.generate_recommendations(
            db_session, assessment.id
        )
        # 过敏类至少 3 条建议
        assert len(recs) >= 3
        categories = {r.category for r in recs}
        assert "lifestyle" in categories or "diet" in categories

    @pytest.mark.asyncio
    async def test_generate_recommendations_priority_mapping(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """优先级按风险等级映射"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        recs = await recommendation_engine.generate_recommendations(
            db_session, assessment.id
        )
        expected_priority = recommendation_engine.RISK_TO_PRIORITY.get(
            assessment.risk_level, "medium"
        )
        assert all(r.priority == expected_priority for r in recs)

    @pytest.mark.asyncio
    async def test_generate_recommendations_unknown_category(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """未知性状类别使用通用模板"""
        # 改 trait category 为不存在的值
        test_trait.category = "unknown_category"
        await db_session.flush()
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        recs = await recommendation_engine.generate_recommendations(
            db_session, assessment.id
        )
        assert len(recs) == 1  # 通用模板
        assert "保持健康生活方式" in recs[0].content

    @pytest.mark.asyncio
    async def test_generate_recommendations_assessment_not_found(self, db_session):
        """评估不存在抛 ValueError"""
        with pytest.raises(ValueError, match="RiskAssessment 不存在"):
            await recommendation_engine.generate_recommendations(
                db_session, uuid_mod.uuid4()
            )

    @pytest.mark.asyncio
    async def test_list_recommendations(
        self, db_session, test_genome, test_trait, test_loci
    ):
        """查询建议列表"""
        await genotype_matcher.match_genotype(db_session, test_genome.id, test_loci)
        assessment = await risk_scorer.score_risk(
            db_session, test_genome.id, test_trait.id
        )
        await recommendation_engine.generate_recommendations(db_session, assessment.id)
        recs = await recommendation_engine.list_recommendations(db_session, assessment.id)
        assert len(recs) >= 3
        assert all("content" in r for r in recs)
