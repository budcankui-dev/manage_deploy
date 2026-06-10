"""Baseline benchmark runner — 容器化执行，保证和实际任务环境一致。

执行流程：
1. 通过 Node Agent 在目标节点启动临时 worker 容器（BENCHMARK_MODE=true）
2. 容器跑完后从日志收集 effective_gflops
3. 重复 N 次，取中位数
4. 校验标准差 < 中位数 10%（稳定性）
5. 返回结果

如果 Node Agent 不可达，fallback 到本地执行（单机演示场景）。
"""

from __future__ import annotations

import json
import logging
import statistics
import asyncio
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 固定基准测试参数（测试方案规定，不可变）
BENCHMARK_PROFILES = {
    "high_throughput_matmul": {
        "metric_key": "effective_gflops",
        "operator": ">=",
        "unit": "GFLOPS",
        "image": "10.112.244.94:5000/scientific-matmul:dev",
        "command": "python3 /app/src/compute_main.py",
        "env": {
            "BENCHMARK_MODE": "true",
            "MATRIX_SIZE": "1024",
            "BATCH_COUNT": "50",
            "SEED": "42",
            "WARMUP_BATCHES": "3",
            "OBSERVATION_DURATION_SEC": "10",
            "SAMPLE_INTERVAL_SEC": "1",
            "SAMPLE_BATCH_COUNT": "5",
            "MIN_SAMPLES": "5",
            "MAX_SAMPLES": "12",
        },
        "profile_id": "gpu_standard",
    },
    "low_latency_video_pipeline": {
        "metric_key": "frame_latency_p90_ms",
        "operator": "<=",
        "unit": "ms",
        "image": "10.112.244.94:5000/low-latency-video:dev",
        "command": "python /app/src/compute_main.py",
        "env": {
            "BENCHMARK_MODE": "true",
            "FRAME_COUNT": "100",
            "RESOLUTION": "720p",
            "FPS": "30",
            "FRAME_STRIDE": "30",
            "WARMUP_FRAMES": "10",
            "MEASURED_FRAMES": "30",
            "WORK_UNITS": "45000",
            "SYNTHETIC_SLEEP_MS": "0",
            "SEED": "42",
            "USE_GPU": "true",
            "VIDEO_ASSET": "bottle-detection.mp4",
            "VIDEO_INFERENCE_MODE": "yolo_onnx",
            "VIDEO_MODEL_NAME": "yolov5n",
            "VIDEO_MODEL_PATH": "models/yolov5n-fp32.onnx",
            "VIDEO_CLASS_NAMES_PATH": "models/coco.names",
            "VIDEO_CONFIDENCE_THRESHOLD": "0.25",
            "VIDEO_NMS_THRESHOLD": "0.45",
            "VIDEO_MAX_DETECTIONS": "8",
        },
        "profile_id": "video_industrial_inspection_720p",
    },
}

STABILITY_THRESHOLD = 0.10  # 标准差 < 中位数 × 10%


async def run_baseline_on_node(
    agent_address: str,
    task_type: str,
    runs: int = 3,
    image_override: str | None = None,
) -> dict[str, Any]:
    """在目标节点上通过容器执行基准测试。

    通过 Node Agent 启动临时 worker 容器（BENCHMARK_MODE=true），
    容器跑完后从日志收集指标，重复 N 次取中位数。
    """
    if task_type not in BENCHMARK_PROFILES:
        raise ValueError(f"不支持的任务类型: {task_type}")

    profile = BENCHMARK_PROFILES[task_type]
    image = image_override or profile["image"]
    command = profile.get("command")
    env = dict(profile["env"])
    values: list[float] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(runs):
            container_name = f"baseline-{task_type}-run{i}-{int(time.time())}"
            metric_value = await _run_single_benchmark(
                client,
                agent_address,
                image,
                env,
                container_name,
                profile["metric_key"],
                command,
            )
            values.append(metric_value)
            logger.info(
                "Baseline run %s/%s: %.4f %s",
                i + 1,
                runs,
                metric_value,
                profile["unit"],
            )

    median_val = statistics.median(values)
    std_dev = statistics.stdev(values) if len(values) > 1 else 0.0
    stable = std_dev < median_val * STABILITY_THRESHOLD if median_val > 0 else True

    return {
        "metric_key": profile["metric_key"],
        "operator": profile["operator"],
        "unit": profile["unit"],
        "baseline_value": median_val,
        "raw_values": values,
        "run_count": runs,
        "std_dev": round(std_dev, 4),
        "stable": stable,
        "profile_id": profile["profile_id"],
    }


async def _run_single_benchmark(
    client: httpx.AsyncClient,
    agent_address: str,
    image: str,
    env: dict[str, str],
    container_name: str,
    metric_key: str,
    command: str | None = None,
) -> float:
    """启动一个临时容器执行基准测试并收集结果。"""
    base_url = agent_address.rstrip("/")
    task_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())

    # 1. 创建容器
    create_payload = {
        "image": image,
        "command": command,
        "env": env,
        "network_mode": "host",
        "restart_policy": "no",
    }
    resp = await client.post(
        f"{base_url}/containers/{task_id}/{node_id}/start",
        json=create_payload,
    )
    resp.raise_for_status()

    # 2. 等待容器退出（轮询状态）
    for _ in range(120):  # max 120s
        await asyncio.sleep(1)
        status_resp = await client.get(f"{base_url}/containers/{task_id}/{node_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.json().get("status", "")
            if status in ("exited", "stopped", "dead"):
                break
    else:
        # 超时，强制停止
        await client.post(f"{base_url}/containers/{task_id}/{node_id}/stop")

    # 3. 收集日志
    logs_resp = await client.get(f"{base_url}/containers/{task_id}/{node_id}/logs")
    logs_text = ""
    if logs_resp.status_code == 200:
        try:
            logs_text = logs_resp.json().get("logs", "")
        except json.JSONDecodeError:
            logs_text = logs_resp.text

    # 4. 删除容器
    await client.delete(f"{base_url}/containers/{task_id}/{node_id}")

    # 5. 解析结果
    return _parse_benchmark_result(logs_text, metric_key)


def _parse_benchmark_result(logs: str, metric_key: str = "effective_gflops") -> float:
    """从容器日志中解析 benchmark_result JSON。"""
    for line in logs.splitlines():
        line = line.strip()
        if "benchmark_result" in line:
            json_start = line.find("{")
            if json_start > 0:
                # Docker logs can include an RFC3339 timestamp prefix when
                # Node Agent reads logs with timestamps=True.
                line = line[json_start:]
            try:
                data = json.loads(line)
                return float(data["benchmark_result"][metric_key])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    raise RuntimeError(f"无法从容器日志解析基准测试结果")


# ---- Local fallback（单机演示场景，Node Agent 不可达时使用）----

def run_benchmark_local(task_type: str, runs: int = 3) -> dict[str, Any]:
    """本地执行基准测试（fallback，不通过容器）。"""
    import sys
    import os
    if task_type not in BENCHMARK_PROFILES:
        raise ValueError(f"不支持的任务类型: {task_type}")

    worker_dir = "low-latency-video" if task_type == "low_latency_video_pipeline" else "high-throughput-matmul"
    _WORKER_SRC = os.path.join(
        os.path.dirname(__file__), f"../../workers/{worker_dir}/src"
    )
    if _WORKER_SRC not in sys.path:
        sys.path.insert(0, os.path.abspath(_WORKER_SRC))

    profile = BENCHMARK_PROFILES[task_type]
    env = profile["env"]

    for k, v in env.items():
        os.environ.setdefault(k, v)

    if task_type == "low_latency_video_pipeline":
        video_src = os.path.join(
            os.path.dirname(__file__), "../../workers/low-latency-video/src"
        )
        if video_src not in sys.path:
            sys.path.insert(0, os.path.abspath(video_src))
        from video_core import run_video_profile

        values: list[float] = []
        job = {
            "frame_count": env["FRAME_COUNT"],
            "resolution": env["RESOLUTION"],
            "fps": env["FPS"],
            "frame_stride": env["FRAME_STRIDE"],
            "warmup_frames": env["WARMUP_FRAMES"],
            "measured_frames": env["MEASURED_FRAMES"],
            "work_units": env["WORK_UNITS"],
            "seed": env["SEED"],
        }
        for _ in range(runs):
            result = run_video_profile(job)
            values.append(float(result[profile["metric_key"]]))

        median_val = statistics.median(values)
        std_dev = statistics.stdev(values) if len(values) > 1 else 0.0
        stable = std_dev < median_val * STABILITY_THRESHOLD if median_val > 0 else True
        return {
            "metric_key": profile["metric_key"],
            "operator": profile["operator"],
            "unit": profile["unit"],
            "baseline_value": median_val,
            "raw_values": values,
            "run_count": runs,
            "std_dev": round(std_dev, 4),
            "stable": stable,
            "profile_id": profile["profile_id"],
        }

    matrix_size = int(env["MATRIX_SIZE"])
    batch_count = int(env["BATCH_COUNT"])
    seed = int(env["SEED"])
    warmup = int(env["WARMUP_BATCHES"])
    values: list[float] = []

    from matmul_core import run_matmul

    for _ in range(runs):
        if warmup > 0:
            run_matmul(matrix_size, warmup, seed)
        result = run_matmul(matrix_size, batch_count, seed)
        values.append(result["effective_gflops"])

    median_val = statistics.median(values)
    std_dev = statistics.stdev(values) if len(values) > 1 else 0.0
    stable = std_dev < median_val * STABILITY_THRESHOLD if median_val > 0 else True

    return {
        "metric_key": profile["metric_key"],
        "operator": profile["operator"],
        "unit": profile["unit"],
        "baseline_value": median_val,
        "raw_values": values,
        "run_count": runs,
        "std_dev": round(std_dev, 4),
        "stable": stable,
        "profile_id": profile["profile_id"],
    }


# 兼容旧 API 调用
def run_benchmark(task_type: str, runs: int = 3) -> dict[str, Any]:
    """兼容接口 — 本地执行（供 POST /baselines/run 使用）。"""
    return run_benchmark_local(task_type, runs)
