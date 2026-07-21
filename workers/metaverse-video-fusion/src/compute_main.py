#!/usr/bin/env python3
"""Metaverse fusion compute: run MODNet frame fusion and POST result."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from fusion_core import run_fusion_profile

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (  # noqa: E402
    get_listen_port,
    get_peer_url_by_name,
    post_json_to_named_peer,
    post_json_to_peer,
    post_json_to_url,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)
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
    "annotated_frame_index",
    "preview_frame_width",
    "preview_frame_height",
    "annotated_frame_latency_ms",
    "annotated_frame_content_type",
    "annotated_frame_data_url",
    "annotated_frame_overlay",
    "fusion_frame_data_url",
    "fusion_frames_data_urls",
    "fusion_frame_count",
    "fusion_frame_sequence_count",
    "samples",
)


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def _result_meta(result: dict) -> dict:
    return {key: result[key] for key in METADATA_KEYS if key in result}


def _metric_tags(result: dict) -> dict:
    result_meta = _result_meta(result)
    instance_id = os.environ.get("TASK_INSTANCE_ID", "unknown-instance")
    return {
        "objects": [
            {
                "name": "metaverse-fusion-result.json",
                "uri": f"s3://{os.environ.get('MINIO_BUCKET', 'task-results')}/{instance_id}/metaverse-fusion-result.json",
                "content_type": "application/json",
            },
            {
                "name": "metaverse-fusion-preview",
                "uri": "inline://result_metadata/annotated_frame_data_url",
                "content_type": result_meta.get("annotated_frame_content_type", "image/jpeg"),
            },
        ],
        "result": result_meta,
        "reported_by": "compute",
    }


def _report_result_from_compute(result: dict) -> None:
    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "frame_latency_p90_ms"
    metric_value = float(result.get(metric_key, result.get("frame_latency_p90_ms", 0.0)))
    report_metric(metric_key, metric_value, unit=objective.get("unit") or "ms", tags=_metric_tags(result))


def _callback_payload(result: dict) -> dict:
    return {
        "order_id": os.environ.get("ORDER_ID") or os.environ.get("BUSINESS_TASK_ID"),
        "task_instance_id": os.environ.get("TASK_INSTANCE_ID"),
        "task_type": os.environ.get("TASK_TYPE", "metaverse_video_fusion"),
        "task_role": "compute",
        "metric_key": "frame_latency_p90_ms",
        "result": result,
    }


def _post_result_callback(result: dict) -> None:
    callback_url = os.environ.get("CALLBACK_URL") or os.environ.get("SINK_CALLBACK_URL")
    if not callback_url:
        return
    try:
        post_json_to_url(callback_url, _callback_payload(result), timeout_sec=10.0, interval_sec=1.0)
        print(f"METAVERSE_COMPUTE_POSTED_CALLBACK url={callback_url}", flush=True)
    except Exception as exc:
        print(f"METAVERSE_COMPUTE_CALLBACK_FAILED {exc}", flush=True)


def _benchmark_job_from_env() -> dict:
    return {
        "profile_id": os.environ.get("PROFILE_ID", "metaverse_offline_fusion_720p"),
        "frame_count": int(os.environ.get("FRAME_COUNT", "180")),
        "resolution": os.environ.get("RESOLUTION", "720p"),
        "fps": int(os.environ.get("FPS", "30")),
        "frame_stride": int(os.environ.get("FRAME_STRIDE", "1")),
        "warmup_frames": int(os.environ.get("WARMUP_FRAMES", "10")),
        "measured_frames": int(os.environ.get("MEASURED_FRAMES", "170")),
        "seed": int(os.environ.get("SEED", "42")),
        "video0_asset": os.environ.get("METAVERSE_VIDEO0_ASSET", "cam0.mp4"),
        "video1_asset": os.environ.get("METAVERSE_VIDEO1_ASSET", "cam1.mp4"),
        "fusion_mode": os.environ.get("METAVERSE_FUSION_MODE", "modnet_offline"),
        "modnet_checkpoint": os.environ.get("MODNET_CKPT", "MODNet/pretrained/modnet_webcam_portrait_matting.ckpt"),
        "strict_gpu": os.environ.get("STRICT_GPU", "true").lower() in {"1", "true", "yes"},
        "use_gpu": os.environ.get("USE_GPU", "true").lower() in {"1", "true", "yes"},
    }


def benchmark_mode() -> int:
    result = run_fusion_profile(_benchmark_job_from_env())
    output = {
        "benchmark_result": {
            "frame_latency_p90_ms": result["frame_latency_p90_ms"],
            "frame_latency_avg_ms": result["frame_latency_avg_ms"],
            "measured_frames": result["measured_frames"],
            "aggregation": result["aggregation"],
            "fusion_mode": result.get("fusion_mode"),
            "actual_backend": result.get("actual_backend"),
            "backend": result.get("backend"),
            "device": result.get("device"),
            "model_name": result.get("model_name"),
            "video0_asset": result.get("video0_asset"),
            "video1_asset": result.get("video1_asset"),
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
    print(f"METAVERSE_COMPUTE_STARTING port={port}", flush=True)
    start_server(port, PostDataHandler)

    if get_peer_url_by_name("source"):
        post_json_to_named_peer("source", "/data", {"status": "ready"}, timeout_sec=30.0)
        print("METAVERSE_COMPUTE_READY_SIGNAL_SENT", flush=True)
    else:
        print("METAVERSE_COMPUTE_WAITING_FOR_EXTERNAL_SOURCE", flush=True)

    job = wait_for_data_handler(port, timeout_sec=180.0)
    print(
        f"METAVERSE_COMPUTE_GOT_JOB pairs={len(job.get('frame_pairs') or [])} "
        f"measured={job.get('measured_frames')}",
        flush=True,
    )

    result = run_fusion_profile(job)
    print(
        f"METAVERSE_COMPUTE_DONE p90_ms={result['frame_latency_p90_ms']:.2f} "
        f"frames={result['measured_frames']}",
        flush=True,
    )
    PostDataHandler.result_data = result
    if get_peer_url_by_name("sink"):
        post_json_to_peer("compute", "/data", result, timeout_sec=180.0)
        print("METAVERSE_COMPUTE_POSTED_RESULT to sink", flush=True)
    else:
        _report_result_from_compute(result)
        _post_result_callback(result)
        print("METAVERSE_COMPUTE_REPORTED_RESULT metric=frame_latency_p90_ms", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        if os.environ.get("BENCHMARK_MODE", "").lower() in ("true", "1", "yes"):
            sys.exit(benchmark_mode())
        sys.exit(main())
    except Exception as exc:
        print(f"METAVERSE_COMPUTE_FAILED {exc}", flush=True)
        sys.exit(1)
