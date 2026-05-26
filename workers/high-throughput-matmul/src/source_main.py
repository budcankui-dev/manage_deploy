#!/usr/bin/env python3
"""Matmul pipeline source: POST job to compute via HTTP."""

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
    post_json_to_peer,
    PostDataHandler,
    start_server,
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

    # source 启动 HTTP server（用于接收 compute 的就绪信号，但不再依赖它）
    # 直接推送 job 给 compute，附带重试逻辑
    port = get_listen_port("source")
    print(f"SOURCE_STARTING port={port} job={job}", flush=True)

    # 延迟确保容器完全启动，HTTP server 先起来
    time.sleep(2)
    start_server(port, PostDataHandler)

    # 直接 POST job 给 compute，带重试因为 compute 可能还在启动中
    # 推送成功即认为 job 已送达，后续 compute 会处理
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