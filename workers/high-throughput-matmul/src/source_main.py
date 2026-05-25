#!/usr/bin/env python3
"""Matmul pipeline source: POST job to compute after starting HTTP server."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    get_peer_url,
    post_json_to_peer,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)


def _parse_json_env(name: str, default: dict | None = None) -> dict:
    raw = os.environ.get(name, "")
    if not raw:
        return default or {}
    return json.loads(raw)


def main() -> int:
    profile = _parse_json_env("DATA_PROFILE")
    matrix_size = int(profile.get("matrix_size") or 512)
    batch_count = int(profile.get("batch_count") or 4)
    seed = int(profile.get("seed") or 42)

    job = {
        "matrix_size": matrix_size,
        "batch_count": batch_count,
        "seed": seed,
        "profile_id": profile.get("profile_id", "matmul_dev"),
    }

    # source 监听自己的端口，等待下游 compute 推送完成信号（compute 开始等待 job）
    # 或者：compute 启动后直接 POST 给 source，source 收到后再 POST 给 compute
    # 当前设计：source 启动 HTTP server，等待 compute 发送"就绪"信号，
    # 然后 source POST job 给 compute
    port = get_listen_port("source")
    print(f"SOURCE_STARTING port={port} job={job}", flush=True)

    # 启动 server 等待 compute 的"就绪"信号
    start_server(port, PostDataHandler)

    # 等待 compute 发来 POST /data（表示 compute 已就绪）
    _ = wait_for_data_handler(port, timeout_sec=120.0)
    print("SOURCE_COMPUTE_READY", flush=True)

    # POST job 给 compute
    post_json_to_peer("source", "/data", job, timeout_sec=120.0)
    print(f"SOURCE_POSTED_JOB to compute", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SOURCE_FAILED {exc}", flush=True)
        sys.exit(1)