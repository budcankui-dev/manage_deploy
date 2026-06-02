#!/usr/bin/env python3
"""Quick local baseline test — runs matmul on this machine and optionally saves to backend.

Usage:
  python run_baseline_local.py                          # just print result
  python run_baseline_local.py --save --node-id NODE_ID  # save to backend
  python run_baseline_local.py --runs 5 --matrix-size 1024 --batch-count 50
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../workers/high-throughput-matmul/src"))


def main():
    parser = argparse.ArgumentParser(description="Local matmul baseline test")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--matrix-size", type=int, default=1024)
    parser.add_argument("--batch-count", type=int, default=50)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--node-id", default="")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    args = parser.parse_args()

    # Override env vars so run_benchmark_local picks up CLI params
    os.environ["MATRIX_SIZE"] = str(args.matrix_size)
    os.environ["BATCH_COUNT"] = str(args.batch_count)

    from services.baseline_runner import run_benchmark_local

    result = run_benchmark_local("high_throughput_matmul", runs=args.runs)

    print(f"baseline_value : {result['baseline_value']:.4f} {result['unit']}")
    print(f"raw_values     : {[round(v, 4) for v in result['raw_values']]}")
    print(f"std_dev        : {result['std_dev']}")
    print(f"stable         : {result['stable']}")

    if not args.save:
        return

    if not args.node_id:
        print("--node-id is required when --save is used", file=sys.stderr)
        sys.exit(1)

    import httpx

    base = args.backend_url.rstrip("/")

    # Login
    resp = httpx.post(f"{base}/api/auth/login",
                      json={"username": args.username, "password": args.password},
                      timeout=10)
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # POST /api/baselines/run
    payload = {
        "node_id": args.node_id,
        "task_type": "high_throughput_matmul",
        "runs": args.runs,
    }
    resp = httpx.post(f"{base}/api/baselines/run", json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    print(f"Saved — baseline_id: {data.get('baseline_id')}, value: {data.get('baseline_value')}")


if __name__ == "__main__":
    main()
