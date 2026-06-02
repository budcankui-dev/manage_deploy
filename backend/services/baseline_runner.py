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
import time
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
        "env": {
            "BENCHMARK_MODE": "true",
            "MATRIX_SIZE": "1024",
            "BATCH_COUNT": "50",
            "SEED": "42",
            "WARMUP_BATCHES": "3",
        },
        "profile_id": "cpu_standard",
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
    env = dict(profile["env"])
    values: list[float] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(runs):
            container_name = f"baseline-{task_type}-run{i}-{int(time.time())}"
            gflops = await _run_single_benchmark(
                client, agent_address, image, env, container_name
            )
            values.append(gflops)
            logger.info(f"Baseline run {i+1}/{runs}: {gflops:.2f} GFLOPS")

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
) -> float:
    """启动一个临时容器执行基准测试并收集结果。"""
    base_url = agent_address.rstrip("/")

    # 1. 创建容器
    create_payload = {
        "image": image,
        "env": env,
        "network_mode": "host",
        "restart_policy": "no",
    }
    resp = await client.post(
        f"{base_url}/containers/start",
        json=create_payload,
        params={"name": container_name},
    )
    resp.raise_for_status()
    container_id = resp.json().get("container_id") or resp.json().get("id")

    # 2. 等待容器退出（轮询状态）
    for _ in range(120):  # max 120s
        time.sleep(1)
        status_resp = await client.get(f"{base_url}/containers/{container_name}/status")
        if status_resp.status_code == 200:
            status = status_resp.json().get("status", "")
            if status in ("exited", "stopped", "dead"):
                break
    else:
        # 超时，强制停止
        await client.post(f"{base_url}/containers/{container_name}/stop")

    # 3. 收集日志
    logs_resp = await client.get(f"{base_url}/containers/{container_name}/logs")
    logs_text = logs_resp.text if logs_resp.status_code == 200 else ""

    # 4. 删除容器
    await client.delete(f"{base_url}/containers/{container_name}")

    # 5. 解析结果
    return _parse_benchmark_result(logs_text)


def _parse_benchmark_result(logs: str) -> float:
    """从容器日志中解析 benchmark_result JSON。"""
    for line in logs.splitlines():
        line = line.strip()
        if "benchmark_result" in line:
            try:
                data = json.loads(line)
                return float(data["benchmark_result"]["effective_gflops"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    raise RuntimeError(f"无法从容器日志解析基准测试结果")


# ---- Local fallback（单机演示场景，Node Agent 不可达时使用）----

def run_benchmark_local(task_type: str, runs: int = 3) -> dict[str, Any]:
    """本地执行基准测试（fallback，不通过容器）。"""
    import sys
    import os
    _WORKER_SRC = os.path.join(
        os.path.dirname(__file__), "../../workers/high-throughput-matmul/src"
    )
    if _WORKER_SRC not in sys.path:
        sys.path.insert(0, os.path.abspath(_WORKER_SRC))

    if task_type not in BENCHMARK_PROFILES:
        raise ValueError(f"不支持的任务类型: {task_type}")

    profile = BENCHMARK_PROFILES[task_type]
    env = profile["env"]

    for k, v in env.items():
        os.environ.setdefault(k, v)

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
