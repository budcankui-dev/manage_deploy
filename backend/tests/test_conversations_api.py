import pytest
from sqlalchemy import select

from config import settings
from models import TaskInstanceNode, TaskOrder
from tests.test_business_tasks_api import _auth_headers, _seed_business_fixture


@pytest.mark.asyncio
async def test_conversation_parse_confirm_route_and_submit(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)
    node_ids, _template_id = await _seed_business_fixture(client)
    catalog_response = await client.post(
        "/api/business-template-catalog",
        json={
            "task_type": "high_throughput_matmul",
            "modality": "high_throughput_compute",
            "template_id": _template_id,
            "source_node_name": "source",
            "compute_node_name": "compute",
            "sink_node_name": "sink",
        },
    )
    assert catalog_response.status_code == 200

    create_response = await client.post("/api/conversations", json={"title": "矩阵任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]
    assert create_response.json()["task_id"] == conversation_id

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["latest_draft"]["task_type"] == "high_throughput_matmul"
    assert body["latest_draft"]["parse_status"] == "valid"
    assert body["latest_draft"]["data_profile"]["matrix_size"] == 1024
    assert body["latest_draft"]["data_profile"]["batch_count"] == 50
    assert len(body["messages"]) == 2
    assert body["workflow_trace"]["engine"] == "rule_parser"

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["status"] == "awaiting_routing"
    routing_id = confirm_body["latest_routing_request"]["id"]

    callback_response = await client.post(
        f"/api/routing-results/{routing_id}",
        headers={"X-Service-Token": settings.service_api_token},
        json={
            "status": "completed",
            "strategy": "completion_time_first",
            "placements": {
                "source": {"node_id": node_ids[0], "gpu_indices": []},
                "worker": {
                    "node_id": node_ids[1],
                    "node_name": "worker-b",
                    "gpu_indices": [0],
                    "allocated_resources": {"gpu_units": 1},
                },
                "sink": {"node_id": node_ids[2], "gpu_indices": []},
            },
            "estimated_metric": {
                "metric_key": "end_to_end_latency_ms",
                "metric_value": 180,
                "unit": "ms",
            },
            "external_routing_id": "router-mock-001",
        },
    )
    assert callback_response.status_code == 200

    detail_response = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "ready_to_submit"
    assert detail_response.json()["latest_routing_request"]["placements"]["worker"]["node_id"] == node_ids[1]

    submit_response = await client.post(
        f"/api/conversations/{conversation_id}/submit?auto_start=false",
        headers=headers,
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["instance_id"]
    assert submit_body["order_id"]

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == submit_body["order_id"]))
    ).scalar_one()
    assert order.runtime_config["business_task"]["routing_result"]["placements"]["worker"]["node_id"] == node_ids[1]

    inst_nodes = (
        await db_session.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == submit_body["instance_id"])
        )
    ).scalars().all()
    by_role = {node.env["TASK_ROLE"]: node for node in inst_nodes}
    assert by_role["compute"].node_id == node_ids[1]
    assert by_role["compute"].gpu_id == "0"
    assert by_role["compute"].env["GPU_DEVICE"] == "0"


@pytest.mark.asyncio
async def test_video_conversation_demo_route_materializes_same_order(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)
    _node_ids, _template_id = await _seed_business_fixture(client)

    create_response = await client.post("/api/conversations", json={"title": "视频推理任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "视频AI推理任务，从 worker-a 到 worker-c，720p视频，100帧，30fps，现在开始跑2小时，低时延策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["latest_draft"]["task_type"] == "low_latency_video_pipeline"
    assert body["latest_draft"]["parse_status"] == "valid"
    assert body["latest_draft"]["data_profile"]["resolution"] == "720p"

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["materialized_order_id"] == conversation_id
    assert confirm_response.json()["status"] == "awaiting_routing"

    route_response = await client.post(
        f"/api/conversations/{conversation_id}/demo-route",
        headers=headers,
    )
    assert route_response.status_code == 200
    route_body = route_response.json()
    assert route_body["status"] == "submitted"
    assert route_body["materialized_order_id"] == conversation_id
    assert route_body["latest_routing_request"]["status"] == "completed"
    assert route_body["latest_routing_request"]["placements"]["compute"]["worker_host"] == "worker-b"
    assert route_body["latest_routing_request"]["placements"]["compute"]["gpu_device"] == "0"

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    assert order.status == "materialized"
    assert order.routing_status == "completed"
    assert order.materialized_instance_id
    assert order.runtime_config["business_task"]["task_type"] == "low_latency_video_pipeline"

    route_placements = order.runtime_config["routing_result"]["placements"]
    compute_route = next(item for item in route_placements if item["node_id"] == "compute")
    assert compute_route["worker_host"] == "worker-b"
    assert compute_route["gpu_device"] == "0"

    inst_nodes = (
        await db_session.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == order.materialized_instance_id)
        )
    ).scalars().all()
    by_role = {node.env["TASK_ROLE"]: node for node in inst_nodes}
    assert by_role["compute"].env["TASK_TYPE"] == "low_latency_video_pipeline"
    assert by_role["compute"].env["USE_GPU"] == "true"
    assert by_role["compute"].env["GPU_DEVICE"] == "0"
    assert by_role["compute"].gpu_id == "0"


@pytest.mark.asyncio
async def test_conversation_rejects_unreasonable_video_latency(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)

    create_response = await client.post("/api/conversations", json={}, headers=headers)
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "视频转发任务，端到端时延低于 1ms"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["status"] == "rejected"
    assert body["latest_draft"]["parse_status"] == "rejected"
    assert body["latest_draft"]["task_type"] == "low_latency_video_pipeline"
