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
    is_routable: bool = True,
    node_kind: str = "terminal",
):
    node = Node(
        hostname=hostname,
        display_name=hostname,
        agent_address=f"http://{management_ip}:8001",
        management_ip=management_ip,
        business_ip=business_ip,
        business_ipv6=business_ipv6,
        topology_node_id=topology_node_id,
        node_kind=node_kind,
        is_schedulable=True,
        is_routable=is_routable,
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


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_non_routable_node(db_session):
    await _add_node(
        db_session,
        hostname="h6",
        topology_node_id="h18009006",
        management_ip="172.16.0.16",
        business_ip="10.112.151.47",
        is_routable=False,
    )

    with pytest.raises(EndpointResolutionError):
        await resolve_user_endpoint(db_session, "h6")


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_node_without_business_address(db_session):
    await _add_node(
        db_session,
        hostname="h7",
        topology_node_id="h4001001",
        management_ip="172.16.0.17",
        business_ip="",
    )

    with pytest.raises(EndpointResolutionError):
        await resolve_user_endpoint(db_session, "h7")


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_compute_node_as_user_endpoint(db_session):
    await _add_node(
        db_session,
        hostname="compute-1",
        topology_node_id="compute-1",
        management_ip="172.16.1.21",
        business_ip="10.112.38.25",
        business_ipv6="2001:db8::21",
        node_kind="worker",
    )

    with pytest.raises(EndpointResolutionError, match="源/目的端点只支持运营商节点"):
        await resolve_user_endpoint(db_session, "compute-1")
