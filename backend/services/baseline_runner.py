"""Baseline benchmark runner — 容器化执行，保证和实际任务环境一致。

执行流程：
1. 通过 Node Agent 在目标节点启动临时 worker 容器（BENCHMARK_MODE=true）
2. 容器跑完后从日志收集业务过程性指标
3. 重复 N 次，取中位数
4. 校验标准差 < 中位数 10%（稳定性）
5. 返回结果
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

from services.deployment_profile import image_ref

logger = logging.getLogger(__name__)

# 固定基准测试参数（测试方案规定，不可变）
BENCHMARK_PROFILES = {
    "high_throughput_matmul": {
        "metric_key": "effective_gflops",
        "operator": ">=",
        "unit": "GFLOPS",
        "image": image_ref("scientific-matmul"),
        "command": "python3 /app/src/compute_main.py",
        "env": {
            "BENCHMARK_MODE": "true",
            "USE_GPU": "true",
            "GPU_DEVICE": "0",
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
        "gpu_id": "0",
        "profile_id": "gpu_standard",
    },
    "low_latency_video_pipeline": {
        "metric_key": "frame_latency_p90_ms",
        "operator": "<=",
        "unit": "ms",
        "image": image_ref("low-latency-video"),
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
        "gpu_id": "0",
        "profile_id": "video_industrial_inspection_720p",
        "warmup_runs": 3,
    },
}

STABILITY_THRESHOLD = 0.10  # 标准差 < 中位数 × 10%

DIAGNOSTIC_KEYS = (
    "backend",
    "actual_backend",
    "detector_backend",
    "device",
    "model_name",
    "gpu_device",
    "gpu_requested",
    "gpu_available",
    "gpu_assigned",
    "gpu_error",
    "frame_latency_avg_ms",
    "frame_latency_min_ms",
    "frame_latency_max_ms",
    "measured_frames",
    "annotated_frame_index",
    "effective_gflops",
    "matrix_size",
    "batch_count",
    "backend_note",
)


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
    gpu_id = profile.get("gpu_id")
    warmup_runs = int(profile.get("warmup_runs", 0) or 0)
    values: list[float] = []
    run_diagnostics: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(warmup_runs):
            container_name = f"baseline-{task_type}-warmup{i}-{int(time.time())}"
            await _run_single_benchmark(
                client,
                agent_address,
                image,
                env,
                container_name,
                profile["metric_key"],
                command,
                gpu_id,
            )
            logger.info("Baseline warmup run %s/%s completed", i + 1, warmup_runs)
        for i in range(runs):
            container_name = f"baseline-{task_type}-run{i}-{int(time.time())}"
            result_payload = await _run_single_benchmark(
                client,
                agent_address,
                image,
                env,
                container_name,
                profile["metric_key"],
                command,
                gpu_id,
            )
            metric_value = float(result_payload[profile["metric_key"]])
            values.append(metric_value)
            run_diagnostics.append(
                _summarize_run_diagnostics(i + 1, result_payload, profile["metric_key"])
            )
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
        "diagnostics": _build_diagnostics(
            task_type=task_type,
            profile=profile,
            image=image,
            command=command,
            gpu_id=gpu_id,
            env=env,
            run_diagnostics=run_diagnostics,
        ),
    }


async def _run_single_benchmark(
    client: httpx.AsyncClient,
    agent_address: str,
    image: str,
    env: dict[str, str],
    container_name: str,
    metric_key: str,
    command: str | None = None,
    gpu_id: str | None = None,
) -> dict[str, Any]:
    """启动一个临时容器执行基准测试并收集结果。"""
    base_url = agent_address.rstrip("/")
    task_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())

    # 1. 创建容器
    create_payload = {
        "image": image,
        "command": command,
        "env": env,
        "gpu_id": gpu_id,
        "network_mode": "host",
        "restart_policy": "no",
        "pull_policy": "always",
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
    result = _parse_benchmark_payload(logs_text)
    if result is None:
        raise RuntimeError("无法从容器日志解析基准测试结果")
    _validate_benchmark_result(result, metric_key)
    return result


def _parse_benchmark_result(logs: str, metric_key: str = "effective_gflops") -> float:
    """从容器日志中解析 benchmark_result JSON。"""
    result = _parse_benchmark_payload(logs)
    if result is None:
        raise RuntimeError(f"无法从容器日志解析基准测试结果")
    _validate_benchmark_result(result, metric_key)
    return float(result[metric_key])


def _summarize_run_diagnostics(
    run_index: int,
    result: dict[str, Any],
    metric_key: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "run_index": run_index,
        "metric_key": metric_key,
        "metric_value": float(result[metric_key]),
    }
    for key in DIAGNOSTIC_KEYS:
        if key in result:
            summary[key] = result.get(key)
    return summary


def _build_diagnostics(
    *,
    task_type: str,
    profile: dict[str, Any],
    image: str,
    command: str | None,
    gpu_id: str | None,
    env: dict[str, str],
    run_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    backends = sorted(
        {
            str(run.get("actual_backend") or run.get("backend") or run.get("detector_backend"))
            for run in run_diagnostics
            if run.get("actual_backend") or run.get("backend") or run.get("detector_backend")
        }
    )
    devices = sorted({str(run.get("device")) for run in run_diagnostics if run.get("device")})
    gpu_errors = [str(run.get("gpu_error")) for run in run_diagnostics if run.get("gpu_error")]
    profile_env_keys = (
        "MATRIX_SIZE",
        "BATCH_COUNT",
        "OBSERVATION_DURATION_SEC",
        "SAMPLE_BATCH_COUNT",
        "FRAME_COUNT",
        "FRAME_STRIDE",
        "WARMUP_FRAMES",
        "MEASURED_FRAMES",
        "VIDEO_INFERENCE_MODE",
        "VIDEO_MODEL_NAME",
        "VIDEO_MODEL_PATH",
        "VIDEO_ASSET",
        "USE_GPU",
    )
    return {
        "task_type": task_type,
        "profile_id": profile["profile_id"],
        "metric_key": profile["metric_key"],
        "operator": profile["operator"],
        "unit": profile["unit"],
        "image": image,
        "command": command,
        "gpu_id": gpu_id,
        "warmup_runs": int(profile.get("warmup_runs", 0) or 0),
        "stability_threshold": STABILITY_THRESHOLD,
        "profile_env": {key: env.get(key) for key in profile_env_keys if key in env},
        "actual_backends": backends,
        "devices": devices,
        "gpu_errors": gpu_errors,
        "runs": run_diagnostics,
    }


def _parse_benchmark_payload(logs: str) -> dict[str, Any] | None:
    """从容器日志中解析 benchmark_result 原始 JSON。"""
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
                result = data.get("benchmark_result")
                return result if isinstance(result, dict) else None
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _validate_benchmark_result(result: dict[str, Any], metric_key: str) -> None:
    if metric_key not in result:
        raise RuntimeError(f"基准测试结果缺少指标字段: {metric_key}")

    # 正式验收基线必须和业务任务一致，不能把 CPU fallback 写入节点基线。
    if metric_key == "effective_gflops":
        backend = str(result.get("backend") or "")
        if backend != "cupy_gpu":
            raise RuntimeError(
                "矩阵计算基线未使用 GPU CuPy 路径，不能作为正式验收基线；"
                f"backend={backend or '-'}, gpu_device={result.get('gpu_device')}"
            )
        return

    # 视频正式验收基线必须和业务任务一致：YOLO 推理 + GPU 后端。
    # CPU / deterministic_surrogate 只能用于本地开发兜底，不能写入正式节点基线。
    if metric_key != "frame_latency_p90_ms":
        return
    backend = str(result.get("actual_backend") or result.get("backend") or result.get("detector_backend") or "")
    device = str(result.get("device") or "")
    model_name = str(result.get("model_name") or "")
    if backend not in {"onnxruntime_cuda", "opencv_dnn_cuda"} or not device.startswith("cuda"):
        raise RuntimeError(
            "视频基线未使用 GPU YOLO 推理路径，不能作为正式验收基线；"
            f"actual_backend={backend or '-'}, device={device or '-'}, "
            f"gpu_requested={result.get('gpu_requested')}, gpu_available={result.get('gpu_available')}, "
            f"gpu_error={result.get('gpu_error')}"
        )
    if "yolo" not in model_name.lower():
        raise RuntimeError(f"视频基线模型不是 YOLO: model_name={model_name or '-'}")


# ---- Local fallback（仅开发调试；正式验收不允许写入 CPU/兜底基线）----

def run_benchmark_local(task_type: str, runs: int = 3) -> dict[str, Any]:
    """本地执行基准测试。

    该路径只用于开发调试。结果仍会经过 GPU/YOLO 校验，避免 CPU 或
    deterministic fallback 被保存为正式节点基线。
    """
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
            _validate_benchmark_result(result, profile["metric_key"])
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
        _validate_benchmark_result(result, profile["metric_key"])
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
    """兼容接口 — 本地开发调试用；正式验收应调用远程容器基线。"""
    return run_benchmark_local(task_type, runs)
