"""Deterministic video inference surrogate used by the video worker."""

from __future__ import annotations

import math
import statistics
import time


def percentile(values: list[float], pct: float) -> float:
    """Return percentile with linear interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def simulate_inference(frame_index: int, work_units: int, seed: int) -> dict:
    """Run a deterministic CPU-bound loop and return per-frame latency."""
    start = time.perf_counter()
    acc = (seed + frame_index * 2654435761) & 0xFFFFFFFF
    for i in range(max(1, work_units)):
        acc = (acc * 1664525 + 1013904223 + i) & 0xFFFFFFFF
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "frame_index": frame_index,
        "latency_ms": elapsed_ms,
        "label": "normal" if acc % 17 else "defect",
        "confidence": round(0.80 + (acc % 1900) / 10000.0, 4),
        "checksum": acc,
    }


def run_video_profile(job: dict) -> dict:
    """Execute warmup and measured frame inference, returning aggregate metrics."""
    frame_count = int(job.get("frame_count", 120))
    frame_stride = max(1, int(job.get("frame_stride", 30)))
    warmup_frames = max(0, int(job.get("warmup_frames", 2)))
    measured_frames = max(1, int(job.get("measured_frames", 30)))
    work_units = max(1, int(job.get("work_units", 60000)))
    seed = int(job.get("seed", 42))
    profile_id = job.get("profile_id", "video_industrial_inspection")
    resolution = job.get("resolution", "720p")
    fps = int(job.get("fps", 30))

    candidate_frames = list(range(0, max(frame_count, 1), frame_stride))
    while len(candidate_frames) < warmup_frames + measured_frames:
        candidate_frames.append(len(candidate_frames) * frame_stride)

    warmup = candidate_frames[:warmup_frames]
    measured = candidate_frames[warmup_frames : warmup_frames + measured_frames]

    for frame_index in warmup:
        simulate_inference(frame_index, work_units, seed)

    start = time.perf_counter()
    samples = [
        simulate_inference(frame_index, work_units, seed + sample_index)
        for sample_index, frame_index in enumerate(measured)
    ]
    observed_duration_sec = time.perf_counter() - start
    latencies = [float(item["latency_ms"]) for item in samples]

    return {
        "frame_latency_p90_ms": percentile(latencies, 0.90),
        "frame_latency_avg_ms": statistics.fmean(latencies) if latencies else 0.0,
        "frame_latency_min_ms": min(latencies) if latencies else 0.0,
        "frame_latency_max_ms": max(latencies) if latencies else 0.0,
        "observed_duration_sec": observed_duration_sec,
        "frame_count": frame_count,
        "profile_id": profile_id,
        "resolution": resolution,
        "fps": fps,
        "frame_stride": frame_stride,
        "warmup_frames": warmup_frames,
        "measured_frames": len(samples),
        "work_units": work_units,
        "seed": seed,
        "aggregation": "p90_after_warmup",
        "samples": [
            {
                "frame_index": item["frame_index"],
                "latency_ms": round(float(item["latency_ms"]), 4),
                "label": item["label"],
                "confidence": item["confidence"],
            }
            for item in samples
        ],
    }
