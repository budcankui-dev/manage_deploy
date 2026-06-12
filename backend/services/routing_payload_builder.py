"""路由 DAG Payload 生成器。

将确认后的 IntentDraft + TaskOrder 转换为外部路由系统要求的 DAG JSON。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services.resource_estimator import estimate_resources, estimate_data_mb, estimate_bandwidth_mbps


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

    字段映射规则见 docs/routing-system-integration-guide.md。
    """
    job_name = _task_type_to_job_name(task_type)
    modal = modality or task_type
    job_id = order_id

    submit_ts_ms = int(business_start_time.timestamp() * 1000)

    nodes = _build_dag_nodes(
        task_type,
        template_nodes,
        resource_requirement,
        data_profile,
        source_name,
        destination_name,
    )
    edges = _build_dag_edges(task_type, nodes, data_profile)

    return {
        "job_id": job_id,
        "order_id": order_id,
        "job_name": job_name,
        "order_name": order_name,
        "source_name": source_name,
        "destination_name": destination_name,
        "modal": modal,
        "_comment": modal,
        "policy_type": _infer_policy_type(task_type),
        "submit_ts_ms": submit_ts_ms,
        "business_start_ts_ms": submit_ts_ms,
        "business_end_ts_ms": int(business_end_time.timestamp() * 1000),
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
    data_profile: dict[str, Any] | None = None,
    source_name: str | None = None,
    destination_name: str | None = None,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的逻辑节点列表。"""
    if template_nodes:
        nodes = []
        for i, n in enumerate(template_nodes):
            node_id = n.get("name", f"node_{i}")
            node_type = n.get("node_type") or _infer_node_type(node_id)
            node = {
                "node_id": node_id,
                "role": _infer_role(node_id),
                "node_type": node_type,
                "resources": {
                    "cpu_units": n.get("cpu_units", 10),
                    "mem_mb": n.get("mem_mb", 1024),
                    "disk_mb": n.get("disk_mb", 1024),
                    "gpu_units": n.get("gpu_units", 0),
                },
            }
            node["network"] = _network_requirements_for_role(node_id, n.get("port_defs"))
            node.update(_endpoint_identity(node_id, source_name, destination_name))
            nodes.append(node)
        return nodes

    defaults = _default_nodes_for_task_type(task_type, resource_requirement, data_profile)
    for node in defaults:
        node.setdefault("role", _infer_role(node["node_id"]))
        node.setdefault("network", _network_requirements_for_role(node["node_id"]))
        node.update(_endpoint_identity(node["node_id"], source_name, destination_name))
    return defaults


def _default_nodes_for_task_type(
    task_type: str,
    resource_requirement: dict[str, Any] | None,
    data_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    estimated = estimate_resources(task_type, data_profile)
    res_override = resource_requirement or {}

    nodes = []
    for role, res in estimated.items():
        # Merge: override wins if provided
        merged = {**res}
        if res_override:
            for key in ("cpu_units", "cpu_mem_mb", "gpu_units", "gpu_mem_mb", "disk_mb"):
                if key in res_override:
                    merged[key] = res_override[key]

        nodes.append({
            "node_id": role,
            "role": _infer_role(role),
            "node_type": _infer_node_type(role),
            "resources": {
                "cpu_units": merged["cpu_units"],
                "mem_mb": merged["cpu_mem_mb"],
                "disk_mb": merged["disk_mb"],
                "gpu_units": merged["gpu_units"],
            },
        })
    return nodes


def _infer_node_type(role: Any) -> str:
    """DAG node category for external routing, not the physical topology node kind."""
    text = str(role or "").lower()
    if text in {"compute", "worker", "infer", "train"}:
        return "compute"
    if text in {"source", "sink", "video", "input", "output"}:
        return "endpoint"
    return "unknown"


def _infer_role(role: Any) -> str:
    text = str(role or "").lower()
    if text in {"source", "video", "input"}:
        return "source"
    if text in {"compute", "worker", "infer", "train"}:
        return "compute"
    if text in {"sink", "output"}:
        return "sink"
    return text or "unknown"


def _endpoint_identity(
    role: Any,
    source_name: str | None,
    destination_name: str | None,
) -> dict[str, str]:
    """Expose user-selected topology endpoints while keeping node_id as the DAG role."""
    text = str(role or "").lower()
    if text in {"source", "video", "input"} and source_name:
        return {"fixed_node_name": source_name, "fixed_node_role": "source"}
    if text in {"sink", "output"} and destination_name:
        return {"fixed_node_name": destination_name, "fixed_node_role": "destination"}
    return {}


def _network_requirements_for_role(
    role: Any,
    port_defs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Logical port requirements. Actual host ports are returned after placement."""
    role_text = str(role or "node").lower()
    requirements: list[dict[str, Any]] = []
    for item in port_defs or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or role_text)
        requirements.append(
            {
                "name": name,
                "protocol": item.get("protocol") or "tcp",
                "auto": bool(item.get("auto", False)),
                "range": item.get("range") or [18800, 19100],
                "direction": item.get("direction") or "inbound",
            }
        )
    if not requirements and role_text in {"source", "compute", "worker", "sink"}:
        requirements.append(
            {
                "name": role_text,
                "protocol": "tcp",
                "auto": True,
                "range": [18800, 19100],
                "direction": "inbound",
            }
        )
    return {"port_requirements": requirements} if requirements else {}


def _build_dag_edges(
    task_type: str,
    nodes: list[dict[str, Any]],
    data_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的边列表，表达业务数据流向。"""
    data_mb = estimate_data_mb(task_type, data_profile)
    bandwidth_mbps = estimate_bandwidth_mbps(task_type, data_profile)

    if len(nodes) < 2:
        return []

    edges = []
    for i in range(len(nodes) - 1):
        src = nodes[i]["node_id"]
        dst = nodes[i + 1]["node_id"]
        edges.append({
            "from": src,
            "to": dst,
            "data_mb": data_mb,
            "bandwidth_mbps": bandwidth_mbps,
            "flow": {
                "flow_id": f"{task_type}:{src}->{dst}",
                "protocol": "tcp",
                "dst_port_ref": f"{dst}.{dst}",
            },
        })
    return edges
