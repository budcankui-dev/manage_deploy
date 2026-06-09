import pytest
from sqlalchemy import select

from api.auth import hash_password
from api.business_tasks import _extract_result_metadata
from config import settings
from enums import OrderStatus, RoutingStatus, UserRole
from models import BusinessObjectiveEvaluation, TaskInstance, TaskInstanceNode, TaskOrder, User


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
async def test_business_task_summary_can_filter_benchmark_orders(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)

    def runtime_config(strategy: str = "resource_guarantee"):
        return {
            "business_task": {
                "task_type": "high_throughput_matmul",
                "data_profile": {"matrix_size": 1024, "batch_count": 50},
                "business_objective": {
                    "metric_key": "effective_gflops",
                    "operator": ">=",
                    "target_value": 80,
                    "unit": "GFLOPS",
                },
                "runtime_plan": {"routing_strategy": strategy},
            }
        }

    normal_order = TaskOrder(
        template_id=template_id,
        name="普通业务工单",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config(),
        materialized_instance_id="normal-instance",
        is_benchmark=False,
    )
    benchmark_order = TaskOrder(
        template_id=template_id,
        name="验收压测工单",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config(),
        materialized_instance_id="benchmark-instance",
        is_benchmark=True,
    )
    db_session.add_all([normal_order, benchmark_order])
    db_session.add_all(
        [
            BusinessObjectiveEvaluation(
                instance_id="normal-instance",
                task_type="high_throughput_matmul",
                routing_strategy="resource_guarantee",
                metric_key="effective_gflops",
                actual_value=90,
                target_value=80,
                operator=">=",
                unit="GFLOPS",
                business_success=True,
            ),
            BusinessObjectiveEvaluation(
                instance_id="benchmark-instance",
                task_type="high_throughput_matmul",
                routing_strategy="resource_guarantee",
                metric_key="effective_gflops",
                actual_value=60,
                target_value=80,
                operator=">=",
                unit="GFLOPS",
                business_success=False,
            ),
        ]
    )
    await db_session.commit()

    all_response = await client.get("/api/business-tasks/summary")
    assert all_response.status_code == 200
    assert all_response.json()[0]["count"] == 2

    benchmark_response = await client.get("/api/business-tasks/summary?is_benchmark=true")
    assert benchmark_response.status_code == 200
    benchmark_summary = benchmark_response.json()
    assert len(benchmark_summary) == 1
    assert benchmark_summary[0]["count"] == 1
    assert benchmark_summary[0]["evaluated_count"] == 1
    assert benchmark_summary[0]["success_count"] == 0
    assert benchmark_summary[0]["business_success_rate"] == 0.0


@pytest.mark.asyncio
async def test_benchmark_summary_and_orders_can_filter_by_run_id(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    admin_headers, _admin = await _auth_headers(
        client,
        db_session,
        username="benchmark-run-admin",
        role=UserRole.ADMIN,
    )

    def runtime_config(run_id: str):
        return {
            "benchmark": {"run_id": run_id},
            "business_task": {
                "task_type": "high_throughput_matmul",
                "data_profile": {"matrix_size": 1024, "batch_count": 50},
                "business_objective": {
                    "metric_key": "effective_gflops",
                    "operator": ">=",
                    "unit": "GFLOPS",
                },
                "runtime_plan": {"routing_strategy": "resource_guarantee"},
            },
        }

    run_a_order = TaskOrder(
        template_id=template_id,
        name="run-a benchmark order",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config("run-a"),
        materialized_instance_id="run-a-instance",
        is_benchmark=True,
    )
    run_b_order = TaskOrder(
        template_id=template_id,
        name="run-b benchmark order",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config("run-b"),
        materialized_instance_id="run-b-instance",
        is_benchmark=True,
    )
    db_session.add_all([run_a_order, run_b_order])
    db_session.add_all(
        [
            BusinessObjectiveEvaluation(
                instance_id="run-a-instance",
                task_type="high_throughput_matmul",
                routing_strategy="resource_guarantee",
                metric_key="effective_gflops",
                actual_value=90,
                target_value=80,
                operator=">=",
                unit="GFLOPS",
                business_success=True,
            ),
            BusinessObjectiveEvaluation(
                instance_id="run-b-instance",
                task_type="high_throughput_matmul",
                routing_strategy="resource_guarantee",
                metric_key="effective_gflops",
                actual_value=60,
                target_value=80,
                operator=">=",
                unit="GFLOPS",
                business_success=False,
            ),
        ]
    )
    await db_session.commit()

    summary_response = await client.get(
        "/api/business-tasks/summary",
        params={"is_benchmark": True, "benchmark_run_id": "run-a"},
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert len(summary) == 1
    assert summary[0]["count"] == 1
    assert summary[0]["success_count"] == 1
    assert summary[0]["business_success_rate"] == 1.0

    orders_response = await client.get(
        "/api/orders",
        params={"is_benchmark": True, "benchmark_run_id": "run-a"},
        headers=admin_headers,
    )
    assert orders_response.status_code == 200
    assert [row["name"] for row in orders_response.json()] == ["run-a benchmark order"]


@pytest.mark.asyncio
async def test_business_task_summary_can_filter_by_task_type(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)

    def runtime_config(task_type: str):
        return {
            "benchmark": {"run_id": "mixed-task-type-run"},
            "business_task": {
                "task_type": task_type,
                "data_profile": {},
                "business_objective": {
                    "metric_key": "effective_gflops" if task_type == "high_throughput_matmul" else "frame_latency_p90_ms",
                    "operator": ">=" if task_type == "high_throughput_matmul" else "<=",
                    "unit": "GFLOPS" if task_type == "high_throughput_matmul" else "ms",
                },
                "runtime_plan": {"routing_strategy": "resource_guarantee"},
            },
        }

    matmul_order = TaskOrder(
        template_id=template_id,
        name="matmul benchmark order",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config("high_throughput_matmul"),
        materialized_instance_id="matmul-summary-instance",
        is_benchmark=True,
    )
    video_order = TaskOrder(
        template_id=template_id,
        name="video benchmark order",
        status=OrderStatus.COMPLETED,
        runtime_config=runtime_config("low_latency_video_pipeline"),
        materialized_instance_id="video-summary-instance",
        is_benchmark=True,
    )
    db_session.add_all([matmul_order, video_order])
    db_session.add_all(
        [
            BusinessObjectiveEvaluation(
                instance_id="matmul-summary-instance",
                task_type="high_throughput_matmul",
                routing_strategy="resource_guarantee",
                metric_key="effective_gflops",
                actual_value=90,
                target_value=80,
                operator=">=",
                unit="GFLOPS",
                business_success=True,
            ),
            BusinessObjectiveEvaluation(
                instance_id="video-summary-instance",
                task_type="low_latency_video_pipeline",
                routing_strategy="resource_guarantee",
                metric_key="frame_latency_p90_ms",
                actual_value=130,
                target_value=150,
                operator="<=",
                unit="ms",
                business_success=True,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        "/api/business-tasks/summary",
        params={
            "is_benchmark": True,
            "benchmark_run_id": "mixed-task-type-run",
            "task_type": "high_throughput_matmul",
        },
    )

    assert response.status_code == 200
    summary = response.json()
    assert len(summary) == 1
    assert summary[0]["task_type"] == "high_throughput_matmul"
    assert summary[0]["count"] == 1


@pytest.mark.asyncio
async def test_batch_benchmark_creates_task_type_aware_video_orders(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, user = await _auth_headers(client, db_session, username="benchmark-video-user")

    response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 2,
            "benchmark_run_id": "video-run-a",
            "data_profile": {
                "frame_count": 150,
                "frame_stride": 30,
                "measured_frames": 90,
                "work_units": 45000,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == body["order_ids"][0]))
    order = row.scalar_one()
    assert order.user_id == user.id
    assert order.is_benchmark is True
    assert order.routing_status == "pending"

    business_task = order.runtime_config["business_task"]
    assert business_task["task_type"] == "low_latency_video_pipeline"
    assert business_task["modality"] == "low_latency_forwarding"
    assert business_task["business_objective"] == {
        "metric_key": "frame_latency_p90_ms",
        "operator": "<=",
        "unit": "ms",
    }
    assert business_task["data_profile"]["frame_count"] == 150
    assert business_task["data_profile"]["profile_id"] == "video_industrial_inspection_720p"

    dag = order.routing_input_dag
    assert dag["job_id"] == order.id
    assert dag["order_id"] == order.id
    assert dag["job_name"] == "视频AI推理"
    assert "constraints" not in dag
    assert [node["node_id"] for node in dag["nodes"]] == ["source", "compute", "sink"]
    assert [node["role"] for node in dag["nodes"]] == ["source", "compute", "sink"]
    assert [node["node_type"] for node in dag["nodes"]] == ["endpoint", "compute", "endpoint"]
    assert dag["nodes"][0]["fixed_node_name"] == "benchmark-video-source"
    assert dag["nodes"][0]["fixed_node_role"] == "source"
    assert dag["nodes"][2]["fixed_node_name"] == "benchmark-video-sink"
    assert dag["nodes"][2]["fixed_node_role"] == "destination"
    assert all("exec" not in node for node in dag["nodes"])
    assert dag["edges"] == [
        {"from": "source", "to": "compute", "data_mb": 2, "bandwidth_mbps": 20},
        {"from": "compute", "to": "sink", "data_mb": 2, "bandwidth_mbps": 20},
    ]


@pytest.mark.asyncio
async def test_order_routing_result_persists_router_metadata_and_is_idempotent(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="route-metadata-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "route-metadata-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    payload = {
        "strategy": "cost_first",
        "selected_strategy": "GPU_EXCLUSIVE_LOW_RENT",
        "external_routing_id": "route-meta-001",
        "placements": [
            {"node_id": "source", "worker_host": "worker-a"},
            {"node_id": "compute", "worker_host": "worker-b", "gpu_device": "0"},
            {"node_id": "sink", "worker_host": "worker-c"},
        ],
        "estimated_metric": {
            "estimated_cost": 1.6,
            "cost_unit": "yuan",
            "confidence": 0.9,
        },
        "metadata": {
            "path": ["worker-a", "worker-b", "worker-c"],
            "rent": {"amount": 1.6, "currency": "CNY", "billing_unit": "task"},
            "selected_reason": "worker-b GPU 0 is exclusive and has the lowest estimated rent",
            "algorithm_version": "router-test",
            "decision_trace_id": "trace-meta-001",
        },
    }
    response = await client.post(f"/api/orders/{order_id}/routing-result", json=payload)
    assert response.status_code == 200, response.text

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.routing_status == RoutingStatus.COMPLETED.value
    routing_result = order.runtime_config["routing_result"]
    assert routing_result["selected_strategy"] == "GPU_EXCLUSIVE_LOW_RENT"
    assert routing_result["external_routing_id"] == "route-meta-001"
    assert routing_result["estimated_metric"]["estimated_cost"] == 1.6
    assert routing_result["metadata"]["rent"]["amount"] == 1.6
    assert routing_result["metadata"]["decision_trace_id"] == "trace-meta-001"

    duplicate = await client.post(f"/api/orders/{order_id}/routing-result", json=payload)
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_service_token_routing_order_http_flow(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-order-http-user")
    service_headers = {"X-Service-Token": settings.service_api_token}

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-http-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    list_response = await client.get(
        "/api/routing-orders",
        headers=service_headers,
        params={
            "status": "pending",
            "benchmark_run_id": "routing-http-run",
            "task_type": "low_latency_video_pipeline",
        },
    )
    assert list_response.status_code == 200
    pending_orders = list_response.json()
    assert [item["order_id"] for item in pending_orders] == [order_id]
    assert pending_orders[0]["routing_input_dag"]["job_id"] == order_id

    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim", headers=service_headers)
    assert claim_response.status_code == 200
    assert claim_response.json()["routing_status"] == "computing"

    result_response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        headers=service_headers,
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"node_id": "source", "worker_host": "worker-a"},
                {"node_id": "compute", "worker_host": "worker-b", "gpu_device": "0"},
                {"node_id": "sink", "worker_host": "worker-c"},
            ],
            "metadata": {
                "path": ["worker-a", "worker-b", "worker-c"],
                "algorithm_version": "router-http-test",
            },
        },
    )
    assert result_response.status_code == 200, result_response.text
    assert result_response.json()["routing_status"] == "completed"

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.materialized_instance_id
    assert order.runtime_config["routing_result"]["metadata"]["algorithm_version"] == "router-http-test"


@pytest.mark.asyncio
async def test_batch_auto_route_can_scope_by_task_type(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="benchmark-scope-user")
    catalog_response = await client.post(
        "/api/business-template-catalog",
        json={
            "task_type": "high_throughput_matmul",
            "modality": "high_throughput_compute",
            "template_id": template_id,
            "source_node_name": "source",
            "compute_node_name": "compute",
            "sink_node_name": "sink",
        },
    )
    assert catalog_response.status_code == 200

    matmul_create = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "high_throughput_matmul",
            "count": 1,
            "benchmark_run_id": "mixed-run",
        },
    )
    assert matmul_create.status_code == 200
    video_create = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "mixed-run",
        },
    )
    assert video_create.status_code == 200
    matmul_order_id = matmul_create.json()["order_ids"][0]
    video_order_id = video_create.json()["order_ids"][0]

    response = await client.post(
        "/api/orders/batch-auto-route",
        headers=headers,
        json={"benchmark_run_id": "mixed-run", "task_type": "high_throughput_matmul"},
    )
    assert response.status_code == 200
    assert response.json()["routed"] == 1, response.json()

    matmul_order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == matmul_order_id))
    ).scalar_one()
    video_order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == video_order_id))
    ).scalar_one()
    assert matmul_order.routing_status == "completed"
    assert matmul_order.materialized_instance_id
    assert video_order.routing_status == "pending"
    assert video_order.materialized_instance_id is None

    detail_response = await client.get(f"/api/orders/{matmul_order_id}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    placements = {item["role"]: item for item in detail["node_placements"]}
    assert placements["compute"]["gpu_id"] == "0"
    assert placements["compute"]["gpu_device"] == "0"
    routing_placements = detail["routing_result"]["placements"]
    compute_route = next(item for item in routing_placements if item["node_id"] == "compute")
    assert compute_route["gpu_device"] == "0"

    inst_nodes = (
        await db_session.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == matmul_order.materialized_instance_id)
        )
    ).scalars().all()
    by_role = {node.env.get("TASK_ROLE"): node for node in inst_nodes}
    assert by_role["compute"].gpu_id == "0"
    assert by_role["compute"].env["GPU_DEVICE"] == "0"

    detail_response = await client.get(f"/api/orders/{matmul_order_id}", headers=headers)
    assert detail_response.status_code == 200
    placements = {item["role"]: item for item in detail_response.json()["node_placements"]}
    assert placements["compute"]["gpu_id"] == "0"
    assert placements["compute"]["gpu_device"] == "0"


@pytest.mark.asyncio
async def test_mock_auto_route_single_order_is_benchmark_only(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    headers, user = await _auth_headers(client, db_session, username="benchmark-single-route-user")
    order = TaskOrder(
        template_id=template_id,
        name="normal pending order",
        status=OrderStatus.PENDING,
        user_id=user.id,
        routing_status=RoutingStatus.PENDING.value,
        is_benchmark=False,
    )
    db_session.add(order)
    await db_session.commit()

    response = await client.post(f"/api/orders/{order.id}/auto-route", headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "Mock auto-route is only available for benchmark orders"


@pytest.mark.asyncio
async def test_admin_can_list_all_benchmark_orders(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    owner_headers, owner = await _auth_headers(client, db_session, username="order-owner")
    other_headers, other = await _auth_headers(client, db_session, username="order-other")
    admin_headers, _admin = await _auth_headers(
        client,
        db_session,
        username="order-admin",
        role=UserRole.ADMIN,
    )

    owner_order = TaskOrder(
        template_id=template_id,
        name="owner benchmark order",
        status=OrderStatus.COMPLETED,
        user_id=owner.id,
        is_benchmark=True,
    )
    other_order = TaskOrder(
        template_id=template_id,
        name="other benchmark order",
        status=OrderStatus.COMPLETED,
        user_id=other.id,
        is_benchmark=True,
    )
    db_session.add_all([owner_order, other_order])
    await db_session.commit()

    owner_response = await client.get(
        "/api/orders",
        params={"is_benchmark": True},
        headers=owner_headers,
    )
    assert owner_response.status_code == 200
    assert [row["name"] for row in owner_response.json()] == ["owner benchmark order"]

    other_response = await client.get(
        "/api/orders",
        params={"is_benchmark": True},
        headers=other_headers,
    )
    assert other_response.status_code == 200
    assert [row["name"] for row in other_response.json()] == ["other benchmark order"]

    admin_response = await client.get(
        "/api/orders",
        params={"is_benchmark": True},
        headers=admin_headers,
    )
    assert admin_response.status_code == 200
    assert {row["name"] for row in admin_response.json()} == {
        "owner benchmark order",
        "other benchmark order",
    }


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
async def test_cleanup_order_instance_preserves_business_evidence(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)
    headers, _admin = await _auth_headers(client, db_session, username="cleanup-admin", role=UserRole.ADMIN)

    payload = {
        "external_task_id": "intent-cleanup-evidence",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "清理实例保留证据测试",
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

    cleanup_response = await client.post(
        "/api/orders/batch/cleanup-instances",
        json={"order_ids": [order_id]},
        headers=headers,
    )
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["succeeded"] == [order_id]

    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    assert instance_row.scalar_one_or_none() is None

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    ).scalar_one()
    assert order.status == OrderStatus.COMPLETED
    assert order.materialized_instance_id == instance_id

    evaluation_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert evaluation_response.status_code == 200
    assert evaluation_response.json()["business_success"] is True

    list_response = await client.get("/api/business-tasks", headers=headers)
    assert list_response.status_code == 200
    item = next(row for row in list_response.json()["items"] if row["order_id"] == order_id)
    assert item["instance_exists"] is False
    assert item["business_success"] is True

    detail_response = await client.get(f"/api/orders/{order_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["instance"] is None
    assert detail_response.json()["evaluation"]["business_success"] is True

    delete_response = await client.delete(f"/api/orders/{order_id}")
    assert delete_response.status_code == 200
    eval_after_delete_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert eval_after_delete_response.status_code == 404


@pytest.mark.asyncio
async def test_order_detail_exposes_video_preview_metadata(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)
    headers, _admin = await _auth_headers(client, db_session, username="video-preview-admin", role=UserRole.ADMIN)

    payload = {
        "external_task_id": "intent-video-preview-evidence",
        "task_type": "low_latency_video_pipeline",
        "modality": "low_latency_forwarding",
        "name": "视频预览证据测试",
        "data_profile": {"profile_id": "video_industrial_inspection_720p", "measured_frames": 30},
        "business_objective": {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "target_value": 500,
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
        json={
            "metric_key": "frame_latency_p90_ms",
            "metric_value": 120.5,
            "unit": "ms",
            "tags": {
                "objects": [
                    {
                        "name": "annotated-frame-preview",
                        "uri": "inline://result_metadata/annotated_frame_data_url",
                        "content_type": "image/jpeg",
                    }
                ],
                "result": {
                    "frame_latency_p90_ms": 120.5,
                    "measured_frames": 30,
                    "model_name": "yolov5n",
                    "video_asset": "bottle-detection.mp4",
                    "gpu_assigned": True,
                    "annotated_frame_data_url": "data:image/jpeg;base64,abc123",
                    "detection_count": 1,
                    "top_label": "bottle",
                    "detections": [
                        {"label": "bottle", "confidence": 0.93, "bbox_xyxy": [10, 20, 100, 160]}
                    ],
                },
            },
        },
    )
    assert metric_response.status_code == 200

    evaluation_response = await client.get(f"/api/business-tasks/{instance_id}/evaluation")
    assert evaluation_response.status_code == 200
    assert evaluation_response.json()["result_metadata"]["annotated_frame_data_url"].startswith("data:image/")

    detail_response = await client.get(f"/api/orders/{order_id}", headers=headers)
    assert detail_response.status_code == 200
    metadata = detail_response.json()["evaluation"]["result_metadata"]
    assert metadata["model_name"] == "yolov5n"
    assert metadata["gpu_assigned"] is True
    assert metadata["detections"][0]["label"] == "bottle"


@pytest.mark.asyncio
async def test_cleanup_order_instances_can_scope_by_benchmark_run_and_task_type(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    headers, _admin = await _auth_headers(
        client,
        db_session,
        username="cleanup-run-admin",
        role=UserRole.ADMIN,
    )

    def runtime_config(task_type: str):
        return {
            "benchmark": {"run_id": "cleanup-run-a"},
            "business_task": {
                "task_type": task_type,
                "routing_result": {
                    "strategy": "resource_guarantee",
                    "placements": {"compute": {"worker_host": "worker-a", "gpu_device": "0"}},
                },
            },
        }

    matmul_instance = TaskInstance(template_id=template_id, name="matmul-instance")
    video_instance = TaskInstance(template_id=template_id, name="video-instance")
    db_session.add_all([matmul_instance, video_instance])
    await db_session.flush()

    matmul_order = TaskOrder(
        template_id=template_id,
        name="matmul cleanup target",
        status=OrderStatus.MATERIALIZED,
        runtime_config=runtime_config("high_throughput_matmul"),
        materialized_instance_id=matmul_instance.id,
        is_benchmark=True,
    )
    video_order = TaskOrder(
        template_id=template_id,
        name="video should stay",
        status=OrderStatus.MATERIALIZED,
        runtime_config=runtime_config("low_latency_video_pipeline"),
        materialized_instance_id=video_instance.id,
        is_benchmark=True,
    )
    db_session.add_all([matmul_order, video_order])
    await db_session.commit()

    response = await client.post(
        "/api/orders/batch/cleanup-instances",
        json={
            "benchmark_run_id": "cleanup-run-a",
            "task_type": "high_throughput_matmul",
            "is_benchmark": True,
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["succeeded"] == [matmul_order.id]

    matmul_remaining = (
        await db_session.execute(select(TaskInstance).where(TaskInstance.id == matmul_instance.id))
    ).scalar_one_or_none()
    video_remaining = (
        await db_session.execute(select(TaskInstance).where(TaskInstance.id == video_instance.id))
    ).scalar_one_or_none()
    assert matmul_remaining is None
    assert video_remaining is not None

    refreshed_matmul_order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == matmul_order.id))
    ).scalar_one()
    assert refreshed_matmul_order.materialized_instance_id == matmul_instance.id
    assert refreshed_matmul_order.status == OrderStatus.COMPLETED


@pytest.mark.asyncio
async def test_business_task_list_api(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)
    headers, _admin = await _auth_headers(client, db_session, username="admin-list", role=UserRole.ADMIN)

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

    list_response = await client.get("/api/business-tasks", headers=headers)
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] >= 1
    assert listed["page"] == 1
    item = next(row for row in listed["items"] if row["order_id"] == order_id)
    assert item["task_type"] == "low_latency_video_pipeline"
    assert item["routing_policy"] == "completion_time_first"
    assert item["instance_id"] == instance_id
    assert item["is_benchmark"] is False
    # Business tasks are always SCHEDULED mode (status = "scheduled")
    assert item["deployment_status"] == "scheduled"
    assert item["scheduled_start_time"] is not None
    assert item["scheduled_end_time"] is not None
    assert item["keep_after_stop"] is False
    assert item["business_success"] is None
    assert item["is_benchmark"] is False

    filtered = await client.get(
        "/api/business-tasks",
        params={"task_type": "low_latency_video_pipeline", "routing_policy": "completion_time_first"},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert any(row["order_id"] == order_id for row in filtered.json()["items"])

    normal_only = await client.get(
        "/api/business-tasks",
        params={"is_benchmark": False},
        headers=headers,
    )
    assert normal_only.status_code == 200
    assert any(row["order_id"] == order_id for row in normal_only.json()["items"])

    benchmark_only = await client.get(
        "/api/business-tasks",
        params={"is_benchmark": True},
        headers=headers,
    )
    assert benchmark_only.status_code == 200
    assert all(row["is_benchmark"] is True for row in benchmark_only.json()["items"])

    benchmark_filtered = await client.get(
        "/api/business-tasks",
        params={"is_benchmark": True},
        headers=headers,
    )
    assert benchmark_filtered.status_code == 200
    assert all(row["is_benchmark"] is True for row in benchmark_filtered.json()["items"])

    await client.post(
        f"/api/instances/{instance_id}/metrics",
        json={"metric_key": "end_to_end_latency_ms", "metric_value": 150, "unit": "ms"},
    )
    after_metric = await client.get("/api/business-tasks", params={"business_success": True}, headers=headers)
    assert after_metric.status_code == 200
    success_item = next(row for row in after_metric.json()["items"] if row["order_id"] == order_id)
    assert success_item["actual_value"] == 150
    assert success_item["business_success"] is True

    detail_response = await client.get(f"/api/orders/{order_id}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["business_task"]["task_type"] == "low_latency_video_pipeline"
    assert detail["routing_result"]["strategy"] == "completion_time_first"
    assert detail["routing_result"]["placements"]["compute"] == node_ids[1]
    assert detail["instance"]["id"] == instance_id
    assert detail["evaluation"]["business_success"] is True
    placements = {item["role"]: item for item in detail["node_placements"]}
    assert placements["compute"]["hostname"] == "worker-b"
    assert placements["compute"]["gpu_id"] == "all"


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
    # Video preview metadata used by management/user detail pages
    (
        {
            "result": {
                "frame_latency_p90_ms": 120.5,
                "measured_frames": 30,
                "detector_backend": "opencv_dnn_cpu",
                "model_name": "yolov5n",
                "video_asset": "bottle-detection.mp4",
                "gpu_assigned": True,
                "preview_frame_width": 1280,
                "preview_frame_height": 720,
                "annotated_frame_data_url": "data:image/jpeg;base64,abc123",
                "annotated_frame_overlay": "zh_yolo_v1",
                "detection_count": 1,
                "top_label": "bottle",
                "top_label_zh": "瓶子",
                "detections": [{"label": "bottle", "label_zh": "瓶子", "confidence": 0.93}],
                "raw_frame_bytes": "prune_me",
            }
        },
        {
            "frame_latency_p90_ms": 120.5,
            "measured_frames": 30,
            "detector_backend": "opencv_dnn_cpu",
            "model_name": "yolov5n",
            "video_asset": "bottle-detection.mp4",
            "gpu_assigned": True,
            "preview_frame_width": 1280,
            "preview_frame_height": 720,
            "annotated_frame_data_url": "data:image/jpeg;base64,abc123",
            "annotated_frame_overlay": "zh_yolo_v1",
            "detection_count": 1,
            "top_label": "bottle",
            "top_label_zh": "瓶子",
            "detections": [{"label": "bottle", "label_zh": "瓶子", "confidence": 0.93}],
        },
    ),
])
def test_extract_result_metadata(tags, expected_keys):
    """_extract_result_metadata white-lists keys and ignores checksum / unknown fields."""
    result = _extract_result_metadata(tags)
    assert result == expected_keys
