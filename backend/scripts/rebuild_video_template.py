#!/usr/bin/env python3
"""Create/update the lightweight video inference template and catalog entry."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from httpx import AsyncClient

from rebuild_matmul_template import auto_port, get_compute_node_ids
from services.deployment_profile import image_repo

WORKER_TAG = os.environ.get("WORKER_TAG", "dev")
WORKER_IMAGE = os.environ.get("WORKER_IMAGE", image_repo("low-latency-video"))
ENDPOINT_WORKER_IMAGE = os.environ.get(
    "VIDEO_ENDPOINT_WORKER_IMAGE",
    image_repo("low-latency-video-endpoint"),
)

# Role-specific image overrides let source/sink run on small terminal disks
# while compute keeps the full CUDA/ONNX Runtime image. If no endpoint override
# is provided, the legacy single-image template is preserved.
COMPUTE_IMAGE_REPO = os.environ.get("VIDEO_COMPUTE_IMAGE", WORKER_IMAGE)
ENDPOINT_IMAGE_REPO = os.environ.get("VIDEO_ENDPOINT_IMAGE", ENDPOINT_WORKER_IMAGE)
VIDEO_COMPUTE_IMAGE = f"{COMPUTE_IMAGE_REPO}:{WORKER_TAG}"
VIDEO_ENDPOINT_IMAGE = f"{ENDPOINT_IMAGE_REPO}:{WORKER_TAG}"

SOURCE_PORT = 18811
COMPUTE_PORT = 18812
SINK_PORT = 18813


async def rebuild_video_template(base_url: str | None = None) -> dict:
    base_url = base_url or os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")
    node_ids = get_compute_node_ids()

    async with AsyncClient(base_url=base_url, timeout=60.0) as client:
        listed = await client.get("/api/templates")
        listed.raise_for_status()
        existing_templates = {item["name"]: item for item in listed.json()}

        template = {
            "name": "视频AI推理任务",
            "description": "Low latency video industrial-inspection surrogate over HTTP",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": VIDEO_ENDPOINT_IMAGE,
                    "command": "python3 /app/src/source_main.py",
                    "port_defs": [auto_port("source", "video source HTTP", SOURCE_PORT)],
                    "node_id": node_ids["compute-1"],
                    "restart_policy": "no",
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": VIDEO_COMPUTE_IMAGE,
                    "command": "python3 /app/src/compute_main.py",
                    "port_defs": [auto_port("compute", "video compute HTTP", COMPUTE_PORT)],
                    "node_id": node_ids["compute-2"],
                    "restart_policy": "no",
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": VIDEO_ENDPOINT_IMAGE,
                    "command": "python3 /app/src/sink_main.py",
                    "port_defs": [auto_port("sink", "video sink HTTP", SINK_PORT)],
                    "node_id": node_ids["compute-3"],
                    "restart_policy": "no",
                },
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        }

        if "视频AI推理任务" in existing_templates:
            template_id = existing_templates["视频AI推理任务"]["id"]
            response = await client.put(f"/api/templates/{template_id}", json=template)
            response.raise_for_status()
        else:
            response = await client.post("/api/templates", json=template)
            response.raise_for_status()
            template_id = response.json()["id"]

        catalog = {
            "task_type": "low_latency_video_pipeline",
            "modality": "低时延转发模态",
            "template_id": template_id,
        }
        catalog_response = await client.put(
            f"/api/business-template-catalog/{catalog['task_type']}",
            json=catalog,
        )
        catalog_response.raise_for_status()

        return {
            "node_ids": node_ids,
            "video_template_id": template_id,
            "compute_image": VIDEO_COMPUTE_IMAGE,
            "endpoint_image": VIDEO_ENDPOINT_IMAGE,
        }


def main() -> None:
    result = asyncio.run(rebuild_video_template())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
