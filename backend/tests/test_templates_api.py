import pytest

from api.templates import update_template
from enums import OrderStatus
from models import TaskInstance, TaskOrder, TaskTemplate, TaskTemplateEdge, TaskTemplateNode
from schemas import TaskTemplateNodeCreate, TaskTemplateEdgeCreate, TaskTemplateUpdate


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


class FakeSession:
    def __init__(self, template):
        self.template = template
        self.flush_calls = 0
        self.commit_calls = 0
        self.execute_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return FakeResult(self.template)

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1


@pytest.mark.asyncio
async def test_update_template_rebuilds_nodes_and_edges(monkeypatch):
    template = TaskTemplate(name="old", description="before")
    template.nodes = [
        TaskTemplateNode(name="legacy", image="busybox", node_id="worker-1"),
    ]
    template.edges = [
        TaskTemplateEdge(from_node_id="legacy", to_node_id="legacy"),
    ]

    captured = {}

    async def fake_populate(db, db_template, nodes_data, edges_data):
        captured["template"] = db_template
        captured["nodes"] = nodes_data
        captured["edges"] = edges_data

    async def noop_unique(*args, **kwargs):
        return None

    monkeypatch.setattr("api.templates._populate_template_graph", fake_populate)
    monkeypatch.setattr("api.templates._ensure_unique_template_name", noop_unique)

    response = await update_template(
        "template-1",
        TaskTemplateUpdate(
            name="new",
            description="after",
            nodes=[
                TaskTemplateNodeCreate(
                    name="extract",
                    image="python:3.11",
                    node_id="worker-2",
                )
            ],
            edges=[
                TaskTemplateEdgeCreate(
                    from_node_id="worker-2",
                    to_node_id="worker-2",
                )
            ],
        ),
        FakeSession(template),
    )

    assert response is template
    assert template.name == "new"
    assert template.description == "after"
    assert template.nodes == []
    assert template.edges == []
    assert len(captured["nodes"]) == 1
    assert len(captured["edges"]) == 1


@pytest.mark.asyncio
async def test_create_template_rejects_duplicate_name(monkeypatch):
    existing = TaskTemplate(name="dup-name", description="x")
    existing.id = "existing-id"

    async def fake_get_by_name(_db, name):
        return existing if name == "dup-name" else None

    monkeypatch.setattr("api.templates._get_template_by_name", fake_get_by_name)

    from api.templates import _ensure_unique_template_name
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _ensure_unique_template_name(FakeSession(None), "dup-name")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_template_rejects_template_with_evidence(client, db_session):
    template = TaskTemplate(id="tpl-in-use", name="tpl-in-use", description="in use")
    db_session.add(template)
    await db_session.flush()
    db_session.add_all(
        [
            TaskInstance(id="inst-1", template_id=template.id, name="instance-1"),
            TaskOrder(
                id="order-1",
                template_id=template.id,
                name="order-1",
                status=OrderStatus.PENDING,
            ),
        ]
    )
    await db_session.commit()

    response = await client.delete(f"/api/templates/{template.id}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "模板已被" in detail
    assert "任务实例 1 条" in detail
    assert "任务工单 1 条" in detail


@pytest.mark.asyncio
async def test_delete_template_without_references_succeeds(client, db_session):
    template = TaskTemplate(id="tpl-unused", name="tpl-unused", description="unused")
    db_session.add(template)
    await db_session.commit()

    response = await client.delete(f"/api/templates/{template.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "模板已删除"
