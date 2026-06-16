#!/usr/bin/env python3
"""轻量用户端 source 客户端：向 compute-only 工单的 compute 接入地址提交任务。

用法示例：

  # 直接指定 compute 基址
  python scripts/user_source_client.py \\
    --compute-url http://10.10.1.2:18801 \\
    --task-type high_throughput_matmul \\
    --matrix-size 256 --batch-count 10 --seed 42

  # 从工单 API 读取 network_bindings（需登录 token）
  python scripts/user_source_client.py \\
    --base-url http://127.0.0.1:8000 \\
    --order-id <order-uuid> \\
    --token <access_token>

  # 提交后轮询 GET /result
  python scripts/user_source_client.py --compute-url http://10.10.1.2:18801 --wait-result
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import requests


def _find_source_to_compute_binding(order: dict) -> dict | None:
    routing = order.get("routing_result") or {}
    bindings = routing.get("network_bindings") or []
    for item in bindings:
        if item.get("from") == "source" and item.get("to") == "compute" and item.get("dst_access_url"):
            return item
    return None


def _build_job(args: argparse.Namespace) -> dict[str, Any]:
    if args.task_type == "low_latency_video_pipeline":
        return {
            "profile_id": args.profile_id or "video_user_demo",
            "resolution": args.resolution,
            "fps": args.fps,
            "frame_count": args.frame_count,
            "frame_stride": args.frame_stride,
            "seed": args.seed,
        }
    return {
        "matrix_size": args.matrix_size,
        "batch_count": args.batch_count,
        "seed": args.seed,
        "profile_id": args.profile_id or "matmul_user_demo",
    }


def _resolve_compute_url(args: argparse.Namespace, session: requests.Session) -> str:
    if args.compute_url:
        return args.compute_url.rstrip("/")
    if not args.order_id:
        raise SystemExit("请提供 --compute-url 或 --order-id")
    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    base = args.base_url.rstrip("/")
    response = session.get(f"{base}/api/orders/{args.order_id}", headers=headers, timeout=30)
    response.raise_for_status()
    binding = _find_source_to_compute_binding(response.json())
    if not binding:
        raise SystemExit("工单未找到 source -> compute 接入地址，请确认路由已完成且 deployable_roles 含 compute")
    return str(binding["dst_access_url"]).rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="用户端轻量 source：向 compute POST /data")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--compute-url", help="compute 接入基址，如 http://10.10.1.2:18801")
    parser.add_argument("--order-id", help="从工单 routing_result.network_bindings 解析接入地址")
    parser.add_argument("--token", help="访问 /api/orders 的 Bearer token")
    parser.add_argument("--task-type", default="high_throughput_matmul",
                        choices=["high_throughput_matmul", "low_latency_video_pipeline"])
    parser.add_argument("--matrix-size", type=int, default=256)
    parser.add_argument("--batch-count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--frame-count", type=int, default=30)
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--wait-result", action="store_true", help="提交后轮询 GET /result")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    args = parser.parse_args()

    session = requests.Session()
    compute_url = _resolve_compute_url(args, session)
    job = _build_job(args)

    print(f"POST {compute_url}/data")
    print(json.dumps(job, ensure_ascii=False, indent=2))
    post = session.post(f"{compute_url}/data", json=job, timeout=120)
    if post.status_code >= 400:
        print(f"提交失败: HTTP {post.status_code} {post.text}", file=sys.stderr)
        return 1
    print("提交成功")

    if not args.wait_result:
        print(f"可用 GET {compute_url}/result 查询结果")
        return 0

    deadline = time.time() + args.poll_timeout
    while time.time() < deadline:
        result = session.get(f"{compute_url}/result", timeout=30)
        if result.status_code == 200:
            payload = result.json()
            print("结果:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        time.sleep(args.poll_interval)

    print("轮询 /result 超时", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
