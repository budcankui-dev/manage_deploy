import pytest
from sqlalchemy import select

from config import settings
from models import TaskInstanceNode, TaskOrder
from tests.test_business_tasks_api import _auth_headers, _seed_business_fixture, _standard_placements


@pytest.mark.asyncio
async def test_conversation_parse_confirm_route_and_submit(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)
    _node_ids, _template_id = await _seed_business_fixture(client)
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
    assert confirm_body["materialized_order_id"] == conversation_id
    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    source_node = next(item for item in order.routing_input_dag["nodes"] if item["task_node_id"] == "source")
    sink_node = next(item for item in order.routing_input_dag["nodes"] if item["task_node_id"] == "sink")
    assert source_node["topology_node_id"] == "worker-a"
    assert source_node["business_ip"] == "10.0.1.1"
    assert sink_node["topology_node_id"] == "worker-c"
    assert sink_node["business_ip"] == "10.0.1.3"

    claim_response = await client.patch(f"/api/routing-orders/{conversation_id}/claim")
    assert claim_response.status_code == 200
    assert claim_response.json()["order_id"] == conversation_id
    assert claim_response.json()["routing_status"] == "computing"

    result_response = await client.post(
        f"/api/routing-orders/{conversation_id}/result",
        json={
            "strategy": "completion_time_first",
            "placements": _standard_placements(),
            "estimated_metric": {
                "metric_key": "end_to_end_latency_ms",
                "metric_value": 180,
                "unit": "ms",
            },
            "external_routing_id": "router-mock-001",
            "require_network_ready": False,
        },
    )
    assert result_response.status_code == 200
    assert result_response.json()["order_id"] == conversation_id
    assert result_response.json()["routing_status"] == "completed"

    detail_response = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "submitted"
    routing_placements = detail_response.json()["latest_routing_request"]["placements"]
    compute_route = next(item for item in routing_placements if item["task_node_id"] == "compute")
    assert compute_route["topology_node_id"] == "worker-b"
    assert compute_route["gpu_device"] == "0"

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    assert order.runtime_config["platform_deployment"]["mode"] == "user_access_demo"
    assert order.runtime_config["platform_deployment"]["deployable_roles"] == ["compute"]
    assert order.materialized_instance_id
    order_placements = order.runtime_config["routing_result"]["placements"]
    compute_order_route = next(item for item in order_placements if item["task_node_id"] == "compute")
    assert compute_order_route["topology_node_id"] == "worker-b"
    assert compute_order_route["gpu_device"] == "0"

    inst_nodes = (
        await db_session.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == order.materialized_instance_id)
        )
    ).scalars().all()
    by_role = {node.env["TASK_ROLE"]: node for node in inst_nodes}
    assert by_role["compute"].node_id
    assert by_role["compute"].gpu_id == "0"
    assert by_role["compute"].env["GPU_DEVICE"] == "0"


@pytest.mark.asyncio
async def test_confirm_intent_preserves_explicit_callback_url(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="callback-url-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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

    create_response = await client.post("/api/conversations", json={"title": "回调矩阵任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    assert message_response.json()["latest_draft"]["parse_status"] == "valid"

    callback_url = "https://user.example.test/api/matmul-result"
    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"callback_url": callback_url},
        headers=headers,
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["latest_draft"]["callback_url"] == callback_url

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    business_task = order.runtime_config["business_task"]
    assert business_task["callback_url"] == callback_url
    assert order.runtime_config["platform_deployment"]["external_endpoints"]["sink"]["callback_url"] == callback_url
    sink_node = next(item for item in order.routing_input_dag["nodes"] if item["task_node_id"] == "sink")
    assert sink_node["callback_url"] == callback_url


@pytest.mark.asyncio
async def test_confirm_intent_resolves_user_endpoint_inputs_into_routing_dag(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="endpoint-input-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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
    source_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "h1",
            "display_name": "h1",
            "agent_address": "http://172.16.0.11:8001",
            "management_ip": "172.16.0.11",
            "business_ip": "10.112.126.124",
            "business_ipv6": "2001:db8::1",
            "node_kind": "terminal",
            "topology_node_id": "h18001001",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert source_response.status_code == 200
    sink_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "h3",
            "display_name": "h3",
            "agent_address": "http://172.16.0.13:8001",
            "management_ip": "172.16.0.13",
            "business_ip": "10.112.20.40",
            "node_kind": "terminal",
            "topology_node_id": "h18005003",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert sink_response.status_code == 200

    create_response = await client.post("/api/conversations", json={"title": "用户端点矩阵任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    assert message_response.json()["latest_draft"]["parse_status"] == "valid"

    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={
            "source_endpoint_input": "h1",
            "destination_endpoint_input": "10.112.20.40",
            "destination_port": 9000,
        },
        headers=headers,
    )
    assert patch_response.status_code == 200
    draft = patch_response.json()["latest_draft"]
    assert draft["source_name"] == "h1"
    assert draft["destination_name"] == "h3"
    assert draft["source_endpoint"]["business_ip"] == "10.112.126.124"
    assert draft["destination_endpoint"]["business_ip"] == "10.112.20.40"
    assert draft["callback_url"] == "http://10.112.20.40:9000/callback"

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    assert order.runtime_config["platform_deployment"]["deployable_roles"] == ["compute"]
    assert order.runtime_config["platform_deployment"]["external_endpoints"]["sink"]["business_port"] == 9000
    source_node = next(item for item in order.routing_input_dag["nodes"] if item["task_node_id"] == "source")
    sink_node = next(item for item in order.routing_input_dag["nodes"] if item["task_node_id"] == "sink")
    assert source_node["deployable"] is False
    assert source_node["topology_node_id"] == "h18001001"
    assert source_node["topology_alias"] == "h1"
    assert source_node["business_ip"] == "10.112.126.124"
    assert sink_node["deployable"] is False
    assert sink_node["topology_node_id"] == "h18005003"
    assert sink_node["topology_alias"] == "h3"
    assert sink_node["business_ip"] == "10.112.20.40"
    assert sink_node["business_port"] == 9000
    assert sink_node["callback_url"] == "http://10.112.20.40:9000/callback"


@pytest.mark.asyncio
async def test_update_draft_can_clear_destination_port_and_generated_callback(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="clear-port-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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
    sink_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "h-clear-sink",
            "display_name": "h-clear-sink",
            "agent_address": "http://172.16.1.13:8001",
            "management_ip": "172.16.1.13",
            "business_ip": "10.112.220.40",
            "node_kind": "terminal",
            "topology_node_id": "h-clear-sink-id",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert sink_response.status_code == 200

    create_response = await client.post("/api/conversations", json={"title": "清空端口"}, headers=headers)
    conversation_id = create_response.json()["id"]
    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200

    set_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"destination_endpoint_input": "h-clear-sink", "destination_port": 9000},
        headers=headers,
    )
    assert set_response.status_code == 200
    assert set_response.json()["latest_draft"]["callback_url"] == "http://10.112.220.40:9000/callback"

    clear_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"destination_port": None},
        headers=headers,
    )
    assert clear_response.status_code == 200
    cleared_draft = clear_response.json()["latest_draft"]
    assert "destination_port" not in (cleared_draft["runtime_plan"] or {})
    assert cleared_draft["callback_url"] is None


@pytest.mark.asyncio
async def test_confirm_intent_rejects_unroutable_user_endpoint(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="bad-endpoint-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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
    bad_node_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "bad-terminal",
            "agent_address": "http://172.16.2.10:8001",
            "management_ip": "172.16.2.10",
            "business_ip": "10.112.2.10",
            "node_kind": "terminal",
            "topology_node_id": "bad-terminal-id",
            "is_schedulable": True,
            "is_routable": False,
        },
    )
    assert bad_node_response.status_code == 200

    create_response = await client.post("/api/conversations", json={"title": "不可路由端点"}, headers=headers)
    conversation_id = create_response.json()["id"]
    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"source_name": "bad-terminal"},
        headers=headers,
    )
    assert patch_response.status_code == 200

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )

    assert confirm_response.status_code == 400
    assert "源端点不可用" in confirm_response.json()["detail"]
    order = (await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))).scalar_one_or_none()
    assert order is None


@pytest.mark.asyncio
async def test_update_draft_rejects_invalid_callback_url(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="bad-callback-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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
    create_response = await client.post("/api/conversations", json={"title": "非法回调"}, headers=headers)
    conversation_id = create_response.json()["id"]
    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200

    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"callback_url": "not-a-url"},
        headers=headers,
    )

    assert patch_response.status_code == 400
    assert "回调地址必须" in patch_response.json()["detail"]


@pytest.mark.asyncio
async def test_confirm_intent_supports_route_only_mode(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="route-only-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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

    create_response = await client.post("/api/conversations", json={"title": "只路由矩阵任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    assert message_response.json()["latest_draft"]["parse_status"] == "valid"

    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"route_only": True},
        headers=headers,
    )
    assert patch_response.status_code == 200
    preview_nodes = patch_response.json()["latest_draft"]["routing_dag_preview"]["nodes"]
    assert all(node["deployable"] is False for node in preview_nodes)

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    assert order.runtime_config["platform_deployment"]["mode"] == "route_only"
    assert order.runtime_config["platform_deployment"]["deployable_roles"] == []
    assert all(node["deployable"] is False for node in order.routing_input_dag["nodes"])


@pytest.mark.asyncio
async def test_video_conversation_demo_route_materializes_same_order(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)
    _node_ids, _template_id = await _seed_business_fixture(client)
    terminal_response = await client.post(
        "/api/nodes",
        json={
            "hostname": "aaa-terminal",
            "agent_address": "http://127.0.0.1:7999",
            "management_ip": "10.99.0.1",
            "business_ip": "10.99.1.1",
            "node_kind": "terminal",
            "is_schedulable": True,
            "is_routable": True,
        },
    )
    assert terminal_response.status_code == 200

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
    routing_placements = route_body["latest_routing_request"]["placements"]
    routing_compute = next(item for item in routing_placements if item["task_node_id"] == "compute")
    assert routing_compute["topology_node_id"] == "worker-b"
    assert routing_compute["gpu_device"] == "0"

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == conversation_id))
    ).scalar_one()
    assert order.status == "materialized"
    assert order.routing_status == "completed"
    assert order.materialized_instance_id
    assert order.runtime_config["business_task"]["task_type"] == "low_latency_video_pipeline"

    route_placements = order.runtime_config["routing_result"]["placements"]
    compute_route = next(item for item in route_placements if item["task_node_id"] == "compute")
    assert compute_route["topology_node_id"] == "worker-b"
    assert compute_route["gpu_device"] == "0"

    inst_nodes = (
        await db_session.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == order.materialized_instance_id)
        )
    ).scalars().all()
    by_role = {node.env["TASK_ROLE"]: node for node in inst_nodes}
    assert by_role["compute"].env["TASK_TYPE"] == "low_latency_video_pipeline"
    assert by_role["compute"].env["TASK_MODALITY"] == "低时延转发模态"
    assert by_role["compute"].env["ROUTING_STRATEGY"] == "low_latency_forwarding"
    assert by_role["compute"].env["USE_GPU"] == "true"
    assert by_role["compute"].env["GPU_DEVICE"] == "0"
    assert by_role["compute"].gpu_id == "0"


@pytest.mark.asyncio
async def test_routing_result_requiring_network_ready_keeps_conversation_pending(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session, username="network-ready-user")
    _node_ids, _template_id = await _seed_business_fixture(client)
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

    create_response = await client.post("/api/conversations", json={"title": "等待网络就绪"}, headers=headers)
    conversation_id = create_response.json()["id"]
    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "矩阵乘法任务，从 worker-a 到 worker-c，1024阶矩阵，50批，现在开始跑2小时，资源保障策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 200

    claim_response = await client.patch(f"/api/routing-orders/{conversation_id}/claim")
    assert claim_response.status_code == 200
    result_response = await client.post(
        f"/api/routing-orders/{conversation_id}/result",
        json={
            "strategy": "resource_guarantee",
            "placements": _standard_placements(),
            "require_network_ready": True,
        },
    )
    assert result_response.status_code == 200
    assert result_response.json()["routing_status"] == "network_binding_ready"

    detail_response = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "ready_to_submit"


@pytest.mark.asyncio
async def test_conversation_ignores_user_supplied_video_latency_threshold(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)

    create_response = await client.post("/api/conversations", json={}, headers=headers)
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "视频AI推理任务，从 worker-a 到 worker-c，720p视频，100帧，30fps，现在开始跑2小时，端到端时延低于 1ms"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["status"] == "drafting"
    assert body["latest_draft"]["parse_status"] == "valid"
    assert body["latest_draft"]["task_type"] == "low_latency_video_pipeline"
    assert body["latest_draft"]["business_objective"] == {
        "metric_key": "frame_latency_p90_ms",
        "operator": "<=",
        "unit": "ms",
    }


@pytest.mark.asyncio
async def test_confirm_intent_rejects_missing_video_fps(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)

    create_response = await client.post("/api/conversations", json={"title": "缺参数视频任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "视频AI推理任务，从 worker-a 到 worker-c，720p视频，100帧，现在开始跑2小时，低时延策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    body = message_response.json()
    assert body["latest_draft"]["task_type"] == "low_latency_video_pipeline"
    assert body["latest_draft"]["parse_status"] == "incomplete"

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 400
    assert "帧率" in "；".join(confirm_response.json()["detail"]["validation_errors"])

    detail_response = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["status"] == "drafting"
    assert detail_body["materialized_order_id"] is None
    assert detail_body["latest_draft"]["parse_status"] == "incomplete"


@pytest.mark.asyncio
async def test_confirm_intent_rejects_invalid_video_fps(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "intent_parser_engine", "rule")
    headers, _user = await _auth_headers(client, db_session)

    create_response = await client.post("/api/conversations", json={"title": "非法参数视频任务"}, headers=headers)
    assert create_response.status_code == 200
    conversation_id = create_response.json()["id"]

    message_response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "视频AI推理任务，从 worker-a 到 worker-c，720p视频，100帧，30fps，现在开始跑2小时，低时延策略"},
        headers=headers,
    )
    assert message_response.status_code == 200
    assert message_response.json()["latest_draft"]["parse_status"] == "valid"

    patch_response = await client.patch(
        f"/api/conversations/{conversation_id}/draft",
        json={"data_profile": {"frame_count": 100, "resolution": "720p", "fps": 0}},
        headers=headers,
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["latest_draft"]["parse_status"] == "incomplete"

    confirm_response = await client.post(
        f"/api/conversations/{conversation_id}/confirm-intent",
        headers=headers,
    )
    assert confirm_response.status_code == 400
    assert "fps" in "；".join(confirm_response.json()["detail"]["validation_errors"])
    assert "1-240" in "；".join(confirm_response.json()["detail"]["validation_errors"])
