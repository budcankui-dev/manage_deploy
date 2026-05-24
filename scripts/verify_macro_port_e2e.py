#!/usr/bin/env python3
"""验收 macro_defs / port_defs / IPv6 PEER URL 与宏变量注入（需 backend:8000 + node agent:8001 + alpine 镜像）。"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
IMAGE = "alpine:latest"


def ok(name: str, detail: str = "") -> bool:
    print(f"  ✓ {name}" + (f" — {detail}" if detail else ""))
    return True


def fail(name: str, detail: str = "") -> bool:
    print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))
    return False


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120.0)
    failures: list[str] = []

    print("=== macro/port/IPv6 验收 ===\n")

    # workers
    workers = {}
    for idx, hostname in enumerate(["demo-worker-a", "demo-worker-b", "demo-worker-c"], start=1):
        r = client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "agent_address": "http://127.0.0.1:8001",
                "management_ip": f"192.168.1.{idx}",
                "business_ip": f"10.0.1.{idx}",
                "business_ipv6": f"2001:db8:1::{idx:x}",
            },
        )
        if r.status_code not in (200, 409):
            fail("register workers", r.text)
            return 1
        workers[hostname] = r.json()["id"]

    # template
    ts = int(time.time())
    tr = client.post(
        "/api/templates",
        json={
            "name": f"verify-macro-port-{ts}",
            "description": "verify script",
            "macro_defs": [
                {"name": "DB_URL", "label": "DB", "default": "postgres://db:5432/tasks"},
                {"name": "MINIO_ENDPOINT", "label": "MinIO", "default": "http://minio:9000"},
            ],
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": IMAGE,
                    "node_id": workers["demo-worker-a"],
                    "network_mode": "host",
                    "port_defs": [{"name": "api", "label": "API", "default": 9000}],
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": IMAGE,
                    "node_id": workers["demo-worker-b"],
                    "network_mode": "host",
                    "port_defs": [{"name": "api", "label": "API", "default": 8080}],
                },
                {"client_id": "sink", "name": "sink", "image": IMAGE, "node_id": workers["demo-worker-c"], "network_mode": "host"},
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        },
    )
    if tr.status_code != 200:
        fail("create template", tr.text)
        return 1
    template_id = tr.json()["id"]

    source_port = 29000 + (ts % 1000)
    compute_port = 28080 + (ts % 1000)

    payload = {
        "name": f"verify-run-{ts}",
        "template_id": template_id,
        "deployment_mode": "immediate",
        "auto_start": False,
        "macro_values": {
            "DB_URL": "postgres://10.0.1.100:5432/verify",
            "MINIO_ENDPOINT": "http://10.0.1.100:9000",
        },
        "node_overrides": [
            {
                "template_node_name": "source",
                "image": IMAGE,
                "command": "sleep 3600",
                "network_mode": "host",
                "port_values": {"api": source_port},
            },
            {
                "template_node_name": "compute",
                "image": IMAGE,
                "command": "sleep 3600",
                "network_mode": "host",
                "port_values": {"api": compute_port},
                "env": {"UPSTREAM": "${PEER_SOURCE_URL_API}"},
            },
        ],
    }

    pf = client.post("/api/instances/preflight", json=payload)
    if not pf.json().get("ok"):
        fail("preflight", str(pf.json().get("conflicts")))
        return 1
    ok("preflight")

    cr = client.post("/api/instances", json=payload)
    if cr.status_code != 200:
        fail("create instance", cr.text)
        return 1
    instance_id = cr.json()["id"]
    ok("create instance", instance_id)

    sr = client.post(f"/api/instances/{instance_id}/start")
    if sr.status_code != 200:
        fail("start instance", sr.text)
        return 1
    ok("start instance")

    time.sleep(3)
    inst = client.get(f"/api/instances/{instance_id}")
    if inst.status_code != 200:
        fail("get instance")
        return 1

    compute_node = next(n for n in inst.json()["nodes"] if n["name"] == "compute")
    cname = compute_node.get("container_name")
    if not cname:
        fail("compute container_name missing (is agent/docker up? alpine pulled?)")
        return 1

    raw = subprocess.check_output(
        ["docker", "inspect", cname, "--format", "{{json .Config.Env}}"],
        text=True,
    )
    env = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in json.loads(raw) if "=" in e}
    expected_url = f"http://[2001:db8:1::1]:{source_port}"
    checks = [
        ("DB_URL", "postgres://10.0.1.100:5432/verify"),
        ("MINIO_ENDPOINT", "http://10.0.1.100:9000"),
        ("PEER_SOURCE_HOST", "2001:db8:1::1"),
        ("PEER_SOURCE_URL_API", expected_url),
        ("UPSTREAM", expected_url),
        ("PORT_API", str(compute_port)),
    ]
    for key, exp in checks:
        if env.get(key) != exp:
            fail(f"env {key}", f"got {env.get(key)}")
            failures.append(key)

    # cleanup
    client.post(f"/api/instances/{instance_id}/stop")
    client.delete(f"/api/instances/{instance_id}")
    client.delete(f"/api/templates/{template_id}")

    print()
    if failures:
        print(f"\n失败 {len(failures)} 项: {', '.join(failures)}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
