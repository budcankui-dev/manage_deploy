#!/usr/bin/env python3
"""Deploy Portainer Agent containers through existing Node Agent APIs.

The script intentionally avoids SSH and host networking changes.  It talks to
the already-running manage_deploy Node Agent on each worker/terminal node and
starts one helper container named ``portainer-mgmt_agent``.
"""

from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "ops" / "inventory" / "topology_nodes.json"
DEFAULT_IMAGE = "172.16.0.254:5000/portainer-agent:latest"
DEFAULT_TASK_ID = "portainer-mgmt"
DEFAULT_NODE_ID = "agent"
DEFAULT_AGENT_PORT = 8001
DEFAULT_PORTAINER_AGENT_PORT = 9001


@dataclass(frozen=True)
class Node:
    hostname: str
    management_ip: str
    agent_port: int
    docker_root_dir: str | None = None


def load_inventory(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_nodes(inventory: dict[str, Any], *, include_manager: bool = False) -> list[Node]:
    items: list[dict[str, Any]] = []
    if include_manager and inventory.get("manager"):
        items.append(inventory["manager"])
    items.extend(inventory.get("compute_nodes") or [])
    items.extend(inventory.get("terminal_nodes") or [])

    nodes: list[Node] = []
    for item in items:
        hostname = str(item.get("hostname") or "").strip()
        management_ip = str(
            item.get("acceptance_management_ip") or item.get("management_ip") or ""
        ).strip()
        if not hostname or not management_ip:
            continue
        nodes.append(
            Node(
                hostname=hostname,
                management_ip=management_ip,
                agent_port=int(item.get("agent_port") or DEFAULT_AGENT_PORT),
                docker_root_dir=item.get("docker_root_dir"),
            )
        )
    return nodes


def volumes_path_for_docker_root(docker_root_dir: str | None) -> str:
    root = str(docker_root_dir or "/var/lib/docker").rstrip("/")
    return f"{root}/volumes"


def start_payload(
    *,
    image: str,
    host_port: int,
    docker_root_dir: str | None,
    pull_policy: str,
) -> dict[str, Any]:
    return {
        "image": image,
        "env": {"EDGE": "0"},
        "ports": {str(DEFAULT_PORTAINER_AGENT_PORT): str(host_port)},
        "volume_mounts": [
            {
                "target": "/var/run/docker.sock",
                "type": "bind",
                "source": "/var/run/docker.sock",
                "auto_create": False,
            },
            {
                "target": "/var/lib/docker/volumes",
                "type": "bind",
                "source": volumes_path_for_docker_root(docker_root_dir),
                "auto_create": False,
            },
        ],
        "network_mode": "bridge",
        "restart_policy": "always",
        "pull_policy": pull_policy,
    }


def request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body) if body else {}


def container_status(node: Node, *, task_id: str, node_id: str, timeout: int) -> str:
    url = f"http://{node.management_ip}:{node.agent_port}/containers/{task_id}/{node_id}/status"
    try:
        data = request_json(url, timeout=timeout)
    except Exception as exc:
        return f"error:{type(exc).__name__}:{exc}"
    return str(data.get("status") or "unknown")


def deploy_node(
    node: Node,
    *,
    image: str,
    host_port: int,
    task_id: str,
    node_id: str,
    pull_policy: str,
    timeout: int,
    dry_run: bool,
    force_recreate: bool,
) -> tuple[bool, str]:
    payload = start_payload(
        image=image,
        host_port=host_port,
        docker_root_dir=node.docker_root_dir,
        pull_policy=pull_policy,
    )
    url = f"http://{node.management_ip}:{node.agent_port}/containers/{task_id}/{node_id}/start"
    if dry_run:
        return True, f"DRY_RUN {url} {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"

    try:
        if force_recreate:
            delete_url = f"http://{node.management_ip}:{node.agent_port}/containers/{task_id}/{node_id}"
            try:
                request_json(delete_url, method="DELETE", timeout=timeout)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        data = request_json(url, method="POST", payload=payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code} {detail}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"container_id={data.get('container_id')}"


def check_tcp(host: str, port: int, timeout: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Portainer Agents on acceptance topology nodes")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--host-port", type=int, default=DEFAULT_PORTAINER_AGENT_PORT)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--pull-policy", choices=["always", "missing", "never"], default="always")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Delete the managed Portainer Agent container before starting it again.",
    )
    args = parser.parse_args()

    nodes = inventory_nodes(load_inventory(args.inventory))
    failures = 0
    for node in nodes:
        if args.check_only:
            reachable = check_tcp(node.management_ip, args.host_port, timeout=min(args.timeout, 5))
            status = container_status(node, task_id=args.task_id, node_id=args.node_id, timeout=min(args.timeout, 5))
            ok = reachable and status == "running"
            failures += 0 if ok else 1
            print(f"{'OK' if ok else 'FAIL'} {node.hostname} {node.management_ip}:{args.host_port} tcp={reachable} status={status}")
            continue

        ok, message = deploy_node(
            node,
            image=args.image,
            host_port=args.host_port,
            task_id=args.task_id,
            node_id=args.node_id,
            pull_policy=args.pull_policy,
            timeout=args.timeout,
            dry_run=args.dry_run,
            force_recreate=args.force_recreate,
        )
        failures += 0 if ok else 1
        print(f"{'OK' if ok else 'FAIL'} {node.hostname} {node.management_ip} {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
