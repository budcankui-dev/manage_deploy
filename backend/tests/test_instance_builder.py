from services.instance_builder import resolve_port_values


def test_resolve_port_values_from_defs_and_instance_values():
    port_defs = [{"name": "api", "label": "HTTP", "default": 9000}]
    port_values = {"api": 9100}

    docker_ports, normalized = resolve_port_values(port_defs, port_values)

    assert docker_ports == {"9100": "9100"}
    assert normalized == {"api": 9100}


def test_resolve_port_values_falls_back_to_default():
    port_defs = [{"name": "metrics", "default": 9090}]

    docker_ports, normalized = resolve_port_values(port_defs, None)

    assert docker_ports == {"9090": "9090"}
    assert normalized == {"metrics": 9090}


def test_resolve_port_values_legacy_ports():
    legacy = {"9000": "9000", "8080": "8080"}

    docker_ports, normalized = resolve_port_values(None, None, legacy)

    assert docker_ports == {"9000": "9000", "8080": "8080"}
    assert normalized["9000"] == 9000
