"""Tests for on-demand preflight reconcile of stale running instances.

When `_preflight_instance_plan` discovers a DB-recorded running instance whose
container has actually been removed on the remote node_agent (e.g. operator
ran `docker rm -f` after a host reboot), the stale row should be marked
stopped + a `reconcile_stale_container` task_event written, and the
new deployment should be allowed to proceed. If node_agent still reports
the container as running, or is unreachable, the conflict must be preserved.

Round 7: the reconcile DB writes (stale row cleanup + audit event) MUST land
in an INDEPENDENT session that is not rolled back when the surrounding
FastAPI request raises `HTTPException` due to other unreconcilable conflicts
in the same preflight pass. The tests below verify both behaviours.
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.instances import _reconcile_stale_running_node
from database import Base
from enums import NodeStatus, TaskStatus
from models import TaskEvent, TaskInstance, TaskInstanceNode, TaskTemplate
from services import dag_executor as dag_executor_module
from services.dag_executor import DAGExecutor


class FakeDb:
    """Minimal AsyncSession stand-in for the executor's *request* session.

    The executor still owns this session for DAG-executor-time mutations.
    The independent-session helper (Round 7) does NOT touch this object.
    """

    def __init__(self):
        self.commit_calls = 0
        self.flush_calls = 0
        self.added: list = []
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def flush(self):
        self.flush_calls += 1

    async def rollback(self):
        self.rolled_back = True


def _make_machine(hostname="compute-1") -> SimpleNamespace:
    return SimpleNamespace(
        hostname=hostname,
        management_ip="10.0.0.1",
        agent_address="http://10.0.0.1:8001",
        business_ip="10.0.0.1",
        business_ipv6=None,
    )


class _BaseRecorderAgent:
    def __init__(self):
        self.get_status_calls: list[dict] = []


class AgentSaysRemoved(_BaseRecorderAgent):
    async def get_container_status(self, **kwargs):
        self.get_status_calls.append(kwargs)
        return "not_found", False, None


class AgentSaysRunning(_BaseRecorderAgent):
    async def get_container_status(self, **kwargs):
        self.get_status_calls.append(kwargs)
        return "running", True, None


class AgentUnreachable(_BaseRecorderAgent):
    async def get_container_status(self, **kwargs):
        self.get_status_calls.append(kwargs)
        # Mirrors AgentClient behaviour on httpx.RequestError / non-2xx.
        return "unknown", False, "connection refused"


class _StubExecutor(DAGExecutor):
    """DAGExecutor with `get_node_machine` stubbed for tests."""

    def __init__(self, db, machine):
        super().__init__(db)
        self._machine = machine

    async def get_node_machine(self, node_id):  # type: ignore[override]
        return self._machine


@pytest_asyncio.fixture
async def independent_db():
    """Provide a real sqlite engine + session_maker that
    `_reconcile_stale_running_node` / `record_agent_failure_event_independent`
    will use as their INDEPENDENT session.

    The fixture monkeypatches `dag_executor._default_session_maker` so the
    helpers pick up this sessionmaker without the caller having to pass it.
    Returns the sessionmaker for direct verification reads.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original = dag_executor_module._default_session_maker
    dag_executor_module._default_session_maker = lambda: session_maker
    try:
        # Seed a stale "running" instance + node in the independent DB so the
        # reconcile path has a row to flip to "stopped".
        async with session_maker() as setup:
            template = TaskTemplate(id="tpl-stale", name="stale-template")
            setup.add(template)
            await setup.flush()
            instance = TaskInstance(
                id="instance-stale-1",
                template_id="tpl-stale",
                name="stale-task",
                status=TaskStatus.RUNNING,
            )
            setup.add(instance)
            await setup.flush()
            node = TaskInstanceNode(
                id="node-stale-1",
                instance_id="instance-stale-1",
                template_node_id="tn-1",
                name="source",
                image="img:dev",
                node_id="worker-1",
                container_id="cid-abc",
                container_name="instance-stale-1_node-stale-1",
                status=NodeStatus.RUNNING,
            )
            setup.add(node)
            await setup.commit()
        yield session_maker
    finally:
        dag_executor_module._default_session_maker = original
        await engine.dispose()


def _existing_node_proxy(container_id="cid-abc") -> SimpleNamespace:
    """In-memory proxy of the stale DB row (the request session's loaded view)."""
    return SimpleNamespace(
        id="node-stale-1",
        instance_id="instance-stale-1",
        node_id="worker-1",
        name="source",
        container_id=container_id,
        container_name="instance-stale-1_node-stale-1",
        status=NodeStatus.RUNNING,
    )


def _existing_instance_proxy() -> SimpleNamespace:
    return SimpleNamespace(
        id="instance-stale-1",
        name="stale-task",
        status=TaskStatus.RUNNING,
    )


@pytest.mark.asyncio
async def test_reconcile_marks_stopped_when_agent_reports_container_removed(independent_db):
    db = FakeDb()
    executor = _StubExecutor(db, _make_machine())
    executor.agent_client = AgentSaysRemoved()

    existing_node = _existing_node_proxy()
    existing_instance = _existing_instance_proxy()

    reconciled = await _reconcile_stale_running_node(
        executor=executor,
        existing_node=existing_node,
        existing_instance=existing_instance,
    )

    assert reconciled is True
    # In-memory ORM objects also reflect the new state for downstream callers.
    assert existing_node.container_id is None
    assert existing_node.container_name is None
    assert existing_node.status == NodeStatus.STOPPED
    assert existing_instance.status == TaskStatus.STOPPED

    # The request session must NOT be where the audit row landed: that's the
    # whole point of Round 7. Nothing was added to executor.db.
    request_events = [obj for obj in db.added if isinstance(obj, TaskEvent)]
    assert request_events == []

    # The audit row + the reconciled state MUST be present in the independent
    # session (i.e. it would survive a request-session rollback).
    async with independent_db() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "instance-stale-1")
            )
        ).scalars().all()
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "reconcile_stale_container"
        assert event.node_id == "node-stale-1"
        assert event.new_status == "stopped"
        assert "node_agent" in (event.message or "")
        assert "not_found" in (event.message or "")

        node_row = (
            await verify.execute(
                select(TaskInstanceNode).where(TaskInstanceNode.id == "node-stale-1")
            )
        ).scalar_one()
        assert node_row.container_id is None
        assert node_row.container_name is None
        assert node_row.status == NodeStatus.STOPPED

        instance_row = (
            await verify.execute(
                select(TaskInstance).where(TaskInstance.id == "instance-stale-1")
            )
        ).scalar_one()
        assert instance_row.status == TaskStatus.STOPPED

    # The agent client must have been asked for the EXISTING (stale) node,
    # not the new deployment's node.
    assert executor.agent_client.get_status_calls[0]["task_id"] == "instance-stale-1"
    assert executor.agent_client.get_status_calls[0]["node_id"] == "node-stale-1"


@pytest.mark.asyncio
async def test_reconcile_survives_request_session_rollback(independent_db):
    """Mixed-conflict scenario: one stale row reconcilable + something else
    forces preflight to raise. The independent commit MUST be visible after
    rollback of the request session.
    """
    db = FakeDb()
    executor = _StubExecutor(db, _make_machine())
    executor.agent_client = AgentSaysRemoved()

    existing_node = _existing_node_proxy()
    existing_instance = _existing_instance_proxy()

    reconciled = await _reconcile_stale_running_node(
        executor=executor,
        existing_node=existing_node,
        existing_instance=existing_instance,
    )
    assert reconciled is True

    # Simulate the FastAPI rollback path that previously erased everything.
    await db.rollback()
    assert db.rolled_back is True

    # Independent commit must still be there.
    async with independent_db() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "instance-stale-1")
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "reconcile_stale_container"

        node_row = (
            await verify.execute(
                select(TaskInstanceNode).where(TaskInstanceNode.id == "node-stale-1")
            )
        ).scalar_one()
        assert node_row.status == NodeStatus.STOPPED
        assert node_row.container_id is None


@pytest.mark.asyncio
async def test_reconcile_keeps_conflict_when_agent_reports_running(independent_db):
    db = FakeDb()
    executor = _StubExecutor(db, _make_machine())
    executor.agent_client = AgentSaysRunning()

    existing_node = _existing_node_proxy()
    existing_instance = _existing_instance_proxy()

    reconciled = await _reconcile_stale_running_node(
        executor=executor,
        existing_node=existing_node,
        existing_instance=existing_instance,
    )

    assert reconciled is False
    # DB rows untouched in BOTH the request session view and the independent DB.
    assert existing_node.container_id == "cid-abc"
    assert existing_node.status == NodeStatus.RUNNING
    assert existing_instance.status == TaskStatus.RUNNING
    assert [obj for obj in db.added if isinstance(obj, TaskEvent)] == []
    async with independent_db() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "instance-stale-1")
            )
        ).scalars().all()
        assert events == []
        node_row = (
            await verify.execute(
                select(TaskInstanceNode).where(TaskInstanceNode.id == "node-stale-1")
            )
        ).scalar_one()
        assert node_row.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_reconcile_keeps_conflict_when_agent_unreachable(independent_db):
    db = FakeDb()
    executor = _StubExecutor(db, _make_machine())
    executor.agent_client = AgentUnreachable()

    existing_node = _existing_node_proxy()
    existing_instance = _existing_instance_proxy()

    reconciled = await _reconcile_stale_running_node(
        executor=executor,
        existing_node=existing_node,
        existing_instance=existing_instance,
    )

    assert reconciled is False
    assert existing_node.container_id == "cid-abc"
    assert existing_node.status == NodeStatus.RUNNING
    assert existing_instance.status == TaskStatus.RUNNING
    assert [obj for obj in db.added if isinstance(obj, TaskEvent)] == []
    async with independent_db() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "instance-stale-1")
            )
        ).scalars().all()
        assert events == []


@pytest.mark.asyncio
async def test_reconcile_skipped_when_existing_node_has_no_container_id(independent_db):
    """Without a container_id we cannot reasonably probe node_agent; the DB
    row is treated as authoritative and the conflict is preserved."""
    db = FakeDb()
    executor = _StubExecutor(db, _make_machine())
    executor.agent_client = AgentSaysRemoved()

    existing_node = _existing_node_proxy(container_id=None)
    existing_instance = _existing_instance_proxy()

    reconciled = await _reconcile_stale_running_node(
        executor=executor,
        existing_node=existing_node,
        existing_instance=existing_instance,
    )

    assert reconciled is False
    assert executor.agent_client.get_status_calls == []
    assert [obj for obj in db.added if isinstance(obj, TaskEvent)] == []
    async with independent_db() as verify:
        events = (
            await verify.execute(
                select(TaskEvent).where(TaskEvent.instance_id == "instance-stale-1")
            )
        ).scalars().all()
        assert events == []
