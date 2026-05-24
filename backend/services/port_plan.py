"""宿主机端口规划：提取、冲突检测、节点互访环境变量。"""

from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enums import TaskStatus
from models import Node as NodeModel, TaskInstance, TaskInstanceNode


def extract_host_ports(ports: Optional[dict], network_mode: str = "host") -> list[int]:
    if not ports:
        return []

    host_ports: list[int] = []
    seen: set[int] = set()
    for container_port, host_port in ports.items():
        raw = str(host_port).strip() if host_port is not None else ""
        if not raw and network_mode == "host":
            raw = str(container_port).strip()
        if not raw:
            continue
        try:
            port_num = int(raw)
        except ValueError:
            continue
        if port_num <= 0 or port_num > 65535 or port_num in seen:
            continue
        seen.add(port_num)
        host_ports.append(port_num)
    return sorted(host_ports)


def extract_ports_from_values(port_values: Optional[dict]) -> list[int]:
    if not port_values:
        return []
    ports: list[int] = []
    seen: set[int] = set()
    for raw in port_values.values():
        try:
            port_num = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= port_num <= 65535 and port_num not in seen:
            seen.add(port_num)
            ports.append(port_num)
    return sorted(ports)


def sanitize_env_key(name: str) -> str:
    key = re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).upper().strip("_")
    return key or "NODE"


def get_business_address(machine: NodeModel, prefer_ipv6: bool = True) -> str:
    """业务互访地址：验收/生产优先 IPv6，开发可回退 IPv4。"""
    ipv6 = (getattr(machine, "business_ipv6", None) or "").strip()
    if prefer_ipv6 and ipv6:
        return ipv6
    return machine.business_ip


def format_service_url(business_address: str, port: int) -> str:
    if ":" in business_address and not business_address.startswith("["):
        host = f"[{business_address}]"
    else:
        host = business_address
    return f"http://{host}:{port}"


def build_local_port_env(role_name: str, port_values: Optional[dict]) -> dict[str, str]:
    """本节点命名端口 → PORT_API=8080 / SOURCE_PORT_API=8080。"""
    env: dict[str, str] = {}
    role = sanitize_env_key(role_name)
    for var_name, raw in (port_values or {}).items():
        try:
            port = int(raw)
        except (TypeError, ValueError):
            continue
        var_key = sanitize_env_key(str(var_name))
        port_text = str(port)
        env[f"PORT_{var_key}"] = port_text
        env[f"{role}_PORT_{var_key}"] = port_text
    return env


def _peer_port_map(peer: TaskInstanceNode) -> dict[str, int]:
    if peer.port_values:
        result: dict[str, int] = {}
        for name, raw in peer.port_values.items():
            try:
                result[str(name)] = int(raw)
            except (TypeError, ValueError):
                continue
        if result:
            return result
    host_ports = extract_host_ports(peer.ports, peer.network_mode or "host")
    if not host_ports:
        return {}
    if len(host_ports) == 1:
        return {"default": host_ports[0]}
    return {str(port): port for port in host_ports}


def build_peer_env_for_node(
    current: TaskInstanceNode,
    peers: list[TaskInstanceNode],
    machines: dict[str, NodeModel],
    prefer_ipv6: bool = True,
) -> dict[str, str]:
    """为当前节点生成同任务其他节点的 PEER_* 环境变量（URL 用业务 IPv6 优先）。"""
    env: dict[str, str] = {}
    peer_payload: list[dict] = []

    for peer in peers:
        if peer.id == current.id:
            continue

        machine = machines.get(peer.node_id)
        if not machine:
            continue

        role = sanitize_env_key(peer.name)
        business_addr = get_business_address(machine, prefer_ipv6)
        named_ports = _peer_port_map(peer)
        host_ports = sorted(set(named_ports.values()))
        primary = str(host_ports[0]) if host_ports else ""

        env[f"PEER_{role}_HOST"] = business_addr
        env[f"PEER_{role}_BUSINESS_IP"] = machine.business_ip
        if getattr(machine, "business_ipv6", None):
            env[f"PEER_{role}_BUSINESS_IPV6"] = machine.business_ipv6
        if primary:
            env[f"PEER_{role}_PORT"] = primary
        if host_ports:
            env[f"PEER_{role}_PORTS"] = ",".join(str(p) for p in host_ports)
        if primary:
            env[f"PEER_{role}_URL"] = format_service_url(business_addr, host_ports[0])

        for var_name, port in named_ports.items():
            var_key = sanitize_env_key(var_name)
            env[f"PEER_{role}_PORT_{var_key}"] = str(port)
            env[f"PEER_{role}_URL_{var_key}"] = format_service_url(business_addr, port)

        peer_payload.append(
            {
                "name": peer.name,
                "role": role,
                "business_ip": machine.business_ip,
                "business_ipv6": getattr(machine, "business_ipv6", None),
                "business_address": business_addr,
                "ports": host_ports,
                "named_ports": named_ports,
                "primary_port": host_ports[0] if host_ports else None,
                "network_mode": peer.network_mode,
            }
        )

    if peer_payload:
        env["TASK_PEERS_JSON"] = json.dumps(peer_payload, ensure_ascii=False)
    return env


async def find_running_port_conflicts(
    db: AsyncSession,
    node_plans: list[dict],
    exclude_instance_id: Optional[str] = None,
) -> list[str]:
    active_statuses = (TaskStatus.RUNNING, TaskStatus.STARTING)
    messages: list[str] = []

    for plan in node_plans:
        worker_id = plan.get("node_id")
        ports = plan.get("ports") or {}
        if not worker_id or not ports:
            continue

        requested = {str(p) for p in extract_host_ports(ports, plan.get("network_mode") or "host")}
        if not requested:
            continue

        stmt = (
            select(TaskInstanceNode, TaskInstance)
            .join(TaskInstance, TaskInstance.id == TaskInstanceNode.instance_id)
            .where(
                TaskInstanceNode.node_id == worker_id,
                TaskInstance.status.in_(active_statuses),
            )
        )
        if exclude_instance_id:
            stmt = stmt.where(TaskInstance.id != exclude_instance_id)

        result = await db.execute(stmt)
        for existing_node, existing_instance in result.all():
            existing_ports = {
                str(p)
                for p in extract_host_ports(existing_node.ports, existing_node.network_mode or "host")
            }
            overlap = requested & existing_ports
            if not overlap:
                continue
            ports_text = ",".join(sorted(overlap))
            messages.append(
                f"Worker {worker_id} 端口 {ports_text} 已被运行中实例 "
                f"「{existing_instance.name}」节点「{existing_node.name}」占用"
            )

    return messages
