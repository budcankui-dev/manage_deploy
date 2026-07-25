#!/usr/bin/env python3
"""Metaverse fusion compute: run MODNet frame fusion and POST result."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

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


def _result_meta(result: dict) -> dict:
    return {key: result[key] for key in METADATA_KEYS if key in result}


def _download_source_asset(source_url: str, descriptor: dict, label: str) -> Path:
    """Stream one Source-hosted video to a local temporary file for MODNet."""
    import httpx

    name = str(descriptor.get("name") or "")
    relative_path = str(descriptor.get("path") or "")
    if name not in {"cam0.mp4", "cam1.mp4"} or relative_path != f"/assets/{name}":
        raise RuntimeError(f"invalid {label} source asset descriptor")
    url = urljoin(f"{source_url.rstrip('/')}/", relative_path.lstrip("/"))
    fd, raw_path = tempfile.mkstemp(prefix=f"metaverse-{label}-", suffix=".mp4")
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as output, httpx.stream(
            "GET", url, timeout=httpx.Timeout(180.0, connect=10.0), follow_redirects=False,
        ) as response:
            response.raise_for_status()
            if "video/mp4" not in response.headers.get("content-type", "").lower():
                raise RuntimeError(f"{label} source asset has an unexpected content type")
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                output.write(chunk)
        if path.stat().st_size == 0:
            raise RuntimeError(f"{label} source asset is empty")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _download_source_inputs(job: dict) -> tuple[dict, list[Path]]:
    """Replace source descriptors with locally streamed files for the compute core."""
    source_url = get_peer_url_by_name("source")
    if not source_url:
        raise RuntimeError("metaverse compute requires PEER_SOURCE_URL for dual-video input transfer")
    descriptors = job.get("source_assets")
    if not isinstance(descriptors, dict):
        raise RuntimeError("metaverse source did not provide dual-video asset descriptors")
    downloaded: list[Path] = []
    try:
        video0 = _download_source_asset(source_url, dict(descriptors.get("video0") or {}), "video0")
        downloaded.append(video0)
        video1 = _download_source_asset(source_url, dict(descriptors.get("video1") or {}), "video1")
        downloaded.append(video1)
        compute_job = dict(job)
        compute_job["video0_asset"] = str(video0)
        compute_job["video1_asset"] = str(video1)
        return compute_job, downloaded
    except Exception:
        for path in downloaded:
            path.unlink(missing_ok=True)
        raise


def _archive_to_minio(result: dict) -> dict:
    """Persist durable metaverse evidence before passing a compact result downstream."""
    access = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER")
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD")
    if not access or not secret:
        raise RuntimeError("MinIO credentials are required for metaverse result archival")
    from minio import Minio

    endpoint = os.environ.get("MINIO_ENDPOINT", "http://host.docker.internal:9000")
    bucket = os.environ.get("MINIO_BUCKET", "task-results")
    instance_id = os.environ["TASK_INSTANCE_ID"]
    client = Minio(
        endpoint.replace("http://", "").replace("https://", ""),
        access_key=access,
        secret_key=secret,
        secure=endpoint.startswith("https://"),
    )
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    prefix = f"{instance_id}/metaverse"
    archive_path = Path(str(result.pop("fusion_archive_path")))
    preview = bytes(result.pop("fusion_preview_jpeg"))
    if not preview:
        raise RuntimeError("fusion preview is empty; refusing to archive an incomplete result")
    try:
        archive = archive_path.read_bytes()
    finally:
        archive_path.unlink(missing_ok=True)
    video_key = f"{prefix}/fusion-result.mp4"
    preview_key = f"{prefix}/fusion-preview.jpg"
    result_key = f"{prefix}/result.json"
    client.put_object(bucket, video_key, BytesIO(archive), len(archive), content_type="video/mp4")
    client.put_object(bucket, preview_key, BytesIO(preview), len(preview), content_type="image/jpeg")
    compact = _result_meta(result)
    compact.update({
        "fusion_video_uri": f"s3://{bucket}/{video_key}",
        "fusion_preview_uri": f"s3://{bucket}/{preview_key}",
        "fusion_result_uri": f"s3://{bucket}/{result_key}",
        "fusion_video_url": f"/api/demo-assets/metaverse-results/{instance_id}/fusion-result.mp4",
        "fusion_preview_url": f"/api/demo-assets/metaverse-results/{instance_id}/fusion-preview.jpg",
    })
    body = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    client.put_object(bucket, result_key, BytesIO(body), len(body), content_type="application/json")
    print(f"METAVERSE_COMPUTE_MINIO_ARCHIVED prefix=s3://{bucket}/{prefix}", flush=True)
    # Do not pass per-frame payloads to Sink/Manager.  The durable objects are
    # the full result; this message carries only the platform result summary.
    return compact


def _metric_tags(result: dict) -> dict:
    result_meta = _result_meta(result)
    return {
        "objects": [
            {
                "name": "metaverse/result.json",
                "uri": result_meta.get("fusion_result_uri", ""),
                "content_type": "application/json",
            },
            {
                "name": "metaverse/fusion-result.mp4",
                "uri": result_meta.get("fusion_video_uri", ""),
                "content_type": "video/mp4",
            },
            {
                "name": "metaverse/fusion-preview.jpg",
                "uri": result_meta.get("fusion_preview_uri", ""),
                "content_type": "image/jpeg",
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
        f"METAVERSE_COMPUTE_GOT_JOB videos={job.get('video0_asset')},{job.get('video1_asset')} "
        f"measured={job.get('measured_frames')}",
        flush=True,
    )

    compute_job, downloaded_inputs = _download_source_inputs(job)
    try:
        fusion_result = run_fusion_profile(compute_job)
        # Persist logical Source asset names, never transient Compute paths.
        fusion_result["video0_asset"] = job["video0_asset"]
        fusion_result["video1_asset"] = job["video1_asset"]
        result = _archive_to_minio(fusion_result)
    finally:
        for path in downloaded_inputs:
            path.unlink(missing_ok=True)
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
