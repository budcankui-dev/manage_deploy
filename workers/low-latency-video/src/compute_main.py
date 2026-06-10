#!/usr/bin/env python3
"""Video pipeline compute: run fixed-video YOLO inference and POST result."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from video_core import run_video_profile

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    post_json_to_named_peer,
    post_json_to_peer,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)


def _benchmark_job_from_env() -> dict:
    return {
        "profile_id": os.environ.get("PROFILE_ID", "video_industrial_inspection_720p"),
        "frame_count": int(os.environ.get("FRAME_COUNT", "120")),
        "resolution": os.environ.get("RESOLUTION", "720p"),
        "fps": int(os.environ.get("FPS", "30")),
        "frame_stride": int(os.environ.get("FRAME_STRIDE", "30")),
        "warmup_frames": int(os.environ.get("WARMUP_FRAMES", "2")),
        "measured_frames": int(os.environ.get("MEASURED_FRAMES", "30")),
        "work_units": int(os.environ.get("WORK_UNITS", "60000")),
        "seed": int(os.environ.get("SEED", "42")),
        "video_asset": os.environ.get("VIDEO_ASSET", "bottle-detection.mp4"),
        "inference_mode": os.environ.get("VIDEO_INFERENCE_MODE", "yolo_onnx"),
        "model_name": os.environ.get("VIDEO_MODEL_NAME", "yolov5n"),
        "model_path": os.environ.get("VIDEO_MODEL_PATH", "models/yolov5n-fp32.onnx"),
        "class_names_path": os.environ.get("VIDEO_CLASS_NAMES_PATH", "models/coco.names"),
        "confidence_threshold": float(os.environ.get("VIDEO_CONFIDENCE_THRESHOLD", "0.25")),
        "nms_threshold": float(os.environ.get("VIDEO_NMS_THRESHOLD", "0.45")),
        "max_detections": int(os.environ.get("VIDEO_MAX_DETECTIONS", "8")),
    }


def benchmark_mode() -> int:
    result = run_video_profile(_benchmark_job_from_env())
    output = {
        "benchmark_result": {
            "frame_latency_p90_ms": result["frame_latency_p90_ms"],
            "frame_latency_avg_ms": result["frame_latency_avg_ms"],
            "measured_frames": result["measured_frames"],
            "aggregation": result["aggregation"],
            "detector_backend": result.get("detector_backend"),
            "actual_backend": result.get("actual_backend"),
            "backend": result.get("backend"),
            "device": result.get("device"),
            "detector_fallback_reason": result.get("detector_fallback_reason"),
            "model_name": result.get("model_name"),
            "video_asset": result.get("video_asset"),
            "detection_count": result.get("detection_count"),
            "top_label": result.get("top_label"),
            "top_confidence": result.get("top_confidence"),
            "gpu_device": result.get("gpu_device"),
            "gpu_requested": result.get("gpu_requested"),
            "gpu_available": result.get("gpu_available"),
            "gpu_assigned": result.get("gpu_assigned"),
            "gpu_error": result.get("gpu_error"),
        }
    }
    print(json.dumps(output), flush=True)
    return 0


def main() -> int:
    port = get_listen_port("compute")
    print(f"VIDEO_COMPUTE_STARTING port={port}", flush=True)
    start_server(port, PostDataHandler)

    post_json_to_named_peer("source", "/data", {"status": "ready"}, timeout_sec=30.0)
    print("VIDEO_COMPUTE_READY_SIGNAL_SENT", flush=True)

    job = wait_for_data_handler(port, timeout_sec=120.0)
    print(
        f"VIDEO_COMPUTE_GOT_JOB frames={job.get('frame_count')} "
        f"stride={job.get('frame_stride')}",
        flush=True,
    )

    result = run_video_profile(job)
    print(
        f"VIDEO_COMPUTE_DONE p90_ms={result['frame_latency_p90_ms']:.2f} "
        f"frames={result['measured_frames']}",
        flush=True,
    )
    post_json_to_peer("compute", "/data", result, timeout_sec=120.0)
    print("VIDEO_COMPUTE_POSTED_RESULT to sink", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        if os.environ.get("BENCHMARK_MODE", "").lower() in ("true", "1", "yes"):
            sys.exit(benchmark_mode())
        sys.exit(main())
    except Exception as exc:
        print(f"VIDEO_COMPUTE_FAILED {exc}", flush=True)
        sys.exit(1)
