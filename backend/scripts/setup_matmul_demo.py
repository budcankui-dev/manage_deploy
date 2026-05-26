#!/usr/bin/env python3
"""Prepare the scientific matmul demo nodes, template, and catalog entry."""

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402

WORKER_TAG = os.environ.get("WORKER_TAG", "dev")
MATMUL_IMAGE = f"manage-deploy/scientific-matmul:{WORKER_TAG}"

SOURCE_PORT = 18801
COMPUTE_PORT = 18802
SINK_PORT = 18803

PORT_HC_SOURCE = {"type": "port", "port": SOURCE_PORT, "timeout": 120, "interval": 2, "retry": 30}
PORT_HC_COMPUTE = {"type": "port", "port": COMPUTE_PORT, "timeout": 300, "interval": 3, "retry": 40}
PORT_HC_SINK = {"type": "port", "port": SINK_PORT, "timeout": 300, "interval": 3, "retry": 40}

# 开发：三台逻辑 worker 同机，业务 IPv4 与管理面一致（host 网络下容器互访本机）
DEV_BUSINESS_IP = os.environ.get("DEV_BUSINESS_IP", "127.0.0.1")


async def setup_demo(base_url: str | None = None) -> dict:
    """默认 HTTP 调正在运行的 Manager，与 E2E/手工联调同一库。SETUP_USE_ASGI=1 时走内存 ASGI。"""
    base_url = (
        base_url
        or os.environ.get("DEMO_BASE_URL")
        or os.environ.get("SEED_BASE_URL", "http://127.0.0.1:8000")
    )
    use_asgi = (
        os.environ.get("SETUP_USE_ASGI", "") or os.environ.get("SEED_USE_ASGI", "")
    ).lower() in ("1", "true", "yes")

    if use_asgi:
        from database import init_db  # noqa: E402
        import models  # noqa: F401,E402
        from main import app  # noqa: E402

        await init_db()
        transport = ASGITransport(app=app)
        client_ctx = AsyncClient(transport=transport, base_url=base_url)
    else:
        client_ctx = AsyncClient(base_url=base_url, timeout=60.0)

    async with client_ctx as client:
        hostnames = ["demo-worker-a", "demo-worker-b", "demo-worker-c"]
        listed = await client.get("/api/nodes")
        listed.raise_for_status()
        by_host = {item["hostname"]: item["id"] for item in listed.json()}
        node_ids = []
        for hostname in hostnames:
            if hostname in by_host:
                node_ids.append(by_host[hostname])
                continue
            response = await client.post(
                "/api/nodes",
                json={
                    "hostname": hostname,
                    "agent_address": "http://127.0.0.1:8001",
                    "management_ip": DEV_BUSINESS_IP,
                    "business_ip": DEV_BUSINESS_IP,
                },
            )
            response.raise_for_status()
            node_ids.append(response.json()["id"])

        matmul_template = {
            "name": "scientific-matmul-demo",
            "description": "Scientific computing demo: source/compute/sink matrix multiplication over HTTP",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": MATMUL_IMAGE,
                    "command": "python /app/src/source_main.py",
                    "port_defs": [
                        {"name": "source", "label": "source HTTP", "default": SOURCE_PORT}
                    ],
                    "node_id": node_ids[0],
                    "restart_policy": "no",
                    "health_check": PORT_HC_SOURCE,
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": MATMUL_IMAGE,
                    "command": "python /app/src/compute_main.py",
                    "port_defs": [
                        {"name": "compute", "label": "compute HTTP", "default": COMPUTE_PORT}
                    ],
                    "node_id": node_ids[1],
                    "restart_policy": "no",
                    "health_check": PORT_HC_COMPUTE,
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": MATMUL_IMAGE,
                    "command": "python /app/src/sink_main.py",
                    "port_defs": [
                        {"name": "sink", "label": "sink HTTP", "default": SINK_PORT}
                    ],
                    "node_id": node_ids[2],
                    "restart_policy": "no",
                    "health_check": PORT_HC_SINK,
                },
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        }

        async def ensure_template(payload: dict) -> str:
            response = await client.post("/api/templates", json=payload)
            if response.status_code == 409:
                existing = await client.get("/api/templates")
                for item in existing.json():
                    if item["name"] == payload["name"]:
                        return item["id"]
                raise RuntimeError(f"template exists but not found: {payload['name']}")
            response.raise_for_status()
            return response.json()["id"]

        matmul_template_id = await ensure_template(matmul_template)

        catalogs = [
            {
                "task_type": "high_throughput_matmul",
                "modality": "high_throughput_compute",
                "template_id": matmul_template_id,
            },
        ]

        created_catalogs = []
        for item in catalogs:
            response = await client.put(
                f"/api/business-template-catalog/{item['task_type']}",
                json=item,
            )
            response.raise_for_status()
            created_catalogs.append(response.json())

        return {
            "node_ids": node_ids,
            "matmul_template_id": matmul_template_id,
            "worker_image": MATMUL_IMAGE,
            "catalogs": created_catalogs,
        }


seed = setup_demo


def main() -> None:
    result = asyncio.run(setup_demo())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
