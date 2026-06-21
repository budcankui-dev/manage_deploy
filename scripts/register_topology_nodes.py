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
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from services.deployment_profile import deployment_profile

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


def _profiled_value(item: dict[str, Any], key: str, profile: str) -> Any:
    if profile == "acceptance":
        profile_key = f"acceptance_{key}"
        if item.get(profile_key) is not None:
            return item.get(profile_key)
    return item.get(key)


def _node_payload(
    item: dict[str, Any],
    registry_host: str | None = None,
    *,
    network_profile: str = "acceptance",
) -> dict[str, Any]:
    management_ip = _profiled_value(item, "management_ip", network_profile)
    if not management_ip:
        raise ValueError(f"{item.get('hostname') or item!r} missing management_ip for {network_profile}")
    agent_port = int(item.get("agent_port") or 8001)
    business_ip = _profiled_value(item, "business_ip", network_profile) or management_ip
    business_ipv6 = _profiled_value(item, "business_ipv6", network_profile)
    agent_address = (
        _profiled_value(item, "agent_address", network_profile)
        or item.get("agent_address")
        or f"http://{management_ip}:{agent_port}"
    )
    profile_label = "验收网络" if network_profile == "acceptance" else "当前调试网络"
    payload = {
        "hostname": item["hostname"],
        "display_name": item.get("display_name"),
        "topology_node_id": item.get("topology_node_id"),
        "topology_zone": item.get("topology_zone"),
        "agent_address": agent_address,
        "management_ip": management_ip,
        "business_ip": business_ip,
        "business_ipv6": business_ipv6,
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
        or f"拓扑区域 {item.get('topology_zone') or '-'}；按 {profile_label} 注册，业务面优先使用 business_ipv6。",
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
    parser.add_argument(
        "--network-profile",
        default=os.environ.get("NETWORK_PROFILE", "acceptance"),
        help="acceptance/accept/prod uses 172.16 management and 3012 IPv6 fields when present; current/dev/campus uses 10.112 debug addresses",
    )
    parser.add_argument("--api-base")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--include-compute", action="store_true", help="also upsert compute_nodes from inventory")
    parser.add_argument("--include-admin", action="store_true", help="also upsert manager node from inventory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = deployment_profile(args.network_profile)
    network_profile = profile.name
    api_base = (args.api_base or profile.manager_api_base).rstrip("/")

    inventory = _load_inventory(args.inventory)
    registry = profile.registry
    items: list[dict[str, Any]] = list(inventory.get("terminal_nodes") or [])
    if args.include_compute:
        items.extend(inventory.get("compute_nodes") or [])
    if args.include_admin and isinstance(inventory.get("manager"), dict):
        items.append(inventory["manager"])

    if args.dry_run:
        print(
            json.dumps(
                [
                    _node_payload(item, registry, network_profile=network_profile)
                    for item in items
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    token = _login(api_base)
    nodes = _request("GET", f"{api_base}/api/nodes", token=token)
    by_hostname = {item["hostname"]: item for item in nodes}

    for item in items:
        payload = _node_payload(item, registry, network_profile=network_profile)
        existing = by_hostname.get(payload["hostname"])
        if existing:
            result = _request(
                "PUT",
                f"{api_base}/api/nodes/{existing['id']}",
                token=token,
                payload=payload,
            )
            action = "updated"
        else:
            result = _request("POST", f"{api_base}/api/nodes", token=token, payload=payload)
            action = "created"
        print(f"{action}: {result['hostname']} {result.get('management_ip')} {result.get('node_kind')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
