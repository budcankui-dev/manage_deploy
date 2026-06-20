import pytest


@pytest.mark.asyncio
async def test_batch_baseline_only_runs_on_compute_nodes(client, monkeypatch):
    created = {}
    for hostname, node_kind in [
        ("h1", "terminal"),
        ("compute-1", "worker"),
        ("compute-2", "worker"),
        ("compute-3", "worker"),
        ("intent-stale-1", "worker"),
        ("admin", "admin"),
    ]:
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "display_name": hostname,
                "agent_address": f"http://{hostname}:8001",
                "management_ip": f"10.0.0.{len(created) + 1}",
                "business_ip": f"10.0.1.{len(created) + 1}",
                "node_kind": node_kind,
                "is_schedulable": True,
                "is_routable": True,
            },
        )
        assert response.status_code == 200
        created[hostname] = response.json()["id"]

    called_endpoints = []

    async def fake_run_baseline_on_node(endpoint, task_type, runs):
        called_endpoints.append(endpoint)
        return {
            "metric_key": "effective_gflops",
            "baseline_value": 100.0,
            "operator": ">=",
            "unit": "GFLOPS",
            "run_count": runs,
            "raw_values": [99.0, 100.0, 101.0],
            "std_dev": 1.0,
            "stable": True,
            "diagnostics": {"actual_backends": ["cuda"]},
        }

    monkeypatch.setattr("services.baseline_runner.run_baseline_on_node", fake_run_baseline_on_node)

    response = await client.post(
        "/api/baselines/batch-run",
        json={"task_type": "high_throughput_matmul", "runs": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 3
    assert body["failed"] == []
    assert body["nodes"] == ["compute-1", "compute-2", "compute-3"]
    assert called_endpoints == [
        "http://compute-1:8001",
        "http://compute-2:8001",
        "http://compute-3:8001",
    ]


@pytest.mark.asyncio
async def test_batch_baseline_returns_readable_partial_failures(client, monkeypatch):
    for hostname in ["compute-1", "compute-2"]:
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "display_name": hostname,
                "agent_address": f"http://{hostname}:8001",
                "management_ip": f"10.0.0.{hostname[-1]}",
                "business_ip": f"10.0.1.{hostname[-1]}",
                "node_kind": "worker",
                "is_schedulable": True,
                "is_routable": True,
            },
        )
        assert response.status_code == 200

    async def fake_run_baseline_on_node(endpoint, task_type, runs):
        if "compute-2" in endpoint:
            raise RuntimeError('Head "https://10.112.244.94:5000/v2/x": http: server gave HTTP response to HTTPS client')
        return {
            "metric_key": "effective_gflops",
            "baseline_value": 100.0,
            "operator": ">=",
            "unit": "GFLOPS",
            "run_count": runs,
            "raw_values": [100.0],
            "diagnostics": {"actual_backends": ["cuda"]},
        }

    monkeypatch.setattr("services.baseline_runner.run_baseline_on_node", fake_run_baseline_on_node)

    response = await client.post(
        "/api/baselines/batch-run",
        json={"task_type": "high_throughput_matmul", "runs": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 1
    assert body["nodes"] == ["compute-1"]
    assert body["failed"] == [
        {
            "node": "compute-2",
            "error": "节点 Docker 未配置私有镜像仓库 10.112.244.94:5000 为可信 HTTP 仓库，请修复节点 Docker 配置后重测",
        }
    ]
