"""Build authenticated, order-specific instructions for user endpoint demos."""

from __future__ import annotations

import json
import shlex
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Node, TaskInstance, TaskOrder
from services.deployment_profile import image_ref
from services.port_plan import format_service_url, get_business_address


_TASK_CONFIG = {
    "high_throughput_matmul": {
        "label": "矩阵乘法计算任务",
        "endpoint_image": "scientific-matmul-endpoint",
        "receiver_port": 9000,
        "source_command": "python3 /app/src/source_main.py",
        "receiver_command": "python3 /app/src/receiver_main.py",
        "source_env": {"SOURCE_LISTEN": "false"},
    },
    "low_latency_video_pipeline": {
        "label": "视频AI推理任务",
        "endpoint_image": "low-latency-video-endpoint",
        "receiver_port": 9100,
        "source_command": "python3 /app/src/source_main.py",
        "receiver_command": "python3 /app/src/receiver_main.py",
        "source_env": {"SOURCE_LISTEN": "false", "WAIT_FOR_COMPUTE_READY": "false"},
    },
    "metaverse_video_fusion": {
        "label": "元宇宙沉浸式交互任务",
        "endpoint_image": "metaverse-video-fusion-endpoint",
        "receiver_port": 9200,
        "source_command": "python3 /app/src/source_main.py",
        "receiver_command": "python3 /app/src/receiver_main.py",
        # Source must remain reachable: Compute streams both MP4 inputs from
        # its /assets endpoint over the routed business plane.
        "source_env": {"PORT_SOURCE": "18821"},
    },
}


def _deployment_is_user_access_demo(order: TaskOrder) -> bool:
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    deployment = config.get("platform_deployment") if isinstance(config.get("platform_deployment"), dict) else {}
    roles = deployment.get("deployable_roles")
    return deployment.get("mode") == "user_access_demo" and {
        str(role).lower() for role in roles or []
    } == {"compute"}


def _shell_env(env: dict[str, Any]) -> str:
    return " ".join(
        f"-e {key}={shlex.quote(str(value))}"
        for key, value in env.items()
        if value is not None and value != ""
    )


def _docker_run(*, name: str, image: str, env: dict[str, Any], command: str, detached: bool) -> str:
    mode = "-d " if detached else "--rm "
    return (
        f"docker run {mode}--pull always --name {shlex.quote(name)} --network host "
        f"{_shell_env(env)} {shlex.quote(image)} {command}"
    )


def _endpoint_payload(node: Node | None, fallback: dict[str, Any], *, port: int | None = None) -> dict[str, Any]:
    management_ip = node.management_ip if node else fallback.get("management_ip")
    business_ip = node.business_ip if node else fallback.get("business_ip")
    business_ipv6 = node.business_ipv6 if node else fallback.get("business_ipv6")
    business_address = get_business_address(node, settings.prefer_business_ipv6) if node else (business_ipv6 or business_ip)
    topology_id = (
        (node.topology_node_id or node.hostname) if node else fallback.get("topology_node_id")
    )
    hostname = node.hostname if node else fallback.get("topology_alias") or topology_id
    ssh_user = settings.demo_terminal_ssh_user.strip()
    ssh_port = max(1, int(settings.demo_terminal_ssh_port or 22))
    return {
        "hostname": hostname,
        "topology_node_id": topology_id,
        "management_ip": management_ip,
        "business_ip": business_ip,
        "business_ipv6": business_ipv6,
        "business_address": business_address,
        "port": port,
        "ssh_user": ssh_user or None,
        "ssh_port": ssh_port if ssh_user and management_ip else None,
        "ssh_password": settings.demo_terminal_ssh_password or None,
        "ssh_command": f"ssh -p {ssh_port} {ssh_user}@{management_ip}" if ssh_user and management_ip else None,
    }


async def _load_endpoint_nodes(db: AsyncSession, endpoints: dict[str, dict[str, Any]]) -> dict[str, Node]:
    values: set[str] = set()
    for endpoint in endpoints.values():
        for key in ("topology_node_id", "topology_alias", "input_value"):
            if endpoint.get(key):
                values.add(str(endpoint[key]))
    if not values:
        return {}
    result = await db.execute(
        select(Node).where(or_(Node.hostname.in_(values), Node.topology_node_id.in_(values)))
    )
    nodes = result.scalars().all()
    return {
        value: node
        for node in nodes
        for value in (node.hostname, node.topology_node_id)
        if value
    }


def _binding(result: dict[str, Any], src: str, dst: str) -> dict[str, Any]:
    for item in result.get("network_bindings") or []:
        if isinstance(item, dict) and item.get("from") == src and item.get("to") == dst:
            return item
    return {}


async def build_user_access_guide(
    db: AsyncSession,
    order: TaskOrder,
    instance: TaskInstance | None,
    business_task: dict[str, Any] | None,
    routing_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a guide only for supported compute-only user-access work orders."""

    if not _deployment_is_user_access_demo(order) or not isinstance(business_task, dict):
        return None
    task_type = str(business_task.get("task_type") or "")
    task = _TASK_CONFIG.get(task_type)
    if not task:
        return None

    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    deployment = config.get("platform_deployment") if isinstance(config.get("platform_deployment"), dict) else {}
    raw_endpoints = deployment.get("external_endpoints") if isinstance(deployment.get("external_endpoints"), dict) else {}
    source_raw = raw_endpoints.get("source") if isinstance(raw_endpoints.get("source"), dict) else {}
    sink_raw = raw_endpoints.get("sink") if isinstance(raw_endpoints.get("sink"), dict) else {}
    endpoints = {"source": source_raw, "sink": sink_raw}
    nodes = await _load_endpoint_nodes(db, endpoints)
    source_node = next((nodes[key] for key in (source_raw.get("topology_node_id"), source_raw.get("topology_alias")) if key in nodes), None)
    sink_node = next((nodes[key] for key in (sink_raw.get("topology_node_id"), sink_raw.get("topology_alias")) if key in nodes), None)

    receiver_port = int(sink_raw.get("business_port") or task["receiver_port"])
    source = _endpoint_payload(source_node, source_raw)
    sink = _endpoint_payload(sink_node, sink_raw, port=receiver_port)
    receiver_url = format_service_url(sink["business_address"], receiver_port) if sink.get("business_address") else None
    image = image_ref(str(task["endpoint_image"]))
    short_order_id = order.id.replace("-", "")[:12]
    receiver_env = {
        "ENDPOINT_PORT": receiver_port,
        "ENDPOINT_NODE_ALIAS": sink.get("hostname"),
        "ENDPOINT_TOPOLOGY_NODE_ID": sink.get("topology_node_id"),
        "ENDPOINT_MANAGEMENT_IP": sink.get("management_ip"),
        "ENDPOINT_BUSINESS_IP": sink.get("business_ip"),
        "ENDPOINT_BUSINESS_IPV6": sink.get("business_ipv6"),
    }
    receiver_command = _docker_run(
        name=f"user-{short_order_id}-receiver",
        image=image,
        env=receiver_env,
        command=f"{task['receiver_command']} --port {receiver_port}",
        detached=True,
    )

    result = routing_result if isinstance(routing_result, dict) else {}
    compute_binding = _binding(result, "source", "compute")
    compute_url = str(compute_binding.get("dst_access_url") or "").rstrip("/") or None
    compute_ready = bool(instance and instance.status in {"running", "starting", "ready"})
    data_profile = business_task.get("data_profile") if isinstance(business_task.get("data_profile"), dict) else {}
    source_env = {
        "PEER_COMPUTE_URL": compute_url,
        "ORDER_ID": order.id,
        "TASK_INSTANCE_ID": instance.id if instance else None,
        "TASK_TYPE": task_type,
        "DATA_PROFILE": json.dumps(data_profile, ensure_ascii=False, separators=(",", ":")),
        **task["source_env"],
    }
    source_command = _docker_run(
        name=f"user-{short_order_id}-source",
        image=image,
        env=source_env,
        command=str(task["source_command"]),
        detached=False,
    ) if compute_url and instance and compute_ready else None

    return {
        "task_type": task_type,
        "task_label": task["label"],
        "image": image,
        "source": source,
        "sink": sink,
        "receiver_url": receiver_url,
        "receiver_command": receiver_command,
        "compute_url": compute_url,
        "compute_status": instance.status if instance else None,
        "compute_ready": compute_ready,
        "source_command": source_command,
        "source_waiting_reason": (
            None
            if source_command
            else (
                "计算服务接入地址已生成，等待平台启动计算容器。"
                if compute_url
                else "等待路由结果生成计算服务接入地址，并由平台启动计算容器。"
            )
        ),
        "result_hint": (
            "视频 receiver 页面会自动展示带框推理帧、检测类别、置信度与时延。"
            if task_type == "low_latency_video_pipeline"
            else (
                "元宇宙 Source 会向 Compute 流式提供两路视频；receiver 页面会展示融合结果和业务目标判定。"
                if task_type == "metaverse_video_fusion"
                else "receiver 页面会展示实际有效计算吞吐量、参数和业务目标判定。"
            )
        ),
    }
