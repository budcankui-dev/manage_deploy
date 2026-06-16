#!/usr/bin/env python3
"""Minimal external-router mock for local integration.

The script uses the frozen order-based routing protocol:
GET /api/routing-orders -> PATCH /claim -> POST /result -> POST /network-ready.
It intentionally emits only the current placement format:
task_node_id/topology_node_id/gpu_device.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests


def extract_fixed_endpoint(order: dict[str, Any], role: str) -> str | None:
    dag = order.get("routing_input_dag") or {}
    nodes = dag.get("nodes") if isinstance(dag, dict) else []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("task_node_id") or "").lower() == role.lower():
            value = node.get("fixed_topology_node_id")
            return str(value) if value else None
    fallback_key = "source_name" if role.lower() == "source" else "destination_name"
    value = order.get(fallback_key)
    return str(value) if value else None


def build_result_payload(
    order: dict[str, Any],
    *,
    compute_node: str,
    gpu_device: str | None = "0",
    algorithm_version: str = "mock-external-router",
    require_network_ready: bool = True,
) -> dict[str, Any]:
    dag = order.get("routing_input_dag") or {}
    strategy = dag.get("routing_strategy") if isinstance(dag, dict) else None
    if not strategy:
        strategy = "resource_guarantee"

    placement = {"task_node_id": "compute", "topology_node_id": compute_node}
    if gpu_device is not None and str(gpu_device) != "":
        placement["gpu_device"] = str(gpu_device)

    source = extract_fixed_endpoint(order, "source")
    sink = extract_fixed_endpoint(order, "sink")
    path = [item for item in (source, compute_node, sink) if item]

    return {
        "strategy": strategy,
        "selected_strategy": "MOCK_GPU_EXCLUSIVE_FIRST_FIT",
        "external_routing_id": f"mock-router-{order.get('order_id')}",
        "placements": [placement],
        "metadata": {
            "path": path,
            "selected_reason": "local mock router selected the configured compute node",
            "algorithm_version": algorithm_version,
        },
        "require_network_ready": require_network_ready,
    }


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> tuple[int, Any]:
    response = session.request(method, url, timeout=timeout, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def _print_json(label: str, value: Any) -> None:
    print(f"\n{label}")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def run(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    session = requests.Session()
    params: dict[str, Any] = {"status": "pending", "limit": args.limit}
    if args.benchmark_run_id:
        params["benchmark_run_id"] = args.benchmark_run_id
    if args.task_type:
        params["task_type"] = args.task_type

    status, orders = _request_json(
        session,
        "GET",
        f"{base_url}/api/routing-orders",
        params=params,
        timeout=args.timeout,
    )
    if status != 200:
        _print_json("读取待路由工单失败", orders)
        return 1
    if not isinstance(orders, list):
        _print_json("待路由工单响应格式异常", orders)
        return 1
    if args.dry_run:
        _print_json("待路由工单（dry-run）", orders)
        return 0
    if not orders:
        print("没有 pending 路由工单。")
        return 0

    ok = 0
    failed: list[dict[str, Any]] = []
    compute_nodes = [item.strip() for item in args.compute_nodes.split(",") if item.strip()]
    if not compute_nodes:
        print("compute node candidate list is empty", file=sys.stderr)
        return 2

    for index, order in enumerate(orders):
        order_id = order.get("order_id")
        if not order_id:
            failed.append({"order": order, "error": "missing order_id"})
            continue

        claim_status, claim_body = _request_json(
            session,
            "PATCH",
            f"{base_url}/api/routing-orders/{order_id}/claim",
            timeout=args.timeout,
        )
        if claim_status == 409:
            print(f"跳过已被其他路由进程领取的工单: {order_id}")
            continue
        if claim_status != 200:
            failed.append({"order_id": order_id, "step": "claim", "status": claim_status, "body": claim_body})
            continue

        compute_node = compute_nodes[index % len(compute_nodes)]
        payload = build_result_payload(
            order,
            compute_node=compute_node,
            gpu_device=args.gpu_device,
            algorithm_version=args.algorithm_version,
            require_network_ready=not args.skip_network_ready,
        )
        result_status, result_body = _request_json(
            session,
            "POST",
            f"{base_url}/api/routing-orders/{order_id}/result",
            json=payload,
            timeout=args.timeout,
        )
        if result_status != 200:
            failed.append({"order_id": order_id, "step": "result", "status": result_status, "body": result_body})
            continue

        _print_json(f"工单 {order_id} 路由回写结果", result_body)

        if result_body.get("network_ready_required"):
            ready_status, ready_body = _request_json(
                session,
                "POST",
                f"{base_url}/api/routing-orders/{order_id}/network-ready",
                json={
                    "metadata": {
                        "source": "mock_external_router.py",
                        "flow_rule_count": len(result_body.get("network_bindings") or []),
                    },
                    "auto_start": args.auto_start,
                },
                timeout=args.timeout,
            )
            if ready_status != 200:
                failed.append({"order_id": order_id, "step": "network-ready", "status": ready_status, "body": ready_body})
                continue
            _print_json(f"工单 {order_id} 网络就绪结果", ready_body)

        ok += 1

    if failed:
        _print_json("失败项", failed)
    print(f"\n处理完成：成功 {ok}，失败 {len(failed)}。")
    return 0 if not failed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen order-based routing mock.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--benchmark-run-id")
    parser.add_argument("--task-type")
    parser.add_argument("--compute-nodes", default="compute-1,compute-2,compute-3")
    parser.add_argument("--gpu-device", default="0")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--algorithm-version", default="mock-external-router")
    parser.add_argument("--auto-start", action="store_true")
    parser.add_argument("--skip-network-ready", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
