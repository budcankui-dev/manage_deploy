from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from enums import NodeStatus, TaskStatus
from models import TaskEvent, TaskInstance
from services.dag_executor import (
    DAGExecutor,
    record_agent_failure_event_independent,
)


class FakeDb:
    def __init__(self):
        self.commit_calls = 0
        self.flush_calls = 0
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

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


class FailingDeleteAgent(RecordingAgentClient):
    async def delete_container(self, **kwargs):
        self.kwargs = kwargs
        return False, {"error": "boom", "status_code": 500}


@pytest.mark.asyncio
async def test_remove_node_writes_task_event_on_failure():
    """When node_agent returns non-2xx during delete, a task_event must be added."""
    from models import TaskEvent

    db = FakeDb()
    executor = StatusExecutor(db)
    executor.agent_client = FailingDeleteAgent()
    node = SimpleNamespace(
        id="node-1",
        node_id="worker-1",
        instance_id="ins-1",
        container_id="cid",
        container_name="name",
        error_message=None,
        status=NodeStatus.READY,
    )

    success, error = await executor.remove_node(node)

    assert success is False
    assert error and "http 500" in error and "boom" in error
    events = [obj for obj in db.added if isinstance(obj, TaskEvent)]
    assert len(events) == 1
    assert events[0].instance_id == "ins-1"
    assert events[0].node_id == "node-1"
    assert events[0].event_type == "node_agent_error"
    assert events[0].new_status == "failed"
    assert "delete_container" in events[0].message
    assert "500" in events[0].message
    assert "boom" in events[0].message


class FailingStopAgent(RecordingAgentClient):
    async def stop_container(self, **kwargs):
        self.kwargs = kwargs
        return False, {"error": "connection refused", "status_code": None}


@pytest.mark.asyncio
async def test_stop_node_writes_task_event_when_agent_unreachable():
    from models import TaskEvent

    db = FakeDb()
    executor = StatusExecutor(db)
    executor.agent_client = FailingStopAgent()
    node = SimpleNamespace(
        id="node-stop",
        node_id="worker-1",
        instance_id="ins-stop",
        container_id="cid",
        container_name="name",
        error_message=None,
        status=NodeStatus.RUNNING,
    )

    success, error = await executor.stop_node(node)

    assert success is False
    assert error and "unreachable" in error
    events = [obj for obj in db.added if isinstance(obj, TaskEvent)]
    assert len(events) == 1
    assert events[0].instance_id == "ins-stop"
    assert events[0].node_id == "node-stop"
    assert events[0].event_type == "node_agent_error"
    assert "stop_container" in events[0].message


# ---------------------------------------------------------------------------
# Round 7: independent-session helper for preflight-time event writes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_agent_failure_event_independent_commits_to_provided_session_maker():
    """The independent helper opens its own session, commits, and the audit
    row survives any external rollback (since it's a different session)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    await record_agent_failure_event_independent(
        instance_id="ins-pf-1",
        node_id=None,
        node_status=None,
        operation="preflight_ports(compute-1)",
        result={"error": "All connection attempts failed", "status_code": None},
        session_maker=session_maker,
    )

    async with session_maker() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "ins-pf-1")
            )
        ).scalars().all()
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "node_agent_error"
        assert event.new_status == "failed"
        assert event.node_id is None
        assert "preflight_ports(compute-1)" in (event.message or "")
        assert "unreachable" in (event.message or "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_record_agent_failure_event_independent_does_not_raise_on_db_error():
    """Audit-write failures must never bubble to the caller; the caller is
    already reporting the user-visible error and the audit is a side-channel."""

    class ExplodingSessionMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("simulated DB outage")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    # No assertion of behaviour besides "does not raise".
    await record_agent_failure_event_independent(
        instance_id="ins-pf-2",
        node_id=None,
        node_status=None,
        operation="preflight_ports(compute-2)",
        result={"error": "boom", "status_code": 500},
        session_maker=ExplodingSessionMaker(),
    )
