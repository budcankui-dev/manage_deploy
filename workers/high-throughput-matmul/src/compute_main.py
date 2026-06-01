#!/usr/bin/env python3
"""Matmul pipeline compute: receive job via POST, POST result to sink."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from matmul_core import run_matmul

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    post_json_to_peer,
    post_json_to_named_peer,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)


def main() -> int:
    port = get_listen_port("compute")
    print(f"COMPUTE_STARTING port={port}", flush=True)

    # 启动 HTTP server 等待 source 发来 job
    start_server(port, PostDataHandler)

    # POST "ready" 信号给 source，让 source 开始推送 job
    post_json_to_named_peer("source", "/data", {"status": "ready"}, timeout_sec=30.0)
    print("COMPUTE_READY_SIGNAL_SENT", flush=True)

    # 等待 source POST 的 job 数据
    job = wait_for_data_handler(port, timeout_sec=120.0)
    print(f"COMPUTE_GOT_JOB matrix_size={job['matrix_size']}", flush=True)

    metrics = run_matmul(
        int(job["matrix_size"]),
        int(job["batch_count"]),
        int(job["seed"]),
    )
    result = {
        "compute_latency_ms": metrics["elapsed_ms"],
        "effective_gflops": metrics["effective_gflops"],
        "matrix_size": job["matrix_size"],
        "batch_count": job["batch_count"],
        "seed": job["seed"],
        "result_preview": metrics["checksum"],
    }
    print(f"COMPUTE_DONE elapsed_ms={metrics['elapsed_ms']:.2f} gflops={metrics['effective_gflops']:.2f}", flush=True)

    # POST result 给 sink
    post_json_to_peer("compute", "/data", result, timeout_sec=120.0)
    print("COMPUTE_POSTED_RESULT to sink", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"COMPUTE_FAILED {exc}", flush=True)
        sys.exit(1)
