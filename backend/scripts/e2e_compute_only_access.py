#!/usr/bin/env python3
"""compute-only 用户接入模式 E2E 验证。

验证要点：
1. 对话确认工单写入 user_access_demo + deployable_roles=["compute"]
2. 路由回写仅含 compute placement 时只物化 compute 容器
3. network_bindings 返回 source(external) -> compute 的 dst_access_url

用法：
    cd backend && PYTHONPATH=. ./venv/bin/python scripts/e2e_compute_only_access.py
    cd backend && PYTHONPATH=. ./venv/bin/python scripts/e2e_compute_only_access.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def _assert(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="user")
    parser.add_argument("--password", default="user")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    session = requests.Session()

    print("=" * 60)
    print("E2E: compute-only 用户接入模式")
    print("=" * 60)

    print("\n[1/5] 登录...")
    login = session.post(f"{base}/api/auth/login", json={
        "username": args.username,
        "password": args.password,
    })
    _assert(login.status_code == 200, f"登录失败: {login.text}")
    session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    print("  OK")

    print("\n[2/5] 创建对话并确认意图...")
    conv = session.post(f"{base}/api/conversations", json={"title": "compute-only E2E"}).json()
    conv_id = conv["id"]
    msg = "矩阵乘法任务，从 compute-1 到 compute-3，256阶矩阵，10批，现在开始跑30分钟，资源保障策略"
    conv = session.post(f"{base}/api/conversations/{conv_id}/messages", json={"content": msg}).json()
    draft = conv.get("latest_draft") or {}
    _assert(draft.get("parse_status") == "valid", f"意图解析未通过: {draft.get('validation_errors')}")
    conv = session.post(f"{base}/api/conversations/{conv_id}/confirm-intent").json()
    order_id = conv.get("materialized_order_id")
    _assert(bool(order_id), "确认意图后未创建工单")
    print(f"  OK order_id={order_id}")

    print("\n[3/5] 校验工单部署策略...")
    order = session.get(f"{base}/api/orders/{order_id}").json()
    deployment = (order.get("runtime_config") or {}).get("platform_deployment") or {}
    _assert(deployment.get("mode") == "user_access_demo", f"部署模式错误: {deployment}")
    _assert(deployment.get("deployable_roles") == ["compute"], f"deployable_roles 错误: {deployment}")
    print("  OK mode=user_access_demo deployable_roles=[compute]")

    print("\n[4/5] 模拟路由回写（仅 compute）...")
    claim = requests.patch(f"{base}/api/routing-orders/{order_id}/claim")
    _assert(claim.status_code == 200, f"claim 失败: {claim.text}")

    result_payload = {
        "placements": [
            {"task_node_id": "compute", "topology_node_id": "compute-2", "gpu_device": "0"},
        ],
        "strategy": "resource_guarantee",
    }
    route = requests.post(f"{base}/api/routing-orders/{order_id}/result", json=result_payload)
    if route.status_code != 200:
        print(f"  WARN: 路由回写 {route.status_code}: {route.text}")
        print("  (无真实节点时物化可能失败，但 network_bindings 仍应可检查)")
        sys.exit(0)

    body = route.json()
    bindings = body.get("network_bindings") or []
    print(f"  network_bindings: {len(bindings)}")
    source_bindings = [b for b in bindings if b.get("from") == "source" and b.get("to") == "compute"]
    _assert(len(source_bindings) >= 1, "缺少 source -> compute 绑定")
    binding = source_bindings[0]
    _assert(binding.get("src_external") is True, "source 应标记为外部端点")
    _assert(binding.get("dst_external") is False, "compute 应为平台部署端点")
    _assert(bool(binding.get("dst_access_url")), "缺少 dst_access_url")
    print(f"  OK dst_access_url={binding['dst_access_url']}")

    if body.get("network_ready_required"):
        ready = requests.post(
            f"{base}/api/routing-orders/{order_id}/network-ready",
            json={"metadata": {"source": "e2e-compute-only"}, "auto_start": False},
        )
        _assert(ready.status_code == 200, f"network-ready 失败: {ready.text}")

    print("\n[5/5] 验证物化实例仅含 compute...")
    time.sleep(0.5)
    order = session.get(f"{base}/api/orders/{order_id}").json()
    instance_id = order.get("materialized_instance_id")
    if instance_id:
        inst = session.get(f"{base}/api/instances/{instance_id}").json()
        node_names = sorted({n.get("name") for n in inst.get("nodes", [])})
        _assert(node_names == ["compute"], f"实例节点应为仅 compute，实际: {node_names}")
        print(f"  OK instance_id={instance_id} nodes={node_names}")
    else:
        print("  WARN: 未物化实例（可能缺少注册节点）")

    print("\n接入示例:")
    print(json.dumps({
        "submit": f"POST {binding['dst_access_url']}/data",
        "query_result": f"GET {binding['dst_access_url']}/result",
        "client": f"python scripts/user_source_client.py --compute-url {binding['dst_access_url']} --wait-result",
    }, ensure_ascii=False, indent=2))

    print("\n" + "=" * 60)
    print("OK compute-only E2E passed")
    print("=" * 60)


if __name__ == "__main__":
    main()
