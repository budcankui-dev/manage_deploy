import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import models  # noqa: F401
from database import Base, _ensure_default_users
from enums import UserRole
from models import User


@pytest_asyncio.fixture
async def user_seed_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("database.async_session_maker", session_maker)
    yield session_maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_default_users_creates_admin_and_user(user_seed_session):
    await _ensure_default_users()
    async with user_seed_session() as session:
        admin = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one_or_none()
        user = (
            await session.execute(select(User).where(User.username == "user"))
        ).scalar_one_or_none()

    assert admin is not None
    assert admin.role == UserRole.ADMIN
    assert user is not None
    assert user.role == UserRole.USER


@pytest.mark.asyncio
async def test_ensure_default_users_is_idempotent(user_seed_session):
    await _ensure_default_users()
    await _ensure_default_users()
    async with user_seed_session() as session:
        admin_count = (
            await session.execute(
                select(func.count(User.id)).where(User.username == "admin")
            )
        ).scalar_one()
        user_count = (
            await session.execute(
                select(func.count(User.id)).where(User.username == "user")
            )
        ).scalar_one()

    assert admin_count == 1
    assert user_count == 1
