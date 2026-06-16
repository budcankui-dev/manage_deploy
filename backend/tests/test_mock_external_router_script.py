import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mock_external_router.py"
SPEC = importlib.util.spec_from_file_location("mock_external_router", SCRIPT_PATH)
mock_external_router = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mock_external_router)

build_result_payload = mock_external_router.build_result_payload
extract_fixed_endpoint = mock_external_router.extract_fixed_endpoint


def test_extract_fixed_endpoint_reads_dag_role_endpoint():
    order = {
        "routing_input_dag": {
            "nodes": [
                {"task_node_id": "source", "fixed_topology_node_id": "h1"},
                {"task_node_id": "compute", "resources": {"gpu_units": 1}},
                {"task_node_id": "sink", "fixed_topology_node_id": "h2"},
            ]
        }
    }

    assert extract_fixed_endpoint(order, "source") == "h1"
    assert extract_fixed_endpoint(order, "sink") == "h2"
    assert extract_fixed_endpoint(order, "compute") is None


def test_build_result_payload_only_places_compute_by_default():
    order = {
        "order_id": "order-1",
        "routing_input_dag": {
            "routing_strategy": "low_latency_forwarding",
            "nodes": [
                {"task_node_id": "source", "fixed_topology_node_id": "h1"},
                {"task_node_id": "compute", "resources": {"gpu_units": 1}},
                {"task_node_id": "sink", "fixed_topology_node_id": "h2"},
            ],
        },
    }

    payload = build_result_payload(
        order,
        compute_node="compute-2",
        gpu_device="0",
        algorithm_version="mock-router-test",
    )

    assert payload["strategy"] == "low_latency_forwarding"
    assert payload["placements"] == [
        {"task_node_id": "compute", "topology_node_id": "compute-2", "gpu_device": "0"}
    ]
    assert payload["metadata"]["path"] == ["h1", "compute-2", "h2"]
    assert payload["metadata"]["algorithm_version"] == "mock-router-test"


def test_build_result_payload_can_omit_gpu_for_cpu_like_route():
    order = {
        "order_id": "order-2",
        "routing_input_dag": {
            "routing_strategy": "resource_guarantee",
            "nodes": [{"task_node_id": "source"}, {"task_node_id": "compute"}],
        },
    }

    payload = build_result_payload(order, compute_node="compute-1", gpu_device="")

    assert payload["placements"] == [
        {"task_node_id": "compute", "topology_node_id": "compute-1"}
    ]
