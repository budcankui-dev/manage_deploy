#!/usr/bin/env python3
"""Metaverse fusion sink: receive fused-frame result and report P90 latency."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from io import BytesIO
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
    "fusion_frame_sequence_url",
    "fusion_frame_sequence_uri",
    "fusion_frame_sequence_storage",
    "fusion_frame_sequence_count",
    "fusion_frame_sequence_fps",
    "fusion_frame_sequence_content_type",
    "samples",
)


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def _upload_frame_sequence_to_minio(instance_id: str, payload: dict) -> dict:
    """Store the full fusion sequence in MinIO when platform credentials exist.

    The Manager upload below remains the playback cache for the detail panel.
    Object storage is the durable copy and is deliberately best-effort so a
    MinIO outage cannot turn an otherwise valid fusion run into a failed task.
    """
    access = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER")
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD")
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://host.docker.internal:9000")
    bucket = os.environ.get("MINIO_BUCKET", "task-results")
    if not access or not secret:
        print("METAVERSE_SINK_MINIO_SKIPPED credentials unavailable", flush=True)
        return {}

    try:
        from minio import Minio

        host = endpoint.replace("http://", "").replace("https://", "")
        client = Minio(
            host,
            access_key=access,
            secret_key=secret,
            secure=endpoint.startswith("https://"),
        )
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        key = f"{instance_id}/metaverse-fusion-frames.json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        client.put_object(
            bucket,
            key,
            BytesIO(body),
            length=len(body),
            content_type="application/json",
        )
        uri = f"s3://{bucket}/{key}"
        print(f"METAVERSE_SINK_MINIO_UPLOADED uri={uri} bytes={len(body)}", flush=True)
        return {
            "fusion_frame_sequence_uri": uri,
            "fusion_frame_sequence_storage": "minio",
        }
    except Exception as exc:
        print(f"METAVERSE_SINK_MINIO_SKIPPED {type(exc).__name__}: {exc}", flush=True)
        return {}


def _upload_frame_sequence(result: dict) -> dict:
    frames = result.pop("fusion_frame_sequence", None)
    if not isinstance(frames, list) or not frames:
        print("METAVERSE_SINK_FRAME_SEQUENCE_SKIPPED no frames", flush=True)
        return {}

    import httpx

    base = os.environ["MANAGER_API_BASE"].rstrip("/")
    instance_id = os.environ["TASK_INSTANCE_ID"]
    url = f"{base}/api/demo-assets/metaverse-results/{instance_id}/frame-sequence"
    headers: dict[str, str] = {}
    token = os.environ.get("SERVICE_API_TOKEN")
    if token:
        headers["X-Service-Token"] = token
    payload = {
        "fps": int(result.get("fps") or 30),
        "frame_count": len(frames),
        "frames": frames,
    }
    storage_meta = _upload_frame_sequence_to_minio(instance_id, payload)
    print(
        f"METAVERSE_SINK_UPLOAD_SEQUENCE url={url} frames={len(frames)} fps={payload['fps']}",
        flush=True,
    )
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=180.0)
            response.raise_for_status()
            break
        except Exception as exc:
            last_error = exc
            print(
                f"METAVERSE_SINK_UPLOAD_SEQUENCE_RETRY attempt={attempt} error={type(exc).__name__}: {exc}",
                flush=True,
            )
            if attempt >= 5:
                raise
            time.sleep(min(2 * attempt, 8))
    else:
        raise RuntimeError(f"failed to upload frame sequence: {last_error}")
    uploaded = response.json()
    print(
        f"METAVERSE_SINK_UPLOADED_SEQUENCE url={uploaded.get('url')} "
        f"frames={uploaded.get('frame_count')}",
        flush=True,
    )
    return {
        **storage_meta,
        "fusion_frame_sequence_url": uploaded.get("url"),
        "fusion_frame_sequence_count": int(uploaded.get("frame_count") or len(frames)),
        "fusion_frame_sequence_fps": int(uploaded.get("fps") or result.get("fps") or 30),
        "fusion_frame_sequence_content_type": "application/json",
    }


def main() -> int:
    port = get_listen_port("sink")
    print(f"METAVERSE_SINK_STARTING port={port}", flush=True)
    start_server(port, PostDataHandler)

    result = wait_for_data_handler(port, timeout_sec=240.0)
    sequence_meta = _upload_frame_sequence(result)
    result.update({key: value for key, value in sequence_meta.items() if value is not None})
    print(
        f"METAVERSE_SINK_GOT_RESULT p90_ms={result.get('frame_latency_p90_ms')} "
        f"frames={result.get('measured_frames')} sequence={result.get('fusion_frame_sequence_count', 0)}",
        flush=True,
    )

    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "frame_latency_p90_ms"
    metric_value = float(result.get(metric_key, result.get("frame_latency_p90_ms", 0.0)))
    result_meta = {key: result[key] for key in METADATA_KEYS if key in result}
    instance_id = os.environ["TASK_INSTANCE_ID"]
    sequence_uri = (
        result_meta.get("fusion_frame_sequence_uri")
        or result_meta.get("fusion_frame_sequence_url")
        or "inline://result_metadata/fusion_frames_data_urls"
    )

    report_metric(
        metric_key,
        metric_value,
        unit=objective.get("unit") or "ms",
        tags={
            "objects": [
                {
                    "name": "metaverse-fusion-frames.json",
                    "uri": sequence_uri,
                    "content_type": result_meta.get("fusion_frame_sequence_content_type", "application/json"),
                },
                {
                    "name": "metaverse-fusion-frame-sequence",
                    "uri": result_meta.get("fusion_frame_sequence_url") or "inline://result_metadata/fusion_frames_data_urls",
                    "content_type": result_meta.get("fusion_frame_sequence_content_type", "application/json"),
                },
                {
                    "name": "metaverse-fusion-preview",
                    "uri": "inline://result_metadata/annotated_frame_data_url",
                    "content_type": result_meta.get("annotated_frame_content_type", "image/jpeg"),
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
