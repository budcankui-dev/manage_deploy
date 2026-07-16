#!/usr/bin/env python3
"""Create/update the route-only source-to-sink transfer template and catalog entry."""

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
import pymysql

from rebuild_matmul_template import _resolve_mysql_config, get_compute_node_ids

PLACEHOLDER_IMAGE = os.environ.get("TERMINAL_ROUTE_PLACEHOLDER_IMAGE", "busybox:latest")


def get_placeholder_node_ids() -> dict[str, str]:
    """Choose template anchor nodes without requiring any specific compute host.

    Route-only terminal transfer orders never start these template containers.
    Prefer compute-1/compute-3 for readability, but fall back to any existing
    non-deleted nodes so a temporarily unavailable or missing compute row does
    not block catalog registration.
    """
    try:
        compute_nodes = get_compute_node_ids()
        return {
            "source": compute_nodes["compute-1"],
            "sink": compute_nodes["compute-3"],
            "mode": "preferred_compute_nodes",
        }
    except RuntimeError as exc:
        print(f"Falling back to generic template anchors: {exc}", file=sys.stderr)

    conn = pymysql.connect(**_resolve_mysql_config())
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, hostname
        FROM nodes
        WHERE deleted_at IS NULL
        ORDER BY
            CASE
                WHEN hostname LIKE 'compute-%' THEN 0
                WHEN hostname REGEXP '^h[0-9]+' THEN 1
                ELSE 2
            END,
            hostname ASC
        LIMIT 2
        """
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        raise RuntimeError("No nodes found in MySQL; cannot anchor terminal route template.")
    source_id = rows[0][0]
    sink_id = rows[1][0] if len(rows) > 1 else rows[0][0]
    print(f"Using generic terminal route anchors: {rows}", file=sys.stderr)
    return {"source": source_id, "sink": sink_id, "mode": "generic_existing_nodes"}


async def rebuild_terminal_route_template(base_url: str | None = None) -> dict:
    """Register a minimal template for route-only terminal transfer orders.

    The template is intentionally not used to start containers. The conversation
    and routing flow still requires a business-template-catalog row, so this
    source -> sink template acts as a stable catalog anchor for the task type.
    """
    base_url = base_url or os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")
    node_ids = get_placeholder_node_ids()

    async with AsyncClient(base_url=base_url, timeout=60.0) as client:
        listed = await client.get("/api/templates")
        listed.raise_for_status()
        existing_templates = {item["name"]: item for item in listed.json()}

        template = {
            "name": "端到端传输路由任务",
            "description": "Route-only source-to-sink transfer. No platform-managed compute container is created.",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": PLACEHOLDER_IMAGE,
                    "command": "true",
                    "node_id": node_ids["source"],
                    "restart_policy": "no",
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": PLACEHOLDER_IMAGE,
                    "command": "true",
                    "node_id": node_ids["sink"],
                    "restart_policy": "no",
                },
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "sink"},
            ],
        }

        if template["name"] in existing_templates:
            template_id = existing_templates[template["name"]]["id"]
            response = await client.put(f"/api/templates/{template_id}", json=template)
            response.raise_for_status()
        else:
            response = await client.post("/api/templates", json=template)
            response.raise_for_status()
            template_id = response.json()["id"]

        catalog = {
            "task_type": "terminal_route_transfer",
            "modality": "低时延转发模态",
            "template_id": template_id,
            "source_node_name": "source",
            "compute_node_name": "compute",
            "sink_node_name": "sink",
            "description": "只有源端和目的端，外部路由建立链路，不创建 Docker 实例。",
        }
        catalog_response = await client.put(
            f"/api/business-template-catalog/{catalog['task_type']}",
            json=catalog,
        )
        catalog_response.raise_for_status()

        return {
            "node_ids": node_ids,
            "terminal_route_template_id": template_id,
            "placeholder_image": PLACEHOLDER_IMAGE,
        }


def main() -> None:
    result = asyncio.run(rebuild_terminal_route_template())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
