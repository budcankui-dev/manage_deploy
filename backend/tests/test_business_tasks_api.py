from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from api.auth import hash_password
from api.business_tasks import _extract_result_metadata
from enums import OrderStatus, RoutingStatus, UserRole
from models import (
    BusinessObjectiveEvaluation,
    Node,
    NodeBaseline,
    RoutingResourceEvent,
    SystemSetting,
    TaskInstance,
    TaskInstanceNode,
    TaskMetric,
    TaskOrder,
    User,
)


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
    node_kinds = {
        "worker-a": "terminal",
        "worker-b": "worker",
        "worker-c": "terminal",
    }
    for idx, hostname in enumerate(["worker-a", "worker-b", "worker-c"], start=1):
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "agent_address": f"http://127.0.0.1:800{idx}",
                "management_ip": f"10.0.0.{idx}",
                "business_ip": f"10.0.1.{idx}",
                "node_kind": node_kinds[hostname],
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
                    "port_defs": [{"name": "source", "label": "source HTTP", "default": 18801, "auto": True, "range": [18800, 18899]}],
                    "node_id": node_ids[0],
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "compute", "label": "compute HTTP", "default": 18802, "auto": True, "range": [18800, 18899]}],
                    "node_id": node_ids[1],
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "sink", "label": "sink HTTP", "default": 18803, "auto": True, "range": [18800, 18899]}],
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


def _standard_placements(
    source: str = "worker-a",
    compute: str = "worker-b",
    sink: str = "worker-c",
    *,
    gpu_device: str | None = "0",
) -> list[dict]:
    rows = [
        {"task_node_id": "source", "topology_node_id": source},
        {"task_node_id": "compute", "topology_node_id": compute},
        {"task_node_id": "sink", "topology_node_id": sink},
    ]
    if gpu_device is not None:
        rows[1]["gpu_device"] = gpu_device
    return rows


async def _submit_routing_result(client, order_id: str, payload: dict):
    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_response.status_code == 200, claim_response.text
    return await client.post(f"/api/routing-orders/{order_id}/result", json=payload)


async def _seed_stable_baselines(db_session, node_ids, task_type: str = "high_throughput_matmul"):
    metric_key = "frame_latency_p90_ms" if task_type == "low_latency_video_pipeline" else "effective_gflops"
    operator = "<=" if task_type == "low_latency_video_pipeline" else ">="
    unit = "ms" if task_type == "low_latency_video_pipeline" else "GFLOPS"
    value = 120.0 if task_type == "low_latency_video_pipeline" else 240.0
    db_session.add_all(
        [
            NodeBaseline(
                node_id=node_id,
                task_type=task_type,
                metric_key=metric_key,
                baseline_value=value,
                operator=operator,
                unit=unit,
                run_count=3,
                raw_values=[value - 1, value, value + 1],
            )
            for node_id in node_ids
        ]
    )
    await db_session.flush()


async def _set_runtime_settings(db_session, **overrides):
    value = {
        "environment_mode": "production",
        "intent_parser_mode": "llm",
        "intent_rule_fallback_enabled": True,
        "benchmark_routing_mode": "external",
        "expert_mode": True,
        "show_internal_controls": False,
        "show_routing_dag_json": False,
        **overrides,
    }
    row = (
        await db_session.execute(select(SystemSetting).where(SystemSetting.key == "runtime_modes"))
    ).scalar_one_or_none()
    if row is None:
        row = SystemSetting(key="runtime_modes", value=value)
        db_session.add(row)
    else:
        row.value = value
    await db_session.flush()
    return value


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
async def test_admin_system_settings_roundtrip_and_normalization(client, db_session):
    headers, admin = await _auth_headers(
        client,
        db_session,
        username="system-settings-admin",
        role=UserRole.ADMIN,
    )

    default_response = await client.get("/api/admin/system-settings", headers=headers)
    assert default_response.status_code == 200
    defaults = default_response.json()
    assert defaults["environment_mode"] == "production"
    assert defaults["labels"]["environment_mode"] == "标准模式"
    assert defaults["benchmark_routing_mode"] == "internal_auto"
    assert defaults["expert_mode"] is True
    assert defaults["labels"]["benchmark_routing_mode"] == "自动路由"
    assert defaults["modality_priority_map"]["低时延转发模态"] == 1
    assert defaults["task_modality_override_enabled"] is False
    assert defaults["task_resource_override_enabled"] is False

    update_response = await client.put(
        "/api/admin/system-settings",
        headers=headers,
        json={
            "environment_mode": "not-a-mode",
            "intent_parser_mode": "rule",
            "intent_rule_fallback_enabled": False,
            "benchmark_routing_mode": "external",
            "expert_mode": False,
            "show_internal_controls": True,
            "modality_priority_map": {
                "低时延转发模态": 2,
                "high_throughput_compute": 4,
                "unknown": 99,
            },
            "task_modality_override_enabled": True,
            "task_modality_overrides": {
                "low_latency_video_pipeline": "确定性转发模态",
                "unknown": "低时延转发模态",
            },
            "task_resource_override_enabled": True,
            "task_resource_overrides": {
                "high_throughput_matmul": {
                    "compute": {
                        "cpu_units": 12,
                        "mem_mb": 4096,
                        "disk_mb": 2048,
                        "gpu_units": 1,
                    },
                    "unknown": {"cpu_units": 99},
                }
            },
            "notes": "联调路由系统",
        },
    )
    assert update_response.status_code == 200
    body = update_response.json()
    assert body["environment_mode"] == "production"
    assert body["intent_parser_mode"] == "rule"
    assert body["intent_rule_fallback_enabled"] is False
    assert body["benchmark_routing_mode"] == "external"
    assert body["expert_mode"] is False
    assert body["show_internal_controls"] is True
    assert body["notes"] == "联调路由系统"
    assert body["labels"]["benchmark_routing_mode"] == "外部路由系统"
    assert body["labels"]["environment_mode"] == "标准模式"
    assert body["modality_priority_map"]["低时延转发模态"] == 2
    assert body["modality_priority_map"]["高通量计算模态"] == 4
    assert len(body["modality_priority_rows"]) == 8
    assert body["task_modality_override_enabled"] is True
    assert body["task_modality_overrides"] == {
        "low_latency_video_pipeline": "确定性转发模态",
    }
    assert body["task_resource_override_enabled"] is True
    assert body["task_resource_overrides"]["high_throughput_matmul"]["compute"] == {
        "cpu_units": 12,
        "mem_mb": 4096,
        "disk_mb": 2048,
        "gpu_units": 1,
    }

    stored = (
        await db_session.execute(select(SystemSetting).where(SystemSetting.key == "runtime_modes"))
    ).scalar_one()
    assert stored.updated_by == admin.id
    assert "labels" not in stored.value
    assert "modality_priority_rows" not in stored.value


@pytest.mark.asyncio
async def test_admin_parse_one_uses_runtime_settings(client, db_session):
    headers, _admin = await _auth_headers(
        client,
        db_session,
        username="parse-one-admin",
        role=UserRole.ADMIN,
    )
    await client.put(
        "/api/admin/system-settings",
        headers=headers,
        json={
            "intent_parser_mode": "rule",
            "intent_rule_fallback_enabled": False,
            "benchmark_routing_mode": "internal_auto",
        },
    )
    db_session.add_all(
        [
            Node(
                hostname="h99",
                agent_address="http://127.0.0.1:8999",
                management_ip="10.99.0.1",
                business_ip="10.99.1.1",
                node_kind="terminal",
                is_schedulable=True,
                is_routable=True,
            ),
            Node(
                hostname="h100",
                agent_address="http://127.0.0.1:8100",
                management_ip="10.100.0.1",
                business_ip="10.100.1.1",
                node_kind="terminal",
                is_schedulable=True,
                is_routable=True,
            ),
        ]
    )
    await db_session.commit()

    response = await client.post(
        "/api/admin/intent-parser/parse-one",
        headers=headers,
        json={
            "utterance": "矩阵乘法任务，从 h99 到 h100，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "rule_parser"
    assert body["runtime_settings"]["intent_parser_mode"] == "rule"
    assert body["task_type"] == "high_throughput_matmul"
    assert body["source_name"] == "h99"
    assert body["destination_name"] == "h100"
    assert body["source_endpoint"]["business_ip"] == "10.99.1.1"
    assert body["destination_endpoint"]["business_ip"] == "10.100.1.1"
    assert body["routing_dag"]["job_id"] == "preview"
    assert body["routing_dag"]["priority"] == 5
    assert body["routing_dag"]["edges"][0]["flow"]["priority"] == 5


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
            "placements": _standard_placements(),
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
                "placements": _standard_placements(),
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
        name="验收测评工单",
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
async def test_recalculate_benchmark_evaluations_from_metrics(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    admin_headers, _admin = await _auth_headers(
        client,
        db_session,
        username="benchmark-recalc-admin",
        role=UserRole.ADMIN,
    )
    instance = TaskInstance(
        id="recalc-instance",
        template_id=template_id,
        name="recalc-instance",
        status="stopped",
    )
    order = TaskOrder(
        template_id=template_id,
        name="recalc benchmark order",
        status=OrderStatus.COMPLETED,
        runtime_config={
            "benchmark": {"run_id": "recalc-run"},
            "business_task": {
                "task_type": "high_throughput_matmul",
                "data_profile": {"matrix_size": 1024, "batch_count": 50},
                "business_objective": {
                    "metric_key": "effective_gflops",
                    "operator": ">=",
                    "target_value": 80,
                    "unit": "GFLOPS",
                },
                "runtime_plan": {"routing_strategy": "resource_guarantee"},
                "routing_result": {"strategy": "resource_guarantee", "placements": _standard_placements()},
            },
        },
        materialized_instance_id=instance.id,
        is_benchmark=True,
    )
    metric = TaskMetric(
        instance_id=instance.id,
        template_id=template_id,
        metric_key="effective_gflops",
        metric_value=100,
        unit="GFLOPS",
        tags={
            "result": {
                "effective_gflops": 100,
                "matrix_size": 1024,
                "observation_duration_sec": 10,
                "sample_batch_count": 5,
                "min_samples": 5,
                "backend": "gpu",
            }
        },
    )
    db_session.add_all([instance, order, metric])
    await db_session.commit()

    before = await client.get(
        "/api/business-tasks/summary",
        params={"is_benchmark": True, "benchmark_run_id": "recalc-run"},
    )
    assert before.status_code == 200
    assert before.json()[0]["evaluated_count"] == 0

    response = await client.post(
        "/api/orders/benchmark/recalculate",
        headers=admin_headers,
        json={"benchmark_run_id": "recalc-run", "task_type": "high_throughput_matmul"},
    )
    assert response.status_code == 200
    assert response.json()["succeeded"] == [order.id]
    assert response.json()["failed"] == {}

    after = await client.get(
        "/api/business-tasks/summary",
        params={"is_benchmark": True, "benchmark_run_id": "recalc-run"},
    )
    assert after.status_code == 200
    assert after.json()[0]["evaluated_count"] == 1
    assert after.json()[0]["success_count"] == 1
    assert after.json()[0]["business_success_rate"] == 1.0


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
            "routing_strategy": "low_latency_forwarding",
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
    assert business_task["modality"] == "低时延转发模态"
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
    assert dag["task_type"] == "low_latency_video_pipeline"
    assert dag["modal"] == "低时延转发模态"
    assert dag["routing_strategy"] == "low_latency_forwarding"
    assert dag["policy_type"] == "LATENCY_CONSTRAINED"
    assert dag["priority"] == 1
    assert "constraints" not in dag
    assert [node["task_node_id"] for node in dag["nodes"]] == ["source", "compute", "sink"]
    assert [node["task_role"] for node in dag["nodes"]] == ["source", "compute", "sink"]
    assert [node["task_node_type"] for node in dag["nodes"]] == ["terminal", "worker", "terminal"]
    assert order.source_name == "worker-a"
    assert order.destination_name == "worker-c"
    assert order.runtime_config["platform_deployment"]["deployable_roles"] == ["source", "compute", "sink"]
    assert dag["nodes"][0]["fixed_topology_node_id"] == "worker-a"
    assert dag["nodes"][2]["fixed_topology_node_id"] == "worker-c"
    assert all("exec" not in node for node in dag["nodes"])
    edge_pairs = [(edge["from"], edge["to"], edge["data_mb"], edge["bandwidth_mbps"]) for edge in dag["edges"]]
    assert edge_pairs == [
        ("source", "compute", 2, 20),
        ("compute", "sink", 2, 20),
    ]
    assert dag["edges"][0]["flow"]["dst_port_ref"] == "compute.compute"
    assert "traffic_class" not in dag["edges"][0]["flow"]
    assert dag["edges"][0]["flow"]["priority"] == 1
    assert dag["edges"][1]["flow"]["priority"] == 1
    assert business_task["resource_requirement"] == {
        node["task_node_id"]: node["resources"] for node in dag["nodes"]
    }


@pytest.mark.asyncio
async def test_batch_benchmark_applies_system_resource_overrides_to_routing_dag(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="benchmark-resource-override-user")
    await _set_runtime_settings(
        db_session,
        task_resource_override_enabled=True,
        task_resource_overrides={
            "low_latency_video_pipeline": {
                "compute": {
                    "cpu_units": 6,
                    "mem_mb": 3072,
                    "disk_mb": 2048,
                    "gpu_units": 1,
                }
            }
        },
    )
    await db_session.commit()

    response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "video-resource-override-run",
            "routing_strategy": "low_latency_forwarding",
        },
    )

    assert response.status_code == 200
    order_id = response.json()["order_ids"][0]
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    by_role = {node["task_node_id"]: node["resources"] for node in order.routing_input_dag["nodes"]}

    assert by_role["compute"] == {
        "cpu_units": 6,
        "mem_mb": 3072,
        "disk_mb": 2048,
        "gpu_units": 1,
    }
    assert order.runtime_config["business_task"]["resource_requirement"]["compute"] == by_role["compute"]


@pytest.mark.asyncio
async def test_batch_benchmark_respects_fixed_endpoint_names(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="benchmark-fixed-endpoint-user")

    for idx, hostname in enumerate(["h1", "h2"], start=10):
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "display_name": hostname,
                "agent_address": f"http://127.0.0.1:81{idx}",
                "management_ip": f"10.0.0.{idx}",
                "business_ip": f"10.0.1.{idx}",
                "node_kind": "terminal",
                "is_schedulable": True,
                "is_routable": True,
            },
        )
        assert response.status_code == 200

    response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "fixed-endpoint-run",
            "source_name": "h1",
            "destination_name": "h2",
        },
    )

    assert response.status_code == 200
    order_id = response.json()["order_ids"][0]
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()

    assert order.source_name == "h1"
    assert order.destination_name == "h2"
    assert order.routing_input_dag["nodes"][0]["fixed_topology_node_id"] == "h1"
    assert order.routing_input_dag["nodes"][2]["fixed_topology_node_id"] == "h2"


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
        "strategy": "cost_priority",
        "selected_strategy": "GPU_EXCLUSIVE_LOW_RENT",
        "external_routing_id": "route-meta-001",
        "placements": [
            {"task_node_id": "source", "topology_node_id": "worker-a"},
            {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            {"task_node_id": "sink", "topology_node_id": "worker-c"},
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
    response = await _submit_routing_result(client, order_id, payload)
    assert response.status_code == 200, response.text

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.routing_status == RoutingStatus.NETWORK_BINDING_READY.value
    routing_result = order.runtime_config["routing_result"]
    assert routing_result["selected_strategy"] == "GPU_EXCLUSIVE_LOW_RENT"
    assert routing_result["external_routing_id"] == "route-meta-001"
    assert routing_result["estimated_metric"]["estimated_cost"] == 1.6
    assert routing_result["metadata"]["rent"]["amount"] == 1.6
    assert routing_result["metadata"]["decision_trace_id"] == "trace-meta-001"

    duplicate = await client.post(f"/api/routing-orders/{order_id}/result", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent"] is True

    changed_payload = {
        **payload,
        "selected_strategy": "SHOULD_NOT_REPLACE_PERSISTED_RESULT",
        "external_routing_id": "route-meta-retry",
        "metadata": {"decision_trace_id": "retry-should-not-overwrite"},
    }
    duplicate_changed = await client.post(f"/api/routing-orders/{order_id}/result", json=changed_payload)
    assert duplicate_changed.status_code == 200
    assert duplicate_changed.json()["idempotent"] is True
    routing_row = await db_session.execute(
        select(TaskOrder).where(TaskOrder.id == order_id)
    )
    retried_order = routing_row.scalar_one()
    assert retried_order.runtime_config["routing_result"]["selected_strategy"] == "GPU_EXCLUSIVE_LOW_RENT"
    assert retried_order.runtime_config["routing_result"]["external_routing_id"] == "route-meta-001"
    assert retried_order.runtime_config["routing_result"]["metadata"]["decision_trace_id"] == "trace-meta-001"

    ready_response = await client.post(
        f"/api/routing-orders/{order_id}/network-ready",
        json={"metadata": {"flow_rules": "installed"}, "auto_start": False},
    )
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["routing_status"] == "completed"

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.routing_status == RoutingStatus.COMPLETED.value
    assert order.runtime_config["routing_result"]["network_ready"] is True


@pytest.mark.asyncio
async def test_routing_result_terminal_only_dag_does_not_create_instance(client, db_session):
    for idx, hostname in enumerate(["terminal-a", "terminal-b"], start=1):
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "agent_address": f"http://127.0.0.1:81{idx}",
                "management_ip": f"10.9.0.{idx}",
                "business_ip": f"10.9.1.{idx}",
                "node_kind": "terminal",
                "is_schedulable": False,
            },
        )
        assert response.status_code == 200

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "terminal-only-template",
            "description": "routing-only terminal DAG",
            "nodes": [],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="terminal-only-routing",
        source_name="terminal-a",
        destination_name="terminal-b",
        runtime_config={
            "business_task": {"task_type": "terminal_connectivity"},
            "platform_deployment": {"deployable_roles": []},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "terminal-only-routing",
            "order_id": "terminal-only-routing",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "task_node_type": "terminal", "fixed_topology_node_id": "terminal-a"},
                {"task_node_id": "sink", "task_role": "sink", "task_node_type": "terminal", "fixed_topology_node_id": "terminal-b"},
            ],
            "edges": [{"from": "source", "to": "sink", "data_mb": 1, "bandwidth_mbps": 10}],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [],
            "metadata": {"path": ["terminal-a", "terminal-b"]},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deployment_required"] is False
    assert body["instance_id"] is None

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    saved = row.scalar_one()
    assert saved.routing_status == RoutingStatus.COMPLETED.value
    assert saved.status == OrderStatus.COMPLETED
    assert saved.materialized_instance_id is None
    assert saved.runtime_config["deployment_required"] is False

    instances = await db_session.execute(select(TaskInstance).where(TaskInstance.source_order_id == order.id))
    assert instances.scalars().all() == []


@pytest.mark.asyncio
async def test_route_only_with_compute_placement_does_not_materialize_instance(client, db_session):
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "route-only-compute",
            "agent_address": "http://127.0.0.1:8191",
            "management_ip": "10.9.10.1",
            "business_ip": "10.9.11.1",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "route-only-compute-template",
            "description": "route decision only; no platform deployment",
            "nodes": [
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": compute_response.json()["id"],
                }
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="route-only-compute-decision",
        source_name="h1",
        destination_name="h2",
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul"},
            "platform_deployment": {"mode": "route_only", "deployable_roles": []},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "route-only-compute-decision",
            "order_id": "route-only-compute-decision",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "task_node_type": "terminal", "deployable": False},
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker", "deployable": False},
                {"task_node_id": "sink", "task_role": "sink", "task_node_type": "terminal", "deployable": False},
            ],
            "edges": [{"from": "source", "to": "compute"}, {"from": "compute", "to": "sink"}],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "low_latency_forwarding",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "route-only-compute", "gpu_device": "0"},
            ],
            "metadata": {
                "selected_reason": "仅返回本策略下推荐节点，不触发平台部署",
                "candidate_scores": [{"topology_node_id": "route-only-compute", "latency_ms": 18.2}],
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deployment_required"] is False
    assert body["instance_id"] is None

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    saved = row.scalar_one()
    assert saved.status == OrderStatus.COMPLETED
    assert saved.routing_status == RoutingStatus.COMPLETED.value
    assert saved.materialized_instance_id is None
    assert saved.runtime_config["deployment_required"] is False
    routing_result = saved.runtime_config["routing_result"]
    assert routing_result["deployment_mode"] == "route_only"
    assert routing_result["route_only"] is True
    assert routing_result["placements"] == [
        {"task_node_id": "compute", "topology_node_id": "route-only-compute", "gpu_device": "0"}
    ]
    assert routing_result["metadata"]["candidate_scores"][0]["latency_ms"] == 18.2

    instances = await db_session.execute(select(TaskInstance).where(TaskInstance.source_order_id == order.id))
    assert instances.scalars().all() == []


@pytest.mark.asyncio
async def test_deployable_endpoint_must_be_schedulable_unless_route_only(client, db_session):
    source_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "terminal-without-agent",
            "agent_address": "http://127.0.0.1:8301",
            "management_ip": "10.11.0.1",
            "business_ip": "10.11.1.1",
            "node_kind": "terminal",
            "is_schedulable": False,
            "is_routable": True,
        },
    )
    assert source_response.status_code == 200
    sink_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "worker-sink",
            "agent_address": "http://127.0.0.1:8302",
            "management_ip": "10.11.0.2",
            "business_ip": "10.11.1.2",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert sink_response.status_code == 200
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "worker-compute",
            "agent_address": "http://127.0.0.1:8303",
            "management_ip": "10.11.0.3",
            "business_ip": "10.11.1.3",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "endpoint-validation-template",
            "description": "source/sink endpoint validation",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": sink_response.json()["id"],
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": compute_response.json()["id"],
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": sink_response.json()["id"],
                },
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="endpoint-validation-routing",
        source_name="terminal-without-agent",
        destination_name="worker-sink",
        runtime_config={"business_task": {"task_type": "high_throughput_matmul"}},
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "endpoint-validation-routing",
            "order_id": "endpoint-validation-routing",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "task_node_type": "terminal", "fixed_topology_node_id": "terminal-without-agent"},
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker"},
                {"task_node_id": "sink", "task_role": "sink", "task_node_type": "terminal", "fixed_topology_node_id": "worker-sink"},
            ],
            "edges": [{"from": "source", "to": "compute"}, {"from": "compute", "to": "sink"}],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-compute", "gpu_device": "0"},
            ],
        },
    )
    assert response.status_code == 422
    assert "Endpoint role" in response.json()["detail"]


@pytest.mark.asyncio
async def test_routing_result_allows_worker_nodes_as_fixed_source_and_sink(client, db_session):
    source_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "worker-source",
            "agent_address": "http://127.0.0.1:8401",
            "management_ip": "10.12.0.1",
            "business_ip": "10.12.1.1",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert source_response.status_code == 200
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "worker-compute-2",
            "agent_address": "http://127.0.0.1:8402",
            "management_ip": "10.12.0.2",
            "business_ip": "10.12.1.2",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200
    sink_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "worker-sink-2",
            "agent_address": "http://127.0.0.1:8403",
            "management_ip": "10.12.0.3",
            "business_ip": "10.12.1.3",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert sink_response.status_code == 200

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "worker-endpoints-template",
            "description": "source/sink are fixed topology worker nodes",
            "nodes": [
                {
                    "client_id": "source",
                    "name": "source",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": source_response.json()["id"],
                },
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": compute_response.json()["id"],
                },
                {
                    "client_id": "sink",
                    "name": "sink",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "node_id": sink_response.json()["id"],
                },
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    start = datetime.now(UTC)
    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="worker-endpoint-routing",
        source_name="worker-source",
        destination_name="worker-sink-2",
        business_start_time=start,
        business_end_time=start + timedelta(minutes=5),
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul", "data_profile": {}},
            "platform_deployment": {"deployable_roles": ["source", "compute", "sink"]},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "worker-endpoint-routing",
            "order_id": "worker-endpoint-routing",
            "nodes": [
                {
                    "task_node_id": "source",
                    "task_role": "source",
                    "task_node_type": "terminal",
                    "fixed_topology_node_id": "worker-source",
                },
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker"},
                {
                    "task_node_id": "sink",
                    "task_role": "sink",
                    "task_node_type": "terminal",
                    "fixed_topology_node_id": "worker-sink-2",
                },
            ],
            "edges": [{"from": "source", "to": "compute"}, {"from": "compute", "to": "sink"}],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-compute-2", "gpu_device": "0"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["instance_id"]

    nodes = await db_session.execute(
        select(TaskInstanceNode).where(TaskInstanceNode.instance_id == body["instance_id"])
    )
    placements = {node.name: node for node in nodes.scalars().all()}
    assert set(placements) == {"source", "compute", "sink"}
    assert placements["source"].node_id == source_response.json()["id"]
    assert placements["compute"].node_id == compute_response.json()["id"]
    assert placements["compute"].gpu_id == "0"
    assert placements["sink"].node_id == sink_response.json()["id"]


@pytest.mark.asyncio
async def test_routing_result_two_node_dag_materializes_only_compute_node(client, db_session):
    source_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "endpoint-source",
            "agent_address": "http://127.0.0.1:8201",
            "management_ip": "10.10.0.1",
            "business_ip": "10.10.1.1",
            "node_kind": "terminal",
            "is_schedulable": False,
        },
    )
    assert source_response.status_code == 200
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "compute-dest",
            "agent_address": "http://127.0.0.1:8202",
            "management_ip": "10.10.0.2",
            "business_ip": "10.10.1.2",
            "node_kind": "worker",
        },
    )
    assert compute_response.status_code == 200
    compute_node_id = compute_response.json()["id"]

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "terminal-to-compute-template",
            "description": "source endpoint is virtual, compute is deployed",
            "nodes": [
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "compute", "label": "compute HTTP", "auto": True, "range": [18800, 18899]}],
                    "node_id": compute_node_id,
                }
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    start = datetime.now(UTC)
    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="terminal-to-compute-routing",
        source_name="endpoint-source",
        destination_name="compute-dest",
        business_start_time=start,
        business_end_time=start + timedelta(minutes=5),
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul", "data_profile": {}},
            "platform_deployment": {"deployable_roles": ["compute"]},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "terminal-to-compute-routing",
            "order_id": "terminal-to-compute-routing",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "task_node_type": "terminal", "fixed_topology_node_id": "endpoint-source"},
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker", "fixed_topology_node_id": "compute-dest"},
            ],
            "edges": [{"from": "source", "to": "compute", "data_mb": 1, "bandwidth_mbps": 10}],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "compute-dest", "gpu_device": "0"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    instance_id = response.json()["instance_id"]
    assert instance_id

    nodes = await db_session.execute(select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id))
    instance_nodes = nodes.scalars().all()
    assert len(instance_nodes) == 1
    compute_node = instance_nodes[0]
    assert compute_node.name == "compute"
    assert compute_node.node_id == compute_node_id
    assert compute_node.gpu_id == "0"
    assert compute_node.env["TASK_ROLE"] == "compute"
    assert compute_node.env["SOURCE_NAME"] == "endpoint-source"
    assert compute_node.env["DESTINATION_NAME"] == "compute-dest"
    assert compute_node.env["GPU_DEVICE"] == "0"
    assert compute_node.env["DEPLOYABLE_ROLES"] == "compute"
    assert compute_node.env["PEER_WAIT_TIMEOUT_SEC"] == "3600"

    bindings = response.json()["network_bindings"]
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["from"] == "source"
    assert binding["to"] == "compute"
    assert binding["binding_source"] == "routing_dag"
    assert binding["src_external"] is True
    assert binding["dst_external"] is False
    assert binding["src_host"] == "endpoint-source"
    assert binding["src_ip"] == "10.10.1.1"
    assert binding["dst_host"] == "compute-dest"
    assert binding["dst_ip"] == "10.10.1.2"
    assert isinstance(binding["dst_port"], int)
    assert binding["dst_access_url"] == f"http://10.10.1.2:{binding['dst_port']}"


@pytest.mark.asyncio
async def test_compute_only_external_sink_binding_uses_callback_url(client, db_session):
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "callback-compute",
            "agent_address": "http://127.0.0.1:8304",
            "management_ip": "10.12.0.2",
            "business_ip": "10.12.1.2",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200
    compute_node_id = compute_response.json()["id"]

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "compute-with-external-callback-template",
            "description": "compute is deployed and calls back external sink",
            "nodes": [
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "compute", "label": "compute HTTP", "auto": True, "range": [18800, 18899]}],
                    "node_id": compute_node_id,
                }
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    callback_url = "https://user.example.test/result-callback"
    start = datetime.now(UTC)
    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="compute-external-sink-callback",
        source_name="endpoint-source",
        destination_name="user-sink",
        business_start_time=start,
        business_end_time=start + timedelta(minutes=5),
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul", "data_profile": {}},
            "platform_deployment": {
                "deployable_roles": ["compute"],
                "external_endpoints": {
                    "sink": {
                        "callback_url": callback_url,
                    },
                },
            },
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "compute-external-sink-callback",
            "order_id": "compute-external-sink-callback",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "task_node_type": "terminal", "fixed_topology_node_id": "endpoint-source"},
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker"},
                {
                    "task_node_id": "sink",
                    "task_role": "sink",
                    "task_node_type": "terminal",
                    "fixed_topology_node_id": "user-sink",
                    "callback_url": callback_url,
                },
            ],
            "edges": [
                {"from": "source", "to": "compute", "data_mb": 1, "bandwidth_mbps": 10},
                {"from": "compute", "to": "sink", "data_mb": 1, "bandwidth_mbps": 10},
            ],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "callback-compute", "gpu_device": "0"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    instance_id = response.json()["instance_id"]

    nodes = await db_session.execute(select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id))
    compute_node = nodes.scalars().one()
    assert compute_node.env["CALLBACK_URL"] == callback_url
    assert compute_node.env["PEER_WAIT_TIMEOUT_SEC"] == "3600"

    bindings = response.json()["network_bindings"]
    assert len(bindings) == 2
    sink_binding = next(item for item in bindings if item["to"] == "sink")
    assert sink_binding["from"] == "compute"
    assert sink_binding["dst_external"] is True
    assert sink_binding["dst_host"] == "user-sink"
    assert sink_binding["dst_callback_url"] == callback_url
    assert sink_binding["dst_access_url"] == callback_url


@pytest.mark.asyncio
async def test_compute_only_bindings_resolve_fixed_topology_node_ids(client, db_session):
    source_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "h-binding-source",
            "agent_address": "http://127.0.0.1:8401",
            "management_ip": "10.13.0.1",
            "business_ip": "10.13.1.1",
            "node_kind": "terminal",
            "topology_node_id": "h18001001",
            "is_schedulable": False,
            "is_routable": True,
        },
    )
    assert source_response.status_code == 200
    sink_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "h-binding-sink",
            "agent_address": "http://127.0.0.1:8403",
            "management_ip": "10.13.0.3",
            "business_ip": "10.13.1.3",
            "node_kind": "terminal",
            "topology_node_id": "h18005003",
            "is_schedulable": False,
            "is_routable": True,
        },
    )
    assert sink_response.status_code == 200
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "binding-compute",
            "agent_address": "http://127.0.0.1:8402",
            "management_ip": "10.13.0.2",
            "business_ip": "10.13.1.2",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200
    compute_node_id = compute_response.json()["id"]

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "compute-only-topology-id-template",
            "description": "compute is deployed, endpoints are fixed by asset topology id",
            "nodes": [
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "compute", "label": "compute HTTP", "auto": True, "range": [18800, 18899]}],
                    "node_id": compute_node_id,
                }
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    start = datetime.now(UTC)
    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="compute-only-topology-id-routing",
        source_name="h-binding-source",
        destination_name="h-binding-sink",
        business_start_time=start,
        business_end_time=start + timedelta(minutes=5),
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul", "data_profile": {}},
            "platform_deployment": {"deployable_roles": ["compute"]},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "compute-only-topology-id-routing",
            "order_id": "compute-only-topology-id-routing",
            "nodes": [
                {
                    "task_node_id": "source",
                    "task_role": "source",
                    "task_node_type": "terminal",
                    "fixed_topology_node_id": "h18001001",
                    "topology_alias": "h-binding-source",
                },
                {"task_node_id": "compute", "task_role": "compute", "task_node_type": "worker"},
                {
                    "task_node_id": "sink",
                    "task_role": "sink",
                    "task_node_type": "terminal",
                    "fixed_topology_node_id": "h18005003",
                    "topology_alias": "h-binding-sink",
                    "business_port": 9000,
                },
            ],
            "edges": [
                {"from": "source", "to": "compute", "data_mb": 1, "bandwidth_mbps": 10},
                {"from": "compute", "to": "sink", "data_mb": 1, "bandwidth_mbps": 10},
            ],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "binding-compute", "gpu_device": "0"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    bindings = response.json()["network_bindings"]
    source_binding = next(item for item in bindings if item["from"] == "source")
    sink_binding = next(item for item in bindings if item["to"] == "sink")
    assert source_binding["src_topology_node_id"] == "h18001001"
    assert source_binding["src_host"] == "h-binding-source"
    assert source_binding["src_ip"] == "10.13.1.1"
    assert sink_binding["dst_topology_node_id"] == "h18005003"
    assert sink_binding["dst_host"] == "h-binding-sink"
    assert sink_binding["dst_ip"] == "10.13.1.3"
    assert sink_binding["dst_port"] == 9000
    assert sink_binding["dst_access_url"] == "http://10.13.1.3:9000"


@pytest.mark.asyncio
async def test_compute_only_bindings_ignore_router_source_sink_placements(client, db_session):
    await client.post(
        "/api/nodes",
        json={
            "hostname": "user-source-fixed",
            "agent_address": "http://127.0.0.1:8451",
            "management_ip": "10.14.0.1",
            "business_ip": "10.14.1.1",
            "node_kind": "terminal",
            "topology_node_id": "h18001001",
            "is_schedulable": False,
            "is_routable": True,
        },
    )
    await client.post(
        "/api/nodes",
        json={
            "hostname": "user-sink-fixed",
            "agent_address": "http://127.0.0.1:8453",
            "management_ip": "10.14.0.3",
            "business_ip": "10.14.1.3",
            "node_kind": "terminal",
            "topology_node_id": "h18005003",
            "is_schedulable": False,
            "is_routable": True,
        },
    )
    compute_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "compute-fixed-only",
            "agent_address": "http://127.0.0.1:8452",
            "management_ip": "10.14.0.2",
            "business_ip": "10.14.1.2",
            "node_kind": "worker",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert compute_response.status_code == 200

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "compute-only-ignore-router-endpoints",
            "nodes": [
                {
                    "client_id": "compute",
                    "name": "compute",
                    "image": "busybox:latest",
                    "command": "sleep 3600",
                    "port_defs": [{"name": "compute", "label": "compute HTTP", "auto": True, "range": [18800, 18899]}],
                    "node_id": compute_response.json()["id"],
                }
            ],
            "edges": [],
        },
    )
    assert template_response.status_code == 200

    start = datetime.now(UTC)
    order = TaskOrder(
        template_id=template_response.json()["id"],
        name="compute-only-ignore-router-endpoints",
        source_name="user-source-fixed",
        destination_name="user-sink-fixed",
        business_start_time=start,
        business_end_time=start + timedelta(minutes=5),
        runtime_config={
            "business_task": {"task_type": "high_throughput_matmul", "data_profile": {}},
            "platform_deployment": {"deployable_roles": ["compute"]},
        },
        routing_status=RoutingStatus.PENDING.value,
        status=OrderStatus.PENDING,
        routing_input_dag={
            "job_id": "compute-only-ignore-router-endpoints",
            "order_id": "compute-only-ignore-router-endpoints",
            "nodes": [
                {"task_node_id": "source", "task_role": "source", "fixed_topology_node_id": "h18001001"},
                {"task_node_id": "compute", "task_role": "compute"},
                {
                    "task_node_id": "sink",
                    "task_role": "sink",
                    "fixed_topology_node_id": "h18005003",
                    "business_port": 9000,
                },
            ],
            "edges": [
                {"from": "source", "to": "compute", "data_mb": 1, "bandwidth_mbps": 10},
                {"from": "compute", "to": "sink", "data_mb": 1, "bandwidth_mbps": 10},
            ],
        },
    )
    db_session.add(order)
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order.id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "source", "topology_node_id": "wrong-router-source"},
                {"task_node_id": "compute", "topology_node_id": "compute-fixed-only", "gpu_device": "0"},
                {"task_node_id": "sink", "topology_node_id": "wrong-router-sink"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    bindings = response.json()["network_bindings"]
    source_binding = next(item for item in bindings if item["from"] == "source")
    sink_binding = next(item for item in bindings if item["to"] == "sink")
    assert source_binding["src_topology_node_id"] == "h18001001"
    assert source_binding["src_host"] == "user-source-fixed"
    assert source_binding["src_ip"] == "10.14.1.1"
    assert sink_binding["dst_topology_node_id"] == "h18005003"
    assert sink_binding["dst_host"] == "user-sink-fixed"
    assert sink_binding["dst_ip"] == "10.14.1.3"


@pytest.mark.asyncio
async def test_routing_result_can_omit_fixed_source_and_sink_placements(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="route-compute-only-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "route-compute-only-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    dag_nodes = []
    for node in order.routing_input_dag["nodes"]:
        item = dict(node)
        if item["task_node_id"] == "source":
            item["fixed_topology_node_id"] = "worker-a"
        elif item["task_node_id"] == "sink":
            item["fixed_topology_node_id"] = "worker-c"
        dag_nodes.append(item)
    order.source_name = "worker-a"
    order.destination_name = "worker-c"
    order.routing_input_dag = {**order.routing_input_dag, "nodes": dag_nodes}
    await db_session.flush()

    response = await _submit_routing_result(
        client,
        order_id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            ],
            "metadata": {"path": ["worker-a", "worker-b", "worker-c"]},
        },
    )
    assert response.status_code == 200, response.text
    instance_id = response.json()["instance_id"]

    nodes = await db_session.execute(select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id))
    names = sorted(node.name for node in nodes.scalars().all())
    assert names == ["compute", "sink", "source"]

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    placements = order.runtime_config["routing_result"]["placements"]
    assert [item["task_node_id"] for item in placements] == ["compute", "source", "sink"]
    assert order.runtime_config["routing_result"]["router_placements"] == [
        {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"}
    ]


@pytest.mark.asyncio
async def test_routing_result_rejects_legacy_placement_fields(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-asset-id-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-asset-id-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    response = await _submit_routing_result(
        client,
        order_id,
        {
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_indices": ["0"]},
            ],
        },
    )
    assert response.status_code == 422
    assert "gpu_indices" in response.text


@pytest.mark.asyncio
async def test_routing_order_http_flow_without_service_token(client, db_session):
    _node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-order-http-user")

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
    assert pending_orders[0]["routing_input_dag"]["task_type"] == "low_latency_video_pipeline"

    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_response.status_code == 200
    assert claim_response.json()["routing_status"] == "computing"

    result_response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "source", "topology_node_id": "worker-a"},
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
                {"task_node_id": "sink", "topology_node_id": "worker-c"},
            ],
            "metadata": {
                "path": ["worker-a", "worker-b", "worker-c"],
                "algorithm_version": "router-http-test",
            },
        },
    )
    assert result_response.status_code == 200, result_response.text
    result_body = result_response.json()
    assert result_body["routing_status"] == "network_binding_ready"
    assert result_body["network_ready_required"] is True
    assert result_body["network_ready"] is False
    assert "network_bindings" in result_body
    assert len(result_body["network_bindings"]) == 2
    compute_binding = next(item for item in result_body["network_bindings"] if item["to"] == "compute")
    sink_binding = next(item for item in result_body["network_bindings"] if item["to"] == "sink")
    assert compute_binding["dst_host"] == "worker-b"
    assert isinstance(compute_binding["dst_port"], int)
    assert sink_binding["dst_host"] == "worker-c"

    start_blocked = await client.post(f"/api/instances/{result_body['instance_id']}/start")
    assert start_blocked.status_code == 409
    assert "network-ready" in start_blocked.json()["detail"]

    ready_response = await client.post(
        f"/api/routing-orders/{order_id}/network-ready",
        json={"metadata": {"flow_rules": "installed"}, "auto_start": False},
    )
    assert ready_response.status_code == 200, ready_response.text
    assert ready_response.json()["routing_status"] == "completed"

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.materialized_instance_id
    assert order.routing_status == RoutingStatus.COMPLETED.value
    assert order.runtime_config["routing_result"]["metadata"]["algorithm_version"] == "router-http-test"
    assert order.runtime_config["routing_result"]["network_ready"] is True


@pytest.mark.asyncio
async def test_routing_order_result_requires_claim(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-claim-required-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-claim-required-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    result_response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            ],
        },
    )

    assert result_response.status_code == 409
    assert result_response.json()["detail"] == "Please claim this order before submitting routing result"


@pytest.mark.asyncio
async def test_legacy_order_routing_result_endpoint_is_not_public(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="legacy-routing-endpoint-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "legacy-routing-endpoint-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    result_response = await client.post(
        f"/api/orders/{order_id}/routing-result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            ],
        },
    )

    assert result_response.status_code == 404


@pytest.mark.asyncio
async def test_router_can_requeue_and_fail_routing_order_without_service_token(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-status-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-status-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_response.status_code == 200
    assert claim_response.json()["routing_status"] == "computing"

    requeue_response = await client.patch(
        f"/api/routing-orders/{order_id}/requeue",
        json={"reason": "GPU slots temporarily full"},
    )
    assert requeue_response.status_code == 200
    assert requeue_response.json()["routing_status"] == "pending"

    claim_again = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_again.status_code == 200

    fail_response = await client.patch(
        f"/api/routing-orders/{order_id}/fail",
        json={"reason": "No feasible placement"},
    )
    assert fail_response.status_code == 200
    assert fail_response.json()["routing_status"] == "failed"

    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one()
    assert order.error_message == "No feasible placement"


@pytest.mark.asyncio
async def test_routing_result_rejects_active_gpu_slot_conflict(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-conflict-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 2,
            "benchmark_run_id": "routing-conflict-run",
        },
    )
    assert create_response.status_code == 200
    first_id, second_id = create_response.json()["order_ids"]

    payload = {
        "strategy": "resource_guarantee",
        "placements": [
            {"task_node_id": "source", "topology_node_id": "worker-a"},
            {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            {"task_node_id": "sink", "topology_node_id": "worker-c"},
        ],
    }
    first_claim = await client.patch(f"/api/routing-orders/{first_id}/claim")
    assert first_claim.status_code == 200
    first = await client.post(f"/api/routing-orders/{first_id}/result", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["routing_status"] == "network_binding_ready"

    second_claim = await client.patch(f"/api/routing-orders/{second_id}/claim")
    assert second_claim.status_code == 200
    second = await client.post(f"/api/routing-orders/{second_id}/result", json=payload)
    assert second.status_code == 409
    assert "GPU slot conflict" in second.json()["detail"]


@pytest.mark.asyncio
async def test_routing_result_default_benchmark_gpu_participates_in_conflict_check(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-default-gpu-conflict-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 2,
            "benchmark_run_id": "routing-default-gpu-conflict-run",
        },
    )
    assert create_response.status_code == 200
    first_id, second_id = create_response.json()["order_ids"]

    payload_without_gpu = {
        "strategy": "resource_guarantee",
        "placements": [
            {"task_node_id": "source", "topology_node_id": "worker-a"},
            {"task_node_id": "compute", "topology_node_id": "worker-b"},
            {"task_node_id": "sink", "topology_node_id": "worker-c"},
        ],
    }
    first_claim = await client.patch(f"/api/routing-orders/{first_id}/claim")
    assert first_claim.status_code == 200
    first = await client.post(f"/api/routing-orders/{first_id}/result", json=payload_without_gpu)
    assert first.status_code == 200, first.text

    first_order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == first_id))
    ).scalar_one()
    placements = first_order.runtime_config["routing_result"]["placements"]
    compute = next(item for item in placements if item["task_node_id"] == "compute")
    assert compute["gpu_device"] == "0"

    second_claim = await client.patch(f"/api/routing-orders/{second_id}/claim")
    assert second_claim.status_code == 200
    second = await client.post(f"/api/routing-orders/{second_id}/result", json=payload_without_gpu)
    assert second.status_code == 409
    assert "GPU slot conflict" in second.json()["detail"]


@pytest.mark.asyncio
async def test_routing_result_rejects_soft_deleted_order(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-deleted-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-deleted-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    ).scalar_one()
    order.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    await db_session.flush()

    response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
            ],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


@pytest.mark.asyncio
async def test_delete_order_emits_and_acks_routing_resource_release_event(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-release-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-release-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_response.status_code == 200

    result_response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "source", "topology_node_id": "worker-a"},
                {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
                {"task_node_id": "sink", "topology_node_id": "worker-c"},
            ],
            "external_routing_id": "route-release-001",
            "metadata": {"algorithm_version": "release-test"},
        },
    )
    assert result_response.status_code == 200, result_response.text

    delete_response = await client.delete(f"/api/orders/{order_id}")
    assert delete_response.status_code == 200

    events_response = await client.get(
        "/api/routing-resource-events",
        params={"benchmark_run_id": "routing-release-run"},
    )
    assert events_response.status_code == 200
    events = events_response.json()
    assert len(events) == 1
    assert events[0]["order_id"] == order_id
    assert events[0]["job_id"] == order_id
    assert events[0]["node_hostname"] == "worker-b"
    assert events[0]["resource_kind"] == "gpu"
    assert events[0]["resource_id"] == "0"
    assert events[0]["reason"] == "delete_order"

    ack_response = await client.post(
        "/api/routing-resource-events/ack",
        json={"ids": [events[0]["id"]]},
    )
    assert ack_response.status_code == 200
    assert ack_response.json()["acked"] == 1

    event_row = (
        await db_session.execute(select(RoutingResourceEvent).where(RoutingResourceEvent.id == events[0]["id"]))
    ).scalar_one()
    assert event_row.router_ack_at is not None


@pytest.mark.asyncio
async def test_delete_order_releases_default_benchmark_gpu_when_router_omits_gpu(client, db_session):
    await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-default-gpu-release-user")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "routing-default-gpu-release-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    claim_response = await client.patch(f"/api/routing-orders/{order_id}/claim")
    assert claim_response.status_code == 200

    result_response = await client.post(
        f"/api/routing-orders/{order_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": [
                {"task_node_id": "source", "topology_node_id": "worker-a"},
                {"task_node_id": "compute", "topology_node_id": "worker-b"},
                {"task_node_id": "sink", "topology_node_id": "worker-c"},
            ],
            "external_routing_id": "route-default-gpu-release-001",
        },
    )
    assert result_response.status_code == 200, result_response.text

    delete_response = await client.delete(f"/api/orders/{order_id}")
    assert delete_response.status_code == 200

    events_response = await client.get(
        "/api/routing-resource-events",
        params={"benchmark_run_id": "routing-default-gpu-release-run"},
    )
    assert events_response.status_code == 200
    events = events_response.json()
    assert len(events) == 1
    assert events[0]["node_hostname"] == "worker-b"
    assert events[0]["resource_kind"] == "gpu"
    assert events[0]["resource_id"] == "0"


@pytest.mark.asyncio
async def test_batch_auto_route_can_scope_by_task_type(client, db_session, monkeypatch):
    import api.orders as orders_api

    async def all_agents_healthy(nodes):
        return list(nodes), []

    monkeypatch.setattr(orders_api, "_filter_nodes_with_healthy_agents", all_agents_healthy)

    node_ids, template_id = await _seed_business_fixture(client)
    await _seed_stable_baselines(db_session, node_ids, "high_throughput_matmul")
    headers, _user = await _auth_headers(client, db_session, username="benchmark-scope-user")
    await _set_runtime_settings(db_session, benchmark_routing_mode="internal_auto")
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
    compute_route = next(item for item in routing_placements if item["task_node_id"] == "compute")
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
async def test_batch_auto_route_skips_non_routable_nodes(client, db_session, monkeypatch):
    import api.orders as orders_api

    async def all_agents_healthy(nodes):
        return list(nodes), []

    monkeypatch.setattr(orders_api, "_filter_nodes_with_healthy_agents", all_agents_healthy)

    node_ids, template_id = await _seed_business_fixture(client)
    await _seed_stable_baselines(db_session, node_ids, "high_throughput_matmul")
    headers, _user = await _auth_headers(client, db_session, username="benchmark-routable-user")
    await _set_runtime_settings(db_session, benchmark_routing_mode="internal_auto")

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

    nodes = (await db_session.execute(select(TaskInstanceNode))).scalars().all()
    assert nodes == []

    node_rows = await client.get("/api/nodes")
    assert node_rows.status_code == 200
    worker_b = next(node for node in node_rows.json() if node["hostname"] == "worker-b")
    update_response = await client.put(f"/api/nodes/{worker_b['id']}", json={"is_routable": False})
    assert update_response.status_code == 200

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "high_throughput_matmul",
            "count": 6,
            "benchmark_run_id": "routable-run",
        },
    )
    assert create_response.status_code == 200
    order_ids = create_response.json()["order_ids"]

    route_response = await client.post(
        "/api/orders/batch-auto-route",
        headers=headers,
        json={"benchmark_run_id": "routable-run"},
    )
    assert route_response.status_code == 200
    route_body = route_response.json()
    assert route_body["routed"] == 0
    assert len(route_body["failed"]) == len(order_ids)
    assert all("No stable baseline compute nodes available" in item["error"] for item in route_body["failed"])


@pytest.mark.asyncio
async def test_batch_auto_route_skips_unhealthy_agent_nodes(client, db_session, monkeypatch):
    import api.orders as orders_api

    node_ids, template_id = await _seed_business_fixture(client)
    await _seed_stable_baselines(db_session, node_ids, "high_throughput_matmul")
    headers, _user = await _auth_headers(client, db_session, username="benchmark-healthy-agent-user")
    await _set_runtime_settings(db_session, benchmark_routing_mode="internal_auto")

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

    async def fake_probe(nodes):
        healthy = [node for node in nodes if node.hostname != "worker-b"]
        skipped = [
            {"hostname": node.hostname, "reason": "node_agent unreachable"}
            for node in nodes
            if node.hostname == "worker-b"
        ]
        return healthy, skipped

    monkeypatch.setattr(orders_api, "_filter_nodes_with_healthy_agents", fake_probe)

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "high_throughput_matmul",
            "count": 3,
            "benchmark_run_id": "healthy-agent-run",
        },
    )
    assert create_response.status_code == 200
    order_ids = create_response.json()["order_ids"]

    route_response = await client.post(
        "/api/orders/batch-auto-route",
        headers=headers,
        json={"benchmark_run_id": "healthy-agent-run"},
    )
    assert route_response.status_code == 200
    body = route_response.json()
    assert body["routed"] == 0
    assert body["skipped_unhealthy_nodes"] == [
        {"hostname": "worker-b", "reason": "node_agent unreachable"}
    ]
    assert len(body["failed"]) == len(order_ids)
    assert all("No stable baseline compute nodes available" in item["error"] for item in body["failed"])


@pytest.mark.asyncio
async def test_batch_auto_route_rejected_when_external_routing_configured(client, db_session):
    node_ids, template_id = await _seed_business_fixture(client)
    await _seed_stable_baselines(db_session, node_ids, "high_throughput_matmul")
    headers, _user = await _auth_headers(client, db_session, username="benchmark-external-route-user")
    await _set_runtime_settings(db_session, benchmark_routing_mode="external")

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

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "high_throughput_matmul",
            "count": 1,
            "benchmark_run_id": "external-route-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    route_response = await client.post(
        "/api/orders/batch-auto-route",
        headers=headers,
        json={"benchmark_run_id": "external-route-run"},
    )
    assert route_response.status_code == 409

    single_response = await client.post(f"/api/orders/{order_id}/auto-route", headers=headers)
    assert single_response.status_code == 409


@pytest.mark.asyncio
async def test_mock_auto_route_single_order_is_benchmark_only(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    headers, user = await _auth_headers(client, db_session, username="benchmark-single-route-user")
    await _set_runtime_settings(db_session, benchmark_routing_mode="internal_auto")
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
    assert response.json()["detail"] == "系统自动分配仅支持业务测评工单"


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
            "placements": _standard_placements(),
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
            "placements": _standard_placements(),
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
            "placements": _standard_placements(),
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
            "placements": _standard_placements(),
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
async def test_order_detail_uses_latest_metric_as_unscored_evidence(client, db_session):
    _node_ids, template_id = await _seed_business_fixture(client)
    headers, user = await _auth_headers(client, db_session, username="metric-evidence-user")
    instance = TaskInstance(
        id="metric-evidence-instance",
        template_id=template_id,
        name="metric-evidence-instance",
        status="running",
    )
    order = TaskOrder(
        template_id=template_id,
        name="轻量演示工单",
        status=OrderStatus.MATERIALIZED,
        user_id=user.id,
        runtime_config={
            "business_task": {
                "task_type": "high_throughput_matmul",
                "data_profile": {"matrix_size": 256, "batch_count": 10},
                "business_objective": {
                    "metric_key": "effective_gflops",
                    "operator": ">=",
                    "unit": "GFLOPS",
                },
                "runtime_plan": {"routing_strategy": "resource_guarantee"},
            },
        },
        materialized_instance_id=instance.id,
        is_benchmark=False,
    )
    metric = TaskMetric(
        instance_id=instance.id,
        template_id=template_id,
        metric_key="effective_gflops",
        metric_value=4.82,
        unit="GFLOPS",
        tags={
            "result": {
                "effective_gflops": 4.82,
                "matrix_size": 256,
                "batch_count": 10,
                "backend": "gpu",
            }
        },
    )
    db_session.add_all([instance, order, metric])
    await db_session.commit()

    detail_response = await client.get(f"/api/orders/{order.id}", headers=headers)
    assert detail_response.status_code == 200
    evaluation = detail_response.json()["evaluation"]
    assert evaluation["metric_key"] == "effective_gflops"
    assert evaluation["actual_value"] == 4.82
    assert evaluation["target_value"] is None
    assert evaluation["business_success"] is None
    assert "尚未形成正式业务目标判定" in evaluation["failure_reason"]
    assert evaluation["result_metadata"]["matrix_size"] == 256


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
                    "placements": [
                        {"task_node_id": "compute", "topology_node_id": "worker-a", "gpu_device": "0"}
                    ],
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
            "placements": _standard_placements(),
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
    compute_route = next(item for item in detail["routing_result"]["placements"] if item["task_node_id"] == "compute")
    assert compute_route["topology_node_id"] == "worker-b"
    assert detail["instance"]["id"] == instance_id
    assert detail["evaluation"]["business_success"] is True
    placements = {item["role"]: item for item in detail["node_placements"]}
    assert placements["compute"]["hostname"] == "worker-b"
    assert placements["compute"]["gpu_id"] == "0"


@pytest.mark.asyncio
async def test_order_detail_exposes_routing_decision_summary(client, db_session):
    node_ids, _template_id = await _seed_business_fixture(client)
    headers, _user = await _auth_headers(client, db_session, username="routing-decision-user")
    await _seed_stable_baselines(db_session, node_ids, "low_latency_video_pipeline")

    create_response = await client.post(
        "/api/orders/batch-benchmark",
        headers=headers,
        json={
            "task_type": "low_latency_video_pipeline",
            "count": 1,
            "benchmark_run_id": "decision-summary-run",
        },
    )
    assert create_response.status_code == 200
    order_id = create_response.json()["order_ids"][0]

    payload = {
        "strategy": "low_latency_forwarding",
        "selected_strategy": "LATENCY_CONSTRAINED",
        "placements": [
            {"task_node_id": "compute", "topology_node_id": "worker-b", "gpu_device": "0"},
        ],
        "metadata": {
            "path": ["worker-a", "worker-b", "worker-c"],
            "selected_reason": "worker-b 在低时延转发策略下链路更短，且 GPU baseline 稳定",
            "candidate_scores": [
                {"topology_node_id": "worker-b", "latency_ms": 18.2, "score": 0.93},
                {"topology_node_id": "worker-c", "latency_ms": 24.8, "score": 0.81},
            ],
            "rent": {"amount": 1.6, "currency": "CNY", "billing_unit": "task"},
        },
    }
    response = await _submit_routing_result(client, order_id, payload)
    assert response.status_code == 200, response.text

    detail_response = await client.get(f"/api/orders/{order_id}", headers=headers)
    assert detail_response.status_code == 200, detail_response.text
    decision = detail_response.json()["routing_decision"]
    assert decision["strategy"] == "low_latency_forwarding"
    assert decision["selected_strategy"] == "LATENCY_CONSTRAINED"
    assert decision["selected_compute"]["topology_node_id"] == "worker-b"
    assert decision["selected_compute"]["gpu_device"] == "0"
    assert decision["selected_compute"]["baseline"]["metric_key"] == "frame_latency_p90_ms"
    assert decision["selected_compute"]["baseline"]["baseline_value"] == 120.0
    assert decision["path"] == ["worker-a", "worker-b", "worker-c"]
    assert decision["selected_reason"].startswith("worker-b")
    assert decision["candidate_scores"][0]["baseline"]["baseline_value"] == 120.0
    assert decision["metadata"]["rent"]["amount"] == 1.6


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
