"""Unified resource estimation for routing DAG nodes.

Derives resource requirements deterministically from task_type + data_profile,
so every routing DAG and worker env uses the same explainable values.
"""

from __future__ import annotations

import re
import math
from typing import Any


def _clamp(value: int, min_val: int, max_val: int) -> int:
    return max(min_val, min(value, max_val))


def _base_node(cpu: int = 2, cpu_mem: int = 512, gpu: int = 0, gpu_mem: int = 0, disk: int = 512) -> dict[str, int]:
    return {
        "cpu_units": cpu,
        "cpu_mem_mb": cpu_mem,
        "gpu_units": gpu,
        "gpu_mem_mb": gpu_mem,
        "disk_mb": disk,
    }


def estimate_resources(task_type: str, data_profile: dict[str, Any] | None = None) -> dict[str, dict[str, int]]:
    """Estimate per-node resource requirements from task type and data profile.

    Returns a dict keyed by logical node role with resource values.
    """
    profile = data_profile or {}

    if task_type == "high_throughput_matmul":
        return _estimate_matmul(profile)
    elif task_type == "low_latency_video_pipeline":
        return _estimate_video(profile)
    elif task_type == "llm_text_generation":
        return _estimate_llm(profile)
    else:
        return _estimate_default(profile)


def _estimate_matmul(profile: dict[str, Any]) -> dict[str, dict[str, int]]:
    ms = profile.get("matrix_size", 1024)
    bc = profile.get("batch_count", 1)

    gpu_mem_mb = _clamp(int(ms * ms * 8 * 3 * bc / (1024 * 1024)), 256, 16384)
    cpu_mem_mb = max(1024, gpu_mem_mb // 2)

    return {
        "source": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
        "compute": _base_node(cpu=8, cpu_mem=cpu_mem_mb, gpu=1, gpu_mem=gpu_mem_mb, disk=1024),
        "sink": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
    }


def _estimate_video(profile: dict[str, Any]) -> dict[str, dict[str, int]]:
    resolution = _parse_resolution_height(profile.get("resolution", 1080))
    gpu_mem_mb = 2048 if resolution <= 720 else 4096

    return {
        "source": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
        "compute": _base_node(cpu=4, cpu_mem=2048, gpu=1, gpu_mem=gpu_mem_mb, disk=1024),
        "sink": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
    }


def _parse_resolution_height(value: Any) -> int:
    """Accept values such as 720, "720p" or "1920x1080" for routing estimates."""
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return 1080
    if "x" in text:
        try:
            return int(text.rsplit("x", 1)[1].removesuffix("p"))
        except ValueError:
            return 1080
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else 1080


def _estimate_llm(profile: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        "source": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
        "compute": _base_node(cpu=8, cpu_mem=4096, gpu=1, gpu_mem=8192, disk=1024),
        "sink": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
    }


def _estimate_default(profile: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        "source": _base_node(cpu=4, cpu_mem=1024, gpu=0, gpu_mem=0, disk=512),
        "compute": _base_node(cpu=4, cpu_mem=1024, gpu=0, gpu_mem=0, disk=512),
        "sink": _base_node(cpu=4, cpu_mem=1024, gpu=0, gpu_mem=0, disk=512),
    }


def estimate_data_mb(task_type: str, data_profile: dict[str, Any] | None = None) -> int:
    """Estimate data transfer size in MB between DAG nodes."""
    profile = data_profile or {}

    if task_type == "high_throughput_matmul":
        ms = profile.get("matrix_size", 1024)
        # Two FP32 input matrices plus a compact result/metadata envelope.
        return max(1, int(ms * ms * 4 * 2 / (1024 * 1024)))

    if task_type == "low_latency_video_pipeline":
        height = _parse_resolution_height(profile.get("resolution", 720))
        width = int(height * 16 / 9)
        frame_count = int(profile.get("frame_count", profile.get("measured_frames", 90)) or 90)
        stride = max(1, int(profile.get("frame_stride", 30) or 30))
        sampled_frames = max(1, math.ceil(frame_count / stride))
        # Acceptance demo sends compressed/sampled frame payloads, not raw video.
        compressed_ratio = 0.08
        frame_mb = width * height * 3 * compressed_ratio / (1024 * 1024)
        return max(1, int(math.ceil(frame_mb * sampled_frames)))

    if task_type == "llm_text_generation":
        prompt = int(profile.get("prompt_tokens", 512) or 512)
        output = int(profile.get("max_new_tokens", 256) or 256)
        return max(1, int(math.ceil((prompt + output) * 4 / (1024 * 1024))))

    return 20


def estimate_bandwidth_mbps(task_type: str, data_profile: dict[str, Any] | None = None) -> int:
    """Estimate required link bandwidth between adjacent DAG nodes.

    The value is intentionally conservative and explainable for acceptance:
    it gives the external routing system a usable network constraint before
    we have enough production measurements to replace it with empirical data.
    """
    profile = data_profile or {}
    data_mb = estimate_data_mb(task_type, profile)

    if task_type == "high_throughput_matmul":
        return _clamp(max(10, data_mb * 2), 10, 1000)

    if task_type == "low_latency_video_pipeline":
        fps = int(profile.get("fps", 30) or 30)
        stride = max(1, int(profile.get("frame_stride", 30) or 30))
        effective_fps = max(1, math.ceil(fps / stride))
        # Keep a floor so the route visibly prefers a healthy data path.
        return _clamp(max(20, data_mb * 8 * effective_fps), 20, 1000)

    if task_type == "llm_text_generation":
        return 10

    return _clamp(max(10, data_mb * 2), 10, 500)
