#!/usr/bin/env python3
"""Metaverse fusion sink: receive fused-frame result and report P90 latency."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import get_listen_port, PostDataHandler, start_server, wait_for_data_handler  # noqa: E402
from _common.reporter import report_metric  # noqa: E402


METADATA_KEYS = (
    "frame_latency_p90_ms",
    "frame_latency_avg_ms",
    "frame_latency_min_ms",
    "frame_latency_max_ms",
    "observed_duration_sec",
    "profile_id",
    "resolution",
    "fps",
    "frame_count",
    "frame_stride",
    "warmup_frames",
    "measured_frames",
    "aggregation",
    "fusion_mode",
    "model_name",
    "video0_asset",
    "video1_asset",
    "detector_backend",
    "actual_backend",
    "backend",
    "device",
    "gpu_device",
    "gpu_requested",
    "gpu_available",
    "gpu_assigned",
    "gpu_error",
    "preview_frame_index",
    "preview_frame_width",
    "preview_frame_height",
    "fusion_result_uri",
    "fusion_video_uri",
    "fusion_video_url",
    "fusion_preview_uri",
    "fusion_preview_url",
)


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def main() -> int:
    port = get_listen_port("sink")
    print(f"METAVERSE_SINK_STARTING port={port}", flush=True)
    start_server(port, PostDataHandler)

    result = wait_for_data_handler(port, timeout_sec=240.0)
    if not result.get("fusion_result_uri") or not result.get("fusion_video_uri"):
        raise RuntimeError("compute did not provide required MinIO fusion result URIs")
    print(
        f"METAVERSE_SINK_GOT_RESULT p90_ms={result.get('frame_latency_p90_ms')} "
        f"frames={result.get('measured_frames')} video={result.get('fusion_video_uri')}",
        flush=True,
    )

    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "frame_latency_p90_ms"
    metric_value = float(result.get(metric_key, result.get("frame_latency_p90_ms", 0.0)))
    result_meta = {key: result[key] for key in METADATA_KEYS if key in result}
    instance_id = os.environ["TASK_INSTANCE_ID"]

    report_metric(
        metric_key,
        metric_value,
        unit=objective.get("unit") or "ms",
        tags={
            "objects": [
                {
                    "name": "metaverse/result.json",
                    "uri": result_meta["fusion_result_uri"],
                    "content_type": "application/json",
                },
                {
                    "name": "metaverse/fusion-result.mp4",
                    "uri": result_meta["fusion_video_uri"],
                    "content_type": "video/mp4",
                },
                {
                    "name": "metaverse/fusion-preview.jpg",
                    "uri": result_meta["fusion_preview_uri"],
                    "content_type": "image/jpeg",
                },
            ],
            "result": result_meta,
        },
    )
    print(f"METAVERSE_SINK_DONE metric={metric_key} value={metric_value:.4f}", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"METAVERSE_SINK_FAILED {exc}", flush=True)
        traceback.print_exc()
        sys.exit(1)
