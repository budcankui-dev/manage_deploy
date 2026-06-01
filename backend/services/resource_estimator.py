"""Unified resource estimation for routing DAG nodes.

Derives resource requirements deterministically from task_type + data_profile,
eliminating inconsistencies between dag_builder and routing_payload_builder.
"""

from __future__ import annotations

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
    resolution = profile.get("resolution", 1080)
    gpu_mem_mb = 2048 if resolution <= 720 else 4096

    return {
        "source": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
        "video": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
        "infer": _base_node(cpu=4, cpu_mem=2048, gpu=1, gpu_mem=gpu_mem_mb, disk=1024),
        "sink": _base_node(cpu=2, cpu_mem=512, gpu=0, gpu_mem=0, disk=512),
    }


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
        return max(1, int(ms * ms * 8 / (1024 * 1024)))

    return 20
