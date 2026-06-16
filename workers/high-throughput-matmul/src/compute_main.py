#!/usr/bin/env python3
"""Matmul pipeline compute: receive job via POST, POST result to sink."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

from matmul_core import run_matmul

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")


def benchmark_mode() -> int:
    """Run fixed workload, output JSON result, exit."""
    matrix_size = int(os.environ.get("MATRIX_SIZE", "1024"))
    batch_count = int(os.environ.get("BATCH_COUNT", "50"))
    seed = int(os.environ.get("SEED", "42"))
    warmup = int(os.environ.get("WARMUP_BATCHES", "3"))
    result = _run_observation_window(
        {
            "matrix_size": matrix_size,
            "batch_count": batch_count,
            "seed": seed,
            "warmup_batches": warmup,
            "observation_duration_sec": os.environ.get("OBSERVATION_DURATION_SEC", "0"),
            "sample_interval_sec": os.environ.get("SAMPLE_INTERVAL_SEC", "1"),
            "sample_batch_count": os.environ.get("SAMPLE_BATCH_COUNT", batch_count),
            "min_samples": os.environ.get("MIN_SAMPLES", "1"),
            "max_samples": os.environ.get("MAX_SAMPLES", "50"),
        }
    )
    output = {
        "benchmark_result": {
            "effective_gflops": result["effective_gflops"],
            "elapsed_ms": result["compute_latency_ms"],
            "matrix_size": matrix_size,
            "batch_count": result["batch_count"],
            "seed": seed,
            "backend": result.get("backend"),
            "gpu_device": result.get("gpu_device"),
            "warmup_batches": warmup,
            "aggregation": result.get("aggregation"),
            "sample_count": result.get("sample_count"),
            "observation_duration_sec": result.get("observation_duration_sec"),
        }
    }
    print(json.dumps(output), flush=True)
    return 0


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_observation_window(job: dict) -> dict:
    """Collect process samples locally, then return one aggregated business metric."""
    matrix_size = _as_int(job.get("matrix_size"), 1024)
    seed = _as_int(job.get("seed"), 42)
    observation_duration_sec = max(0.0, _as_float(job.get("observation_duration_sec"), 0.0))
    sample_interval_sec = max(0.0, _as_float(job.get("sample_interval_sec"), 1.0))
    sample_batch_count = max(1, _as_int(job.get("sample_batch_count"), max(1, _as_int(job.get("batch_count"), 50))))
    warmup_batches = max(0, _as_int(job.get("warmup_batches"), 0))
    min_samples = max(1, _as_int(job.get("min_samples"), 1))
    max_samples = max(min_samples, _as_int(job.get("max_samples"), 50))

    if observation_duration_sec <= 0:
        metrics = run_matmul(matrix_size, max(1, _as_int(job.get("batch_count"), 50)), seed)
        return {
            "compute_latency_ms": metrics["elapsed_ms"],
            "effective_gflops": metrics["effective_gflops"],
            "matrix_size": matrix_size,
            "batch_count": _as_int(job.get("batch_count"), 50),
            "seed": seed,
            "result_preview": metrics["checksum"],
            "backend": metrics.get("backend"),
            "gpu_device": os.environ.get("GPU_DEVICE"),
            "aggregation": "single_run",
            "sample_count": 1,
        }

    if warmup_batches > 0:
        run_matmul(matrix_size, warmup_batches, seed)

    window_start = time.perf_counter()
    samples: list[dict] = []
    sample_index = 0
    backend_label = None
    while len(samples) < max_samples:
        now = time.perf_counter()
        if samples and len(samples) >= min_samples and now - window_start >= observation_duration_sec:
            break

        sample_t0 = time.perf_counter()
        metrics = run_matmul(matrix_size, sample_batch_count, seed + sample_index)
        sample_t1 = time.perf_counter()
        backend_label = metrics.get("backend") or backend_label
        sample_index += 1
        samples.append(
            {
                "index": sample_index,
                "relative_sec": round(sample_t1 - window_start, 3),
                "elapsed_ms": round(metrics["elapsed_ms"], 3),
                "effective_gflops": round(metrics["effective_gflops"], 4),
            }
        )

        if sample_interval_sec > 0:
            sleep_for = sample_interval_sec - (time.perf_counter() - sample_t0)
            if sleep_for > 0:
                time.sleep(sleep_for)

    values = [float(item["effective_gflops"]) for item in samples]
    median_gflops = statistics.median(values) if values else 0.0
    mean_gflops = statistics.fmean(values) if values else 0.0
    observed_duration_sec = time.perf_counter() - window_start
    return {
        "compute_latency_ms": observed_duration_sec * 1000.0,
        "effective_gflops": median_gflops,
        "matrix_size": matrix_size,
        "batch_count": sample_batch_count * len(samples),
        "seed": seed,
        "backend": backend_label,
        "gpu_device": os.environ.get("GPU_DEVICE"),
        "aggregation": "median_after_warmup",
        "mean_effective_gflops": mean_gflops,
        "min_effective_gflops": min(values) if values else 0.0,
        "max_effective_gflops": max(values) if values else 0.0,
        "observation_duration_sec": observation_duration_sec,
        "observed_duration_sec": observed_duration_sec,
        "sample_interval_sec": sample_interval_sec,
        "sample_batch_count": sample_batch_count,
        "warmup_batches": warmup_batches,
        "sample_count": len(samples),
        "min_samples": min_samples,
        "samples": samples,
    }

from _common.http_server import (
    get_listen_port,
    get_peer_url_by_name,
    post_json_to_peer,
    post_json_to_named_peer,
    post_json_to_url,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)
from _common.reporter import report_metric


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def _metric_tags(result: dict) -> dict:
    metadata_keys = (
        "compute_latency_ms",
        "effective_gflops",
        "matrix_size",
        "batch_count",
        "seed",
        "backend",
        "gpu_device",
        "result_preview",
        "aggregation",
        "mean_effective_gflops",
        "min_effective_gflops",
        "max_effective_gflops",
        "observation_duration_sec",
        "observed_duration_sec",
        "sample_interval_sec",
        "sample_batch_count",
        "warmup_batches",
        "sample_count",
        "min_samples",
        "samples",
    )
    result_meta = {key: result[key] for key in metadata_keys if key in result}
    instance_id = os.environ.get("TASK_INSTANCE_ID", "unknown-instance")
    result_uri = f"s3://{os.environ.get('MINIO_BUCKET', 'task-results')}/{instance_id}/result.json"
    return {
        "objects": [
            {
                "name": "result.json",
                "uri": result_uri,
                "content_type": "application/json",
            }
        ],
        "result": result_meta,
        "reported_by": "compute",
    }


def _report_result_from_compute(result: dict) -> None:
    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "effective_gflops"
    if metric_key == "effective_gflops":
        metric_value = float(result.get("effective_gflops", 0))
    else:
        metric_value = float(result.get(metric_key, result.get("compute_latency_ms", 0)))
    report_metric(
        metric_key,
        metric_value,
        unit=objective.get("unit") or "GFLOPS",
        tags=_metric_tags(result),
    )


def _callback_payload(result: dict) -> dict:
    return {
        "order_id": os.environ.get("ORDER_ID") or os.environ.get("BUSINESS_TASK_ID"),
        "task_instance_id": os.environ.get("TASK_INSTANCE_ID"),
        "task_type": os.environ.get("TASK_TYPE", "high_throughput_matmul"),
        "task_role": "compute",
        "metric_key": "effective_gflops",
        "result": result,
    }


def _post_result_callback(result: dict) -> None:
    callback_url = os.environ.get("CALLBACK_URL") or os.environ.get("SINK_CALLBACK_URL")
    if not callback_url:
        return
    try:
        post_json_to_url(callback_url, _callback_payload(result), timeout_sec=10.0, interval_sec=1.0)
        print(f"COMPUTE_POSTED_CALLBACK url={callback_url}", flush=True)
    except Exception as exc:
        print(f"COMPUTE_CALLBACK_FAILED {exc}", flush=True)


def main() -> int:
    port = get_listen_port("compute")
    print(f"COMPUTE_STARTING port={port}", flush=True)

    # 启动 HTTP server 等待 source 发来 job
    start_server(port, PostDataHandler)

    # POST "ready" 信号给 source，让 source 开始推送 job
    if get_peer_url_by_name("source"):
        post_json_to_named_peer("source", "/data", {"status": "ready"}, timeout_sec=30.0)
        print("COMPUTE_READY_SIGNAL_SENT", flush=True)
    else:
        print("COMPUTE_WAITING_FOR_EXTERNAL_SOURCE", flush=True)

    # 等待 source POST 的 job 数据
    job = wait_for_data_handler(port, timeout_sec=120.0)
    print(f"COMPUTE_GOT_JOB matrix_size={job['matrix_size']}", flush=True)

    metrics = _run_observation_window(job)
    result = {
        "compute_latency_ms": metrics["compute_latency_ms"],
        "effective_gflops": metrics["effective_gflops"],
        "matrix_size": metrics["matrix_size"],
        "batch_count": metrics["batch_count"],
        "seed": metrics["seed"],
        "backend": metrics.get("backend"),
        "gpu_device": metrics.get("gpu_device"),
    }
    for key in (
        "result_preview",
        "aggregation",
        "mean_effective_gflops",
        "min_effective_gflops",
        "max_effective_gflops",
        "observation_duration_sec",
        "observed_duration_sec",
        "sample_interval_sec",
        "sample_batch_count",
        "warmup_batches",
        "sample_count",
        "min_samples",
        "samples",
    ):
        if key in metrics:
            result[key] = metrics[key]
    print(
        f"COMPUTE_DONE elapsed_ms={metrics['compute_latency_ms']:.2f} "
        f"gflops={metrics['effective_gflops']:.2f} samples={metrics.get('sample_count', 1)}",
        flush=True,
    )

    PostDataHandler.result_data = result
    if get_peer_url_by_name("sink"):
        # POST result 给 sink
        post_json_to_peer("compute", "/data", result, timeout_sec=120.0)
        print("COMPUTE_POSTED_RESULT to sink", flush=True)
    else:
        _report_result_from_compute(result)
        _post_result_callback(result)
        print("COMPUTE_REPORTED_RESULT metric=effective_gflops", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        if os.environ.get("BENCHMARK_MODE", "").lower() in ("true", "1", "yes"):
            sys.exit(benchmark_mode())
        sys.exit(main())
    except Exception as exc:
        print(f"COMPUTE_FAILED {exc}", flush=True)
        sys.exit(1)
