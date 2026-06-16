"""End-to-end matmul test with new image."""
import asyncio, os, sys
sys.path.insert(0, ".")

import httpx

BASE = "http://localhost:8000"
AGENT_C1 = "http://10.112.249.191:8001"
AGENT_C2 = "http://10.112.150.166:8001"

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # Clean up any running instances to free ports
        instances = (await c.get("/api/instances?limit=20", headers=h)).json()
        items = instances if isinstance(instances, list) else instances.get("items", [])
        for inst in items:
            if inst["status"] in ("running", "scheduled", "pending") and "matmul" in inst.get("name", "").lower():
                await c.post(f"/api/instances/{inst['id']}/stop", headers=h)
                await asyncio.sleep(2)
                await c.delete(f"/api/instances/{inst['id']}", headers=h)
                print(f"cleaned: {inst['id'][:8]}")

        await asyncio.sleep(2)

        # New conversation
        conv_id = (await c.post("/api/conversations", headers=h, json={"name": "e2e-v4"})).json()["id"]
        print(f"conv: {conv_id[:8]}")

        # Intent
        msg = await c.post(f"/api/conversations/{conv_id}/messages", headers=h,
            json={"content": "高吞吐矩阵乘法，矩阵1024，批次50，从compute-1到compute-2，今天下午3点到5点"})
        draft = msg.json().get("latest_draft", {})
        print(f"parse: {draft.get('parse_status')} matrix={draft.get('data_profile',{}).get('matrix_size')}")
        assert draft.get("parse_status") == "valid"

        # Confirm
        confirm = await c.post(f"/api/conversations/{conv_id}/confirm-intent", headers=h, json={})
        cj = confirm.json()
        if "detail" in cj:
            print(f"confirm error: {cj['detail']}")
            # Order was already created, find it
            orders = (await c.get("/api/orders?limit=5", headers=h)).json()
            order_list = orders if isinstance(orders, list) else orders.get("items", [])
            order = next((o for o in order_list if o.get("status") == "pending" and "matmul" in o.get("name","").lower()), None)
            if not order:
                print("No pending matmul order found")
                return
        else:
            order_id = cj.get("materialized_order_id")
            if not order_id:
                orders = (await c.get("/api/orders?limit=3", headers=h)).json()
                order_list = orders if isinstance(orders, list) else orders.get("items", [])
                order = order_list[0]
            else:
                order = (await c.get(f"/api/orders/{order_id}", headers=h)).json()

        order_id = order["id"]
        print(f"order: {order_id[:8]} status={order['status']}")

        # Route
        if order["routing_status"] != "completed":
            claim = await c.patch(f"/api/routing-orders/{order_id}/claim")
            print(f"claim: {claim.status_code}")
            route = await c.post(f"/api/routing-orders/{order_id}/result", json={
                "strategy": "fastest_completion",
                "placements": [
                    {"task_node_id": "compute", "topology_node_id": "compute-1", "gpu_device": "0"},
                ],
                "require_network_ready": False,
            })
            rj = route.json()
            print(f"routing: {rj.get('routing_status')} instance={str(rj.get('instance_id',''))[:8]}")
            instance_id = rj.get("instance_id")
        else:
            instance_id = order.get("materialized_instance_id")
            print(f"already routed, instance={str(instance_id)[:8]}")

        # Start
        start = await c.post(f"/api/instances/{instance_id}/start", headers=h)
        sj = start.json()
        if "detail" in sj:
            print(f"start error: {sj['detail']}")
            return
        print(f"started: {sj}")

        # Poll for evaluation (max 120s)
        print("Waiting for task completion...")
        for i in range(40):
            await asyncio.sleep(3)
            order = (await c.get(f"/api/orders/{order_id}", headers=h)).json()
            ev = order.get("evaluation")
            if ev:
                print(f"\n=== EVALUATION RESULT ===")
                print(f"  metric:  {ev.get('metric_key')}")
                print(f"  actual:  {ev.get('actual_value')} {ev.get('unit','')}")
                print(f"  target:  {ev.get('target_value')}")
                print(f"  success: {ev.get('business_success')}")
                print(f"  reason:  {ev.get('failure_reason')}")
                return
            sys.stdout.write(f"\r  [{i*3}s] status={order['status']}")
            sys.stdout.flush()

        # Timeout - get logs
        print("\nTimeout, fetching logs...")
        inst = (await c.get(f"/api/instances/{instance_id}", headers=h)).json()
        for n in inst.get("nodes", []):
            agent = AGENT_C1 if n["name"] in ("source", "compute") else AGENT_C2
            try:
                logs = httpx.get(f"{agent}/containers/{instance_id}/{n['id']}/logs", timeout=5)
                print(f"\n=== {n['name']} ===")
                print(logs.json().get("logs", "")[-600:])
            except Exception as e:
                print(f"log error {n['name']}: {e}")

asyncio.run(main())
