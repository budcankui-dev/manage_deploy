from datetime import datetime, timedelta

import pytest

from services.routing_payload_builder import build_routing_payload


def test_routing_payload_applies_task_resource_override_to_matching_role():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-1",
        order_name="资源覆盖测试",
        task_type="high_throughput_matmul",
        modality="高通量计算模态",
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"matrix_size": 1024, "batch_count": 50},
        task_resource_override_enabled=True,
        task_resource_overrides={
            "high_throughput_matmul": {
                "compute": {
                    "cpu_units": 12,
                    "mem_mb": 4096,
                    "disk_mb": 2048,
                    "gpu_units": 1,
                }
            }
        },
    )

    compute = next(node for node in payload["nodes"] if node["task_node_id"] == "compute")
    source = next(node for node in payload["nodes"] if node["task_node_id"] == "source")

    assert compute["resources"] == {
        "cpu_units": 12,
        "mem_mb": 4096,
        "disk_mb": 2048,
        "gpu_units": 1,
    }
    assert source["resources"]["cpu_units"] == 2


def test_routing_payload_applies_per_order_role_resource_with_highest_priority():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-2",
        order_name="单工单资源覆盖测试",
        task_type="low_latency_video_pipeline",
        modality="低时延转发模态",
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"frame_count": 90, "resolution": "720p", "fps": 30},
        resource_requirement={
            "source": {"cpu_units": 1, "mem_mb": 256, "disk_mb": 256, "gpu_units": 0},
            "compute": {"cpu_units": 6, "mem_mb": 3072, "disk_mb": 2048, "gpu_units": 1},
            "sink": {"cpu_units": 1, "mem_mb": 256, "disk_mb": 256, "gpu_units": 0},
        },
        task_resource_override_enabled=True,
        task_resource_overrides={
            "low_latency_video_pipeline": {
                "compute": {"cpu_units": 4, "mem_mb": 2048, "disk_mb": 1024, "gpu_units": 1}
            }
        },
    )

    by_role = {node["task_node_id"]: node["resources"] for node in payload["nodes"]}

    assert by_role["source"] == {"cpu_units": 1, "mem_mb": 256, "disk_mb": 256, "gpu_units": 0}
    assert by_role["compute"] == {"cpu_units": 6, "mem_mb": 3072, "disk_mb": 2048, "gpu_units": 1}
    assert by_role["sink"] == {"cpu_units": 1, "mem_mb": 256, "disk_mb": 256, "gpu_units": 0}


def test_routing_payload_default_strategy_is_resource_guarantee():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-3",
        order_name="默认策略测试",
        task_type="high_throughput_matmul",
        modality="高通量计算模态",
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"matrix_size": 1024, "batch_count": 50},
    )

    assert payload["routing_strategy"] == "resource_guarantee"
    assert payload["policy_type"] == "RESOURCE_GUARANTEE"


def test_routing_payload_normalizes_legacy_modality_alias_for_router():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-legacy-modality",
        order_name="旧模态兼容测试",
        task_type="low_latency_video_pipeline",
        modality="low_latency_forwarding",
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"frame_count": 90, "resolution": "720p", "fps": 30},
        routing_strategy="low_latency_forwarding",
    )

    assert payload["modal"] == "低时延转发模态"
    assert payload["_comment"] == "低时延转发模态"
    assert payload["routing_strategy"] == "low_latency_forwarding"
    assert payload["policy_type"] == "LATENCY_CONSTRAINED"


def test_routing_payload_rejects_unknown_strategy():
    now = datetime(2026, 6, 16, 10, 0, 0)

    with pytest.raises(ValueError, match="routing_strategy"):
        build_routing_payload(
            order_id="order-unknown-strategy",
            order_name="未知策略拒绝测试",
            task_type="low_latency_video_pipeline",
            modality="低时延转发模态",
            source_name="h1",
            destination_name="h2",
            business_start_time=now,
            business_end_time=now + timedelta(hours=1),
            data_profile={"frame_count": 90, "resolution": "720p", "fps": 30},
            routing_strategy="legacy_unknown_strategy",
        )


def test_routing_payload_rejects_legacy_strategy_alias():
    now = datetime(2026, 6, 16, 10, 0, 0)

    with pytest.raises(ValueError, match="routing_strategy"):
        build_routing_payload(
            order_id="order-legacy-routing-strategy",
            order_name="旧策略名拒绝测试",
            task_type="high_throughput_matmul",
            modality="高通量计算模态",
            source_name="h1",
            destination_name="h2",
            business_start_time=now,
            business_end_time=now + timedelta(hours=1),
            data_profile={"matrix_size": 1024, "batch_count": 50},
            routing_strategy="completion_time_first",
        )


def test_routing_payload_includes_clean_dynamic_port_requirements():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-4",
        order_name="端口需求测试",
        task_type="low_latency_video_pipeline",
        modality="低时延转发模态",
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"frame_count": 90, "resolution": "720p", "fps": 30},
    )

    by_role = {node["task_node_id"]: node for node in payload["nodes"]}
    for role in ("source", "compute", "sink"):
        requirements = by_role[role]["network"]["port_requirements"]
        assert requirements == [
            {
                "name": role,
                "protocol": "tcp",
                "auto": True,
                "range": [18800, 19100],
                "direction": "inbound",
            }
        ]
    assert payload["edges"][0]["flow"]["dst_port_ref"] == "compute.compute"
    assert payload["edges"][1]["flow"]["dst_port_ref"] == "sink.sink"


def test_routing_payload_includes_external_user_endpoint_identity():
    now = datetime(2026, 6, 16, 10, 0, 0)

    payload = build_routing_payload(
        order_id="order-user-endpoints",
        order_name="用户端点演示",
        task_type="low_latency_video_pipeline",
        modality="低时延转发模态",
        source_name="h1",
        destination_name="h3",
        business_start_time=now,
        business_end_time=now + timedelta(hours=1),
        data_profile={"frame_count": 90, "resolution": "720p", "fps": 30},
        source_endpoint={
            "topology_node_id": "h18001001",
            "topology_alias": "h1",
            "business_ip": "10.112.126.124",
            "business_ipv6": "2001:db8::1",
        },
        destination_endpoint={
            "topology_node_id": "h18005003",
            "topology_alias": "h3",
            "business_ip": "10.112.20.40",
        },
        destination_port=9000,
        callback_url="http://10.112.20.40:9000/callback",
        deployable_roles=["compute"],
    )

    by_role = {node["task_node_id"]: node for node in payload["nodes"]}

    source = by_role["source"]
    assert source["task_role"] == "source"
    assert source["task_node_type"] == "terminal"
    assert source["deployable"] is False
    assert source["fixed_topology_node_id"] == "h18001001"
    assert source["topology_node_id"] == "h18001001"
    assert source["topology_alias"] == "h1"
    assert source["business_ip"] == "10.112.126.124"
    assert source["business_ipv6"] == "2001:db8::1"
    assert by_role["compute"]["deployable"] is True
    assert by_role["sink"]["deployable"] is False
    assert by_role["sink"]["fixed_topology_node_id"] == "h18005003"
    assert by_role["sink"]["topology_node_id"] == "h18005003"
    assert by_role["sink"]["topology_alias"] == "h3"
    assert by_role["sink"]["business_ip"] == "10.112.20.40"
    assert by_role["sink"]["business_port"] == 9000
    assert by_role["sink"]["callback_url"] == "http://10.112.20.40:9000/callback"
    assert [(edge["from"], edge["to"]) for edge in payload["edges"]] == [("source", "compute"), ("compute", "sink")]
