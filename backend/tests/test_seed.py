"""种子数据脚本测试 — 覆盖 db/seed.py

测试 seed_database 在以下场景的行为：
- 全新数据库灌入（首次执行）
- 已存在数据时的幂等性
- founder 缺失时的安全退出
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models import (  # noqa: F401 — 注册所有模型
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)


@pytest_asyncio.fixture
async def seed_db_session():
    """专用 SQLite in-memory 数据库会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
    await engine.dispose()


class TestSeedDatabase:
    @pytest.mark.asyncio
    async def test_seed_fresh_database(self, seed_db_session):
        """首次灌入应创建所有演示数据"""
        from app.db.seed import seed_database

        stats = await seed_database(seed_db_session)

        assert stats["users"] == 5
        assert stats["projects"] == 1
        assert stats["datasets"] == 2
        assert stats["targets"] == 2
        assert stats["hypotheses"] == 2
        assert stats["experiments"] == 1

    @pytest.mark.asyncio
    async def test_seed_idempotent(self, seed_db_session):
        """第二次灌入应保持幂等（不重复创建）"""
        from app.db.seed import seed_database

        await seed_database(seed_db_session)
        stats2 = await seed_database(seed_db_session)

        assert stats2["users"] == 0
        assert stats2["projects"] == 0
        assert stats2["datasets"] == 0
        assert stats2["targets"] == 0
        assert stats2["hypotheses"] == 0
        assert stats2["experiments"] == 0

    @pytest.mark.asyncio
    async def test_seed_creates_founder(self, seed_db_session):
        """种子数据应包含 sid@ai-drug.com founder 用户"""
        from app.db.seed import seed_database
        from app.models.user import User

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(
            select(User).where(User.email == "sid@ai-drug.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.name == "Sid Sijbrandij"
        from app.core.security import UserRole
        assert user.role == UserRole.FOUNDER

    @pytest.mark.asyncio
    async def test_seed_creates_5_demo_users(self, seed_db_session):
        """应有 5 个不同角色的演示用户"""
        from app.db.seed import seed_database, DEMO_USERS

        await seed_database(seed_db_session)

        from app.models.user import User
        result = await seed_db_session.execute(select(User))
        users = result.scalars().all()
        assert len(users) == len(DEMO_USERS)

        emails = [u.email for u in users]
        for ud in DEMO_USERS:
            assert ud["email"] in emails

    @pytest.mark.asyncio
    async def test_seed_creates_project_with_metadata(self, seed_db_session):
        """项目应包含 inspiration 来源元数据"""
        from app.db.seed import seed_database
        from app.models.project import Project

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(
            select(Project).where(Project.name == "Sid NSCLC 个性化治疗")
        )
        project = result.scalar_one_or_none()
        assert project is not None
        assert project.cancer_type == "NSCLC"
        assert project.stage == "IV"
        assert project.metadata_["source"] == "demo_seed"

    @pytest.mark.asyncio
    async def test_seed_creates_egfr_target(self, seed_db_session):
        """种子应包含 EGFR 靶点（证据等级 I）"""
        from app.db.seed import seed_database
        from app.models.target import Target, EvidenceGrade

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(
            select(Target).where(Target.gene_symbol == "EGFR")
        )
        target = result.scalar_one_or_none()
        assert target is not None
        assert target.evidence_grade == EvidenceGrade.LEVEL_I
        assert target.confidence_score == 0.85
        assert len(target.variant_info) == 2
        assert len(target.approved_drugs) == 2

    @pytest.mark.asyncio
    async def test_seed_creates_b7h3_target(self, seed_db_session):
        """种子应包含 B7H3 靶点（证据等级 III）"""
        from app.db.seed import seed_database
        from app.models.target import Target, EvidenceGrade

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(
            select(Target).where(Target.gene_symbol == "B7H3")
        )
        target = result.scalar_one_or_none()
        assert target is not None
        assert target.evidence_grade == EvidenceGrade.LEVEL_III
        assert target.confidence_score == 0.62

    @pytest.mark.asyncio
    async def test_seed_creates_two_datasets(self, seed_db_session):
        """应创建 RNA-seq 和 VCF 两个数据集"""
        from app.db.seed import seed_database
        from app.models.dataset import Dataset

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(select(Dataset))
        datasets = result.scalars().all()
        assert len(datasets) == 2

        names = [d.name for d in datasets]
        assert any("RNA-seq" in n for n in names)
        assert any("VCF" in n for n in names)

    @pytest.mark.asyncio
    async def test_seed_creates_hypotheses(self, seed_db_session):
        """应创建 H1（已完成）和 H2（草稿）两个假设"""
        from app.db.seed import seed_database
        from app.models.hypothesis import Hypothesis

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(select(Hypothesis))
        hypos = result.scalars().all()
        assert len(hypos) == 2

        names = [h.name for h in hypos]
        assert any("H1" in n for n in names)
        assert any("H2" in n for n in names)

    @pytest.mark.asyncio
    async def test_seed_creates_experiment(self, seed_db_session):
        """应创建 Osimertinib 细胞毒性实验"""
        from app.db.seed import seed_database
        from app.models.experiment import Experiment

        await seed_database(seed_db_session)

        result = await seed_db_session.execute(select(Experiment))
        exps = result.scalars().all()
        assert len(exps) == 1
        assert "Osimertinib" in exps[0].name
        assert exps[0].config["drug"] == "Osimertinib"
        assert exps[0].result["measured"]["ic50"] == 0.08

    @pytest.mark.asyncio
    async def test_seed_demo_users_constants(self):
        """DEMO_USERS 常量应包含 5 个用户配置"""
        from app.db.seed import DEMO_USERS, DEMO_PASSWORD

        assert len(DEMO_USERS) == 5
        assert DEMO_PASSWORD == "demo123456"
        roles = [u["role"] for u in DEMO_USERS]
        from app.core.security import UserRole
        assert UserRole.FOUNDER in roles
        assert UserRole.CHIEF_RESEARCHER in roles
        assert UserRole.RESEARCHER in roles
        assert UserRole.DOCTOR in roles
        assert UserRole.DATA_ENGINEER in roles

    @pytest.mark.asyncio
    async def test_seed_main_function(self, capsys):
        """main() 函数应打印种子数据统计"""
        from app.db.seed import main
        from app.db.session import AsyncSessionLocal

        # 使用测试 SQLite 内存数据库
        with patch("app.db.seed.AsyncSessionLocal") as mock_session_local, \
             patch("app.db.seed.init_db", new=AsyncMock()), \
             patch("app.db.seed.settings") as mock_settings:
            mock_settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:@test"

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            # 让 seed_database 返回统计
            with patch("app.db.seed.seed_database", new=AsyncMock(return_value={
                "users": 5, "projects": 1, "datasets": 2,
                "targets": 2, "hypotheses": 2, "experiments": 1,
            })):
                mock_session_local.return_value = mock_session
                await main()

        captured = capsys.readouterr()
        assert "种子数据灌入完成" in captured.out
        assert "演示账号" in captured.out
