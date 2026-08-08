"""服务重启中断运行恢复测试

验证 _recover_interrupted_runs 将 RUNNING/PENDING 标记为 FAILED，
且不影响已终态（COMPLETED）的运行。
"""
import os
import sys
import uuid as uuid_mod
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault("USE_MOCK", "true")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.main import _recover_interrupted_runs  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.coscientist_run import CoScientistRun, RunStatus  # noqa: E402


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield SessionLocal
    await engine.dispose()


def _make_run(session: AsyncSession, status: str):
    run = CoScientistRun(
        id=uuid_mod.uuid4(),
        user_id=uuid_mod.uuid4(),
        research_goal="测试研究目标",
        status=status,
    )
    session.add(run)
    return run


@pytest.mark.asyncio
async def test_recover_interrupted_marks_running_failed(session_factory, monkeypatch):
    """启动恢复：RUNNING/PENDING → FAILED，COMPLETED 不受影响"""
    import app.db.session as db_session_module

    async with session_factory() as session:
        running = _make_run(session, RunStatus.RUNNING)
        pending = _make_run(session, RunStatus.PENDING)
        completed = _make_run(session, RunStatus.COMPLETED)
        await session.commit()
        running_id = running.id
        pending_id = pending.id
        completed_id = completed.id

    monkeypatch.setattr(db_session_module, "async_session_factory", session_factory)

    await _recover_interrupted_runs()

    async with session_factory() as session:
        result = await session.execute(select(CoScientistRun))
        recovered = list(result.scalars().all())
        by_id = {r.id: r for r in recovered}
        assert by_id[running_id].status == RunStatus.FAILED
        assert by_id[pending_id].status == RunStatus.FAILED
        assert by_id[completed_id].status == RunStatus.COMPLETED
        assert "服务重启中断" in (by_id[running_id].error_message or "")


@pytest.mark.asyncio
async def test_recover_no_interrupted_runs_is_noop(session_factory, monkeypatch):
    """无中断运行时不报错"""
    import app.db.session as db_session_module

    async with session_factory() as session:
        _make_run(session, RunStatus.COMPLETED)
        _make_run(session, RunStatus.CANCELLED)
        await session.commit()

    monkeypatch.setattr(db_session_module, "async_session_factory", session_factory)

    await _recover_interrupted_runs()

    async with session_factory() as session:
        result = await session.execute(select(CoScientistRun))
        runs = list(result.scalars().all())
        assert all(r.status in (RunStatus.COMPLETED, RunStatus.CANCELLED) for r in runs)