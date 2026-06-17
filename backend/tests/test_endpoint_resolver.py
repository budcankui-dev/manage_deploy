import pytest

from models import Node
from services.endpoint_resolver import EndpointResolutionError, resolve_user_endpoint


async def _add_node(
    db_session,
    *,
    hostname: str,
    topology_node_id: str,
    management_ip: str,
    business_ip: str,
    business_ipv6: str | None = None,
):
    node = Node(
        hostname=hostname,
        display_name=hostname,
        agent_address=f"http://{management_ip}:8001",
        management_ip=management_ip,
        business_ip=business_ip,
        business_ipv6=business_ipv6,
        topology_node_id=topology_node_id,
        node_kind="terminal",
        is_schedulable=True,
        is_routable=True,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.mark.asyncio
async def test_resolve_endpoint_by_hostname_returns_business_identity(db_session):
    await _add_node(
        db_session,
        hostname="h1",
        topology_node_id="h18001001",
        management_ip="172.16.0.11",
        business_ip="10.112.126.124",
        business_ipv6="2001:db8::1",
    )

    resolved = await resolve_user_endpoint(db_session, "h1")

    assert resolved.input_value == "h1"
    assert resolved.topology_node_id == "h18001001"
    assert resolved.topology_alias == "h1"
    assert resolved.business_ip == "10.112.126.124"
    assert resolved.business_ipv6 == "2001:db8::1"


@pytest.mark.asyncio
async def test_resolve_endpoint_by_business_ip_returns_same_identity(db_session):
    await _add_node(
        db_session,
        hostname="h2",
        topology_node_id="h18015002",
        management_ip="172.16.0.12",
        business_ip="10.112.253.42",
    )

    resolved = await resolve_user_endpoint(db_session, "10.112.253.42")

    assert resolved.topology_node_id == "h18015002"
    assert resolved.topology_alias == "h2"
    assert resolved.business_ip == "10.112.253.42"


@pytest.mark.asyncio
async def test_resolve_endpoint_by_topology_node_id_returns_alias(db_session):
    await _add_node(
        db_session,
        hostname="h3",
        topology_node_id="h18005003",
        management_ip="172.16.0.13",
        business_ip="10.112.20.40",
    )

    resolved = await resolve_user_endpoint(db_session, "h18005003")

    assert resolved.topology_node_id == "h18005003"
    assert resolved.topology_alias == "h3"
    assert resolved.business_ip == "10.112.20.40"


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_unknown_ip(db_session):
    await _add_node(
        db_session,
        hostname="h4",
        topology_node_id="h18007004",
        management_ip="172.16.0.14",
        business_ip="10.112.83.255",
    )

    with pytest.raises(EndpointResolutionError):
        await resolve_user_endpoint(db_session, "10.112.99.99")


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_management_ip_when_not_business_ip(db_session):
    await _add_node(
        db_session,
        hostname="h5",
        topology_node_id="h18014005",
        management_ip="172.16.0.15",
        business_ip="10.112.202.252",
    )

    with pytest.raises(EndpointResolutionError):
        await resolve_user_endpoint(db_session, "172.16.0.15")
