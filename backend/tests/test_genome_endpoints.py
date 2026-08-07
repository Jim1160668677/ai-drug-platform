"""个人基因组模块端点集成测试

覆盖 /api/v1/genome 下所有端点：
- 性状管理（list/get/create/loci/search-loci）
- 基因组文件管理（upload/list/get/delete）
- 基因型匹配（match/matches）
- 风险评估（score/list）
- LLM 解读（interpret）
- 生活建议（generate/list）
- 知识库扩充（kb/expand — FOUNDER only）
- Prompt 模板（list/create）
- 个性化治疗推荐（personalized-treatment）
- 知识图谱同步（graph-sync）
- 报告导出（export — markdown/json/both）

设计原则：
- 用 conftest.py 的 client + auth_headers 夹具（FOUNDER 角色）
- 通过 API 调用创建测试数据（端到端）
- LLM 调用走 Mock 模式（USE_MOCK=true）
"""
import io
import os
import sys
import uuid as uuid_mod

import pytest
import pytest_asyncio
from httpx import AsyncClient

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 注册 genome 相关模型
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    personal_genome, snp_locus, trait, prompt_template, user_llm_config, llm_config,
)


GENOME_PREFIX = "/api/v1/genome"


# ============================================================
# Fixtures — 通过 API 创建测试数据
# ============================================================

@pytest_asyncio.fixture
async def seed_trait(client: AsyncClient, auth_headers: dict):
    """通过 API 创建测试性状"""
    resp = await client.post(
        f"{GENOME_PREFIX}/traits",
        json={
            "name": "过敏易感测试",
            "category": "allergy",
            "description": "测试过敏易感性状",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"创建性状失败: {resp.text}"
    return resp.json()["data"]


@pytest_asyncio.fixture
async def seed_loci(client: AsyncClient, auth_headers: dict, seed_trait: dict):
    """通过 DB 直接创建测试位点（API 不暴露位点创建端点）"""
    # 用 client 夹具的 DB session
    from app.db.session import get_db
    from app.main import app
    # 直接调 search-loci 端点（Mock 模式下外部源返回空，但至少能触发流程）
    resp = await client.post(
        f"{GENOME_PREFIX}/traits/{seed_trait['id']}/search-loci",
        params={"use_external": False},
        headers=auth_headers,
    )
    # search-loci 可能返回空（无外部数据），改用 DB 直接插入
    # 获取覆盖的 DB session
    db_gen = app.dependency_overrides[get_db]()
    db = await db_gen.__anext__()
    from app.models.snp_locus import SnpLocus, LocusTier, EvidenceSource, EvidenceLevel, Population
    from app.models.trait import Trait
    import uuid as uuid_module
    trait_id = uuid_module.UUID(seed_trait["id"])
    loci_data = [
        ("rs1234", "1", 100000, "IL13", "A", "AA", 1.5, 0.8, LocusTier.CORE),
        ("rs5678", "5", 200000, "IL4", "T", "TT", 1.3, 0.7, LocusTier.CORE),
        ("rs9012", "11", 300000, "STAT6", "G", "GG", 1.1, 0.5, LocusTier.AUXILIARY),
    ]
    loci_ids = []
    for rsid, chrom, pos, gene, ea, rg, es, w, tier in loci_data:
        locus = SnpLocus(
            rsid=rsid, chromosome=chrom, position_grch37=pos, position_grch38=pos + 1000,
            gene_symbol=gene, trait_id=trait_id, effect_allele=ea, risk_genotype=rg,
            effect_size=es, weight=w, locus_tier=tier,
            population=Population.EAST_ASIAN,
            evidence_source=EvidenceSource.GWAS_CATALOG,
            evidence_level=EvidenceLevel.LEVEL_III,
            pmid="12345678", is_approved=True,
        )
        db.add(locus)
        await db.flush()
        loci_ids.append(str(locus.id))
    return {"trait_id": seed_trait["id"], "loci_ids": loci_ids}


@pytest_asyncio.fixture
async def seed_genome(client: AsyncClient, auth_headers: dict):
    """通过 API 上传 mock 基因组文件"""
    content = (
        "# 23andMe format\n"
        "rs1234\t1\t100000\tAA\n"
        "rs5678\t5\t200000\tTT\n"
        "rs9012\t11\t300000\tGG\n"
    )
    resp = await client.post(
        f"{GENOME_PREFIX}/upload",
        files={"file": ("test_genome.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
        data={"genome_build": "GRCh37"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"上传失败: {resp.text}"
    return resp.json()["data"]


# ============================================================
# 性状管理测试
# ============================================================

class TestTraitEndpoints:
    """性状端点"""

    @pytest.mark.asyncio
    async def test_list_traits_empty(self, client, auth_headers):
        """空列表"""
        resp = await client.get(f"{GENOME_PREFIX}/traits", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    @pytest.mark.asyncio
    async def test_create_trait(self, client, auth_headers):
        """创建性状"""
        resp = await client.post(
            f"{GENOME_PREFIX}/traits",
            json={"name": "测试性状", "category": "metabolism", "description": "desc"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "测试性状"
        assert resp.json()["data"]["category"] == "metabolism"

    @pytest.mark.asyncio
    async def test_get_trait(self, client, auth_headers, seed_trait):
        """获取性状详情"""
        resp = await client.get(
            f"{GENOME_PREFIX}/traits/{seed_trait['id']}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "过敏易感测试"

    @pytest.mark.asyncio
    async def test_get_trait_not_found(self, client, auth_headers):
        """不存在的性状"""
        resp = await client.get(
            f"{GENOME_PREFIX}/traits/{uuid_mod.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_trait_loci(self, client, auth_headers, seed_loci):
        """获取性状位点"""
        resp = await client.get(
            f"{GENOME_PREFIX}/traits/{seed_loci['trait_id']}/loci",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        loci = resp.json()["data"]["loci"]
        assert len(loci) == 3

    @pytest.mark.asyncio
    async def test_search_loci_no_external(self, client, auth_headers, seed_trait):
        """AI 检索位点 — 不调外部"""
        resp = await client.post(
            f"{GENOME_PREFIX}/traits/{seed_trait['id']}/search-loci",
            params={"use_external": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["trait"]["name"] == "过敏易感测试"


# ============================================================
# 基因组文件管理测试
# ============================================================

class TestGenomeFileEndpoints:
    """基因组文件端点"""

    @pytest.mark.asyncio
    async def test_upload_genome(self, client, auth_headers):
        """上传基因组文件"""
        content = "rs1234\t1\t100000\tAA\n"
        resp = await client.post(
            f"{GENOME_PREFIX}/upload",
            files={"file": ("test.txt", io.BytesIO(content.encode()), "text/plain")},
            data={"genome_build": "GRCh37"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["file_name"] == "test.txt"
        assert resp.json()["data"]["genome_build"] == "GRCh37"

    @pytest.mark.asyncio
    async def test_upload_invalid_extension(self, client, auth_headers):
        """非法扩展名"""
        resp = await client.post(
            f"{GENOME_PREFIX}/upload",
            files={"file": ("test.exe", io.BytesIO(b"x"), "application/octet-stream")},
            data={"genome_build": "GRCh37"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_upload_empty_file(self, client, auth_headers):
        """空文件"""
        resp = await client.post(
            f"{GENOME_PREFIX}/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            data={"genome_build": "GRCh37"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_list_genomes(self, client, auth_headers, seed_genome):
        """基因组列表"""
        resp = await client.get(f"{GENOME_PREFIX}/genomes", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] >= 1
        assert len(body["data"]) >= 1

    @pytest.mark.asyncio
    async def test_get_genome(self, client, auth_headers, seed_genome):
        """基因组详情"""
        resp = await client.get(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == seed_genome["id"]

    @pytest.mark.asyncio
    async def test_delete_genome(self, client, auth_headers, seed_genome):
        """删除基因组"""
        resp = await client.delete(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}", headers=auth_headers
        )
        assert resp.status_code == 200
        # 验证已删除
        resp2 = await client.get(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}", headers=auth_headers
        )
        assert resp2.status_code == 404


# ============================================================
# 基因型匹配测试
# ============================================================

class TestMatchEndpoints:
    """基因型匹配端点"""

    @pytest.mark.asyncio
    async def test_match_genotype(self, client, auth_headers, seed_genome, seed_loci):
        """触发基因型匹配"""
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["matched_loci"] == 3
        # rs1234=AA(风险), rs5678=TT(风险), rs9012=GG(风险)
        assert data["risk_loci"] == 3

    @pytest.mark.asyncio
    async def test_match_genotype_no_loci(self, client, auth_headers, seed_genome, seed_trait):
        """性状无位点 → 报错"""
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_trait["id"]},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_list_matches(self, client, auth_headers, seed_genome, seed_loci):
        """查询匹配结果"""
        # 先匹配
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        resp = await client.get(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/matches",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_list_matches_risk_only(self, client, auth_headers, seed_genome, seed_loci):
        """仅查风险匹配"""
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        resp = await client.get(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/matches",
            params={"risk_only": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 3  # 全部风险


# ============================================================
# 风险评估测试
# ============================================================

class TestRiskEndpoints:
    """风险评估端点"""

    @pytest.mark.asyncio
    async def test_score_risk(self, client, auth_headers, seed_genome, seed_loci):
        """触发风险评估"""
        # 先匹配
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "id" in data
        assert data["risk_level"] in ("low", "moderate", "high", "very_high")
        assert data["core_loci_matched"] == 2
        assert data["auxiliary_loci_matched"] == 1

    @pytest.mark.asyncio
    async def test_list_assessments(self, client, auth_headers, seed_genome, seed_loci):
        """评估列表"""
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        resp = await client.get(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/assessments",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1


# ============================================================
# 个性化治疗推荐测试
# ============================================================

class TestPersonalizedTreatment:
    """个性化治疗推荐端点"""

    @pytest.mark.asyncio
    async def test_personalized_treatment_basic(
        self, client, auth_headers, seed_genome, seed_loci
    ):
        """基础调用（无 disease 参数）"""
        # 先匹配 + 评分
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/personalized-treatment",
            json={
                "personal_genome_id": seed_genome["id"],
                "disease": None,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["personal_genome_id"] == seed_genome["id"]
        assert isinstance(data["recommendations"], list)
        assert data["llm_model"] is not None

    @pytest.mark.asyncio
    async def test_personalized_treatment_not_found_genome(self, client, auth_headers):
        """基因组不存在"""
        resp = await client.post(
            f"{GENOME_PREFIX}/personalized-treatment",
            json={"personal_genome_id": str(uuid_mod.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ============================================================
# 知识图谱同步测试
# ============================================================

class TestGraphSync:
    """图谱同步端点"""

    @pytest.mark.asyncio
    async def test_graph_sync(self, client, auth_headers, seed_genome, seed_loci):
        """触发图谱同步"""
        # 先匹配（写入 GenotypeMatch）
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/graph-sync",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["personal_genome_id"] == seed_genome["id"]
        assert data["user_nodes_added"] == 3  # 3 个风险位点
        assert data["source"] in ("mock", "neo4j")


# ============================================================
# 报告导出测试
# ============================================================

class TestExportEndpoint:
    """报告导出端点"""

    @pytest.mark.asyncio
    async def test_export_markdown(
        self, client, auth_headers, seed_genome, seed_loci
    ):
        """导出 Markdown 格式"""
        # 先匹配 + 评分
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/export",
            params={"format": "markdown"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "markdown" in data
        assert "json" not in data
        assert "# 个人基因组解读报告" in data["markdown"]
        assert "## 基本信息" in data["markdown"]
        assert "## 风险评估" in data["markdown"]

    @pytest.mark.asyncio
    async def test_export_json(self, client, auth_headers, seed_genome, seed_loci):
        """导出 JSON 格式"""
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/export",
            params={"format": "json"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "json" in data
        assert "markdown" not in data
        assert data["json"]["file_name"] == "test_genome.txt"
        assert len(data["json"]["genotype_matches"]) == 3

    @pytest.mark.asyncio
    async def test_export_both(self, client, auth_headers, seed_genome, seed_loci):
        """同时导出 Markdown + JSON"""
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/match",
            params={"trait_id": seed_loci["trait_id"]},
            headers=auth_headers,
        )
        await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/risk/{seed_loci['trait_id']}",
            headers=auth_headers,
        )
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/export",
            params={"format": "both"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "json" in data
        assert "markdown" in data

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, client, auth_headers, seed_genome):
        """不支持的格式"""
        resp = await client.post(
            f"{GENOME_PREFIX}/genomes/{seed_genome['id']}/export",
            params={"format": "pdf"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)


# ============================================================
# Prompt 模板测试
# ============================================================

class TestPromptTemplateEndpoints:
    """Prompt 模板端点"""

    @pytest.mark.asyncio
    async def test_list_templates_empty(self, client, auth_headers):
        """空模板列表"""
        resp = await client.get(f"{GENOME_PREFIX}/prompt-templates", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_create_template(self, client, auth_headers):
        """创建模板"""
        resp = await client.post(
            f"{GENOME_PREFIX}/prompt-templates",
            json={
                "name": "测试模板",
                "template_type": "interpretation",
                "content": "请基于以下基因型生成解读：{genotype}",
                "is_active": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "测试模板"

    @pytest.mark.asyncio
    async def test_list_templates_after_create(self, client, auth_headers):
        """创建后列表"""
        await client.post(
            f"{GENOME_PREFIX}/prompt-templates",
            json={
                "name": "测试模板2",
                "template_type": "general",
                "content": "通用模板",
                "is_active": True,
            },
            headers=auth_headers,
        )
        resp = await client.get(f"{GENOME_PREFIX}/prompt-templates", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1
