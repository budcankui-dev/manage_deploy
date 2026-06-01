#!/usr/bin/env python3
"""Baseline benchmark script — 在指定节点上运行基准测试并记录结果。

用法:
    PYTHONPATH=backend python backend/scripts/run_baseline.py \
        --node-hostname compute-1 \
        --task-type high_throughput_matmul \
        --runs 3

该脚本在本地运行 matmul 基准测试（不需要容器），计算 effective_gflops，
取中位数作为 baseline_value，然后通过 API 写入 node_baselines 表。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../workers"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../workers/high-throughput-matmul/src"))


TASK_BENCHMARKS = {
    "high_throughput_matmul": {
        "metric_key": "effective_gflops",
        "operator": ">=",
        "unit": "GFLOPS",
        "params": {"matrix_size": 1024, "batch_count": 10, "seed": 42},
    },
}


def run_matmul_benchmark(matrix_size: int, batch_count: int, seed: int) -> float:
    from matmul_core import run_matmul
    result = run_matmul(matrix_size, batch_count, seed)
    return result["effective_gflops"]


def run_benchmark(task_type: str, runs: int) -> dict:
    if task_type not in TASK_BENCHMARKS:
        print(f"Unknown task_type: {task_type}")
        print(f"Available: {list(TASK_BENCHMARKS.keys())}")
        sys.exit(1)

    config = TASK_BENCHMARKS[task_type]
    params = config["params"]
    values = []

    print(f"Running {task_type} benchmark ({runs} runs)...")
    for i in range(runs):
        if task_type == "high_throughput_matmul":
            val = run_matmul_benchmark(**params)
        else:
            raise ValueError(f"No benchmark runner for {task_type}")
        values.append(val)
        print(f"  Run {i+1}/{runs}: {val:.4f} {config['unit']}")

    median_val = statistics.median(values)
    print(f"\nMedian: {median_val:.4f} {config['unit']}")
    return {
        "metric_key": config["metric_key"],
        "operator": config["operator"],
        "unit": config["unit"],
        "baseline_value": median_val,
        "raw_values": values,
        "run_count": runs,
    }


def save_baseline_via_api(
    api_base: str, node_id: str, task_type: str, result: dict
) -> None:
    import httpx

    url = f"{api_base.rstrip('/')}/api/baselines"
    payload = {
        "node_id": node_id,
        "task_type": task_type,
        "metric_key": result["metric_key"],
        "baseline_value": result["baseline_value"],
        "operator": result["operator"],
        "unit": result["unit"],
        "run_count": result["run_count"],
        "raw_values": result["raw_values"],
    }
    resp = httpx.post(url, json=payload, timeout=30)
    if resp.status_code == 201:
        print(f"Baseline saved: {resp.json()['id']}")
    elif resp.status_code == 409:
        print("Baseline already exists, updating...")
        # Find existing and update
        existing = httpx.get(
            url, params={"node_id": node_id, "task_type": task_type}, timeout=30
        ).json()
        if existing:
            bid = existing[0]["id"]
            resp2 = httpx.put(f"{url}/{bid}", json={
                "baseline_value": result["baseline_value"],
                "raw_values": result["raw_values"],
                "run_count": result["run_count"],
            }, timeout=30)
            resp2.raise_for_status()
            print(f"Baseline updated: {bid}")
    else:
        resp.raise_for_status()


def resolve_node_id(api_base: str, hostname: str) -> str:
    import httpx

    url = f"{api_base.rstrip('/')}/api/nodes"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    for node in resp.json():
        if node["hostname"] == hostname:
            return node["id"]
    print(f"Node with hostname '{hostname}' not found")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run baseline benchmark")
    parser.add_argument("--node-hostname", required=True, help="Target node hostname")
    parser.add_argument("--task-type", required=True, help="Task type to benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs (default 3)")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument("--dry-run", action="store_true", help="Only run benchmark, don't save")
    args = parser.parse_args()

    result = run_benchmark(args.task_type, args.runs)

    if args.dry_run:
        print("\n[dry-run] Would save:")
        print(f"  node: {args.node_hostname}")
        print(f"  task_type: {args.task_type}")
        print(f"  baseline_value: {result['baseline_value']:.4f}")
        return

    node_id = resolve_node_id(args.api_base, args.node_hostname)
    save_baseline_via_api(args.api_base, node_id, args.task_type, result)
    print("\nDone.")


if __name__ == "__main__":
    main()
