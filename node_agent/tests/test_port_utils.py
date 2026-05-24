import pytest

from port_utils import extract_host_ports, format_host_ports_label, ports_map_from_host_ports


def test_extract_host_ports_host_mode():
    assert extract_host_ports({"9000": "9000"}, "host") == [9000]
    assert extract_host_ports({"9000": ""}, "host") == [9000]
    assert extract_host_ports({"8080": "8080", "9000": "9000"}, "host") == [8080, 9000]


def test_extract_host_ports_bridge_mode():
    assert extract_host_ports({"80": "8080"}, "bridge") == [8080]


def test_ports_map_from_host_ports():
    assert ports_map_from_host_ports([9000, 8080]) == {"9000": "9000", "8080": "8080"}


def test_format_host_ports_label():
    assert format_host_ports_label([9000, 8080]) == "9000,8080"
