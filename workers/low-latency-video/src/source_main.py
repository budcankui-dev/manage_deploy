#!/usr/bin/env python3
"""Video pipeline source: generate frame metadata and POST job to compute."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import get_listen_port, post_json_to_peer, PostDataHandler, start_server


def _parse_json_env(name: str, default: dict | None = None) -> dict:
    raw = os.environ.get(name, "")
    if not raw:
        return default or {}
    return json.loads(raw)


def _build_job() -> dict:
    profile = _parse_json_env("DATA_PROFILE")
    return {
        "profile_id": profile.get("profile_id", "video_industrial_inspection"),
        "resolution": profile.get("resolution", "720p"),
        "frame_count": int(profile.get("frame_count", 120)),
        "fps": int(profile.get("fps", 30)),
        "frame_stride": int(profile.get("frame_stride", 30)),
        "warmup_frames": int(profile.get("warmup_frames", 2)),
        "measured_frames": int(profile.get("measured_frames", 30)),
        "work_units": int(profile.get("work_units", 60000)),
        "seed": int(profile.get("seed", 42)),
    }


def main() -> int:
    job = _build_job()
    port = get_listen_port("source")
    print(f"VIDEO_SOURCE_STARTING port={port} job={job}", flush=True)

    time.sleep(2)
    start_server(port, PostDataHandler)
    post_json_to_peer("source", "/data", job, timeout_sec=120.0)
    print("VIDEO_SOURCE_POSTED_JOB to compute", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"VIDEO_SOURCE_FAILED {exc}", flush=True)
        sys.exit(1)
