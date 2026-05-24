import pytest

from agents.agent_client import AgentClient


class FakeResponse:
    status_code = 200

    def json(self):
        return {"logs": "service booted"}


class FakeAsyncClient:
    last_delete_url = None
    last_post_url = None
    last_post_json = None
    last_get_url = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        FakeAsyncClient.last_get_url = url
        return FakeResponse()

    async def delete(self, url):
        FakeAsyncClient.last_delete_url = url
        return FakeResponse()

    async def post(self, url, json=None):
        FakeAsyncClient.last_post_url = url
        FakeAsyncClient.last_post_json = json
        return FakeResponse()


@pytest.mark.asyncio
async def test_get_container_logs_reads_json_payload(monkeypatch):
    monkeypatch.setattr("agents.agent_client.httpx.AsyncClient", FakeAsyncClient)

    logs, error = await AgentClient().get_container_logs("10.0.0.2", "task-1", "node-1")

    assert logs == "service booted"
    assert error is None


@pytest.mark.asyncio
async def test_delete_container_supports_full_agent_address(monkeypatch):
    monkeypatch.setattr("agents.agent_client.httpx.AsyncClient", FakeAsyncClient)

    success, payload = await AgentClient().delete_container(
        "http://127.0.0.1:8001",
        "task-9",
        "node-7",
    )

    assert success is True
    assert payload == {"logs": "service booted"}
    assert FakeAsyncClient.last_delete_url == "http://127.0.0.1:8001/containers/task-9/node-7"


@pytest.mark.asyncio
async def test_preflight_ports_posts_payload(monkeypatch):
    monkeypatch.setattr("agents.agent_client.httpx.AsyncClient", FakeAsyncClient)

    success, payload = await AgentClient().preflight_ports(
        "http://127.0.0.1:8001",
        {"80": "18080"},
        "bridge",
        "task_1_node_1",
    )

    assert success is True
    assert payload == {"logs": "service booted"}
    assert FakeAsyncClient.last_post_url == "http://127.0.0.1:8001/preflight/ports"
    assert FakeAsyncClient.last_post_json == {
        "ports": {"80": "18080"},
        "network_mode": "bridge",
        "exclude_container_name": "task_1_node_1",
    }


@pytest.mark.asyncio
async def test_list_managed_containers_uses_managed_endpoint(monkeypatch):
    monkeypatch.setattr("agents.agent_client.httpx.AsyncClient", FakeAsyncClient)

    success, payload = await AgentClient().list_managed_containers("http://127.0.0.1:8001")

    assert success is True
    assert payload == {"containers": {"logs": "service booted"}}
    assert FakeAsyncClient.last_get_url == "http://127.0.0.1:8001/containers/managed"


@pytest.mark.asyncio
async def test_delete_container_by_name_uses_dedicated_managed_route(monkeypatch):
    monkeypatch.setattr("agents.agent_client.httpx.AsyncClient", FakeAsyncClient)

    success, payload = await AgentClient().delete_container_by_name(
        "http://127.0.0.1:8001",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa_bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )

    assert success is True
    assert payload == {"logs": "service booted"}
    assert (
        FakeAsyncClient.last_delete_url
        == "http://127.0.0.1:8001/managed-containers/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa_bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
