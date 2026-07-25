#!/usr/bin/env python3
"""Metaverse fusion source: serve two video inputs and trigger compute."""

from __future__ import annotations

import json
import os
import sys
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


ALLOWED_VIDEO_ASSETS = {"cam0.mp4", "cam1.mp4"}


def _asset_directory() -> Path:
    return Path(os.environ.get("METAVERSE_ASSET_DIR") or "/app/assets") / "videos"


def _asset_path(asset_name: str) -> Path:
    if asset_name not in ALLOWED_VIDEO_ASSETS:
        raise ValueError(f"unsupported metaverse input asset: {asset_name}")
    path = (_asset_directory() / asset_name).resolve()
    if not path.is_file() or _asset_directory().resolve() not in path.parents:
        raise FileNotFoundError(f"metaverse input asset is unavailable: {asset_name}")
    return path


def _asset_response_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive byte range for normal browser/worker range requests."""
    if not value:
        return None
    if not value.startswith("bytes="):
        raise ValueError("invalid Range header")
    start_text, _, end_text = value[6:].partition("-")
    if not _ or (not start_text and not end_text):
        raise ValueError("invalid Range header")
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    else:
        suffix = int(end_text)
        start, end = max(0, size - suffix), size - 1
    if start < 0 or end < start or start >= size:
        raise ValueError("unsatisfiable Range header")
    return start, min(end, size - 1)


class SourceAssetHandler(PostDataHandler):
    """POST readiness/jobs like the shared handler and stream approved input MP4s."""

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/assets/"):
            return super().do_GET()
        asset_name = unquote(parsed.path.removeprefix("/assets/"))
        try:
            asset = _asset_path(asset_name)
            size = asset.stat().st_size
            byte_range = _asset_response_range(self.headers.get("Range"), size)
        except (FileNotFoundError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND, "Metaverse input asset not found")
            return

        start, end = byte_range if byte_range else (0, size - 1)
        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if byte_range else HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with asset.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


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
    job["source_assets"] = {
        "video0": {"name": job["video0_asset"], "path": f"/assets/{job['video0_asset']}", "content_type": "video/mp4"},
        "video1": {"name": job["video1_asset"], "path": f"/assets/{job['video1_asset']}", "content_type": "video/mp4"},
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
        start_server(port, SourceAssetHandler)
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
