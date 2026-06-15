#!/usr/bin/env python3
"""Register or update topology nodes from ops/inventory/topology_nodes.json.

The inventory intentionally does not contain passwords.  Authenticate to the
manager API with MANAGER_USERNAME / MANAGER_PASSWORD or MANAGER_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "ops" / "inventory" / "topology_nodes.json"


def _request(
    method: str,
    url: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    if not body:
        return None
    return json.loads(body.decode())


def _login(api_base: str) -> str:
    token = os.environ.get("MANAGER_TOKEN")
    if token:
        return token
    username = os.environ.get("MANAGER_USERNAME", "admin")
    password = os.environ.get("MANAGER_PASSWORD")
    if not password:
        raise SystemExit("Set MANAGER_PASSWORD or MANAGER_TOKEN before registering nodes")
    result = _request(
        "POST",
        f"{api_base}/api/auth/login",
        payload={"username": username, "password": password},
    )
    return result["access_token"]


def _node_payload(item: dict[str, Any], registry_host: str | None = None) -> dict[str, Any]:
    management_ip = item["management_ip"]
    agent_port = int(item.get("agent_port") or 8001)
    payload = {
        "hostname": item["hostname"],
        "display_name": item.get("display_name"),
        "topology_node_id": item.get("topology_node_id"),
        "topology_zone": item.get("topology_zone"),
        "agent_address": item.get("agent_address") or f"http://{management_ip}:{agent_port}",
        "management_ip": management_ip,
        "business_ip": item.get("business_ip") or management_ip,
        "business_ipv6": item.get("business_ipv6"),
        "node_kind": item.get("node_kind") or "terminal",
        "gpu_count": int(item.get("gpu_count") or 0),
        "gpu_model": item.get("gpu_model"),
        "gpu_memory_mb": item.get("gpu_memory_mb"),
        "cpu_model": item.get("cpu_model"),
        "cpu_cores": item.get("cpu_cores"),
        "memory_mb": item.get("memory_mb"),
        "driver_version": item.get("driver_version"),
        "cuda_version": item.get("cuda_version"),
        "resource_note": item.get("resource_note")
        or f"拓扑区域 {item.get('topology_zone') or '-'}；当前使用 10.112 IPv4，后续业务面网络变更时更新 business_ip/business_ipv6。",
        "is_schedulable": bool(item.get("is_schedulable", True)),
        "is_routable": bool(item.get("is_routable", True)),
    }
    if registry_host:
        payload["resource_note"] = f"{payload['resource_note']} 私有仓库：{registry_host}"
    return payload


def _load_inventory(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Register topology nodes in the manager API")
    parser.add_argument("--api-base", default=os.environ.get("MANAGER_API_BASE", "http://10.112.244.94:8181"))
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--include-compute", action="store_true", help="also upsert compute_nodes from inventory")
    parser.add_argument("--include-admin", action="store_true", help="also upsert manager node from inventory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    inventory = _load_inventory(args.inventory)
    registry = os.environ.get("PRIVATE_REGISTRY", "10.112.244.94:5000")
    items: list[dict[str, Any]] = list(inventory.get("terminal_nodes") or [])
    if args.include_compute:
        items.extend(inventory.get("compute_nodes") or [])
    if args.include_admin and isinstance(inventory.get("manager"), dict):
        items.append(inventory["manager"])

    if args.dry_run:
        print(json.dumps([_node_payload(item, registry) for item in items], ensure_ascii=False, indent=2))
        return 0

    token = _login(args.api_base.rstrip("/"))
    nodes = _request("GET", f"{args.api_base.rstrip('/')}/api/nodes", token=token)
    by_hostname = {item["hostname"]: item for item in nodes}

    for item in items:
        payload = _node_payload(item, registry)
        existing = by_hostname.get(payload["hostname"])
        if existing:
            result = _request(
                "PUT",
                f"{args.api_base.rstrip('/')}/api/nodes/{existing['id']}",
                token=token,
                payload=payload,
            )
            action = "updated"
        else:
            result = _request("POST", f"{args.api_base.rstrip('/')}/api/nodes", token=token, payload=payload)
            action = "created"
        print(f"{action}: {result['hostname']} {result.get('management_ip')} {result.get('node_kind')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
