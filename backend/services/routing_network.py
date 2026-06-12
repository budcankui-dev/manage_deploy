"""Routing/network readiness helpers.

External routers need actual container ports before programming flow rules.
The platform can only allocate those ports after placements are known and the
task instance has been materialized, so this module keeps that handoff explicit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from enums import RoutingStatus
from models import Node as NodeModel, TaskInstance, TaskInstanceEdge, TaskInstanceNode, TaskOrder
from services.port_plan import extract_host_ports, get_business_address


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
    priority = _routing_priority(order)
    modality = _routing_modality(order)
    task_type = _business_task_type(order)
    bindings: list[dict[str, Any]] = []

    for edge in edges:
        src_node = nodes_by_id.get(edge.from_node_id)
        dst_node = nodes_by_id.get(edge.to_node_id)
        if not src_node or not dst_node:
            continue
        src_role = role_by_node_id.get(src_node.id, src_node.name)
        dst_role = role_by_node_id.get(dst_node.id, dst_node.name)
        src_machine = machines.get(src_node.node_id)
        dst_machine = machines.get(dst_node.node_id)
        if not dst_machine:
            continue

        dag_edge = dag_edges.get((src_role, dst_role), {})
        flow = dag_edge.get("flow") if isinstance(dag_edge.get("flow"), dict) else {}
        port_map = _port_map(dst_node)
        dst_ports = sorted(set(port_map.values()))
        primary_port = dst_ports[0] if dst_ports else None
        dst_address = get_business_address(dst_machine, settings.prefer_business_ipv6)

        bindings.append(
            {
                "flow_id": flow.get("flow_id") or f"{order.id}:{src_role}->{dst_role}",
                "from": src_role,
                "to": dst_role,
                "task_type": task_type,
                "modal": modality,
                "priority": priority,
                "src_topology_node_id": src_machine.hostname if src_machine else None,
                "src_host": src_machine.hostname if src_machine else None,
                "src_ip": get_business_address(src_machine, settings.prefer_business_ipv6) if src_machine else None,
                "dst_topology_node_id": dst_machine.hostname,
                "dst_host": dst_machine.hostname,
                "dst_ip": dst_address,
                "dst_port": primary_port,
                "dst_ports": dst_ports,
                "dst_named_ports": port_map,
                "dst_port_ref": flow.get("dst_port_ref") or f"{dst_role}.{next(iter(port_map), 'default')}",
                "protocol": flow.get("protocol") or "tcp",
                "data_mb": dag_edge.get("data_mb"),
                "bandwidth_mbps": dag_edge.get("bandwidth_mbps"),
            }
        )
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
