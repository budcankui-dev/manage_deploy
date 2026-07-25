#!/usr/bin/env python3
"""Metaverse fusion source: read two videos and POST sampled frame pairs."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (  # noqa: E402
    get_listen_port,
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


def _build_job() -> dict:
    profile = _parse_json_env("DATA_PROFILE")
    job = {
        "profile_id": profile.get("profile_id", "metaverse_offline_fusion_720p"),
        "resolution": profile.get("resolution", "720p"),
        "frame_count": int(profile.get("frame_count", 180)),
        "fps": int(profile.get("fps", 30)),
        "frame_stride": int(profile.get("frame_stride", 1)),
        "warmup_frames": int(profile.get("warmup_frames", 10)),
        "measured_frames": int(profile.get("measured_frames", 170)),
        "seed": int(profile.get("seed", 42)),
        "video0_asset": profile.get("video0_asset", "cam0.mp4"),
        "video1_asset": profile.get("video1_asset", "cam1.mp4"),
        "fusion_mode": profile.get("fusion_mode", "modnet_offline"),
        "modnet_checkpoint": profile.get("modnet_checkpoint", "MODNet/pretrained/modnet_webcam_portrait_matting.ckpt"),
        "strict_gpu": profile.get("strict_gpu", True),
        "use_gpu": profile.get("use_gpu", True),
    }
    return job


def _should_wait_for_compute_ready() -> bool:
    raw = os.environ.get("WAIT_FOR_COMPUTE_READY", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _source_listen_enabled() -> bool:
    raw = os.environ.get("SOURCE_LISTEN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def main() -> int:
    job = _build_job()
    listen_enabled = _source_listen_enabled()
    port = get_listen_port("source") if listen_enabled else None
    print(
        f"METAVERSE_SOURCE_STARTING port={port or 'disabled'} "
        f"videos={job['video0_asset']},{job['video1_asset']}",
        flush=True,
    )

    if listen_enabled:
        start_server(port, PostDataHandler)
    if listen_enabled and _should_wait_for_compute_ready():
        print("METAVERSE_SOURCE_READY waiting for compute signal", flush=True)
        ready = wait_for_data_handler(port, timeout_sec=300.0)
        print(f"METAVERSE_SOURCE_GOT_COMPUTE_SIGNAL {ready}", flush=True)
    else:
        print("METAVERSE_SOURCE_READY skip compute-ready wait", flush=True)
    post_json_to_peer("source", "/data", job, timeout_sec=180.0)
    print("METAVERSE_SOURCE_POSTED_JOB to compute", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"METAVERSE_SOURCE_FAILED {exc}", flush=True)
        sys.exit(1)
