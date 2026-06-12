#!/usr/bin/env python3
"""Official baseline CLI wrapper.

This script intentionally calls the Manager API instead of running local worker
code. Formal baselines must be measured inside the benchmark container on the
target node so CPU/GPU runtime, image version, and Node Agent behavior match
real business tasks.
"""

from __future__ import annotations

import argparse
import sys

import httpx


def _resolve_node_id(api_base: str, hostname: str) -> str:
    resp = httpx.get(f"{api_base.rstrip('/')}/api/nodes", timeout=30)
    resp.raise_for_status()
    for node in resp.json():
        if node.get("hostname") == hostname:
            return node["id"]
    raise RuntimeError(f"Node with hostname '{hostname}' not found")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run official containerized baseline via Manager API"
    )
    parser.add_argument("--node-hostname", required=True, help="Target node hostname")
    parser.add_argument("--task-type", required=True, help="Business task type")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs")
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="Manager API base URL",
    )
    parser.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="Developer-only fallback. Do not use for formal acceptance.",
    )
    args = parser.parse_args()

    try:
        node_id = _resolve_node_id(args.api_base, args.node_hostname)
        resp = httpx.post(
            f"{args.api_base.rstrip('/')}/api/baselines/run",
            json={
                "node_id": node_id,
                "task_type": args.task_type,
                "runs": args.runs,
                "allow_local_fallback": args.allow_local_fallback,
            },
            timeout=180,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"Baseline failed: {exc}", file=sys.stderr)
        return 1

    data = resp.json()
    print(
        "Baseline completed: "
        f"value={data.get('baseline_value')} {data.get('unit') or ''}, "
        f"stable={data.get('stable')}, baseline_id={data.get('baseline_id')}"
    )
    print(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
