import pytest

from api.auth import hash_password
from enums import UserRole
from models import User


async def _create_user(db_session, username: str, role: UserRole = UserRole.USER) -> User:
    user = User(username=username, password_hash=hash_password("password123"), role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def _auth_headers(client, db_session, username: str = "testuser", role: UserRole = UserRole.USER):
    user = await _create_user(db_session, username, role)
    response = await client.post("/api/auth/login", json={"username": username, "password": "password123"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


async def _seed_business_fixture(client):
    node_ids = []
    for idx, hostname in enumerate(["worker-a", "worker-b", "worker-c"], start=1):
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "agent_address": f"http://127.0.0.1:800{idx}",
                "management_ip": f"10.0.0.{idx}",
                "business_ip": f"10.0.1.{idx}",
            },
        )
        assert response.status_code == 200
        node_ids.append(response.json()["id"])

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "business-abc",
            "description": "source/compute/sink",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": node_ids[0],
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": node_ids[1],
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": node_ids[2],
                },
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        },
    )
    assert template_response.status_code == 200
    template_id = template_response.json()["id"]

    catalog_response = await client.post(
        "/api/business-template-catalog",
        json={
            "task_type": "low_latency_video_pipeline",
            "modality": "low_latency_forwarding",
            "template_id": template_id,
            "source_node_name": "source",
            "compute_node_name": "compute",
            "sink_node_name": "sink",
        },
    )
    assert catalog_response.status_code == 200
    return node_ids, template_id


@pytest.mark.asyncio
async def test_auth_bootstrap_and_login(client, db_session):
    bootstrap = await client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "password": "admin123"},
    )
    assert bootstrap.status_code == 200

    login = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["access_token"]
    assert body["role"] == "admin"


@pytest.mark.asyncio
async def test_auth_register_creates_regular_user(client, db_session):
    response = await client.post(
        "/api/auth/register",
        json={"username": "regular-user", "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "regular-user"
    assert body["role"] == "user"

    login = await client.post(
        "/api/auth/login",
        json={"username": "regular-user", "password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "user"


@pytest.mark.asyncio
async def test_business_task_create_and_metric_evaluation(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)

    payload = {
        "external_task_id": "intent-api-001",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "低时延视频转发",
        "data_profile": {"profile_id": "video_720p_frame_stream"},
        "business_objective": {
            "metric_key": "end_to_end_latency_ms",
            "operator": "<=",
            "target_value": 200,
            "unit": "ms",
        },
        "runtime_plan": {"codec": "h264", "preset": "ultrafast"},
        "routing_result": {
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
        },
        "auto_start": False,
    }

    create_response = await client.post("/api/business-tasks", json=payload)
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["order_id"]
    assert body["instance_id"]
    instance_id = body["instance_id"]

    metric_response = await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={
            "metric_key": "end_to_end_latency_ms",
            "metric_value": 186.4,
            "unit": "ms",
            "tags": {
                "objects": [
                    {"name": "result.json", "uri": "s3://task-results/instance-1/result.json"}
                ]
            },
        },
    )
    assert metric_response.status_code == 200

    evaluation_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert evaluation_response.status_code == 200
    evaluation = evaluation_response.json()
    assert evaluation["business_success"] is True
    assert evaluation["actual_value"] == 186.4

    summary_response = await client.get("/api/business-tasks/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert len(summary) == 1
    assert summary[0]["success_count"] == 1
    assert summary[0]["business_success_rate"] == 1.0
