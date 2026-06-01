"""Baseline benchmark runner — 可被 API 和 CLI 脚本共同调用。"""

from __future__ import annotations

import statistics
import sys
import os

# Add worker source to path for matmul_core import
_WORKER_SRC = os.path.join(os.path.dirname(__file__), "../../workers/high-throughput-matmul/src")
if _WORKER_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_WORKER_SRC))

TASK_BENCHMARKS = {
    "high_throughput_matmul": {
        "metric_key": "effective_gflops",
        "operator": ">=",
        "unit": "GFLOPS",
        "params": {"matrix_size": 1024, "batch_count": 10, "seed": 42},
    },
}


def run_benchmark(task_type: str, runs: int = 3) -> dict:
    """Run benchmark for given task_type, return results dict."""
    if task_type not in TASK_BENCHMARKS:
        raise ValueError(f"Unknown task_type: {task_type}. Available: {list(TASK_BENCHMARKS.keys())}")

    config = TASK_BENCHMARKS[task_type]
    params = config["params"]
    values = []

    for i in range(runs):
        if task_type == "high_throughput_matmul":
            from matmul_core import run_matmul
            result = run_matmul(**params)
            values.append(result["effective_gflops"])
        else:
            raise ValueError(f"No benchmark runner for {task_type}")

    median_val = statistics.median(values)
    return {
        "metric_key": config["metric_key"],
        "operator": config["operator"],
        "unit": config["unit"],
        "baseline_value": median_val,
        "raw_values": values,
        "run_count": runs,
    }
