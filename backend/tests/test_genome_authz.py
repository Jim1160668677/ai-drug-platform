"""个人基因组模块越权测试 — 验证 owner 校验防止水平越权

测试维度：
1. 基因组文件级越权：User A 不能访问/删除/匹配/评分/导出 User B 的基因组
2. 列表隔离：User A 只能看到自己的基因组文件
3. 角色限制：非 FOUNDER 不能创建性状 / Prompt 模板
4. 风险评估详情越权：User A 不能查看 User B 的风险评估

技术要点：
- 复用 test_horizontal_authz.py 的 mock_get_current_user 模式
- JWT 携带不同 subject，mock 根据 subject 返回对应用户
- 端点应返回 403 Forbidden 或 404 Not Found（不泄露资源存在性）
"""
import os
import sys
import uuid as uuid_mod
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncGenerator, Dict

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.deps import get_current_user, oauth2_scheme  # noqa: E402
from app.core.security import (  # noqa: E402
    UserRole,
    create_access_token,
    decode_token,
    hash_password,
)
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    personal_genome, snp_locus, trait, prompt_template, user_llm_config, llm_config,
)
from app.models.user import User  # noqa: E402
from app.models.personal_genome import (  # noqa: E402
    PersonalGenome, GenotypeMatch, RiskAssessment, LifestyleRecommendation,
    GenomeBuild, SourceFormat,
)
from app.models.snp_locus import (  # noqa: E402
    SnpLocus, LocusTier, Population, EvidenceSource, EvidenceLevel,
)
from app.models.trait import Trait, TraitCategory  # noqa: E402

# 测试用户 ID（固定 UUID 满足 DB 外键约束）
FOUNDER_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000D1")
USER_A_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000D2")
USER_B_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000D3")


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite 内存数据库会话，预置 3 个测试用户"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        users = [
            User(
                id=FOUNDER_ID, email="founder@genome.test", name="Founder",
                hashed_password=hash_password("pass123"), role=UserRole.FOUNDER, is_active=True,
            ),
            User(
                id=USER_A_ID, email="user-a@genome.test", name="User A",
                hashed_password=hash_password("pass123"), role=UserRole.RESEARCHER, is_active=True,
            ),
            User(
                id=USER_B_ID, email="user-b@genome.test", name="User B",
                hashed_password=hash_password("pass123"), role=UserRole.RESEARCHER, is_active=True,
            ),
        ]
        for u in users:
            session.add(u)
        await session.flush()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    await engine.dispose()


def _make_token(user_id: uuid_mod.UUID, role: UserRole) -> str:
    return create_access_token(subject=str(user_id), role=role)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP 客户端 — mock_get_current_user 根据 token subject 返回对应用户"""
    from fastapi import Depends, HTTPException, status

    user_map: Dict[uuid_mod.UUID, dict] = {
        FOUNDER_ID: {"email": "founder@genome.test", "name": "Founder", "role": UserRole.FOUNDER},
        USER_A_ID: {"email": "user-a@genome.test", "name": "User A", "role": UserRole.RESEARCHER},
        USER_B_ID: {"email": "user-b@genome.test", "name": "User B", "role": UserRole.RESEARCHER},
    }

    async def override_get_db():
        yield db_session

    async def mock_get_current_user(token: str = Depends(oauth2_scheme)):
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            uid = uuid_mod.UUID(user_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_info = user_map.get(uid)
        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无法验证凭据",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return SimpleNamespace(
            id=uid,
            email=user_info["email"],
            name=user_info["name"],
            role=user_info["role"],
            is_active=True,
            organization=None,
            created_at=datetime.now(timezone.utc),
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def seed_genome_data(db_session: AsyncSession) -> dict:
    """预置测试数据：User A 和 User B 各有一份基因组 + 性状 + 位点 + 匹配 + 风险评估"""
    # 性状（FOUNDER 级全局数据，两用户共享）
    trait_obj = Trait(
        name="乳糖不耐受", category=TraitCategory.METABOLISM,
        description="乳糖酶基因多态性",
    )
    db_session.add(trait_obj)
    await db_session.flush()

    # 位点
    loci = []
    for rsid, chrom, pos, gene, ea, rg, es, w, tier in [
        ("rs1001", "2", 136608646, "MCM6", "G", "GG", 1.8, 0.8, LocusTier.CORE),
        ("rs1002", "2", 136620000, "LCT", "A", "AA", 1.3, 0.5, LocusTier.AUXILIARY),
    ]:
        locus = SnpLocus(
            rsid=rsid, chromosome=chrom, position_grch37=pos,
            position_grch38=pos + 1000, gene_symbol=gene, trait_id=trait_obj.id,
            effect_allele=ea, risk_genotype=rg, effect_size=es, weight=w,
            locus_tier=tier, population=Population.EAST_ASIAN,
            evidence_source=EvidenceSource.GWAS_CATALOG,
            evidence_level=EvidenceLevel.LEVEL_III,
            pmid="10000111", is_approved=True,
        )
        db_session.add(locus)
        loci.append(locus)
    await db_session.flush()

    # User A 的基因组
    genome_a = PersonalGenome(
        owner_id=USER_A_ID, file_name="user_a_genome.txt",
        storage_path="/tmp/user_a_genome.txt",
        genome_build=GenomeBuild.GRCH37,
        source_format=SourceFormat.TWENTY_THREE_AND_ME,
        total_variants=2,
        parsed_summary={"genotype_sample": {"rs1001": "GG", "rs1002": "AA"}},
        quality_metrics={"parseable": True, "missing_rate": 0.0},
    )
    db_session.add(genome_a)

    # User B 的基因组
    genome_b = PersonalGenome(
        owner_id=USER_B_ID, file_name="user_b_genome.txt",
        storage_path="/tmp/user_b_genome.txt",
        genome_build=GenomeBuild.GRCH37,
        source_format=SourceFormat.GENERIC,
        total_variants=2,
        parsed_summary={"genotype_sample": {"rs1001": "GG", "rs1002": "AA"}},
        quality_metrics={"parseable": True, "missing_rate": 0.0},
    )
    db_session.add(genome_b)
    await db_session.flush()

    # User B 的匹配记录
    match_b = GenotypeMatch(
        personal_genome_id=genome_b.id, snp_locus_id=loci[0].id,
        user_genotype="GG", is_risk=True, risk_score=1.8,
        note="命中风险基因型",
    )
    db_session.add(match_b)
    await db_session.flush()

    # User B 的风险评估
    assessment_b = RiskAssessment(
        personal_genome_id=genome_b.id, trait_id=trait_obj.id,
        overall_risk_score=0.75, risk_level="high",
        core_loci_matched=1, auxiliary_loci_matched=0,
        matched_loci_ids=[str(loci[0].id)],
    )
    db_session.add(assessment_b)
    await db_session.flush()

    return {
        "trait_id": str(trait_obj.id),
        "locus_ids": [str(l.id) for l in loci],
        "genome_a_id": str(genome_a.id),
        "genome_b_id": str(genome_b.id),
        "match_b_id": str(match_b.id),
        "assessment_b_id": str(assessment_b.id),
    }


# ============================================================
# 1. 基因组文件详情越权
# ============================================================

class TestGenomeDetailAuthz:
    """基因组文件详情端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_access_user_b_genome(self, client, seed_genome_data):
        """User A 不能查看 User B 的基因组详情 → 403/404"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_can_access_own_genome(self, client, seed_genome_data):
        """User A 可以查看自己的基因组详情"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_a_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["file_name"] == "user_a_genome.txt"


# ============================================================
# 2. 基因组文件删除越权
# ============================================================

class TestGenomeDeleteAuthz:
    """基因组文件删除端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_delete_user_b_genome(self, client, seed_genome_data):
        """User A 不能删除 User B 的基因组 → 403/404"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.delete(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_can_delete_own_genome(self, client, seed_genome_data):
        """User A 可以删除自己的基因组"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.delete(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_a_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 200


# ============================================================
# 3. 基因型匹配越权
# ============================================================

class TestGenomeMatchAuthz:
    """基因型匹配端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_match_user_b_genome(self, client, seed_genome_data):
        """User A 不能对 User B 的基因组触发匹配 → 403/404"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/match",
            params={"trait_id": seed_genome_data["trait_id"]},
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_a_cannot_list_user_b_matches(self, client, seed_genome_data):
        """User A 不能查看 User B 的匹配结果"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/matches",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)


# ============================================================
# 4. 风险评估越权
# ============================================================

class TestGenomeRiskAuthz:
    """风险评估端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_score_user_b_genome(self, client, seed_genome_data):
        """User A 不能对 User B 的基因组触发风险评估"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/risk/{seed_genome_data['trait_id']}",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_a_cannot_list_user_b_assessments(self, client, seed_genome_data):
        """User A 不能查看 User B 的风险评估列表"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/assessments",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)


# ============================================================
# 5. 报告导出越权
# ============================================================

class TestGenomeExportAuthz:
    """报告导出端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_export_user_b_genome(self, client, seed_genome_data):
        """User A 不能导出 User B 的基因组报告"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/export",
            params={"format": "json"},
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_can_export_own_genome(self, client, seed_genome_data):
        """User B 可以导出自己的基因组报告"""
        token = _make_token(USER_B_ID, UserRole.RESEARCHER)
        resp = await client.post(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/export",
            params={"format": "json"},
            headers=_headers(token),
        )
        assert resp.status_code == 200


# ============================================================
# 6. 知识图谱同步越权
# ============================================================

class TestGenomeGraphSyncAuthz:
    """知识图谱同步端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_sync_user_b_genome(self, client, seed_genome_data):
        """User A 不能同步 User B 的基因组到知识图谱"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            f"/api/v1/genome/genomes/{seed_genome_data['genome_b_id']}/graph-sync",
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)


# ============================================================
# 7. 列表隔离
# ============================================================

class TestGenomeListIsolation:
    """基因组列表端点按 owner 隔离"""

    @pytest.mark.asyncio
    async def test_user_a_sees_only_own_genomes(self, client, seed_genome_data):
        """User A 只能看到自己的基因组"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/genome/genomes", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["file_name"] == "user_a_genome.txt"

    @pytest.mark.asyncio
    async def test_user_b_sees_only_own_genomes(self, client, seed_genome_data):
        """User B 只能看到自己的基因组"""
        token = _make_token(USER_B_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/genome/genomes", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["file_name"] == "user_b_genome.txt"


# ============================================================
# 8. 角色限制
# ============================================================

class TestRoleRestriction:
    """非 FOUNDER 不能创建性状 / Prompt 模板"""

    @pytest.mark.asyncio
    async def test_researcher_cannot_create_trait(self, client, seed_genome_data):
        """RESEARCHER 不能创建性状 → 403"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            "/api/v1/genome/traits",
            json={"name": "新性状", "category": "metabolism", "description": "测试"},
            headers=_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_founder_can_create_trait(self, client, seed_genome_data):
        """FOUNDER 可以创建性状"""
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        resp = await client.post(
            "/api/v1/genome/traits",
            json={"name": "新性状", "category": "metabolism", "description": "测试"},
            headers=_headers(token),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_researcher_cannot_create_prompt_template(self, client, seed_genome_data):
        """RESEARCHER 不能创建 Prompt 模板 → 403"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            "/api/v1/genome/prompt-templates",
            json={
                "name": "测试模板",
                "category": "genome_interpretation",
                "template": "你是一个基因组解读专家...",
                "tier": "deep_insight",
            },
            headers=_headers(token),
        )
        assert resp.status_code == 403


# ============================================================
# 9. 个性化治疗越权
# ============================================================

class TestPersonalizedTreatmentAuthz:
    """个性化治疗端点越权防护"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_use_user_b_genome_for_treatment(self, client, seed_genome_data):
        """User A 不能用 User B 的基因组做个性化治疗"""
        token = _make_token(USER_A_ID, UserRole.RESEARCHER)
        resp = await client.post(
            "/api/v1/genome/personalized-treatment",
            json={
                "personal_genome_id": seed_genome_data["genome_b_id"],
                "trait_id": seed_genome_data["trait_id"],
                "cancer_type": "NSCLC",
                "stage": "IV",
            },
            headers=_headers(token),
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_user_b_can_use_own_genome_for_treatment(self, client, seed_genome_data):
        """User B 可以用自己的基因组做个性化治疗"""
        token = _make_token(USER_B_ID, UserRole.RESEARCHER)
        resp = await client.post(
            "/api/v1/genome/personalized-treatment",
            json={
                "personal_genome_id": seed_genome_data["genome_b_id"],
                "trait_id": seed_genome_data["trait_id"],
                "cancer_type": "NSCLC",
                "stage": "IV",
            },
            headers=_headers(token),
        )
        assert resp.status_code == 200
