"""Build routing DAG JSON from intent draft parameters."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from services.resource_estimator import estimate_resources, estimate_data_mb, estimate_bandwidth_mbps

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

POLICY_TYPE_MAP = {
    "resource_guarantee": "RESOURCE_GUARANTEE",
    "fastest_completion": "TIME_CONSTRAINED",
    "load_balance": "LOAD_BALANCE",
    "cost_priority": "COST_CONSTRAINED",
}


def build_matmul_dag(
    order_id: str,
    source_name: str | None,
    destination_name: str | None,
    business_start_time: datetime | None,
    business_end_time: datetime | None,
    matrix_size: int | None,
    batch_count: int | None,
    routing_strategy: str | None,
) -> dict[str, Any]:
    """Build a 3-node DAG (source -> compute -> sink) for matrix multiplication."""
    now = datetime.now(SHANGHAI_TZ)
    fmt = "%Y-%m-%d %H:%M:%S"

    ms = matrix_size or 1024
    bc = batch_count or 1
    profile = {"matrix_size": ms, "batch_count": bc}
    resources = estimate_resources("high_throughput_matmul", profile)
    data_mb = estimate_data_mb("high_throughput_matmul", profile)
    bandwidth_mbps = estimate_bandwidth_mbps("high_throughput_matmul", profile)

    policy = POLICY_TYPE_MAP.get(routing_strategy or "resource_guarantee", "RESOURCE_GUARANTEE")

    return {
        "job_id": order_id,
        "job_name": "矩阵乘法计算任务",
        "modal": "高吞吐计算模态",
        "policy_type": policy,
        "submit_time": now.strftime(fmt),
        "scheduled_start_time": business_start_time.strftime(fmt) if business_start_time else now.strftime(fmt),
        "scheduled_end_time": business_end_time.strftime(fmt) if business_end_time else "",
        "edges": [
            {
                "from": "source",
                "to": "compute",
                "data_mb": data_mb,
                "bandwidth_mbps": bandwidth_mbps,
                "flow": {
                    "flow_id": f"{order_id}:source->compute",
                    "protocol": "tcp",
                    "dst_port_ref": "compute.compute",
                    "traffic_class": "high_throughput",
                    "priority": 60,
                },
            },
            {
                "from": "compute",
                "to": "sink",
                "data_mb": data_mb,
                "bandwidth_mbps": bandwidth_mbps,
                "flow": {
                    "flow_id": f"{order_id}:compute->sink",
                    "protocol": "tcp",
                    "dst_port_ref": "sink.sink",
                    "traffic_class": "high_throughput",
                    "priority": 60,
                },
            },
        ],
        "nodes": [
            {
                "node_id": "source",
                "resources": resources["source"],
                "network": {
                    "port_requirements": [
                        {"name": "source", "protocol": "tcp", "auto": True, "range": [18800, 19100], "direction": "inbound"}
                    ]
                },
            },
            {
                "node_id": "compute",
                "resources": resources["compute"],
                "network": {
                    "port_requirements": [
                        {"name": "compute", "protocol": "tcp", "auto": True, "range": [18800, 19100], "direction": "inbound"}
                    ]
                },
            },
            {
                "node_id": "sink",
                "resources": resources["sink"],
                "network": {
                    "port_requirements": [
                        {"name": "sink", "protocol": "tcp", "auto": True, "range": [18800, 19100], "direction": "inbound"}
                    ]
                },
            },
        ],
    }
