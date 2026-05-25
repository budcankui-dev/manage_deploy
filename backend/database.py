from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from config import settings

engine = create_async_engine(settings.database_url, echo=False)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_column(conn, "task_template_nodes", "cpu_limit", "FLOAT")
        await _ensure_column(conn, "task_template_nodes", "memory_limit", "VARCHAR(64)")
        await _ensure_column(conn, "task_instance_nodes", "cpu_limit", "FLOAT")
        await _ensure_column(conn, "task_instance_nodes", "memory_limit", "VARCHAR(64)")
        for table in ("task_template_nodes", "task_instance_nodes"):
            await _ensure_column(conn, table, "cpu_reservation", "FLOAT")
            await _ensure_column(conn, table, "cpu_shares", "INTEGER")
            await _ensure_column(conn, table, "cpuset_cpus", "VARCHAR(128)")
            await _ensure_column(conn, table, "cpu_quota", "INTEGER")
            await _ensure_column(conn, table, "cpu_period", "INTEGER")
            await _ensure_column(conn, table, "memory_reservation", "VARCHAR(64)")
            await _ensure_column(conn, table, "memory_swap_limit", "VARCHAR(64)")
            await _ensure_column(conn, table, "volume_mounts", "JSON")
        await _ensure_column(conn, "nodes", "business_ipv6", "VARCHAR(64)")
        await _ensure_column(conn, "task_templates", "macro_defs", "JSON")
        await _ensure_column(conn, "task_template_nodes", "port_defs", "JSON")
        await _ensure_column(conn, "task_instances", "macro_values", "JSON")
        await _ensure_column(conn, "task_instance_nodes", "port_defs", "JSON")
        await _ensure_column(conn, "task_instance_nodes", "port_values", "JSON")
        await _ensure_column(conn, "task_instances", "source_order_id", "VARCHAR(36)")
        await _ensure_column(conn, "task_instances", "keep_after_stop", "BOOLEAN NOT NULL DEFAULT 0")
        await _ensure_column(conn, "task_orders", "keep_after_stop", "BOOLEAN NOT NULL DEFAULT 0")
    await _ensure_default_users()


async def _ensure_default_users() -> None:
    """开发环境默认账号：admin/admin（管理员）、user/user（普通用户）。"""
    from sqlalchemy import select

    from enums import UserRole
    from models import User

    from api.auth import hash_password

    defaults = [
        ("admin", "admin", UserRole.ADMIN),
        ("user", "user", UserRole.USER),
    ]
    async with async_session_maker() as session:
        for username, password, role in defaults:
            exists = (
                await session.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
        await session.commit()


async def _ensure_column(conn, table_name: str, column_name: str, column_type: str) -> None:
    def _has_column(sync_conn):
        columns = inspect(sync_conn).get_columns(table_name)
        return any(c["name"] == column_name for c in columns)

    has_column = await conn.run_sync(_has_column)
    if not has_column:
        await conn.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        )
