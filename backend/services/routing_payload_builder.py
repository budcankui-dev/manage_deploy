"""路由 DAG Payload 生成器。

将确认后的 IntentDraft + TaskOrder 转换为外部路由系统要求的 DAG JSON。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services.modality_catalog import normalize_modality, priority_for_modality
from services.resource_estimator import estimate_resources, estimate_data_mb, estimate_bandwidth_mbps
from services.routing_policy import require_routing_policy

ROUTING_STRATEGY_TO_POLICY_TYPE = {
    "resource_guarantee": "RESOURCE_GUARANTEE",
    "fastest_completion": "TIME_CONSTRAINED",
    "low_latency_forwarding": "LATENCY_CONSTRAINED",
    "load_balance": "LOAD_BALANCE",
    "cost_priority": "COST_CONSTRAINED",
}

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
    modality_priority_map: dict[str, Any] | None = None,
    routing_strategy: str | None = None,
    callback_url: str | None = None,
    source_endpoint: dict[str, Any] | None = None,
    destination_endpoint: dict[str, Any] | None = None,
    destination_port: int | None = None,
    deployable_roles: list[str] | set[str] | tuple[str, ...] | None = None,
    task_resource_override_enabled: bool = False,
    task_resource_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成外部路由系统可消费的 DAG JSON。

    字段映射规则见 docs/routing-system-integration-guide.md。
    """
    job_name = _task_type_to_job_name(task_type)
    modal = normalize_modality(modality, task_type) or modality or task_type
    job_id = order_id
    priority = priority_for_modality(modal, modality_priority_map, task_type)

    submit_ts_ms = int(business_start_time.timestamp() * 1000)

    nodes = _build_dag_nodes(
        task_type,
        template_nodes,
        resource_requirement,
        data_profile,
        source_name,
        destination_name,
        callback_url,
        source_endpoint,
        destination_endpoint,
        destination_port,
        deployable_roles,
        task_resource_override_enabled=task_resource_override_enabled,
        task_resource_overrides=task_resource_overrides,
    )
    edges = _build_dag_edges(task_type, nodes, data_profile, priority)

    normalized_strategy = _normalize_routing_strategy(routing_strategy)

    return {
        "job_id": job_id,
        "order_id": order_id,
        "job_name": job_name,
        "order_name": order_name,
        "task_type": task_type,
        "source_name": source_name,
        "destination_name": destination_name,
        "modal": modal,
        "priority": priority,
        "_comment": modal,
        "routing_strategy": normalized_strategy,
        "policy_type": _policy_type_for(normalized_strategy),
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


def _normalize_routing_strategy(routing_strategy: str | None) -> str:
    if routing_strategy is None or not str(routing_strategy).strip():
        return "resource_guarantee"
    return require_routing_policy(routing_strategy, field_name="routing_strategy")


def _policy_type_for(routing_strategy: str | None) -> str:
    return ROUTING_STRATEGY_TO_POLICY_TYPE[_normalize_routing_strategy(routing_strategy)]


def _build_dag_nodes(
    task_type: str,
    template_nodes: list[dict[str, Any]] | None,
    resource_requirement: dict[str, Any] | None,
    data_profile: dict[str, Any] | None = None,
    source_name: str | None = None,
    destination_name: str | None = None,
    callback_url: str | None = None,
    source_endpoint: dict[str, Any] | None = None,
    destination_endpoint: dict[str, Any] | None = None,
    destination_port: int | None = None,
    deployable_roles: list[str] | set[str] | tuple[str, ...] | None = None,
    task_resource_override_enabled: bool = False,
    task_resource_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的逻辑节点列表。"""
    if template_nodes:
        nodes = []
        for i, n in enumerate(template_nodes):
            task_node_id = n.get("name", f"node_{i}")
            task_node_type = n.get("node_type") or _infer_node_type(task_node_id)
            node = {
                "task_node_id": task_node_id,
                "task_role": _infer_role(task_node_id),
                "task_node_type": task_node_type,
                "resources": {
                    "cpu_units": n.get("cpu_units", 10),
                    "mem_mb": n.get("mem_mb", 1024),
                    "disk_mb": n.get("disk_mb", 1024),
                    "gpu_units": n.get("gpu_units", 0),
                },
            }
            node["network"] = _network_requirements_for_role(task_node_id, n.get("port_defs"))
            node.update(_deployment_identity(task_node_id, deployable_roles))
            node.update(
                _endpoint_identity(
                    task_node_id,
                    source_name,
                    destination_name,
                    callback_url,
                    source_endpoint=source_endpoint,
                    destination_endpoint=destination_endpoint,
                    destination_port=destination_port,
                )
            )
            nodes.append(node)
        return nodes

    defaults = _default_nodes_for_task_type(
        task_type,
        resource_requirement,
        data_profile,
        task_resource_override_enabled=task_resource_override_enabled,
        task_resource_overrides=task_resource_overrides,
    )
    for node in defaults:
        task_node_id = node["task_node_id"]
        node.setdefault("task_role", _infer_role(task_node_id))
        node.setdefault("network", _network_requirements_for_role(task_node_id))
        node.update(_deployment_identity(task_node_id, deployable_roles))
        node.update(
            _endpoint_identity(
                task_node_id,
                source_name,
                destination_name,
                callback_url,
                source_endpoint=source_endpoint,
                destination_endpoint=destination_endpoint,
                destination_port=destination_port,
            )
        )
    return defaults


def _default_nodes_for_task_type(
    task_type: str,
    resource_requirement: dict[str, Any] | None,
    data_profile: dict[str, Any] | None = None,
    *,
    task_resource_override_enabled: bool = False,
    task_resource_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    estimated = estimate_resources(task_type, data_profile)
    res_override = resource_requirement or {}
    configured_overrides = task_resource_overrides or {}
    task_overrides = (
        configured_overrides.get(task_type, {})
        if task_resource_override_enabled and isinstance(configured_overrides, dict)
        else {}
    )

    nodes = []
    for role, res in estimated.items():
        # Merge priority: estimator < system task override < per-order override.
        merged = {**res}
        role_override = task_overrides.get(role, {}) if isinstance(task_overrides, dict) else {}
        _merge_resource_override(merged, _resource_override_for_role(role_override, role))
        _merge_resource_override(merged, _resource_override_for_role(res_override, role))

        nodes.append({
            "task_node_id": role,
            "task_role": _infer_role(role),
            "task_node_type": _infer_node_type(role),
            "resources": {
                "cpu_units": merged["cpu_units"],
                "mem_mb": merged["cpu_mem_mb"],
                "disk_mb": merged["disk_mb"],
                "gpu_units": merged["gpu_units"],
            },
        })
    return nodes


def _resource_override_for_role(value: dict[str, Any] | None, role: str) -> dict[str, Any]:
    """Return a role-specific resource override while preserving flat override compatibility."""
    if not isinstance(value, dict):
        return {}
    role_value = value.get(role)
    if isinstance(role_value, dict):
        return role_value
    if any(key in value for key in ("cpu_units", "cpu_mem_mb", "mem_mb", "gpu_units", "gpu_mem_mb", "disk_mb")):
        return value
    return {}


def _merge_resource_override(target: dict[str, Any], override: dict[str, Any]) -> None:
    if not override:
        return
    for key in ("cpu_units", "cpu_mem_mb", "gpu_units", "gpu_mem_mb", "disk_mb"):
        if key in override:
            target[key] = override[key]
    if "mem_mb" in override:
        target["cpu_mem_mb"] = override["mem_mb"]


def _infer_node_type(role: Any) -> str:
    """DAG subtask category, not the physical topology node kind."""
    text = str(role or "").lower()
    if text in {"compute", "worker", "infer", "train"}:
        return "worker"
    if text in {"source", "sink", "video", "input", "output"}:
        return "terminal"
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
    callback_url: str | None = None,
    *,
    source_endpoint: dict[str, Any] | None = None,
    destination_endpoint: dict[str, Any] | None = None,
    destination_port: int | None = None,
) -> dict[str, Any]:
    """Expose user-selected topology endpoints while keeping task_node_id as the DAG role."""
    text = str(role or "").lower()
    if text in {"source", "video", "input"}:
        if source_endpoint:
            return _endpoint_fields(source_endpoint, fallback_name=source_name)
        if source_name:
            return {"fixed_topology_node_id": source_name}
    if text in {"sink", "output"} and destination_name:
        result = (
            _endpoint_fields(destination_endpoint, fallback_name=destination_name)
            if destination_endpoint
            else {"fixed_topology_node_id": destination_name}
        )
        if destination_port is not None:
            result["business_port"] = int(destination_port)
        if callback_url:
            result["callback_url"] = callback_url
        return result
    return {}


def _endpoint_fields(endpoint: dict[str, Any] | None, *, fallback_name: str | None = None) -> dict[str, Any]:
    if not isinstance(endpoint, dict):
        return {}
    topology_id = endpoint.get("topology_node_id") or fallback_name
    result: dict[str, Any] = {}
    if topology_id:
        result["fixed_topology_node_id"] = str(topology_id)
        result["topology_node_id"] = str(topology_id)
    for key in ("topology_alias", "business_ip", "business_ipv6"):
        value = endpoint.get(key)
        if value:
            result[key] = str(value)
    return result


def _deployment_identity(
    role: Any,
    deployable_roles: list[str] | set[str] | tuple[str, ...] | None,
) -> dict[str, bool]:
    if deployable_roles is None:
        return {}
    normalized = {str(item).lower() for item in deployable_roles}
    return {"deployable": str(role or "").lower() in normalized}


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
    priority: int,
) -> list[dict[str, Any]]:
    """构建路由 DAG 的边列表，表达业务数据流向。"""
    data_mb = estimate_data_mb(task_type, data_profile)
    bandwidth_mbps = estimate_bandwidth_mbps(task_type, data_profile)

    if len(nodes) < 2:
        return []

    edges = []
    for i in range(len(nodes) - 1):
        src = nodes[i]["task_node_id"]
        dst = nodes[i + 1]["task_node_id"]
        edges.append({
            "from": src,
            "to": dst,
            "data_mb": data_mb,
            "bandwidth_mbps": bandwidth_mbps,
            "flow": {
                "flow_id": f"{task_type}:{src}->{dst}",
                "protocol": "tcp",
                "dst_port_ref": f"{dst}.{dst}",
                "priority": priority,
            },
        })
    return edges
