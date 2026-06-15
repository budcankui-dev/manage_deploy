#!/usr/bin/env python3
"""Rebuild the matrix multiplication template in MySQL with proper node IDs.

This is a SYNC script (uses pymysql) — distinct from the backend's async
SQLAlchemy stack. It connects to the same MySQL instance the backend uses,
but the connection parameters are resolved here from the SAME source of
truth as the backend: ``settings.database_url`` (loaded from env via the
backend's pydantic-settings, e.g. ``DATABASE_URL=mysql+...``).

It will refuse to run if ``database_url`` is unset or does not look like a
MySQL URL — there is no hardcoded fallback host / port / user / password.
This keeps lab credentials out of the source tree.

Steps:
1. Resolve MySQL credentials from ``settings.database_url`` (sync-compatible)
2. Query MySQL directly to get compute-1/2/3 node UUIDs
3. Use the API to create/update the template with proper node references
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import pymysql
from httpx import ASGITransport, AsyncClient

from config import settings

WORKER_TAG = os.environ.get("WORKER_TAG", "dev")
# WORKER_IMAGE may be a full registry-qualified reference, e.g.
#   <registry-host:port>/scientific-matmul
# For local single-host runs the default stays the registry-less name.
WORKER_IMAGE = os.environ.get("WORKER_IMAGE", "manage-deploy/scientific-matmul")

# Role-specific image overrides let source/sink use a small endpoint image
# while compute keeps the CUDA/CuPy image.  If no endpoint override is provided
# the legacy single-image template is preserved.
COMPUTE_IMAGE_REPO = os.environ.get("MATMUL_COMPUTE_IMAGE", WORKER_IMAGE)
ENDPOINT_IMAGE_REPO = os.environ.get("MATMUL_ENDPOINT_IMAGE", WORKER_IMAGE)
MATMUL_COMPUTE_IMAGE = f"{COMPUTE_IMAGE_REPO}:{WORKER_TAG}"
MATMUL_ENDPOINT_IMAGE = f"{ENDPOINT_IMAGE_REPO}:{WORKER_TAG}"

SOURCE_PORT = 18801
COMPUTE_PORT = 18802
SINK_PORT = 18803
PORT_RANGE = [18000, 19999]


def auto_port(name: str, label: str, default: int) -> dict:
    """Declare a named host-network port that is allocated per instance."""
    return {
        "name": name,
        "label": label,
        "default": default,
        "auto": True,
        "range": PORT_RANGE,
    }


def _resolve_mysql_config() -> dict:
    """Resolve sync pymysql connection params from settings.database_url.

    The backend uses an async SQLAlchemy driver (mysql+aiomysql://...) which
    pymysql cannot parse directly, so we re-parse the URL here.

    Raises RuntimeError if database_url is unset, blank, or not a MySQL URL.
    No defaults — operators MUST set DATABASE_URL (or one of the explicit
    MYSQL_* env vars below) before running this script.
    """
    explicit_host = os.environ.get("MYSQL_HOST")
    if explicit_host:
        password = os.environ.get("MYSQL_PASSWORD")
        if not password:
            raise RuntimeError(
                "MYSQL_HOST is set but MYSQL_PASSWORD is not. Refusing to "
                "connect with an empty password."
            )
        return {
            "host": explicit_host,
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "user": os.environ.get("MYSQL_USER", "root"),
            "password": password,
            "database": os.environ.get("MYSQL_DATABASE", "task_manager"),
        }

    url = settings.database_url
    if not url:
        raise RuntimeError(
            "settings.database_url is empty. Set DATABASE_URL (e.g. "
            "mysql+aiomysql://USER:PASS@HOST:PORT/DB) or set MYSQL_HOST / "
            "MYSQL_USER / MYSQL_PASSWORD / MYSQL_PORT / MYSQL_DATABASE."
        )
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme != "mysql":
        raise RuntimeError(
            f"settings.database_url scheme={parsed.scheme!r} is not a MySQL "
            "URL; this script requires a MySQL backend."
        )
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise RuntimeError(
            "DATABASE_URL must include user, password, and host "
            "(mysql+aiomysql://USER:PASS@HOST:PORT/DB)."
        )
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username),
        "password": unquote(parsed.password),
        "database": (parsed.path or "/task_manager").lstrip("/") or "task_manager",
    }


def get_compute_node_ids() -> dict[str, str]:
    """Get the real node UUIDs for compute-1, compute-2, compute-3 from MySQL."""
    conn = pymysql.connect(**_resolve_mysql_config())
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, hostname FROM nodes WHERE hostname IN ('compute-1', 'compute-2', 'compute-3')"
    )
    result = {hostname: node_id for node_id, hostname in cursor.fetchall()}
    conn.close()
    if len(result) != 3:
        missing = { 'compute-1', 'compute-2', 'compute-3' } - set(result.keys())
        raise RuntimeError(f"Missing compute nodes in MySQL: {missing}")
    print(f"Found compute nodes: {result}")
    return result


async def rebuild_matmul_template(base_url: str | None = None) -> dict:
    """Create or update the matrix multiplication template with proper node IDs."""
    base_url = base_url or os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")

    # Get the real node UUIDs from MySQL
    node_ids = get_compute_node_ids()

    async with AsyncClient(base_url=base_url, timeout=60.0) as client:
        # Check if template already exists
        listed = await client.get("/api/templates")
        listed.raise_for_status()
        existing_templates = {t["name"]: t for t in listed.json()}

        matmul_template = {
            "name": "矩阵乘法计算任务",
            "description": "Scientific computing: matrix multiplication source/compute/sink workers over HTTP",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": MATMUL_ENDPOINT_IMAGE,
                    "command": "python /app/src/source_main.py",
                    "port_defs": [auto_port("source", "source HTTP", SOURCE_PORT)],
                    "node_id": node_ids["compute-1"],
                    "restart_policy": "no",
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": MATMUL_COMPUTE_IMAGE,
                    "command": "python /app/src/compute_main.py",
                    "port_defs": [auto_port("compute", "compute HTTP", COMPUTE_PORT)],
                    "node_id": node_ids["compute-2"],
                    "restart_policy": "no",
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": MATMUL_ENDPOINT_IMAGE,
                    "command": "python /app/src/sink_main.py",
                    "port_defs": [auto_port("sink", "sink HTTP", SINK_PORT)],
                    "node_id": node_ids["compute-3"],
                    "restart_policy": "no",
                },
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        }

        template_id = None
        if "矩阵乘法计算任务" in existing_templates:
            template_id = existing_templates["矩阵乘法计算任务"]["id"]
            print(f"Template already exists with ID: {template_id}")
            # Update the existing template
            response = await client.put(f"/api/templates/{template_id}", json=matmul_template)
            response.raise_for_status()
            print(f"Template updated successfully")
        else:
            # Create new template
            response = await client.post("/api/templates", json=matmul_template)
            if response.status_code == 409:
                # Race condition - template was created by another process
                listed = await client.get("/api/templates")
                listed.raise_for_status()
                for t in listed.json():
                    if t["name"] == "矩阵乘法计算任务":
                        template_id = t["id"]
                        break
                else:
                    raise RuntimeError("Template conflict but not found")
            else:
                response.raise_for_status()
                template_id = response.json()["id"]
            print(f"Template created with ID: {template_id}")

        # Register in business-template-catalog if not already
        catalog = {
            "task_type": "high_throughput_matmul",
            "modality": "high_throughput_compute",
            "template_id": template_id,
        }
        catalog_response = await client.put(
            f"/api/business-template-catalog/{catalog['task_type']}",
            json=catalog,
        )
        catalog_response.raise_for_status()

        return {
            "node_ids": node_ids,
            "matmul_template_id": template_id,
            "compute_image": MATMUL_COMPUTE_IMAGE,
            "endpoint_image": MATMUL_ENDPOINT_IMAGE,
        }


def main() -> None:
    result = asyncio.run(rebuild_matmul_template())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
