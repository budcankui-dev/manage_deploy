from types import SimpleNamespace

from services.port_plan import (
    build_local_port_env,
    build_peer_env_for_node,
    extract_host_ports,
    format_service_url,
    get_business_address,
    sanitize_env_key,
)


def test_extract_host_ports():
    assert extract_host_ports({"9000": "9000"}, "host") == [9000]


def test_sanitize_env_key():
    assert sanitize_env_key("source") == "SOURCE"
    assert sanitize_env_key("my-node") == "MY_NODE"


def test_format_service_url_ipv6():
    assert format_service_url("2001:db8:1::a", 9000) == "http://[2001:db8:1::a]:9000"


def test_get_business_address_prefers_ipv6():
    machine = SimpleNamespace(business_ip="10.0.1.1", business_ipv6="2001:db8:1::a")
    assert get_business_address(machine, prefer_ipv6=True) == "2001:db8:1::a"
    assert get_business_address(machine, prefer_ipv6=False) == "10.0.1.1"


def test_build_local_port_env():
    env = build_local_port_env("source", {"api": 9000})
    assert env["PORT_API"] == "9000"
    assert env["SOURCE_PORT_API"] == "9000"


def test_build_peer_env_named_ports_ipv6():
    current = SimpleNamespace(
        id="n2",
        name="compute",
        node_id="w2",
        ports={"8080": "8080"},
        port_values={"api": 8080},
        network_mode="host",
    )
    peer = SimpleNamespace(
        id="n1",
        name="source",
        node_id="w1",
        ports={"9000": "9000"},
        port_values={"api": 9000},
        network_mode="host",
    )
    machines = {
        "w1": SimpleNamespace(business_ip="10.0.1.1", business_ipv6="2001:db8:1::a"),
        "w2": SimpleNamespace(business_ip="10.0.1.2", business_ipv6="2001:db8:1::b"),
    }

    env = build_peer_env_for_node(current, [current, peer], machines, prefer_ipv6=True)

    assert env["PEER_SOURCE_HOST"] == "2001:db8:1::a"
    assert env["PEER_SOURCE_BUSINESS_IPV6"] == "2001:db8:1::a"
    assert env["PEER_SOURCE_PORT_API"] == "9000"
    assert env["PEER_SOURCE_URL_API"] == "http://[2001:db8:1::a]:9000"
    assert env["PEER_SOURCE_URL"] == "http://[2001:db8:1::a]:9000"
    assert "TASK_PEERS_JSON" in env
