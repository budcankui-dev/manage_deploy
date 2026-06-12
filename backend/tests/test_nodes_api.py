import pytest
from fastapi import HTTPException

from api.nodes import create_node, update_node, list_node_orphans, sync_node_resources
from models import Node
from schemas import NodeCreate, NodeUpdate


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        class _Scalars:
            def __init__(self, value):
                self._value = value

            def all(self):
                return self._value

        return _Scalars(self.value)


class FakeSession:
    def __init__(self, node=None):
        self.node = node
        self.values = []
        self.added = []
        self.committed = False
        self.refreshed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed = True

    async def execute(self, _query):
        if self.values:
            return FakeResult(self.values.pop(0))
        return FakeResult(self.node)


@pytest.mark.asyncio
async def test_create_node_rejects_non_ipv4_management_ip():
    db = FakeSession()

    with pytest.raises(HTTPException) as exc:
        await create_node(
            NodeCreate(
                hostname="worker-a",
                agent_address="http://10.0.0.1:8001",
                management_ip="2001:db8::1",
                business_ip="10.0.1.10",
            ),
            db,
        )

    assert exc.value.status_code == 400
    assert "valid IPv4" in exc.value.detail


@pytest.mark.asyncio
async def test_create_node_persists_valid_node():
    db = FakeSession()

    node = await create_node(
        NodeCreate(
            hostname="worker-a",
            agent_address="http://10.0.0.1:8001",
            management_ip="10.0.0.1",
            business_ip="10.0.1.10",
        ),
        db,
    )

    assert isinstance(node, Node)
    assert node.hostname == "worker-a"
    assert db.committed is True
    assert db.refreshed is True


@pytest.mark.asyncio
async def test_update_node_validates_management_ip():
    existing = Node(
        hostname="worker-a",
        agent_address="http://10.0.0.1:8001",
        management_ip="10.0.0.1",
        business_ip="10.0.1.10",
    )
    db = FakeSession(existing)

    with pytest.raises(HTTPException) as exc:
        await update_node(
            "node-1",
            NodeUpdate(management_ip="bad-ip"),
            db,
        )

    assert exc.value.status_code == 400
    assert db.committed is False


@pytest.mark.asyncio
async def test_list_node_orphans_filters_known_container_names(monkeypatch):
    node = Node(
        hostname="worker-a",
        agent_address="http://10.0.0.1:8001",
        management_ip="10.0.0.1",
        business_ip="10.0.1.10",
    )
    node.id = "node-1"
    db = FakeSession(node)
    db.values = [
        node,
        ["known-instance_node"],
    ]

    async def fake_list_managed_containers(self, _endpoint):
        return True, {
            "containers": [
                {
                    "container_id": "cid-1",
                    "container_name": "known-instance_node",
                    "status": "running",
                    "image": "nginx:latest",
                    "ports": {},
                },
                {
                    "container_id": "cid-2",
                    "container_name": "12345678-1234-1234-1234-123456789abc_87654321-4321-4321-4321-cba987654321",
                    "status": "exited",
                    "image": "nginx:latest",
                    "ports": {},
                },
            ]
        }

    monkeypatch.setattr("api.nodes.AgentClient.list_managed_containers", fake_list_managed_containers)

    result = await list_node_orphans("node-1", db)

    assert len(result) == 1
    assert result[0].container_id == "cid-2"
    assert "数据库中已不存在" in result[0].reason


@pytest.mark.asyncio
async def test_sync_node_resources_updates_hardware_fields(monkeypatch):
    node = Node(
        hostname="worker-a",
        agent_address="http://10.0.0.1:8001",
        management_ip="10.0.0.1",
        business_ip="10.0.1.10",
    )
    node.id = "node-1"
    db = FakeSession(node)
    db.values = [node]

    async def fake_get_resources(self, _endpoint):
        return True, {
            "gpu_count": 1,
            "gpu_model": "NVIDIA TITAN Xp",
            "gpu_memory_mb": 12288,
            "cpu_model": "Intel Xeon",
            "cpu_cores": 16,
            "memory_mb": 64000,
            "driver_version": "535.171.04",
            "cuda_version": "12.2",
        }

    monkeypatch.setattr("api.nodes.AgentClient.get_resources", fake_get_resources)

    result = await sync_node_resources("node-1", db)

    assert result.cpu_cores == 16
    assert result.cuda_version == "12.2"
    assert result.gpu_model == "NVIDIA TITAN Xp"
    assert db.committed is True


@pytest.mark.asyncio
async def test_sync_node_resources_preserves_gpu_when_probe_unavailable(monkeypatch):
    node = Node(
        hostname="worker-a",
        agent_address="http://10.0.0.1:8001",
        management_ip="10.0.0.1",
        business_ip="10.0.1.10",
        gpu_count=1,
        gpu_model="NVIDIA TITAN Xp",
        gpu_memory_mb=12288,
        driver_version="535.171.04",
    )
    node.id = "node-1"
    db = FakeSession(node)
    db.values = [node]

    async def fake_get_resources(self, _endpoint):
        return True, {
            "cpu_model": "Intel Xeon",
            "cpu_cores": 24,
            "memory_mb": 64000,
            "gpu_count": 0,
            "gpu_model": None,
            "gpu_memory_mb": None,
            "driver_version": None,
            "cuda_version": None,
            "diagnostics": {"nvidia_smi_error": "not found"},
        }

    monkeypatch.setattr("api.nodes.AgentClient.get_resources", fake_get_resources)

    result = await sync_node_resources("node-1", db)

    assert result.cpu_cores == 24
    assert result.gpu_count == 1
    assert result.gpu_model == "NVIDIA TITAN Xp"
    assert result.driver_version == "535.171.04"
    assert "GPU 信息保留原配置" in result.resource_note
