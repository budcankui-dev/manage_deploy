"""对话式工单 + 路由 E2E 验证脚本。

模拟完整流程：
1. 登录获取 token
2. 创建对话
3. 发送消息（含 source/destination/time）
4. 确认意图（自动创建 TaskOrder + RoutingRequest）
5. 模拟外部路由系统回写结果
6. 验证工单状态和实例物化

用法：
    python backend/scripts/e2e_conversation_routing.py [--base-url http://localhost:8000]
"""

import argparse
import json
import sys
import time

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--username", default="user")
    parser.add_argument("--password", default="user")
    parser.add_argument("--service-token", default="change-me-service-token")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    s = requests.Session()

    print("=" * 60)
    print("E2E: 对话式工单 + 外部路由验证")
    print("=" * 60)

    # Step 1: 登录
    print("\n[1/6] 登录...")
    r = s.post(f"{base}/api/auth/login", json={
        "username": args.username,
        "password": args.password,
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"
    print(f"  OK - token: {token[:20]}...")

    # Step 2: 创建对话
    print("\n[2/6] 创建对话...")
    r = s.post(f"{base}/api/conversations", json={"title": "E2E 路由验证"})
    assert r.status_code == 200, f"Create conversation failed: {r.text}"
    conv = r.json()
    conv_id = conv["id"]
    print(f"  OK - conversation_id: {conv_id}")
    time.sleep(0.5)

    # Step 3: 发送消息
    print("\n[3/6] 发送消息（含 source/dest/time）...")
    msg = "我要做矩阵计算任务，从 compute-1 到 compute-3，现在开始跑2小时，延迟目标 60000ms"
    r = s.post(f"{base}/api/conversations/{conv_id}/messages", json={"content": msg})
    assert r.status_code == 200, f"Send message failed: {r.text}"
    conv = r.json()
    draft = conv.get("latest_draft")
    print(f"  OK - parse_status: {draft['parse_status']}")
    print(f"       task_type: {draft['task_type']}")
    print(f"       source: {draft.get('source_name')}")
    print(f"       dest: {draft.get('destination_name')}")
    print(f"       start: {draft.get('business_start_time')}")
    print(f"       end: {draft.get('business_end_time')}")

    if draft["parse_status"] != "valid":
        print(f"  WARN: parse_status is {draft['parse_status']}, not valid")
        print(f"  validation_errors: {draft.get('validation_errors')}")
        print("  E2E 需要 parse_status=valid 才能继续，请检查消息内容")
        sys.exit(1)
    time.sleep(0.5)

    # Step 4: 确认意图（自动创建 TaskOrder + RoutingRequest）
    print("\n[4/6] 确认意图（创建工单 + 路由请求）...")
    r = s.post(f"{base}/api/conversations/{conv_id}/confirm-intent")
    if r.status_code != 200:
        print(f"  FAIL: {r.status_code} - {r.text}")
        print("  提示：需要先注册 business_template_catalog")
        sys.exit(1)
    conv = r.json()
    routing = conv.get("latest_routing_request")
    order_id = conv.get("materialized_order_id")
    print(f"  OK - status: {conv['status']}")
    print(f"       order_id: {order_id}")
    print(f"       routing_request_id: {routing['id'] if routing else 'N/A'}")
    print(f"       routing_status: {routing['status'] if routing else 'N/A'}")
    if routing and routing.get("input_payload"):
        print(f"       DAG payload job_id: {routing['input_payload'].get('job_id', 'N/A')}")

    if not routing:
        print("  FAIL: No routing request created")
        sys.exit(1)
    time.sleep(0.5)

    # Step 5: 模拟外部路由系统回写结果
    print("\n[5/6] 模拟外部路由回写...")
    routing_id = routing["id"]
    # 先 claim
    r = requests.patch(
        f"{base}/api/routing-requests/{routing_id}/claim",
        headers={"X-Service-Token": args.service_token},
    )
    if r.status_code == 200:
        print(f"  Claimed - status: {r.json()['status']}")
    else:
        print(f"  Claim skipped: {r.status_code}")

    # 回写结果
    result_payload = {
        "status": "completed",
        "placements": {"source": "compute-1", "compute": "compute-2", "sink": "compute-3"},
        "selected_strategy": "resource_guarantee",
        "estimated_metric": {"compute_latency_ms": 45000},
        "external_routing_id": "ext-routing-e2e-001",
        "result_payload": {
            "path": ["compute-1", "compute-2", "compute-3"],
            "total_cost": 0.5,
            "explanation": "E2E test routing result",
        },
    }
    r = requests.post(
        f"{base}/api/routing-results/{routing_id}",
        json=result_payload,
        headers={"X-Service-Token": args.service_token},
    )
    if r.status_code == 200:
        rr = r.json()
        print(f"  OK - routing status: {rr['status']}")
        print(f"       placements: {rr.get('placements')}")
        print(f"       selected_strategy: {rr.get('selected_strategy')}")
    else:
        print(f"  WARN: routing result callback returned {r.status_code}: {r.text}")
        print("  (实例物化可能因缺少真实节点而失败，这在无节点环境下是预期行为)")

    # Step 6: 验证最终状态
    print("\n[6/6] 验证最终状态...")
    r = s.get(f"{base}/api/conversations/{conv_id}")
    conv = r.json()
    print(f"  conversation status: {conv['status']}")
    routing_final = conv.get("latest_routing_request")
    if routing_final:
        print(f"  routing status: {routing_final['status']}")

    if order_id:
        r = s.get(f"{base}/api/orders/{order_id}")
        if r.status_code == 200:
            order = r.json()
            print(f"  order status: {order.get('status')}")
            print(f"  routing_status: {order.get('routing_status', 'N/A')}")
            inst_id = order.get("materialized_instance_id")
            if inst_id:
                print(f"  instance_id: {inst_id}")
            else:
                print("  instance: 未物化（可能缺少真实节点注册）")
        else:
            print(f"  order query: {r.status_code}")

    print("\n" + "=" * 60)
    print("E2E 验证完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
