"""C1/C2 — 流水线断点续行测试

验证：
- resume_from_step 跳过之前的步骤（SKIPPED），从指定步骤开始执行
- skip_steps 跳过特定步骤，其他步骤正常执行
- summary 中包含 skipped_steps 列表和 resumed_from 字段
- 无效的 resume_from_step 等同于从头开始
"""
import os
import sys
import uuid
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

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
from app.core.security import UserRole, create_access_token, decode_token  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    user, project, dataset, target, molecule,
    treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
    llm_config,
)
from app.services.orchestrator.discovery_pipeline import (
    DiscoveryPipeline,
    PipelineStepStatus,
    STEP_ORDER,
)

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
async def pipeline(db_session: AsyncSession) -> DiscoveryPipeline:
    return DiscoveryPipeline(db_session)


class TestPipelineStepOrder:
    """步骤顺序常量验证"""

    def test_step_order_includes_all_builtin_steps(self):
        """STEP_ORDER 包含所有内置步骤"""
        assert "target_discovery" in STEP_ORDER
        assert "molecule_generation" in STEP_ORDER
        assert "treatment_matching" in STEP_ORDER
        assert "hypothesis_generation" in STEP_ORDER

    def test_step_order_correct_sequence(self):
        """步骤顺序正确：靶点→分子→治疗→假设"""
        assert STEP_ORDER.index("target_discovery") < STEP_ORDER.index("molecule_generation")
        assert STEP_ORDER.index("molecule_generation") < STEP_ORDER.index("treatment_matching")
        assert STEP_ORDER.index("treatment_matching") < STEP_ORDER.index("hypothesis_generation")


class TestPipelineResumeFromStep:
    """C1: resume_from_step 参数测试"""

    @pytest.mark.asyncio
    async def test_resume_from_molecule_generation_skips_target_discovery(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """resume_from_step='molecule_generation' 时跳过 target_discovery"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step1_discover_targets", new=AsyncMock()
        ) as mock_step1, patch.object(
            pipeline, "_step2_generate_molecules", new=AsyncMock(
                return_value={"status": "success", "molecules_saved": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock(
                return_value={"status": "success", "treatments_created": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock(
                return_value={"status": "success", "hypotheses_generated": 0, "duration_sec": 0}
            )
        ):
            result = await pipeline.run(
                project_id=project.id,
                resume_from_step="molecule_generation",
            )

        assert result["steps"]["target_discovery"]["status"] == PipelineStepStatus.SKIPPED
        mock_step1.assert_not_called()
        assert "target_discovery" in result["summary"]["skipped_steps"]
        assert result["summary"]["resumed_from"] == "molecule_generation"

    @pytest.mark.asyncio
    async def test_invalid_resume_from_step_starts_from_beginning(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """无效的 resume_from_step 等同于从头开始"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step1_discover_targets", new=AsyncMock(
                return_value={"status": "success", "targets_found": 0, "tier": "fast_screen",
                              "duration_sec": 0, "error": None}
            )
        ) as mock_step1, patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock(
                return_value={"status": "success", "treatments_created": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock(
                return_value={"status": "success", "hypotheses_generated": 0, "duration_sec": 0}
            )
        ):
            result = await pipeline.run(
                project_id=project.id,
                resume_from_step="INVALID_STEP",
            )

        # 无效 resume_from_step 等价于 resume_idx=0，所以 target_discovery 应该执行
        mock_step1.assert_called_once()
        assert result["summary"]["resumed_from"] == "INVALID_STEP"


class TestPipelineSkipSteps:
    """C1: skip_steps 参数测试"""

    @pytest.mark.asyncio
    async def test_skip_treatment_matching(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """skip_steps=['treatment_matching'] 跳过该步骤"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step1_discover_targets", new=AsyncMock(
                return_value={"status": "success", "targets_found": 0, "tier": "fast_screen",
                              "duration_sec": 0, "error": None}
            )
        ), patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock()
        ) as mock_step3, patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock(
                return_value={"status": "success", "hypotheses_generated": 0, "duration_sec": 0}
            )
        ):
            result = await pipeline.run(
                project_id=project.id,
                skip_steps=["treatment_matching"],
            )

        assert result["steps"]["treatment_matching"]["status"] == PipelineStepStatus.SKIPPED
        mock_step3.assert_not_called()
        assert "treatment_matching" in result["summary"]["skipped_steps"]

    @pytest.mark.asyncio
    async def test_skip_multiple_steps(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """同时跳过多个步骤"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step1_discover_targets", new=AsyncMock(
                return_value={"status": "success", "targets_found": 0, "tier": "fast_screen",
                              "duration_sec": 0, "error": None}
            )
        ), patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock()
        ) as mock_step3, patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock()
        ) as mock_step4:
            result = await pipeline.run(
                project_id=project.id,
                skip_steps=["treatment_matching", "hypothesis_generation"],
            )

        assert result["steps"]["treatment_matching"]["status"] == PipelineStepStatus.SKIPPED
        assert result["steps"]["hypothesis_generation"]["status"] == PipelineStepStatus.SKIPPED
        mock_step3.assert_not_called()
        mock_step4.assert_not_called()
        assert "treatment_matching" in result["summary"]["skipped_steps"]
        assert "hypothesis_generation" in result["summary"]["skipped_steps"]


class TestPipelineSummarySkippedSteps:
    """C1: summary 中 skipped_steps 与 resumed_from 字段"""

    @pytest.mark.asyncio
    async def test_skipped_steps_in_summary(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """summary.skipped_steps 字段存在且为列表"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step1_discover_targets", new=AsyncMock(
                return_value={"status": "success", "targets_found": 0, "tier": "fast_screen",
                              "duration_sec": 0, "error": None}
            )
        ), patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock(
                return_value={"status": "success", "treatments_created": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock(
                return_value={"status": "success", "hypotheses_generated": 0, "duration_sec": 0}
            )
        ):
            result = await pipeline.run(
                project_id=project.id,
                skip_steps=["treatment_matching"],
            )

        assert "skipped_steps" in result["summary"]
        assert isinstance(result["summary"]["skipped_steps"], list)
        assert "treatment_matching" in result["summary"]["skipped_steps"]
        assert result["summary"]["resumed_from"] is None

    @pytest.mark.asyncio
    async def test_resumed_from_in_summary(
        self, pipeline: DiscoveryPipeline, db_session: AsyncSession
    ):
        """summary.resumed_from 字段记录恢复起点"""
        from app.models.project import Project

        project = Project(
            id=uuid.uuid4(),
            name="测试项目",
            owner_id=TEST_USER_ID,
            status="active",
        )
        db_session.add(project)
        await db_session.flush()

        with patch.object(
            pipeline, "_step2_generate_molecules", new=AsyncMock(
                return_value={"status": "success", "molecules_saved": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step3_match_treatments", new=AsyncMock(
                return_value={"status": "success", "treatments_created": 0, "duration_sec": 0}
            )
        ), patch.object(
            pipeline, "_step4_generate_hypotheses", new=AsyncMock(
                return_value={"status": "success", "hypotheses_generated": 0, "duration_sec": 0}
            )
        ):
            result = await pipeline.run(
                project_id=project.id,
                resume_from_step="molecule_generation",
            )

        assert result["summary"]["resumed_from"] == "molecule_generation"
