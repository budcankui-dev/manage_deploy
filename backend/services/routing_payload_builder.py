"""路由 DAG Payload 生成器。

将确认后的 IntentDraft + TaskOrder 转换为外部路由系统要求的 DAG JSON。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def build_routing_payload(
    order_id: str,
    order_name: str,
    task_type: str,
    modality: str | None,
    source_name: str,
    destination_name: str,
    business_start_time: datetime,
    business_end_time: datetime,
    data_profile: dict[str, Any] | None = None,
    resource_requirement: dict[str, Any] | None = None,
    template_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成外部路由系统可消费的 DAG JSON。

    字段映射规则见 docs/conversation-order-routing-design.md。
    """
    job_name = _task_type_to_job_name(task_type)
    modal = modality or task_type
    job_id = f"{job_name}_{modal}_{order_id}"

    submit_ts_ms = int(business_start_time.timestamp() * 1000)
    deadline_ms = int(business_end_time.timestamp() * 1000)

    nodes = _build_dag_nodes(task_type, template_nodes, resource_requirement)
    edges = _build_dag_edges(task_type, nodes, data_profile)

    return {
        "job_id": job_id,
        "job_name": job_name,
        "modal": modal,
        "_comment": modal,
        "policy_type": _infer_policy_type(task_type),
        "submit_ts_ms": submit_ts_ms,
        "constraints": {
            "budget": None,
            "deadline_ms": deadline_ms,
        },
        "nodes": nodes,
        "edges": edges,
    }


def _task_type_to_job_name(task_type: str) -> str:
    mapping = {
        "high_throughput_matmul": "科学计算矩阵乘法",
        "low_latency_video_pipeline": "视频AI推理",
        "llm_text_generation": "大模型文本生成",
    }
    return mapping.get(task_type, task_type)


def _infer_policy_type(task_type: str) -> str:
    mapping = {
        "high_throughput_matmul": "COST_CONSTRAINED",
        "low_latency_video_pipeline": "LATENCY_CONSTRAINED",
        "llm_text_generation": "COST_CONSTRAINED",
    }
    return mapping.get(task_type, "COST_CONSTRAINED")


def _build_dag_nodes(
    task_type: str,
    template_nodes: list[dict[str, Any]] | None,
    resource_requirement: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的逻辑节点列表。"""
    if template_nodes:
        return [
            {
                "node_id": n.get("name", f"node_{i}"),
                "resources": {
                    "cpu_units": n.get("cpu_units", 10),
                    "mem_mb": n.get("mem_mb", 1024),
                    "disk_mb": n.get("disk_mb", 1024),
                    "gpu_units": n.get("gpu_units", 0),
                },
                "exec": {
                    "est_runtime_ms": n.get("est_runtime_ms", 600000),
                },
            }
            for i, n in enumerate(template_nodes)
        ]

    defaults = _default_nodes_for_task_type(task_type, resource_requirement)
    return defaults


def _default_nodes_for_task_type(
    task_type: str,
    resource_requirement: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    res = resource_requirement or {}
    cpu = res.get("cpu_units", 10)
    mem = res.get("mem_mb", 1024)
    gpu = res.get("gpu_units", 0)
    est_ms = res.get("est_runtime_ms", 600000)

    if task_type == "high_throughput_matmul":
        return [
            {"node_id": "source", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": 0}, "exec": {"est_runtime_ms": est_ms}},
            {"node_id": "compute", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": gpu}, "exec": {"est_runtime_ms": est_ms}},
            {"node_id": "sink", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": 0}, "exec": {"est_runtime_ms": est_ms}},
        ]
    elif task_type == "low_latency_video_pipeline":
        return [
            {"node_id": "video", "resources": {"cpu_units": 20, "mem_mb": mem, "disk_mb": 1024, "gpu_units": 0}, "exec": {"est_runtime_ms": est_ms}},
            {"node_id": "infer", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": gpu}, "exec": {"est_runtime_ms": est_ms}},
        ]
    else:
        return [
            {"node_id": "source", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": 0}, "exec": {"est_runtime_ms": est_ms}},
            {"node_id": "compute", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": gpu}, "exec": {"est_runtime_ms": est_ms}},
            {"node_id": "sink", "resources": {"cpu_units": cpu, "mem_mb": mem, "disk_mb": 1024, "gpu_units": 0}, "exec": {"est_runtime_ms": est_ms}},
        ]


def _build_dag_edges(
    task_type: str,
    nodes: list[dict[str, Any]],
    data_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的边列表，表达业务数据流向。"""
    profile = data_profile or {}
    data_mb = profile.get("data_mb", 20)

    if len(nodes) < 2:
        return []

    edges = []
    for i in range(len(nodes) - 1):
        edges.append({
            "from": nodes[i]["node_id"],
            "to": nodes[i + 1]["node_id"],
            "data_mb": data_mb,
        })
    return edges