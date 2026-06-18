#!/usr/bin/env python3
"""E2E demo: compute-only order + user-managed endpoint containers.

The script uses Node Agent HTTP APIs to start endpoint containers on terminal
nodes. This keeps the demo repeatable without SSH, while preserving the real
story: the platform only materializes compute; user endpoints are started
outside the platform instance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any

import requests


TASK_CONFIG = {
    "high_throughput_matmul": {
        "message": "矩阵乘法任务，从 h1 到 h2，256阶矩阵，10批，现在开始跑30分钟，资源保障策略",
        "endpoint_image": "10.112.244.94:5000/scientific-matmul-endpoint:dev",
        "destination_port": 9000,
        "receiver_command": "python /app/src/receiver_main.py --port 9000",
        "source_command": "python /app/src/source_main.py",
        "source_env": {
            "SOURCE_LISTEN": "false",
            "DATA_PROFILE": json.dumps(
                {
                    "matrix_size": 256,
                    "batch_count": 10,
                    "seed": 42,
                    "profile_id": "matmul_user_endpoint_demo",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        },
    },
    "low_latency_video_pipeline": {
        "message": "视频AI推理任务，从 h1 到 h2，720p测试视频，60帧，30fps，低时延转发策略，现在开始跑30分钟",
        "endpoint_image": "10.112.244.94:5000/low-latency-video-endpoint:dev",
        "destination_port": 9100,
        "receiver_command": "python /app/src/receiver_main.py --port 9100",
        "source_command": "python /app/src/source_main.py",
        "source_env": {
            "SOURCE_LISTEN": "false",
            "WAIT_FOR_COMPUTE_READY": "false",
            "DATA_PROFILE": json.dumps(
                {
                    "profile_id": "video_user_endpoint_demo",
                    "resolution": "720p",
                    "frame_count": 60,
                    "fps": 30,
                    "frame_stride": 15,
                    "warmup_frames": 1,
                    "measured_frames": 12,
                    "video_asset": "bottle-detection.mp4",
                    "inference_mode": "yolo_onnx",
                    "model_name": "yolov5n",
                    "confidence_threshold": 0.25,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    },
}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _post(session: requests.Session, url: str, **kwargs: Any) -> dict[str, Any]:
    response = session.post(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {url} failed: HTTP {response.status_code} {response.text}")
    return _json(response)


def _patch(session: requests.Session, url: str, **kwargs: Any) -> dict[str, Any]:
    response = session.patch(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH {url} failed: HTTP {response.status_code} {response.text}")
    return _json(response)


def _patch_public(url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.patch(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH {url} failed: HTTP {response.status_code} {response.text}")
    return _json(response)


def _post_public(url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.post(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {url} failed: HTTP {response.status_code} {response.text}")
    return _json(response)


def _get(session: requests.Session, url: str, **kwargs: Any) -> dict[str, Any]:
    response = session.get(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {url} failed: HTTP {response.status_code} {response.text}")
    return _json(response)


def _find_binding(order: dict[str, Any], src: str, dst: str) -> dict[str, Any]:
    bindings = ((order.get("routing_result") or {}).get("network_bindings") or [])
    for binding in bindings:
        if binding.get("from") == src and binding.get("to") == dst:
            return binding
    raise RuntimeError(f"missing network binding {src}->{dst}: {bindings}")


def _node_by_alias(base: str, session: requests.Session, alias: str) -> dict[str, Any]:
    nodes = _get(session, f"{base}/api/nodes")
    for node in nodes:
        if alias in {node.get("hostname"), node.get("topology_node_id")}:
            return node
    raise RuntimeError(f"node not found: {alias}")


def _agent_base(node: dict[str, Any]) -> str:
    endpoint = str(node.get("agent_address") or "").strip()
    if endpoint:
        return endpoint.rstrip("/")
    return f"http://{node['management_ip']}:8001"


def _agent_request(method: str, node: dict[str, Any], path: str, **kwargs: Any) -> requests.Response:
    url = f"{_agent_base(node)}{path}"
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
    return response


def _preferred_business_address(node: dict[str, Any]) -> str | None:
    return node.get("business_ipv6") or node.get("business_ip")


def _format_url_host(host: str) -> str:
    text = str(host or "").strip()
    return f"[{text}]" if ":" in text and not text.startswith("[") else text


def _format_service_url(host: str, port: int, path: str = "") -> str:
    suffix = path if path.startswith("/") or not path else f"/{path}"
    return f"http://{_format_url_host(host)}:{port}{suffix}"


def _start_endpoint_container(
    *,
    node: dict[str, Any],
    task_id: str,
    node_id: str,
    image: str,
    command: str,
    env: dict[str, str],
) -> None:
    _delete_endpoint_container(node=node, task_id=task_id, node_id=node_id, quiet=True)
    payload = {
        "image": image,
        "command": command,
        "env": env,
        "ports": {},
        "network_mode": "host",
        "restart_policy": "no",
        "pull_policy": "always",
    }
    response = _agent_request(
        "POST",
        node,
        f"/containers/{task_id}/{node_id}/start",
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"start endpoint container failed on {node.get('hostname')}: "
            f"HTTP {response.status_code} {response.text}"
        )


def _receiver_env(node: dict[str, Any], port: int) -> dict[str, str]:
    env: dict[str, str] = {
        "ENDPOINT_PORT": str(port),
    }
    mapping = {
        "ENDPOINT_NODE_ALIAS": node.get("hostname"),
        "ENDPOINT_TOPOLOGY_NODE_ID": node.get("topology_node_id"),
        "ENDPOINT_BUSINESS_IP": node.get("business_ip"),
        "ENDPOINT_BUSINESS_IPV6": node.get("business_ipv6"),
    }
    for key, value in mapping.items():
        if value:
            env[key] = str(value)
    return env


def _delete_endpoint_container(*, node: dict[str, Any], task_id: str, node_id: str, quiet: bool = False) -> None:
    response = _agent_request("DELETE", node, f"/containers/{task_id}/{node_id}", timeout=30)
    if not quiet and response.status_code >= 400:
        print(f"WARN delete {node.get('hostname')} {task_id}/{node_id}: {response.status_code} {response.text}")


def _delete_old_receivers(node: dict[str, Any]) -> None:
    response = _agent_request("GET", node, "/containers/managed", timeout=30)
    if response.status_code >= 400:
        print(f"WARN list old receivers on {node.get('hostname')}: {response.status_code} {response.text}")
        return
    for item in response.json():
        name = str(item.get("container_name") or "")
        if not (name.startswith("user-demo-") and name.endswith("_receiver")):
            continue
        deleted = _agent_request("DELETE", node, f"/managed-containers/{name}", timeout=30)
        if deleted.status_code >= 400:
            print(f"WARN delete old receiver {name}: {deleted.status_code} {deleted.text}")


def _wait_receiver_result(receiver_url: str, order_id: str, timeout_sec: float) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_error = ""
    while time.time() < deadline:
        try:
            response = requests.get(f"{receiver_url}/orders/{order_id}", timeout=10)
            if response.status_code == 200:
                return response.json()
            last_error = f"HTTP {response.status_code} {response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"receiver did not receive order {order_id}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="compute-only + manual endpoint container E2E")
    parser.add_argument("--base-url", default="http://10.112.244.94:8181")
    parser.add_argument("--username", default="user")
    parser.add_argument("--password", default="user")
    parser.add_argument("--task-type", choices=sorted(TASK_CONFIG), default="high_throughput_matmul")
    parser.add_argument("--source-node", default="h1")
    parser.add_argument("--destination-node", default="h2")
    parser.add_argument("--destination-port", type=int)
    parser.add_argument("--compute-nodes", default="compute-1,compute-3")
    parser.add_argument("--gpu-device", default="0")
    parser.add_argument("--wait-seconds", type=float, default=240.0)
    parser.add_argument("--keep-endpoints", action="store_true")
    args = parser.parse_args()

    config = TASK_CONFIG[args.task_type]
    if args.destination_port is None:
        args.destination_port = int(config["destination_port"])
    base = args.base_url.rstrip("/")
    session = requests.Session()

    print("=" * 72)
    print(f"E2E 用户端手动容器演示 task_type={args.task_type}")
    print("=" * 72)

    print("[1/8] 登录")
    login = _post(session, f"{base}/api/auth/login", json={"username": args.username, "password": args.password})
    session.headers["Authorization"] = f"Bearer {login['access_token']}"

    print("[2/8] 查询源端/目的端节点")
    source_node = _node_by_alias(base, session, args.source_node)
    destination_node = _node_by_alias(base, session, args.destination_node)
    source_ip = _preferred_business_address(source_node)
    destination_ip = _preferred_business_address(destination_node)
    _assert(bool(source_ip and destination_ip), "source/destination must have business_ipv6 or business_ip")
    print(f"  source={args.source_node} {source_ip}")
    print(f"  destination={args.destination_node} {_format_url_host(destination_ip)}:{args.destination_port}")

    print("[3/8] 创建对话工单，登记目的端回调端口")
    conv = _post(session, f"{base}/api/conversations", json={"title": f"user-endpoint-{args.task_type}"})
    conv_id = conv["id"]
    _post(session, f"{base}/api/conversations/{conv_id}/messages", json={"content": config["message"]})
    patched = _patch(
        session,
        f"{base}/api/conversations/{conv_id}/draft",
        json={
            "source_endpoint_input": args.source_node,
            "destination_endpoint_input": args.destination_node,
            "destination_port": args.destination_port,
        },
    )
    draft = patched.get("latest_draft") or {}
    _assert(draft.get("parse_status") == "valid", f"draft invalid: {draft.get('validation_errors')}")
    expected_callback_url = _format_service_url(destination_ip, args.destination_port, "/callback")
    _assert(
        draft.get("callback_url") == expected_callback_url,
        f"draft callback_url mismatch: expected {expected_callback_url}, got {draft.get('callback_url')}",
    )
    confirmed = _post(session, f"{base}/api/conversations/{conv_id}/confirm-intent")
    order_id = confirmed.get("materialized_order_id")
    _assert(bool(order_id), "confirm-intent did not create order")
    print(f"  order_id={order_id}")

    print("[4/8] 启动目的端 receiver 容器")
    demo_task_id = f"user-demo-{order_id[:8]}"
    receiver_url = _format_service_url(destination_ip, args.destination_port)
    _delete_old_receivers(destination_node)
    _start_endpoint_container(
        node=destination_node,
        task_id=demo_task_id,
        node_id="receiver",
        image=config["endpoint_image"],
        command=config["receiver_command"],
        env=_receiver_env(destination_node, args.destination_port),
    )
    print(f"  receiver={receiver_url}/")

    print("[5/8] 路由回写并物化 compute-only 实例")
    _patch_public(f"{base}/api/routing-orders/{order_id}/claim")
    route_body = None
    candidates = [item.strip() for item in args.compute_nodes.split(",") if item.strip()]
    _assert(bool(candidates), "compute candidates cannot be empty")
    for index, compute_node in enumerate(candidates):
        if index > 0:
            _patch_public(f"{base}/api/routing-orders/{order_id}/requeue", json={"reason": "retry candidate"})
            _patch_public(f"{base}/api/routing-orders/{order_id}/claim")
        response = requests.post(
            f"{base}/api/routing-orders/{order_id}/result",
            json={
                "placements": [
                    {"task_node_id": "compute", "topology_node_id": compute_node, "gpu_device": args.gpu_device}
                ],
                "strategy": "resource_guarantee",
                "metadata": {"source": "e2e_user_endpoint_manual_containers", "candidate": compute_node},
            },
            timeout=180,
        )
        if response.status_code == 200:
            route_body = response.json()
            print(f"  placement={compute_node}:gpu{args.gpu_device}")
            break
        conflict = response.status_code == 409 and re.search(r"GPU slot conflict", response.text or "")
        if conflict and index + 1 < len(candidates):
            print(f"  skip {compute_node}:gpu{args.gpu_device} conflict")
            continue
        raise RuntimeError(f"routing result failed on {compute_node}: HTTP {response.status_code} {response.text}")
    _assert(route_body is not None, "no route result")
    compute_binding = next(
        (item for item in route_body.get("network_bindings", []) if item.get("from") == "source" and item.get("to") == "compute"),
        None,
    )
    _assert(compute_binding and compute_binding.get("dst_access_url"), f"missing compute access binding: {route_body}")
    compute_url = str(compute_binding["dst_access_url"]).rstrip("/")
    print(f"  compute_url={compute_url}")
    if route_body.get("network_ready_required"):
        _post_public(
            f"{base}/api/routing-orders/{order_id}/network-ready",
            json={"metadata": {"source": "e2e_user_endpoint_manual_containers"}, "auto_start": False},
            timeout=60,
        )
        print("  network-ready=confirmed")

    print("[6/8] 启动 compute 实例")
    order = _get(session, f"{base}/api/orders/{order_id}")
    instance_id = order.get("materialized_instance_id")
    _assert(bool(instance_id), f"order has no materialized_instance_id: {order}")
    _post(session, f"{base}/api/instances/{instance_id}/start", timeout=180)

    print("[7/8] 启动源端 source 容器提交输入")
    source_env = {
        "PEER_COMPUTE_URL": compute_url,
        "ORDER_ID": order_id,
        "TASK_INSTANCE_ID": instance_id,
        "TASK_TYPE": args.task_type,
        **config["source_env"],
    }
    _start_endpoint_container(
        node=source_node,
        task_id=demo_task_id,
        node_id="source",
        image=config["endpoint_image"],
        command=config["source_command"],
        env=source_env,
    )

    print("[8/8] 等待 receiver 收到结果")
    result = _wait_receiver_result(receiver_url, order_id, args.wait_seconds)
    payload = result.get("payload") or {}
    metric_key = payload.get("metric_key")
    metric_value = (payload.get("result") or {}).get(metric_key)
    print(json.dumps({
        "order_id": order_id,
        "instance_id": instance_id,
        "compute_url": compute_url,
        "receiver_page": f"{receiver_url}/",
        "metric_key": metric_key,
        "metric_value": metric_value,
    }, ensure_ascii=False, indent=2))

    if not args.keep_endpoints:
        _delete_endpoint_container(node=source_node, task_id=demo_task_id, node_id="source", quiet=True)
        _delete_endpoint_container(node=destination_node, task_id=demo_task_id, node_id="receiver", quiet=True)

    print("=" * 72)
    print("OK 用户端手动容器演示 E2E passed")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
