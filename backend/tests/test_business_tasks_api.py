import pytest

from api.auth import hash_password
from api.business_tasks import _extract_result_metadata
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

    # reporter 重试或重复上报时不应产生多条 evaluation
    duplicate_response = await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={
            "metric_key": "end_to_end_latency_ms",
            "metric_value": 186.4,
            "unit": "ms",
        },
    )
    assert duplicate_response.status_code == 200

    evaluation_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert evaluation_response.status_code == 200
    evaluation = evaluation_response.json()
    assert evaluation["business_success"] is True
    assert evaluation["actual_value"] == 186.4

    summary_response = await client.get("/api/business-tasks/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert len(summary) == 1
    assert summary[0]["count"] == 1
    assert summary[0]["evaluated_count"] == 1
    assert summary[0]["success_count"] == 1
    assert summary[0]["business_success_rate"] == 1.0


@pytest.mark.asyncio
async def test_business_task_summary_success_rate_excludes_unevaluated_orders(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)

    async def create_order(external_id: str):
        payload = {
            "external_task_id": external_id,
            "task_type": "low_latency_video_pipeline",
            "modality": "low_latency_forwarding",
            "name": "成功率分母测试",
            "data_profile": {"profile_id": "video_720p_frame_stream"},
            "business_objective": {
                "metric_key": "end_to_end_latency_ms",
                "operator": "<=",
                "target_value": 200,
                "unit": "ms",
            },
            "routing_result": {
                "strategy": "completion_time_first",
                "placements": {
                    "source": node_ids[0],
                    "compute": node_ids[1],
                    "sink": node_ids[2],
                },
            },
            "auto_start": False,
        }
        response = await client.post("/api/business-tasks", json=payload)
        assert response.status_code == 200
        return response.json()

    evaluated = await create_order("intent-summary-evaluated")
    await create_order("intent-summary-pending")

    metric_response = await client.post(
        f"/api/instances/{evaluated['instance_id']}/metrics",
        json={"metric_key": "end_to_end_latency_ms", "metric_value": 150, "unit": "ms"},
    )
    assert metric_response.status_code == 200

    summary_response = await client.get("/api/business-tasks/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert len(summary) == 1
    assert summary[0]["count"] == 2
    assert summary[0]["evaluated_count"] == 1
    assert summary[0]["success_count"] == 1
    assert summary[0]["business_success_rate"] == 1.0


@pytest.mark.asyncio
async def test_business_task_summary_ignores_orphan_evaluations(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)

    payload = {
        "external_task_id": "intent-summary-orphan",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "统计孤儿评估测试",
        "data_profile": {"profile_id": "video_720p_frame_stream"},
        "business_objective": {
            "metric_key": "end_to_end_latency_ms",
            "operator": "<=",
            "target_value": 200,
            "unit": "ms",
        },
        "routing_result": {
            "strategy": "completion_time_first",
            "placements": {
                "source": node_ids[0],
                "compute": node_ids[1],
                "sink": node_ids[2],
            },
        },
        "auto_start": False,
    }
    create_response = await client.post("/api/business-tasks", json=payload)
    assert create_response.status_code == 200
    body = create_response.json()
    order_id = body["order_id"]
    instance_id = body["instance_id"]

    metric_response = await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={"metric_key": "end_to_end_latency_ms", "metric_value": 150, "unit": "ms"},
    )
    assert metric_response.status_code == 200

    delete_response = await client.delete(f"/api/orders/{order_id}")
    assert delete_response.status_code == 200

    summary_response = await client.get("/api/business-tasks/summary")
    assert summary_response.status_code == 200
    assert summary_response.json() == []


@pytest.mark.asyncio
async def test_delete_order_purges_evaluation(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)

    payload = {
        "external_task_id": "intent-purge-eval",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "删除级联测试",
        "data_profile": {"profile_id": "video_720p_frame_stream"},
        "business_objective": {
            "metric_key": "end_to_end_latency_ms",
            "operator": "<=",
            "target_value": 200,
            "unit": "ms",
        },
        "routing_result": {
            "strategy": "completion_time_first",
            "placements": {
                "source": node_ids[0],
                "compute": node_ids[1],
                "sink": node_ids[2],
            },
        },
        "auto_start": False,
    }
    create_response = await client.post("/api/business-tasks", json=payload)
    assert create_response.status_code == 200
    body = create_response.json()
    order_id = body["order_id"]
    instance_id = body["instance_id"]

    await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={"metric_key": "end_to_end_latency_ms", "metric_value": 150, "unit": "ms"},
    )

    delete_response = await client.delete(f"/api/orders/{order_id}")
    assert delete_response.status_code == 200

    eval_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert eval_response.status_code == 404


@pytest.mark.asyncio
async def test_business_task_list_api(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)

    payload = {
        "external_task_id": "intent-list-001",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "列表测试任务",
        "data_profile": {"profile_id": "video_720p_frame_stream"},
        "business_objective": {
            "metric_key": "end_to_end_latency_ms",
            "operator": "<=",
            "target_value": 200,
            "unit": "ms",
        },
        "routing_result": {
            "strategy": "completion_time_first",
            "placements": {
                "source": node_ids[0],
                "compute": node_ids[1],
                "sink": node_ids[2],
            },
        },
        "auto_start": False,
    }
    create_response = await client.post("/api/business-tasks", json=payload)
    assert create_response.status_code == 200
    body = create_response.json()
    order_id = body["order_id"]
    instance_id = body["instance_id"]

    list_response = await client.get("/api/business-tasks")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] >= 1
    assert listed["page"] == 1
    item = next(row for row in listed["items"] if row["order_id"] == order_id)
    assert item["task_type"] == "low_latency_video_pipeline"
    assert item["routing_policy"] == "completion_time_first"
    assert item["instance_id"] == instance_id
    assert item["deployment_status"] == "pending"
    assert item["target_value"] == 200
    assert item["business_success"] is None

    filtered = await client.get(
        "/api/business-tasks",
        params={"task_type": "low_latency_video_pipeline", "routing_policy": "completion_time_first"},
    )
    assert filtered.status_code == 200
    assert any(row["order_id"] == order_id for row in filtered.json()["items"])

    await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={"metric_key": "end_to_end_latency_ms", "metric_value": 150, "unit": "ms"},
    )
    after_metric = await client.get("/api/business-tasks", params={"business_success": True})
    assert after_metric.status_code == 200
    success_item = next(row for row in after_metric.json()["items"] if row["order_id"] == order_id)
    assert success_item["actual_value"] == 150
    assert success_item["business_success"] is True

    detail_response = await client.get(f"/api/orders/{order_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["business_task"]["task_type"] == "low_latency_video_pipeline"
    assert detail["instance"]["id"] == instance_id
    assert detail["evaluation"]["business_success"] is True


@pytest.mark.parametrize("tags,expected_keys", [
    # New format: tags.result with full result.json
    (
        {"result": {"compute_latency_ms": 0.15, "matrix_size": 64, "batch_count": 1, "seed": 42, "checksum": "-5.328465"}},
        {"compute_latency_ms": 0.15, "matrix_size": 64, "batch_count": 1, "seed": 42},
    ),
    # New format: tags.result with extra fields
    (
        {"result": {"compute_latency_ms": 0.20, "matrix_size": 128, "batch_count": 2, "seed": 99, "checksum": "-9.1", "extra_field": "prune_me"}},
        {"compute_latency_ms": 0.20, "matrix_size": 128, "batch_count": 2, "seed": 99},
    ),
    # Old flat tags (backward compat)
    (
        {"compute_latency_ms": 0.18, "matrix_size": 64, "batch_count": 1, "seed": 7},
        {"compute_latency_ms": 0.18, "matrix_size": 64, "batch_count": 1, "seed": 7},
    ),
    # Empty tags
    (None, {}),
    ({}, {}),
    # No result key, no flat keys
    ({"other_field": "ignore"}, {}),
    # Mixed: result wins; flat fallbacks respected
    (
        {"result": {"compute_latency_ms": 0.25, "matrix_size": 256, "batch_count": 3}, "compute_latency_ms": 0.99},
        {"compute_latency_ms": 0.25, "matrix_size": 256, "batch_count": 3},
    ),
])
def test_extract_result_metadata(tags, expected_keys):
    """_extract_result_metadata white-lists keys and ignores checksum / unknown fields."""
    result = _extract_result_metadata(tags)
    assert result == expected_keys
