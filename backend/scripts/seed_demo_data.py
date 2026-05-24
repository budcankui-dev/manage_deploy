#!/usr/bin/env python3
"""Seed demo nodes, templates, and business catalog entries."""

import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from main import app  # noqa: E402


async def seed(base_url: str = "http://127.0.0.1:8000") -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=base_url) as client:
        node_ids = []
        for idx, hostname in enumerate(["demo-worker-a", "demo-worker-b", "demo-worker-c"], start=1):
            response = await client.post(
                "/api/nodes",
                json={
                    "hostname": hostname,
                    "agent_address": "http://127.0.0.1:8001",
                    "management_ip": f"10.0.0.{idx}",
                    "business_ip": f"10.0.1.{idx}",
                },
            )
            if response.status_code == 409:
                nodes = await client.get("/api/nodes")
                node_ids = [item["id"] for item in nodes.json()[:3]]
                break
            response.raise_for_status()
            node_ids.append(response.json()["id"])

        templates = {
            "video": {
                "name": "demo-video-pipeline",
                "description": "A source -> B compute -> C sink",
                "nodes": [
                    {
                        "client_id": "source",
                        "name": "source",
                        "image": "busybox:latest",
                        "command": "sleep 3600",
                        "node_id": node_ids[0],
                    },
                    {
                        "client_id": "compute",
                        "name": "compute",
                        "image": "busybox:latest",
                        "command": "sleep 3600",
                        "node_id": node_ids[1],
                    },
                    {
                        "client_id": "sink",
                        "name": "sink",
                        "image": "busybox:latest",
                        "command": "sleep 3600",
                        "node_id": node_ids[2],
                    },
                ],
                "edges": [
                    {"from_node_id": "source", "to_node_id": "compute"},
                    {"from_node_id": "compute", "to_node_id": "sink"},
                ],
            }
        }

        template_response = await client.post("/api/templates", json=templates["video"])
        if template_response.status_code == 409:
            existing = await client.get("/api/templates")
            template_id = existing.json()[0]["id"]
        else:
            template_response.raise_for_status()
            template_id = template_response.json()["id"]

        catalogs = [
            {
                "task_type": "low_latency_video_pipeline",
                "modality": "low_latency_forwarding",
                "template_id": template_id,
            },
            {
                "task_type": "high_throughput_matmul",
                "modality": "high_throughput_compute",
                "template_id": template_id,
            },
            {
                "task_type": "llm_text_generation",
                "modality": "llm_inference",
                "template_id": template_id,
            },
        ]

        created_catalogs = []
        for item in catalogs:
            response = await client.post("/api/business-template-catalog", json=item)
            if response.status_code == 409:
                continue
            response.raise_for_status()
            created_catalogs.append(response.json())

        return {
            "node_ids": node_ids,
            "template_id": template_id,
            "catalogs": created_catalogs or catalogs,
        }


def main() -> None:
    result = asyncio.run(seed())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
