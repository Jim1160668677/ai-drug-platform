"""数据库会话管理 — 异步 SQLAlchemy"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# SQLite 不支持 pool_size/max_overflow 参数
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine_kwargs = {
    "echo": settings.APP_ENV == "development",
    "pool_pre_ping": not _is_sqlite,
}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 10

# 异步引擎
engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """初始化数据库（创建表）"""
    from app.models.base import Base
    from app.models import (  # noqa: F401 — 确保所有模型被导入
        user, project, dataset, target, molecule,
        treatment, hypothesis, experiment, audit, analysis_job, workflow_run,
        llm_config, report, data_lineage, consent,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_migrations() -> None:
    """运行 Alembic 迁移（生产环境推荐使用）

    Alembic 的 command.upgrade 是同步阻塞调用，在线程池中执行以避免阻塞事件循环。
    """
    import asyncio

    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    except ImportError:
        # Alembic 未安装时降级到 create_all
        await init_db()
