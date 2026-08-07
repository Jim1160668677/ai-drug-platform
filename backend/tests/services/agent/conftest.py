"""Agent 测试共享 fixtures"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UserRole, hash_password
from app.models.user import User


@pytest_asyncio.fixture
async def test_user(async_db_session: AsyncSession) -> User:
    """测试用户（FOUNDER 角色，全权限）"""
    user = User(
        email="agent-test@ai-drug.com",
        name="Agent Test User",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest_asyncio.fixture
async def researcher_user(async_db_session: AsyncSession) -> User:
    """测试用户（RESEARCHER 角色）"""
    user = User(
        email="researcher@ai-drug.com",
        name="Researcher",
        hashed_password=hash_password("test123456"),
        role=UserRole.RESEARCHER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest_asyncio.fixture
async def doctor_user(async_db_session: AsyncSession) -> User:
    """测试用户（DOCTOR 角色）"""
    user = User(
        email="doctor@ai-drug.com",
        name="Doctor",
        hashed_password=hash_password("test123456"),
        role=UserRole.DOCTOR,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest_asyncio.fixture
async def engineer_user(async_db_session: AsyncSession) -> User:
    """测试用户（DATA_ENGINEER 角色）"""
    user = User(
        email="engineer@ai-drug.com",
        name="Engineer",
        hashed_password=hash_password("test123456"),
        role=UserRole.DATA_ENGINEER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user
