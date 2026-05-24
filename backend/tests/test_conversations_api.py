import pytest

from config import settings
from tests.test_business_tasks_api import _auth_headers, _seed_business_fixture


@pytest.mark.asyncio
async def test_conversation_parse_confirm_route_and_submit(client, db_session):
    headers, _user = await _auth_headers(client, db_session)
    node_ids, _template_id = await _seed_business_fixture(client)

    create_response = await client.post("/api/conversations", json={"title": "视频任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "部署低时延视频转发，720p H264，端到端时延低于 200ms"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["latest_draft"]["task_type"] == "low_latency_video_pipeline"
    assert body["latest_draft"]["parse_status"] == "valid"
    assert len(body["messages"]) == 2

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "awaiting_routing"

    routing_response = await client.post(
        "/api/routing-requests",
        json={"conversation_id": conversation_id, "strategy": "completion_time_first"},
        headers=headers,
    )
    assert routing_response.status_code == 200
    routing_id = routing_response.json()["id"]

    callback_response = await client.post(
        f"/api/routing-results/{routing_id}",
        headers={"X-Service-Token": settings.service_api_token},
        json={
            "status": "completed",
            "strategy": "completion_time_first",
            "placements": {
                "source": node_ids[0],
                "compute": node_ids[1],
                "sink": node_ids[2],
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
    assert detail_response.json()["latest_routing_request"]["placements"]["compute"] == node_ids[1]

    submit_response = await client.post(
        f"/api/conversations/{conversation_id}/submit?auto_start=false",
        headers=headers,
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["instance_id"]
    assert submit_body["order_id"]


@pytest.mark.asyncio
async def test_conversation_rejects_unreasonable_latency(client, db_session):
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
