"""Routing/network readiness helpers.

External routers need actual container ports before programming flow rules.
The platform can only allocate those ports after placements are known and the
task instance has been materialized, so this module keeps that handoff explicit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from enums import RoutingStatus
from models import Node as NodeModel, TaskInstance, TaskInstanceEdge, TaskInstanceNode, TaskOrder
from services.port_plan import extract_host_ports, format_service_url, get_business_address


def routing_result(order: TaskOrder) -> dict[str, Any]:
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    result = config.get("routing_result")
    return result if isinstance(result, dict) else {}


def network_ready_required(order: TaskOrder | None) -> bool:
    if order is None:
        return False
    result = routing_result(order)
    return bool(result.get("network_ready_required")) and not bool(result.get("network_ready"))


async def instance_waiting_for_network_ready(db: AsyncSession, instance_id: str) -> TaskOrder | None:
    result = await db.execute(
        select(TaskOrder).where(
            TaskOrder.materialized_instance_id == instance_id,
            TaskOrder.routing_status == RoutingStatus.NETWORK_BINDING_READY.value,
        )
    )
    order = result.scalar_one_or_none()
    if order and network_ready_required(order):
        return order
    return None


def _port_map(node: TaskInstanceNode) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, raw in (node.port_values or {}).items():
        try:
            result[str(name)] = int(raw)
        except (TypeError, ValueError):
            continue
    if result:
        return result
    ports = extract_host_ports(node.ports, node.network_mode or "host")
    if len(ports) == 1:
        return {"default": ports[0]}
    return {str(port): port for port in ports}


def _role_for_node(node: TaskInstanceNode) -> str:
    env = node.env if isinstance(node.env, dict) else {}
    role = env.get("TASK_ROLE") or node.name
    return str(role or "").lower()


def _business_task_type(order: TaskOrder) -> str | None:
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        value = business_task.get("task_type")
        return str(value) if value else None
    return None


def _routing_priority(order: TaskOrder) -> int | None:
    dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    raw_priority = dag.get("priority")
    try:
        return int(raw_priority) if raw_priority is not None else None
    except (TypeError, ValueError):
        return None


def _routing_modality(order: TaskOrder) -> str | None:
    dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    value = dag.get("modal") or dag.get("modality")
    return str(value) if value else None


def _dag_edge_map(order: TaskOrder) -> dict[tuple[str, str], dict[str, Any]]:
    dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    edges = dag.get("edges")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(edges, list):
        return result
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or "").lower()
        dst = str(edge.get("to") or "").lower()
        if src and dst:
            result[(src, dst)] = edge
    return result


def _dag_nodes_by_role(order: TaskOrder) -> dict[str, dict[str, Any]]:
    dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    nodes = dag.get("nodes")
    if not isinstance(nodes, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for key in (node.get("task_node_id"), node.get("task_role")):
            if key:
                result[str(key).lower()] = node
    return result


def _placement_map(order: TaskOrder) -> dict[str, dict[str, Any]]:
    result = routing_result(order)
    placements = result.get("placements")
    if not isinstance(placements, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        role = str(placement.get("task_node_id") or "").lower()
        if role:
            mapped[role] = placement
    return mapped


def _fixed_topology_name(order: TaskOrder, role: str, dag_nodes: dict[str, dict[str, Any]]) -> str | None:
    placement = _placement_map(order).get(role) or {}
    value = placement.get("topology_node_id")
    if value:
        return str(value)
    dag_node = dag_nodes.get(role) or {}
    value = dag_node.get("fixed_topology_node_id")
    if value:
        return str(value)
    if role == "source" and order.source_name:
        return str(order.source_name)
    if role == "sink" and order.destination_name:
        return str(order.destination_name)
    return None


def _dag_node_port(role: str, dag_nodes: dict[str, dict[str, Any]]) -> int | None:
    dag_node = dag_nodes.get(role) or {}
    value = dag_node.get("business_port")
    try:
        port = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if port is None or port < 1 or port > 65535:
        return None
    return port


def _external_callback_url(order: TaskOrder, role: str, dag_nodes: dict[str, dict[str, Any]]) -> str | None:
    dag_node = dag_nodes.get(role) or {}
    value = dag_node.get("callback_url")
    if value:
        return str(value)

    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    deployment = config.get("platform_deployment") if isinstance(config.get("platform_deployment"), dict) else {}
    endpoints = deployment.get("external_endpoints") if isinstance(deployment.get("external_endpoints"), dict) else {}
    endpoint = endpoints.get(role) if isinstance(endpoints.get(role), dict) else {}
    value = endpoint.get("callback_url")
    if value:
        return str(value)

    business_task = config.get("business_task") if isinstance(config.get("business_task"), dict) else {}
    value = business_task.get("callback_url") if role == "sink" else None
    return str(value) if value else None


def _binding_for_roles(
    *,
    order: TaskOrder,
    src_role: str,
    dst_role: str,
    dag_edge: dict[str, Any],
    priority: int | None,
    modality: str | None,
    task_type: str | None,
    role_nodes: dict[str, TaskInstanceNode],
    machines_by_id: dict[str, NodeModel],
    machines_by_hostname: dict[str, NodeModel],
    dag_nodes: dict[str, dict[str, Any]],
    binding_source: str,
) -> dict[str, Any] | None:
    src_node = role_nodes.get(src_role)
    dst_node = role_nodes.get(dst_role)
    src_machine = machines_by_id.get(src_node.node_id) if src_node else None
    dst_machine = machines_by_id.get(dst_node.node_id) if dst_node else None

    src_topology = (
        src_machine.topology_node_id or src_machine.hostname
        if src_machine
        else _fixed_topology_name(order, src_role, dag_nodes)
    )
    dst_topology = (
        dst_machine.topology_node_id or dst_machine.hostname
        if dst_machine
        else _fixed_topology_name(order, dst_role, dag_nodes)
    )
    if not src_machine and src_topology:
        src_machine = machines_by_hostname.get(src_topology)
    if not dst_machine and dst_topology:
        dst_machine = machines_by_hostname.get(dst_topology)

    port_map = _port_map(dst_node) if dst_node else {}
    external_dst_port = _dag_node_port(dst_role, dag_nodes) if dst_node is None else None
    if external_dst_port is not None:
        port_map = {"external": external_dst_port}
    dst_ports = sorted(set(port_map.values()))
    primary_port = dst_ports[0] if dst_ports else None
    flow = dag_edge.get("flow") if isinstance(dag_edge.get("flow"), dict) else {}
    dst_ip = get_business_address(dst_machine, settings.prefer_business_ipv6) if dst_machine else None
    src_ip = get_business_address(src_machine, settings.prefer_business_ipv6) if src_machine else None
    src_callback_url = _external_callback_url(order, src_role, dag_nodes) if src_node is None else None
    dst_callback_url = _external_callback_url(order, dst_role, dag_nodes) if dst_node is None else None
    dst_access_url = (
        dst_callback_url
        or (format_service_url(dst_ip, primary_port) if dst_ip and primary_port else None)
    )

    binding = {
        "flow_id": flow.get("flow_id") or f"{order.id}:{src_role}->{dst_role}",
        "from": src_role,
        "to": dst_role,
        "task_type": task_type,
        "modal": modality,
        "priority": priority,
        "src_topology_node_id": src_topology,
        "src_host": src_machine.hostname if src_machine else src_topology,
        "src_ip": src_ip,
        "dst_topology_node_id": dst_topology,
        "dst_host": dst_machine.hostname if dst_machine else dst_topology,
        "dst_ip": dst_ip,
        "dst_port": primary_port,
        "dst_ports": dst_ports,
        "dst_named_ports": port_map,
        "dst_port_ref": flow.get("dst_port_ref") or f"{dst_role}.{next(iter(port_map), 'default')}",
        "dst_access_url": dst_access_url,
        "src_callback_url": src_callback_url,
        "dst_callback_url": dst_callback_url,
        "protocol": flow.get("protocol") or "tcp",
        "data_mb": dag_edge.get("data_mb"),
        "bandwidth_mbps": dag_edge.get("bandwidth_mbps"),
        "src_external": src_node is None,
        "dst_external": dst_node is None,
        "binding_source": binding_source,
    }
    if not any(binding.get(key) for key in ("src_host", "src_ip", "dst_host", "dst_ip", "dst_port")):
        return None
    return binding


async def build_network_bindings(
    db: AsyncSession,
    order: TaskOrder,
    instance: TaskInstance,
) -> list[dict[str, Any]]:
    """Return actual host/IP/port bindings for each routed business flow."""
    edge_rows = await db.execute(
        select(TaskInstanceEdge).where(TaskInstanceEdge.instance_id == instance.id)
    )
    edges = edge_rows.scalars().all()
    nodes_by_id = {node.id: node for node in instance.nodes}
    role_by_node_id = {node.id: _role_for_node(node) for node in instance.nodes}

    node_ids = {node.node_id for node in instance.nodes}
    if node_ids:
        machine_rows = await db.execute(select(NodeModel).where(NodeModel.id.in_(node_ids)))
        machines = {machine.id: machine for machine in machine_rows.scalars().all()}
    else:
        machines = {}

    dag_edges = _dag_edge_map(order)
    dag_nodes = _dag_nodes_by_role(order)
    priority = _routing_priority(order)
    modality = _routing_modality(order)
    task_type = _business_task_type(order)
    bindings: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    role_nodes = {_role_for_node(node): node for node in instance.nodes}

    endpoint_names = {
        name
        for role in dag_nodes
        for name in [_fixed_topology_name(order, role, dag_nodes)]
        if name
    }
    if endpoint_names:
        endpoint_rows = await db.execute(
            select(NodeModel).where(
                or_(
                    NodeModel.hostname.in_(endpoint_names),
                    NodeModel.topology_node_id.in_(endpoint_names),
                )
            )
        )
        machines_by_hostname = {}
        for machine in endpoint_rows.scalars().all():
            machines_by_hostname[machine.hostname] = machine
            if machine.topology_node_id:
                machines_by_hostname[machine.topology_node_id] = machine
    else:
        machines_by_hostname = {}

    for edge in edges:
        src_node = nodes_by_id.get(edge.from_node_id)
        dst_node = nodes_by_id.get(edge.to_node_id)
        if not src_node or not dst_node:
            continue
        src_role = role_by_node_id.get(src_node.id, src_node.name)
        dst_role = role_by_node_id.get(dst_node.id, dst_node.name)
        dag_edge = dag_edges.get((src_role, dst_role), {})
        binding = _binding_for_roles(
            order=order,
            src_role=src_role,
            dst_role=dst_role,
            dag_edge=dag_edge,
            priority=priority,
            modality=modality,
            task_type=task_type,
            role_nodes=role_nodes,
            machines_by_id=machines,
            machines_by_hostname=machines_by_hostname,
            dag_nodes=dag_nodes,
            binding_source="instance_edge",
        )
        if binding:
            bindings.append(binding)
            seen_edges.add((src_role, dst_role))

    for (src_role, dst_role), dag_edge in dag_edges.items():
        if (src_role, dst_role) in seen_edges:
            continue
        binding = _binding_for_roles(
            order=order,
            src_role=src_role,
            dst_role=dst_role,
            dag_edge=dag_edge,
            priority=priority,
            modality=modality,
            task_type=task_type,
            role_nodes=role_nodes,
            machines_by_id=machines,
            machines_by_hostname=machines_by_hostname,
            dag_nodes=dag_nodes,
            binding_source="routing_dag",
        )
        if binding:
            bindings.append(binding)
    return bindings


def mark_network_binding_ready(order: TaskOrder, bindings: list[dict[str, Any]], *, require_ready: bool) -> None:
    config = dict(order.runtime_config or {})
    result = dict(config.get("routing_result") or {})
    result["network_bindings"] = bindings
    result["network_binding_status"] = "ready"
    result["network_bindings_ready_at"] = datetime.utcnow().isoformat()
    result["network_ready_required"] = bool(require_ready)
    result["network_ready"] = not require_ready
    config["routing_result"] = result
    order.runtime_config = config


def mark_network_ready(order: TaskOrder, metadata: dict[str, Any] | None = None) -> None:
    config = dict(order.runtime_config or {})
    result = dict(config.get("routing_result") or {})
    result["network_ready"] = True
    result["network_ready_at"] = datetime.utcnow().isoformat()
    if metadata:
        result["network_ready_metadata"] = metadata
    config["routing_result"] = result
    order.runtime_config = config
