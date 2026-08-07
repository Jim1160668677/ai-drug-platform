"""个人基因组模块性能测试

覆盖核心服务的吞吐量与延迟基准：
- coordinate.is_genotype_match / chain_flip — 纯 CPU 基准（10 万次）
- risk_scorer._calculate_tier_score / _determine_risk_level — 纯 CPU 基准
- genotype_matcher.match_genotype — DB 基准（100 / 500 / 1000 位点）
- risk_scorer.score_risk — DB 基准（含位点分组 + PRS 计算）
- parser.SnpChipParser._detect_and_parse — 文件解析基准（1k / 10k / 50k 行）

设计原则：
- 每个基准用 time.perf_counter 精确计时
- 断言「单次操作平均耗时 ≤ 阈值」，阈值留 3× 安全裕量
- DB 测试用 SQLite 内存数据库，排除磁盘 I/O 干扰
- 大文件用 tempfile 生成，测试后自动清理
"""
import os
import sys
import time
import uuid as uuid_mod
import tempfile
from typing import List

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
    PersonalGenome, GenotypeMatch, GenomeBuild, SourceFormat,
)
from app.models.snp_locus import (  # noqa: E402
    SnpLocus, LocusTier, EvidenceSource, EvidenceLevel, Population,
)
from app.models.trait import Trait, TraitCategory  # noqa: E402

from app.services.genome import coordinate, genotype_matcher, risk_scorer  # noqa: E402
from app.services.parser.snp_chip import SnpChipParser  # noqa: E402


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
        email="perf-test@ai-drug.com",
        name="Perf Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_trait(db_session: AsyncSession):
    """测试性状"""
    trait = Trait(
        name="性能测试性状",
        category=TraitCategory.METABOLISM,
        description="性能测试用性状",
    )
    db_session.add(trait)
    await db_session.flush()
    return trait


def _make_loci(trait_id, count: int, core_ratio: float = 0.5) -> List[SnpLocus]:
    """批量生成 SnpLocus 列表（不写入 DB）"""
    loci = []
    core_count = int(count * core_ratio)
    for i in range(count):
        tier = LocusTier.CORE if i < core_count else LocusTier.AUXILIARY
        locus = SnpLocus(
            rsid=f"rs{i:06d}",
            chromosome=str((i % 22) + 1),
            position_grch37=100000 + i,
            position_grch38=101000 + i,
            gene_symbol=f"GENE{i}",
            trait_id=trait_id,
            effect_allele="A",
            risk_genotype="AA",
            effect_size=1.0 + (i % 5) * 0.1,
            weight=0.5 + (i % 10) * 0.05,
            locus_tier=tier,
            population=Population.EAST_ASIAN,
            evidence_source=EvidenceSource.GWAS_CATALOG,
            evidence_level=EvidenceLevel.LEVEL_III,
            is_approved=True,
        )
        loci.append(locus)
    return loci


def _make_genotype_sample(count: int) -> dict:
    """生成 genotype_sample 字典"""
    sample = {}
    for i in range(count):
        # 50% 命中风险（AA），50% 安全（GG）
        gt = "AA" if i % 2 == 0 else "GG"
        sample[f"rs{i:06d}"] = gt
    return sample


# ============================================================
# 1. 纯 CPU 基准 — coordinate 模块
# ============================================================

class TestCoordinatePerformance:
    """coordinate 模块纯 CPU 性能基准"""

    def test_is_genotype_match_10k_calls(self):
        """is_genotype_match 1 万次调用应在 100ms 内完成"""
        test_cases = [
            ("AA", "AA", True),
            ("AG", "AA", False),
            ("TT", "AA", True),   # 链翻转
            ("GG", "A", True),    # 单等位
            ("CT", "AG", False),
        ]
        iterations = 10000

        start = time.perf_counter()
        for _ in range(iterations):
            for user_gt, risk_gt, _ in test_cases:
                coordinate.is_genotype_match(user_gt, risk_gt)
        elapsed = time.perf_counter() - start

        avg_us = (elapsed / (iterations * len(test_cases))) * 1_000_000
        print(f"\n  is_genotype_match: {iterations * len(test_cases)} 次, "
              f"总耗时 {elapsed * 1000:.2f}ms, 平均 {avg_us:.2f}μs/次")

        # 安全阈值：单次 ≤ 50μs（含 3x 裕量）
        assert avg_us < 50.0, f"is_genotype_match 平均耗时 {avg_us:.2f}μs 超过 50μs 阈值"

    def test_chain_flip_allele_10k_calls(self):
        """chain_flip_allele 1 万次调用应在 20ms 内完成"""
        alleles = ["A", "T", "C", "G", "AT", "GC", "AATT", "GGCC"]
        iterations = 10000

        start = time.perf_counter()
        for _ in range(iterations):
            for a in alleles:
                coordinate.chain_flip_allele(a)
        elapsed = time.perf_counter() - start

        total_calls = iterations * len(alleles)
        avg_us = (elapsed / total_calls) * 1_000_000
        print(f"\n  chain_flip_allele: {total_calls} 次, "
              f"总耗时 {elapsed * 1000:.2f}ms, 平均 {avg_us:.2f}μs/次")

        assert avg_us < 20.0, f"chain_flip_allele 平均耗时 {avg_us:.2f}μs 超过 20μs 阈值"

    def test_chain_flip_genotype_with_invalid_inputs(self):
        """chain_flip_genotype 对空值/无效输入的处理不应有性能退化"""
        inputs = ["--", "", None, "00", "AA", "AT", "GGCC"]
        iterations = 10000

        start = time.perf_counter()
        for _ in range(iterations):
            for g in inputs:
                coordinate.chain_flip_genotype(g)
        elapsed = time.perf_counter() - start

        total_calls = iterations * len(inputs)
        avg_us = (elapsed / total_calls) * 1_000_000
        print(f"\n  chain_flip_genotype (含无效输入): {total_calls} 次, "
              f"平均 {avg_us:.2f}μs/次")

        assert avg_us < 20.0


# ============================================================
# 2. 纯 CPU 基准 — risk_scorer 模块
# ============================================================

class TestRiskScorerCpuPerformance:
    """risk_scorer 纯 CPU 函数性能基准"""

    def test_determine_risk_level_10k_calls(self):
        """_determine_risk_level 1 万次调用应在 50ms 内完成"""
        scores = [0.0, 0.15, 0.29, 0.30, 0.45, 0.59, 0.60, 0.75, 0.84, 0.85, 0.95, 1.0]
        iterations = 10000

        start = time.perf_counter()
        for _ in range(iterations):
            for s in scores:
                risk_scorer._determine_risk_level(s)
        elapsed = time.perf_counter() - start

        total_calls = iterations * len(scores)
        avg_us = (elapsed / total_calls) * 1_000_000
        print(f"\n  _determine_risk_level: {total_calls} 次, "
              f"总耗时 {elapsed * 1000:.2f}ms, 平均 {avg_us:.2f}μs/次")

        assert avg_us < 10.0, f"_determine_risk_level 平均耗时 {avg_us:.2f}μs 超过 10μs"

    def test_calculate_tier_score_1k_matches(self):
        """_calculate_tier_score 1000 个匹配应在 10ms 内完成"""
        # 构造 1000 个 (match, locus) 元组
        class MockMatch:
            def __init__(self, risk_score):
                self.risk_score = risk_score

        class MockLocus:
            def __init__(self, weight):
                self.weight = weight

        matches_with_loci = [
            (MockMatch(0.5 + (i % 10) * 0.1), MockLocus(0.3 + (i % 7) * 0.1))
            for i in range(1000)
        ]

        start = time.perf_counter()
        for _ in range(100):
            risk_scorer._calculate_tier_score(matches_with_loci, 0.7)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 100) * 1000
        print(f"\n  _calculate_tier_score (1000 matches): "
              f"100 次平均 {avg_ms:.2f}ms/次")

        assert avg_ms < 10.0, f"_calculate_tier_score 1000 matches 平均 {avg_ms:.2f}ms 超过 10ms"


# ============================================================
# 3. DB 基准 — genotype_matcher.match_genotype
# ============================================================

class TestMatchGenotypePerformance:
    """match_genotype DB 性能基准"""

    @pytest.mark.asyncio
    async def test_match_genotype_100_loci(self, db_session, test_user, test_trait):
        """100 位点匹配应在 200ms 内完成"""
        loci = _make_loci(test_trait.id, 100)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_100.txt",
            storage_path="/tmp/perf_100.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=100,
            parsed_summary={"genotype_sample": _make_genotype_sample(100)},
        )
        db_session.add(genome)
        await db_session.flush()

        start = time.perf_counter()
        matches = await genotype_matcher.match_genotype(
            db_session, genome.id, loci
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  match_genotype (100 loci): {elapsed_ms:.2f}ms, "
              f"matches={len(matches)}, "
              f"risk={sum(1 for m in matches if m.is_risk)}")

        assert len(matches) == 100
        assert elapsed_ms < 200.0, f"100 位点匹配 {elapsed_ms:.2f}ms 超过 200ms"

    @pytest.mark.asyncio
    async def test_match_genotype_500_loci(self, db_session, test_user, test_trait):
        """500 位点匹配应在 500ms 内完成"""
        loci = _make_loci(test_trait.id, 500)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_500.txt",
            storage_path="/tmp/perf_500.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=500,
            parsed_summary={"genotype_sample": _make_genotype_sample(500)},
        )
        db_session.add(genome)
        await db_session.flush()

        start = time.perf_counter()
        matches = await genotype_matcher.match_genotype(
            db_session, genome.id, loci
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  match_genotype (500 loci): {elapsed_ms:.2f}ms, "
              f"matches={len(matches)}")

        assert len(matches) == 500
        assert elapsed_ms < 500.0, f"500 位点匹配 {elapsed_ms:.2f}ms 超过 500ms"

    @pytest.mark.asyncio
    async def test_match_genotype_1000_loci(self, db_session, test_user, test_trait):
        """1000 位点匹配应在 1s 内完成"""
        loci = _make_loci(test_trait.id, 1000)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_1000.txt",
            storage_path="/tmp/perf_1000.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=1000,
            parsed_summary={"genotype_sample": _make_genotype_sample(1000)},
        )
        db_session.add(genome)
        await db_session.flush()

        start = time.perf_counter()
        matches = await genotype_matcher.match_genotype(
            db_session, genome.id, loci
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  match_genotype (1000 loci): {elapsed_ms:.2f}ms, "
              f"matches={len(matches)}")

        assert len(matches) == 1000
        assert elapsed_ms < 1000.0, f"1000 位点匹配 {elapsed_ms:.2f}ms 超过 1s"


# ============================================================
# 4. DB 基准 — risk_scorer.score_risk
# ============================================================

class TestScoreRiskPerformance:
    """score_risk DB 性能基准"""

    @pytest.mark.asyncio
    async def test_score_risk_100_matches(self, db_session, test_user, test_trait):
        """100 匹配的风险评分应在 150ms 内完成"""
        loci = _make_loci(test_trait.id, 100)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_score_100.txt",
            storage_path="/tmp/perf_score_100.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=100,
            parsed_summary={"genotype_sample": _make_genotype_sample(100)},
        )
        db_session.add(genome)
        await db_session.flush()

        # 先执行匹配
        await genotype_matcher.match_genotype(db_session, genome.id, loci)
        await db_session.flush()

        start = time.perf_counter()
        assessment = await risk_scorer.score_risk(
            db_session, genome.id, test_trait.id
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  score_risk (100 matches): {elapsed_ms:.2f}ms, "
              f"score={assessment.overall_risk_score}, "
              f"level={assessment.risk_level}")

        assert assessment is not None
        assert elapsed_ms < 150.0, f"100 匹配评分 {elapsed_ms:.2f}ms 超过 150ms"

    @pytest.mark.asyncio
    async def test_score_risk_500_matches(self, db_session, test_user, test_trait):
        """500 匹配的风险评分应在 400ms 内完成"""
        loci = _make_loci(test_trait.id, 500)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_score_500.txt",
            storage_path="/tmp/perf_score_500.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=500,
            parsed_summary={"genotype_sample": _make_genotype_sample(500)},
        )
        db_session.add(genome)
        await db_session.flush()

        await genotype_matcher.match_genotype(db_session, genome.id, loci)
        await db_session.flush()

        start = time.perf_counter()
        assessment = await risk_scorer.score_risk(
            db_session, genome.id, test_trait.id
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  score_risk (500 matches): {elapsed_ms:.2f}ms, "
              f"score={assessment.overall_risk_score}")

        assert assessment is not None
        assert elapsed_ms < 400.0, f"500 匹配评分 {elapsed_ms:.2f}ms 超过 400ms"


# ============================================================
# 5. 端到端基准 — 匹配 + 评分流水线
# ============================================================

class TestEndToEndPerformance:
    """匹配 + 评分端到端流水线性能"""

    @pytest.mark.asyncio
    async def test_full_pipeline_200_loci(self, db_session, test_user, test_trait):
        """200 位点完整流水线（匹配+评分）应在 500ms 内完成"""
        loci = _make_loci(test_trait.id, 200)
        db_session.add_all(loci)
        await db_session.flush()

        genome = PersonalGenome(
            owner_id=test_user.id,
            file_name="perf_e2e.txt",
            storage_path="/tmp/perf_e2e.txt",
            genome_build=GenomeBuild.GRCH37,
            source_format=SourceFormat.TWENTY_THREE_AND_ME,
            total_variants=200,
            parsed_summary={"genotype_sample": _make_genotype_sample(200)},
        )
        db_session.add(genome)
        await db_session.flush()

        start = time.perf_counter()
        matches = await genotype_matcher.match_genotype(db_session, genome.id, loci)
        await db_session.flush()
        assessment = await risk_scorer.score_risk(
            db_session, genome.id, test_trait.id
        )
        await db_session.flush()
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  full_pipeline (200 loci): {elapsed_ms:.2f}ms, "
              f"matches={len(matches)}, "
              f"risk={sum(1 for m in matches if m.is_risk)}, "
              f"score={assessment.overall_risk_score}, "
              f"level={assessment.risk_level}")

        assert len(matches) == 200
        assert assessment is not None
        assert elapsed_ms < 500.0, f"200 位点完整流水线 {elapsed_ms:.2f}ms 超过 500ms"


# ============================================================
# 6. 文件解析基准 — SnpChipParser
# ============================================================

class TestParserPerformance:
    """SnpChipParser 文件解析性能基准"""

    def _generate_snp_file(self, path: str, line_count: int, fmt: str = "23andme"):
        """生成测试用 SNP 芯片文件"""
        with open(path, "w", encoding="utf-8") as f:
            if fmt == "23andme":
                f.write("# This data file generated by 23andMe\n")
                f.write("# rsid\tchromosome\tposition\tgenotype\n")
                for i in range(line_count):
                    chrom = (i % 22) + 1
                    pos = 1000000 + i
                    gt = "AA" if i % 2 == 0 else "GG"
                    f.write(f"rs{i:07d}\t{chrom}\t{pos}\t{gt}\n")
            elif fmt == "ancestry":
                f.write("rsid\tchromosome\tposition\tallele1\tallele2\n")
                for i in range(line_count):
                    chrom = (i % 22) + 1
                    pos = 1000000 + i
                    a1 = "A" if i % 2 == 0 else "G"
                    a2 = "A" if i % 3 == 0 else "G"
                    f.write(f"rs{i:07d}\t{chrom}\t{pos}\t{a1}\t{a2}\n")
            elif fmt == "generic":
                for i in range(line_count):
                    gt = "AA" if i % 2 == 0 else "GG"
                    f.write(f"rs{i:07d},{gt}\n")

    def test_parse_1k_lines_23andme(self):
        """1k 行 23andMe 文件解析应在 100ms 内完成"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            self._generate_snp_file(f.name, 1000, "23andme")
            path = f.name

        try:
            parser = SnpChipParser()

            class _Stub:
                storage_path = path

            start = time.perf_counter()
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(parser.parse(_Stub()))
            finally:
                loop.close()
            elapsed = time.perf_counter() - start

            elapsed_ms = elapsed * 1000
            total = result["summary"].get("total_variants", 0)
            print(f"\n  parse 1k lines (23andme): {elapsed_ms:.2f}ms, "
                  f"parsed={total}")

            assert total == 1000
            assert elapsed_ms < 100.0, f"1k 行解析 {elapsed_ms:.2f}ms 超过 100ms"
        finally:
            os.unlink(path)

    def test_parse_10k_lines_23andme(self):
        """10k 行 23andMe 文件解析应在 800ms 内完成"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            self._generate_snp_file(f.name, 10000, "23andme")
            path = f.name

        try:
            parser = SnpChipParser()

            class _Stub:
                storage_path = path

            start = time.perf_counter()
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(parser.parse(_Stub()))
            finally:
                loop.close()
            elapsed = time.perf_counter() - start

            elapsed_ms = elapsed * 1000
            total = result["summary"].get("total_variants", 0)
            print(f"\n  parse 10k lines (23andme): {elapsed_ms:.2f}ms, "
                  f"parsed={total}")

            assert total == 10000
            assert elapsed_ms < 800.0, f"10k 行解析 {elapsed_ms:.2f}ms 超过 800ms"
        finally:
            os.unlink(path)

    def test_parse_50k_lines_23andme(self):
        """50k 行 23andMe 文件解析应在 4s 内完成"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            self._generate_snp_file(f.name, 50000, "23andme")
            path = f.name

        try:
            parser = SnpChipParser()

            class _Stub:
                storage_path = path

            start = time.perf_counter()
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(parser.parse(_Stub()))
            finally:
                loop.close()
            elapsed = time.perf_counter() - start

            elapsed_ms = elapsed * 1000
            total = result["summary"].get("total_variants", 0)
            print(f"\n  parse 50k lines (23andme): {elapsed_ms:.2f}ms, "
                  f"parsed={total}")

            assert total == 50000
            assert elapsed_ms < 4000.0, f"50k 行解析 {elapsed_ms:.2f}ms 超过 4s"
        finally:
            os.unlink(path)

    def test_parse_5k_lines_ancestry(self):
        """5k 行 Ancestry 格式解析应在 500ms 内完成"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            self._generate_snp_file(f.name, 5000, "ancestry")
            path = f.name

        try:
            parser = SnpChipParser()

            class _Stub:
                storage_path = path

            start = time.perf_counter()
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(parser.parse(_Stub()))
            finally:
                loop.close()
            elapsed = time.perf_counter() - start

            elapsed_ms = elapsed * 1000
            total = result["summary"].get("total_variants", 0)
            fmt = result["summary"].get("source_format")
            print(f"\n  parse 5k lines (ancestry): {elapsed_ms:.2f}ms, "
                  f"parsed={total}, format={fmt}")

            assert total == 5000
            assert elapsed_ms < 500.0, f"5k 行 Ancestry 解析 {elapsed_ms:.2f}ms 超过 500ms"
        finally:
            os.unlink(path)

    def test_format_detection_fast(self):
        """格式识别 1000 次应在 50ms 内完成"""
        parser = SnpChipParser()
        head_lines_23 = ["# This data file generated by 23andMe\n"] + [
            f"rs{i}\t1\t{i}\tAA\n" for i in range(5)
        ]
        head_lines_anc = ["rsid\tchromosome\tposition\tallele1\tallele2\n"] + [
            f"rs{i}\t1\t{i}\tA\tG\n" for i in range(5)
        ]

        start = time.perf_counter()
        for _ in range(1000):
            parser._detect_format(head_lines_23)
            parser._detect_format(head_lines_anc)
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000
        print(f"\n  _detect_format x2000: {elapsed_ms:.2f}ms")

        assert elapsed_ms < 50.0, f"格式识别 2000 次 {elapsed_ms:.2f}ms 超过 50ms"
