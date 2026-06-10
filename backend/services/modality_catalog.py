"""Modality taxonomy shared by intent parsing and routing payloads."""

from __future__ import annotations

from typing import Any


MODALITIES = [
    "高通量计算模态",
    "低时延转发模态",
    "智算中心模态",
    "分布式存算模态",
    "大规模连接模态",
    "确定性转发模态",
    "高能效边缘计算模态",
    "高安全传输模态",
]


TASK_TYPE_MODALITY = {
    "high_throughput_matmul": "高通量计算模态",
    "low_latency_video_pipeline": "低时延转发模态",
    "llm_text_generation": "智算中心模态",
    "ai_model_training": "智算中心模态",
    "distributed_storage_compute": "分布式存算模态",
    "massive_connection_collect": "大规模连接模态",
    "deterministic_forwarding": "确定性转发模态",
    "energy_efficient_edge_inference": "高能效边缘计算模态",
    "secure_transmission": "高安全传输模态",
}


TASK_TYPE_NAMES = {
    "high_throughput_matmul": "矩阵乘法计算任务",
    "low_latency_video_pipeline": "视频AI推理任务",
    "llm_text_generation": "大模型文本生成任务",
    "ai_model_training": "文本模型训练任务",
    "distributed_storage_compute": "分布式存算任务",
    "massive_connection_collect": "大规模连接采集任务",
    "deterministic_forwarding": "确定性转发任务",
    "energy_efficient_edge_inference": "高能效边缘推理任务",
    "secure_transmission": "高安全传输任务",
}


def modality_for_task_type(task_type: str | None) -> str | None:
    if not task_type:
        return None
    return TASK_TYPE_MODALITY.get(task_type)


def task_name_for_task_type(task_type: str) -> str:
    return TASK_TYPE_NAMES.get(task_type, task_type)


def normalize_modality(value: str | None, task_type: str | None = None) -> str | None:
    """Return the Chinese modality label used by expert-facing screens."""
    if value in MODALITIES:
        return value
    legacy = {
        "high_throughput_compute": "高通量计算模态",
        "low_latency_forwarding": "低时延转发模态",
        "llm_text": "智算中心模态",
    }
    if value in legacy:
        return legacy[value]
    return modality_for_task_type(task_type) or value


def default_objective_for_task_type(task_type: str | None) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        "high_throughput_matmul": {"metric_key": "effective_gflops", "operator": ">=", "unit": "GFLOPS"},
        "low_latency_video_pipeline": {"metric_key": "frame_latency_p90_ms", "operator": "<=", "unit": "ms"},
        "llm_text_generation": {"metric_key": "tokens_per_second", "operator": ">=", "unit": "tokens/s"},
        "ai_model_training": {"metric_key": "samples_per_second", "operator": ">=", "unit": "samples/s"},
        "distributed_storage_compute": {"metric_key": "data_throughput_mb_s", "operator": ">=", "unit": "MB/s"},
        "massive_connection_collect": {"metric_key": "connection_count", "operator": ">=", "unit": "connections"},
        "deterministic_forwarding": {"metric_key": "jitter_ms", "operator": "<=", "unit": "ms"},
        "energy_efficient_edge_inference": {"metric_key": "energy_per_frame_j", "operator": "<=", "unit": "J/frame"},
        "secure_transmission": {"metric_key": "secure_throughput_mb_s", "operator": ">=", "unit": "MB/s"},
    }
    return dict(mapping.get(task_type or "", {"metric_key": "service_success_rate", "operator": ">=", "unit": "%"}))
