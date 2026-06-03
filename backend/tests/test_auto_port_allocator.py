from services.auto_port_allocator import _allocate_from_range


def test_allocate_from_range_skips_excluded_ports():
    auto_ports = [{"name": "api"}, {"name": "metrics"}]

    ports = _allocate_from_range(auto_ports, 18801, 18805, [18801, 18802, 18803])

    assert ports == [18804, 18805]
