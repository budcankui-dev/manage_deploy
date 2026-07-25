#!/usr/bin/env python3
"""Video pipeline compute: run fixed-video YOLO inference and POST result."""

from __future__ import annotations

import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

from video_core import run_video_profile

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    get_peer_url_by_name,
    post_json_to_named_peer,
    post_json_to_peer,
    post_json_to_url,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)
from _common.reporter import report_metric


_INLINE_RESULT_FIELDS = frozenset(
    {
        "annotated_frame_data_url",
        "preview_frames",
        "annotated_frame_content_type",
    }
)


def _build_minio_client_from_env():
    access = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER")
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD")
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://host.docker.internal:9000")
    if not access or not secret:
        raise RuntimeError("MinIO credentials are required to archive video inference evidence")

    from minio import Minio

    host = endpoint.removeprefix("http://").removeprefix("https://")
    return Minio(host, access_key=access, secret_key=secret, secure=endpoint.startswith("https://"))


def _video_result_for_transport(result: dict) -> dict:
    """Remove worker-local binary/Base64 evidence before crossing a process boundary."""
    return {
        key: value
        for key, value in result.items()
        if key not in _INLINE_RESULT_FIELDS and key != "evidence_frames"
    }


def _evidence_suffix(content_type: str) -> str:
    return "svg" if content_type == "image/svg+xml" else "jpg"


def upload_video_evidence(result: dict, instance_id: str) -> dict:
    """Archive every measured annotated frame and a compact result manifest in MinIO."""
    client = _build_minio_client_from_env()
    bucket = os.environ.get("MINIO_BUCKET", "task-results")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    evidence_frames = result.get("evidence_frames") or []
    archived_frames: list[dict] = []
    object_entries: list[dict] = []
    for evidence in evidence_frames:
        if not isinstance(evidence, dict):
            raise RuntimeError("Invalid video evidence frame")
        content = evidence.get("content")
        if not isinstance(content, bytes) or not content:
            raise RuntimeError("Video evidence frame content is missing")
        frame_index = int(evidence.get("frame_index", len(archived_frames)))
        content_type = str(evidence.get("content_type") or "image/jpeg")
        key = f"{instance_id}/video/frames/{frame_index:06d}.{_evidence_suffix(content_type)}"
        client.put_object(bucket, key, BytesIO(content), length=len(content), content_type=content_type)
        uri = f"s3://{bucket}/{key}"
        archived = {
            key: value
            for key, value in evidence.items()
            if key not in {"content", "content_type"}
        }
        archived.update({"uri": uri, "content_type": content_type})
        archived_frames.append(archived)
        object_entries.append(
            {
                "name": f"video-frame-{frame_index:06d}",
                "uri": uri,
                "content_type": content_type,
            }
        )

    manifest_key = f"{instance_id}/video/result.json"
    manifest_uri = f"s3://{bucket}/{manifest_key}"
    transport_result = _video_result_for_transport(result)
    transport_result.update(
        {
            "evidence_manifest_uri": manifest_uri,
            "evidence_frame_count": len(archived_frames),
            "evidence_frames": archived_frames,
            "evidence_upload_status": "uploaded",
        }
    )
    manifest = {
        "schema_version": "video-evidence/v1",
        "instance_id": instance_id,
        "result": _video_result_for_transport(transport_result),
        "evidence_frames": archived_frames,
    }
    data = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    client.put_object(bucket, manifest_key, BytesIO(data), length=len(data), content_type="application/json")
    transport_result["result_objects"] = [
        {
            "name": "video-result.json",
            "uri": manifest_uri,
            "content_type": "application/json",
        },
        *object_entries,
    ]
    return transport_result


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
    result_meta = {key: result[key] for key in metadata_keys if key in result}
    return {
        "objects": list(result.get("result_objects") or []),
        "result": result_meta,
        "reported_by": "compute",
    }


def _report_result_from_compute(result: dict) -> None:
    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "frame_latency_p90_ms"
    metric_value = float(result.get(metric_key, result.get("frame_latency_p90_ms", 0.0)))
    report_metric(
        metric_key,
        metric_value,
        unit=objective.get("unit") or "ms",
        tags=_metric_tags(result),
    )


def _callback_payload(result: dict) -> dict:
    return {
        "event_type": "final",
        "order_id": os.environ.get("ORDER_ID") or os.environ.get("BUSINESS_TASK_ID"),
        "task_instance_id": os.environ.get("TASK_INSTANCE_ID"),
        "task_type": os.environ.get("TASK_TYPE", "low_latency_video_pipeline"),
        "task_role": "compute",
        "metric_key": "frame_latency_p90_ms",
        "result": result,
    }


def _progress_callback_payload(event: dict) -> dict:
    result: dict = {
        "samples": [
            {
                "frame_index": event.get("frame_index"),
                "latency_ms": event.get("latency_ms"),
                "label": event.get("label"),
                "confidence": event.get("confidence", 0.0),
            }
        ],
        "video_asset": os.environ.get("VIDEO_ASSET", "bottle-detection.mp4"),
    }
    return {
        "event_type": "progress",
        "order_id": os.environ.get("ORDER_ID") or os.environ.get("BUSINESS_TASK_ID"),
        "task_instance_id": os.environ.get("TASK_INSTANCE_ID"),
        "task_type": os.environ.get("TASK_TYPE", "low_latency_video_pipeline"),
        "task_role": "compute",
        "metric_key": "frame_latency_p90_ms",
        "result": result,
    }


def _post_progress_callback(event: dict) -> None:
    callback_url = os.environ.get("CALLBACK_URL") or os.environ.get("SINK_CALLBACK_URL")
    if not callback_url:
        return
    try:
        post_json_to_url(callback_url, _progress_callback_payload(event), timeout_sec=3.0, interval_sec=0.2)
    except Exception as exc:
        print(f"VIDEO_COMPUTE_PROGRESS_CALLBACK_FAILED {exc}", flush=True)


def _post_result_callback(result: dict) -> None:
    callback_url = os.environ.get("CALLBACK_URL") or os.environ.get("SINK_CALLBACK_URL")
    if not callback_url:
        return
    try:
        post_json_to_url(callback_url, _callback_payload(result), timeout_sec=10.0, interval_sec=1.0)
        print(f"VIDEO_COMPUTE_POSTED_CALLBACK url={callback_url}", flush=True)
    except Exception as exc:
        print(f"VIDEO_COMPUTE_CALLBACK_FAILED {exc}", flush=True)


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

    if get_peer_url_by_name("source"):
        post_json_to_named_peer("source", "/data", {"status": "ready"}, timeout_sec=30.0)
        print("VIDEO_COMPUTE_READY_SIGNAL_SENT", flush=True)
    else:
        print("VIDEO_COMPUTE_WAITING_FOR_EXTERNAL_SOURCE", flush=True)

    job = wait_for_data_handler(port, timeout_sec=120.0)
    print(
        f"VIDEO_COMPUTE_GOT_JOB frame_count={job.get('frame_count')} "
        f"stride={job.get('frame_stride')}",
        flush=True,
    )

    progress_callback = _post_progress_callback if not get_peer_url_by_name("sink") else None
    result = upload_video_evidence(run_video_profile(job, progress_callback=progress_callback), os.environ["TASK_INSTANCE_ID"])
    print(
        f"VIDEO_COMPUTE_DONE p90_ms={result['frame_latency_p90_ms']:.2f} "
        f"measured_frames={result['measured_frames']}",
        flush=True,
    )
    PostDataHandler.result_data = result
    if get_peer_url_by_name("sink"):
        post_json_to_peer("compute", "/data", result, timeout_sec=120.0)
        print("VIDEO_COMPUTE_POSTED_RESULT to sink", flush=True)
    else:
        _report_result_from_compute(result)
        _post_result_callback(result)
        print("VIDEO_COMPUTE_REPORTED_RESULT metric=frame_latency_p90_ms", flush=True)

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
