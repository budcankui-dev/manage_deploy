import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database import Base
from models import Node as NodeModel


@pytest_asyncio.fixture
async def isolated_engine_and_sessionmaker(monkeypatch):
    """Patch async_session_maker so resolve_manager_public_url binds to a temp DB."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the module-level reference used by resolve_manager_public_url.
    import services.self_identity as self_identity

    monkeypatch.setattr(self_identity, "async_session_maker", sm)
    yield sm
    await engine.dispose()


@pytest.fixture
def restore_manager_url():
    """Save and restore the settings.manager_public_url + backend_hostname around each test."""
    saved_url = settings.manager_public_url
    saved_host = settings.backend_hostname
    saved_port = settings.backend_port
    try:
        yield
    finally:
        settings.manager_public_url = saved_url
        settings.backend_hostname = saved_host
        settings.backend_port = saved_port


@pytest.mark.asyncio
async def test_resolve_uses_explicit_override_when_set(
    isolated_engine_and_sessionmaker, restore_manager_url
):
    from services.self_identity import resolve_manager_public_url

    settings.manager_public_url = "http://override.example:9999"
    settings.backend_hostname = "admin"

    url = await resolve_manager_public_url()

    assert url == "http://override.example:9999"
    assert settings.manager_public_url == "http://override.example:9999"


@pytest.mark.asyncio
async def test_resolve_looks_up_management_ip_from_nodes_table(
    isolated_engine_and_sessionmaker, restore_manager_url
):
    from services.self_identity import resolve_manager_public_url

    settings.manager_public_url = None
    settings.backend_hostname = "admin"
    settings.backend_port = 8000

    async with isolated_engine_and_sessionmaker() as session:
        session.add(
            NodeModel(
                hostname="admin",
                agent_address="http://10.99.0.1:8001",
                management_ip="10.99.0.1",
                business_ip="10.99.0.1",
            )
        )
        await session.commit()

    url = await resolve_manager_public_url()

    assert url == "http://10.99.0.1:8000"
    assert settings.manager_public_url == "http://10.99.0.1:8000"


@pytest.mark.asyncio
async def test_resolve_respects_custom_backend_port(
    isolated_engine_and_sessionmaker, restore_manager_url
):
    from services.self_identity import resolve_manager_public_url

    settings.manager_public_url = None
    settings.backend_hostname = "admin"
    settings.backend_port = 18000

    async with isolated_engine_and_sessionmaker() as session:
        session.add(
            NodeModel(
                hostname="admin",
                agent_address="http://10.99.0.2:8001",
                management_ip="10.99.0.2",
                business_ip="10.99.0.2",
            )
        )
        await session.commit()

    url = await resolve_manager_public_url()

    assert url == "http://10.99.0.2:18000"


@pytest.mark.asyncio
async def test_resolve_fails_fast_when_hostname_missing(
    isolated_engine_and_sessionmaker, restore_manager_url
):
    from services.self_identity import resolve_manager_public_url, BackendSelfIdentityError

    settings.manager_public_url = None
    settings.backend_hostname = "ghost-host-does-not-exist"

    with pytest.raises(BackendSelfIdentityError) as excinfo:
        await resolve_manager_public_url()

    assert "ghost-host-does-not-exist" in str(excinfo.value)
    assert "BACKEND_HOSTNAME" in str(excinfo.value) or "MANAGER_PUBLIC_URL" in str(excinfo.value)


@pytest.mark.asyncio
async def test_resolve_fails_when_management_ip_blank(
    isolated_engine_and_sessionmaker, restore_manager_url
):
    from services.self_identity import resolve_manager_public_url, BackendSelfIdentityError

    settings.manager_public_url = None
    settings.backend_hostname = "admin"

    async with isolated_engine_and_sessionmaker() as session:
        session.add(
            NodeModel(
                hostname="admin",
                agent_address="http://placeholder:8001",
                management_ip="   ",
                business_ip="10.99.0.3",
            )
        )
        await session.commit()

    with pytest.raises(BackendSelfIdentityError):
        await resolve_manager_public_url()
