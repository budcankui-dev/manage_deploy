#!/usr/bin/env python3
"""Video pipeline sink: receive result and report frame latency metric."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import get_listen_port, PostDataHandler, start_server, wait_for_data_handler
from _common.reporter import report_metric


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def _metric_tags(result: dict) -> dict:
    metadata_keys = (
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
        "work_units",
        "seed",
        "aggregation",
        "detector_backend",
        "actual_backend",
        "backend",
        "device",
        "detector_fallback_reason",
        "model_name",
        "video_asset",
        "confidence_threshold",
        "nms_threshold",
        "gpu_device",
        "gpu_requested",
        "gpu_available",
        "gpu_assigned",
        "gpu_error",
        "annotated_frame_index",
        "preview_frame_width",
        "preview_frame_height",
        "annotated_frame_latency_ms",
        "annotated_frame_overlay",
        "detection_count",
        "top_label",
        "top_label_zh",
        "top_confidence",
        "detections",
        "samples",
        "evidence_manifest_uri",
        "evidence_frame_count",
        "evidence_frames",
        "evidence_upload_status",
    )
    return {
        "objects": list(result.get("result_objects") or []),
        "result": {key: result[key] for key in metadata_keys if key in result},
    }


def main() -> int:
    port = get_listen_port("sink")
    print(f"VIDEO_SINK_STARTING port={port}", flush=True)
    start_server(port, PostDataHandler)

    result = wait_for_data_handler(port, timeout_sec=180.0)
    print(
        f"VIDEO_SINK_GOT_RESULT p90_ms={result.get('frame_latency_p90_ms')} "
        f"measured_frames={result.get('measured_frames')}",
        flush=True,
    )

    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "frame_latency_p90_ms"
    metric_value = float(result.get(metric_key, result.get("frame_latency_p90_ms", 0.0)))

    report_metric(
        metric_key,
        metric_value,
        unit=objective.get("unit") or "ms",
        tags=_metric_tags(result),
    )
    print(f"VIDEO_SINK_DONE metric={metric_key} value={metric_value:.4f}", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"VIDEO_SINK_FAILED {exc}", flush=True)
        sys.exit(1)
