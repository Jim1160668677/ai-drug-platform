"""水平越权校验测试 (P5 后续) — 验证列表端点按角色过滤数据可见范围

测试维度：
1. RESEARCHER 隔离：两个 RESEARCHER 只能看到各自拥有的项目及关联资源
2. FOUNDER 全局可见：FOUNDER 能看到所有项目
3. CHIEF_RESEARCHER 全局可见：CHIEF_RESEARCHER 能看到所有项目
4. project_id 过滤叠加：即使指定 project_id，非领导角色也只能看到自己拥有的项目
5. 分子隔离：RESEARCHER 只能看到自己项目下靶点关联的分子

技术要点：
- httpx.AsyncClient + ASGITransport(app=app)
- 多用户场景：DB 中创建多个用户，JWT 携带不同 subject/role
- mock_get_current_user 根据 token 的 subject 返回对应用户
- 不使用 --cov 运行（PyO3/bcrypt 兼容性问题）
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
    llm_config,
)
from app.models.user import User  # noqa: E402

# 测试用户 ID（固定 UUID 满足 DB 外键约束）
FOUNDER_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000A1")
RESEARCHER_A_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000B1")
RESEARCHER_B_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000B2")
CHIEF_ID = uuid_mod.UUID("00000000-0000-0000-0000-0000000000C1")


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite 内存数据库会话，预置 4 个测试用户"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        # 预置 4 个用户
        users = [
            User(
                id=FOUNDER_ID, email="founder@authz.test", name="Founder",
                hashed_password=hash_password("pass123"), role=UserRole.FOUNDER, is_active=True,
            ),
            User(
                id=RESEARCHER_A_ID, email="researcher-a@authz.test", name="Researcher A",
                hashed_password=hash_password("pass123"), role=UserRole.RESEARCHER, is_active=True,
            ),
            User(
                id=RESEARCHER_B_ID, email="researcher-b@authz.test", name="Researcher B",
                hashed_password=hash_password("pass123"), role=UserRole.RESEARCHER, is_active=True,
            ),
            User(
                id=CHIEF_ID, email="chief@authz.test", name="Chief",
                hashed_password=hash_password("pass123"), role=UserRole.CHIEF_RESEARCHER, is_active=True,
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
    """为指定用户生成 JWT token"""
    return create_access_token(subject=str(user_id), role=role)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP 客户端 — mock_get_current_user 根据 token subject 返回对应用户"""
    from fastapi import Depends, HTTPException, status

    # 预置用户映射（id → 用户属性）
    user_map: Dict[uuid_mod.UUID, dict] = {
        FOUNDER_ID: {"email": "founder@authz.test", "name": "Founder", "role": UserRole.FOUNDER},
        RESEARCHER_A_ID: {"email": "researcher-a@authz.test", "name": "Researcher A", "role": UserRole.RESEARCHER},
        RESEARCHER_B_ID: {"email": "researcher-b@authz.test", "name": "Researcher B", "role": UserRole.RESEARCHER},
        CHIEF_ID: {"email": "chief@authz.test", "name": "Chief", "role": UserRole.CHIEF_RESEARCHER},
    }

    async def override_get_db():
        yield db_session

    async def mock_get_current_user(token: str = Depends(oauth2_scheme)):
        """根据 token 的 subject 返回对应用户（保留 JWT 签名校验）"""
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
async def seed_projects(client: AsyncClient, db_session: AsyncSession) -> dict:
    """预置测试数据：两个 RESEARCHER 各创建一个项目并上传数据集

    返回包含各资源 ID 的字典供测试引用。
    """
    from app.models.dataset import Dataset, DataType, ParseStatus
    from app.models.target import Target
    from app.models.molecule import Molecule
    from app.models.hypothesis import Hypothesis
    from app.models.treatment import Treatment
    from app.models.experiment import Experiment

    # Researcher A 创建项目 A
    proj_a = project.Project(
        name="Project A", patient_pseudonym="PA-001", cancer_type="NSCLC",
        stage="IV", owner_id=RESEARCHER_A_ID,
    )
    # Researcher B 创建项目 B
    proj_b = project.Project(
        name="Project B", patient_pseudonym="PB-001", cancer_type="Breast",
        stage="III", owner_id=RESEARCHER_B_ID,
    )
    db_session.add_all([proj_a, proj_b])
    await db_session.flush()

    # 各项目下创建数据集
    ds_a = Dataset(
        project_id=proj_a.id, name="Dataset A", data_type=DataType.RNA_SEQ,
        parse_status=ParseStatus.COMPLETED, uploaded_by=RESEARCHER_A_ID,
    )
    ds_b = Dataset(
        project_id=proj_b.id, name="Dataset B", data_type=DataType.RNA_SEQ,
        parse_status=ParseStatus.COMPLETED, uploaded_by=RESEARCHER_B_ID,
    )
    db_session.add_all([ds_a, ds_b])
    await db_session.flush()

    # 各项目下创建靶点
    tg_a = Target(project_id=proj_a.id, gene_symbol="EGFR", evidence_grade="I")
    tg_b = Target(project_id=proj_b.id, gene_symbol="KRAS", evidence_grade="II")
    db_session.add_all([tg_a, tg_b])
    await db_session.flush()

    # 各靶点下创建分子
    mol_a = Molecule(target_id=tg_a.id, smiles="CCO", name="Mol A")
    mol_b = Molecule(target_id=tg_b.id, smiles="CCC", name="Mol B")
    db_session.add_all([mol_a, mol_b])
    await db_session.flush()

    # 各项目下创建假设
    hyp_a = Hypothesis(project_id=proj_a.id, name="Hypothesis A", created_by=RESEARCHER_A_ID)
    hyp_b = Hypothesis(project_id=proj_b.id, name="Hypothesis B", created_by=RESEARCHER_B_ID)
    db_session.add_all([hyp_a, hyp_b])
    await db_session.flush()

    # 各项目下创建治疗方案
    tr_a = Treatment(project_id=proj_a.id, name="Treatment A", therapy_type="targeted")
    tr_b = Treatment(project_id=proj_b.id, name="Treatment B", therapy_type="chemo")
    db_session.add_all([tr_a, tr_b])
    await db_session.flush()

    # 各项目下创建实验
    exp_a = Experiment(project_id=proj_a.id, name="Experiment A", exp_type="dry_lab")
    exp_b = Experiment(project_id=proj_b.id, name="Experiment B", exp_type="wet_lab")
    db_session.add_all([exp_a, exp_b])
    await db_session.flush()

    return {
        "proj_a_id": str(proj_a.id),
        "proj_b_id": str(proj_b.id),
        "ds_a_id": str(ds_a.id),
        "ds_b_id": str(ds_b.id),
        "tg_a_id": str(tg_a.id),
        "tg_b_id": str(tg_b.id),
        "mol_a_id": str(mol_a.id),
        "mol_b_id": str(mol_b.id),
        "hyp_a_id": str(hyp_a.id),
        "hyp_b_id": str(hyp_b.id),
        "tr_a_id": str(tr_a.id),
        "tr_b_id": str(tr_b.id),
        "exp_a_id": str(exp_a.id),
        "exp_b_id": str(exp_b.id),
    }


# ============================================================
# 1. 项目列表可见性
# ============================================================

class TestProjectListVisibility:
    """验证 GET /projects 按角色过滤可见范围"""

    @pytest.mark.asyncio
    async def test_researcher_a_sees_only_own_project(self, client, seed_projects):
        """Researcher A 只能看到自己的项目"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/projects", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        names = [p["name"] for p in body["data"]]
        assert "Project A" in names
        assert "Project B" not in names, "Researcher A 不应看到 Researcher B 的项目"
        assert body["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_researcher_b_sees_only_own_project(self, client, seed_projects):
        """Researcher B 只能看到自己的项目"""
        token = _make_token(RESEARCHER_B_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/projects", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [p["name"] for p in body["data"]]
        assert "Project B" in names
        assert "Project A" not in names
        assert body["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_founder_sees_all_projects(self, client, seed_projects):
        """FOUNDER 能看到所有项目"""
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        resp = await client.get("/api/v1/projects", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [p["name"] for p in body["data"]]
        assert "Project A" in names
        assert "Project B" in names
        assert body["meta"]["total"] == 2

    @pytest.mark.asyncio
    async def test_chief_researcher_sees_all_projects(self, client, seed_projects):
        """CHIEF_RESEARCHER 能看到所有项目（研究领导层全局可见）"""
        token = _make_token(CHIEF_ID, UserRole.CHIEF_RESEARCHER)
        resp = await client.get("/api/v1/projects", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [p["name"] for p in body["data"]]
        assert "Project A" in names
        assert "Project B" in names
        assert body["meta"]["total"] == 2


# ============================================================
# 2. 数据集列表可见性
# ============================================================

class TestDatasetListVisibility:
    """验证 GET /data 按项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_datasets(self, client, seed_projects):
        """Researcher A 只能看到自己项目下的数据集"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/data", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [d["name"] for d in body["data"]]
        assert "Dataset A" in names
        assert "Dataset B" not in names
        assert body["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_founder_sees_all_datasets(self, client, seed_projects):
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        resp = await client.get("/api/v1/data", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2

    @pytest.mark.asyncio
    async def test_researcher_cannot_access_other_project_dataset_via_filter(
        self, client, seed_projects
    ):
        """即使指定他人的 project_id，Researcher A 也看不到 Researcher B 的数据集"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            "/api/v1/data",
            params={"project_id": seed_projects["proj_b_id"]},
            headers=_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        # 过滤后应为空（project_id 是 B 的，但 A 无权访问 B 的项目）
        assert body["data"] == []
        assert body["meta"]["total"] == 0


# ============================================================
# 3. 靶点列表可见性
# ============================================================

class TestTargetListVisibility:
    """验证 GET /targets 按项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_targets(self, client, seed_projects):
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/targets", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        genes = [t["gene_symbol"] for t in body["data"]]
        assert "EGFR" in genes
        assert "KRAS" not in genes
        assert body["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_founder_sees_all_targets(self, client, seed_projects):
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        resp = await client.get("/api/v1/targets", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2


# ============================================================
# 4. 分子列表可见性
# ============================================================

class TestMoleculeListVisibility:
    """验证 GET /molecules 按靶点→项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_molecules(self, client, seed_projects):
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/molecules", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [m["name"] for m in body["data"]]
        assert "Mol A" in names
        assert "Mol B" not in names
        assert body["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_founder_sees_all_molecules(self, client, seed_projects):
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        resp = await client.get("/api/v1/molecules", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2


# ============================================================
# 5. 假设列表可见性
# ============================================================

class TestHypothesisListVisibility:
    """验证 GET /hypotheses 按项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_hypotheses(self, client, seed_projects):
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/hypotheses", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [h["name"] for h in body["data"]]
        assert "Hypothesis A" in names
        assert "Hypothesis B" not in names
        assert body["meta"]["total"] == 1


# ============================================================
# 6. 治疗方案列表可见性
# ============================================================

class TestTreatmentListVisibility:
    """验证 GET /treatments 按项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_treatments(self, client, seed_projects):
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/treatments", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [t["name"] for t in body["data"]]
        assert "Treatment A" in names
        assert "Treatment B" not in names
        assert body["meta"]["total"] == 1


# ============================================================
# 7. 实验列表可见性
# ============================================================

class TestExperimentListVisibility:
    """验证 GET /experiments 按项目归属过滤"""

    @pytest.mark.asyncio
    async def test_researcher_sees_only_own_experiments(self, client, seed_projects):
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get("/api/v1/experiments", headers=_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        names = [e["name"] for e in body["data"]]
        assert "Experiment A" in names
        assert "Experiment B" not in names
        assert body["meta"]["total"] == 1


# ============================================================
# 8. 详情端点越权防护（回归验证）
# ============================================================

class TestDetailCrossTenantGuard:
    """验证详情端点仍然阻止跨租户访问（已有逻辑的回归测试）"""

    @pytest.mark.asyncio
    async def test_researcher_cannot_access_other_project_detail(self, client, seed_projects):
        """Researcher A 不能访问 Researcher B 的项目详情"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/projects/{seed_projects['proj_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_researcher_cannot_access_other_dataset_detail(self, client, seed_projects):
        """Researcher A 不能访问 Researcher B 的数据集详情"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/data/{seed_projects['ds_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_researcher_cannot_access_other_target_detail(self, client, seed_projects):
        """Researcher A 不能访问 Researcher B 的靶点详情"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/targets/{seed_projects['tg_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_researcher_cannot_access_other_molecule_detail(self, client, seed_projects):
        """Researcher A 不能访问 Researcher B 的分子详情"""
        token = _make_token(RESEARCHER_A_ID, UserRole.RESEARCHER)
        resp = await client.get(
            f"/api/v1/molecules/{seed_projects['mol_b_id']}",
            headers=_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_founder_can_access_any_project_detail(self, client, seed_projects):
        """FOUNDER 可以访问任意项目详情"""
        token = _make_token(FOUNDER_ID, UserRole.FOUNDER)
        for pid_key in ("proj_a_id", "proj_b_id"):
            resp = await client.get(
                f"/api/v1/projects/{seed_projects[pid_key]}",
                headers=_headers(token),
            )
            assert resp.status_code == 200, f"FOUNDER 应能访问 {pid_key}"
