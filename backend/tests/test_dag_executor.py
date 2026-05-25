from types import SimpleNamespace

import pytest

from enums import NodeStatus, TaskStatus
from models import TaskInstance
from services.dag_executor import DAGExecutor


class FakeDb:
    def __init__(self):
        self.commit_calls = 0
        self.flush_calls = 0

    async def commit(self):
        self.commit_calls += 1

    async def flush(self):
        self.flush_calls += 1


class RootlessExecutor(DAGExecutor):
    def __init__(self, db, instance):
        super().__init__(db)
        self.instance = instance

    async def get_instance_with_graph(self, instance_id):
        return self.instance

    async def get_root_nodes(self, instance_id):
        return []


class RecordingAgentClient:
    def __init__(self):
        self.kwargs = None

    async def get_container_status(self, **kwargs):
        self.kwargs = kwargs
        return "running", True, None

    async def delete_container(self, **kwargs):
        self.kwargs = kwargs
        return True, {"message": "deleted"}


class StatusExecutor(DAGExecutor):
    async def get_node_machine(self, node_id):
        return SimpleNamespace(management_ip="10.0.0.8", agent_address="http://ignored")


@pytest.mark.asyncio
async def test_execute_dag_start_marks_rootless_instance_running():
    instance = TaskInstance(template_id="tpl-1", name="demo", status=TaskStatus.PENDING)
    instance.error_message = "old error"
    db = FakeDb()
    executor = RootlessExecutor(db, instance)

    success, error = await executor.execute_dag_start("ins-1")

    assert success is True
    assert error is None
    assert instance.status == TaskStatus.RUNNING
    assert instance.error_message is None
    assert instance.start_time is not None
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_get_node_status_prefers_agent_address():
    executor = StatusExecutor(FakeDb())
    executor.agent_client = RecordingAgentClient()
    node = SimpleNamespace(id="node-1", node_id="worker-1", instance_id="ins-1")

    status, healthy, message = await executor.get_node_status(node)

    assert (status, healthy, message) == ("running", True, None)
    assert executor.agent_client.kwargs["management_ip"] == "http://ignored"


@pytest.mark.asyncio
async def test_rollback_removes_started_and_failed_nodes():
    """失败回滚应对已启动节点与失败节点均调用 remove_node，而非仅 stop READY 节点。"""
    removed_ids: list[str] = []

    class RollbackExecutor(DAGExecutor):
        async def get_node_by_id(self, node_id: str):
            return SimpleNamespace(
                id=node_id,
                node_id="worker-1",
                instance_id="ins-rollback",
                container_id=f"cid-{node_id}",
                container_name=f"ins-rollback_{node_id}",
                status=NodeStatus.FAILED if node_id == "failed-1" else NodeStatus.READY,
                error_message="hc failed" if node_id == "failed-1" else None,
            )

        async def remove_node(self, node):
            removed_ids.append(node.id)
            return True, None

    executor = RollbackExecutor(FakeDb())
    started_nodes = {"ready-1": True, "ready-2": True, "pending-1": False}
    failed_nodes = {"failed-1"}

    await executor._rollback_started_nodes("ins-rollback", started_nodes, failed_nodes)

    assert set(removed_ids) == {"ready-1", "ready-2", "failed-1"}


@pytest.mark.asyncio
async def test_remove_node_clears_runtime_metadata():
    executor = StatusExecutor(FakeDb())
    executor.agent_client = RecordingAgentClient()
    node = SimpleNamespace(
        id="node-1",
        node_id="worker-1",
        instance_id="ins-1",
        container_id="cid",
        container_name="name",
        error_message="boom",
        status="failed",
    )

    success, error = await executor.remove_node(node)

    assert success is True
    assert error is None
    assert node.container_id is None
    assert node.container_name is None
    assert node.error_message is None
    assert node.status == "stopped"
    assert executor.agent_client.kwargs["management_ip"] == "http://ignored"
