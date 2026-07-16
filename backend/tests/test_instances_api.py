import pytest

from enums import TaskStatus
from models import TaskInstance, TaskTemplate


@pytest.mark.asyncio
async def test_list_instances_returns_server_side_pagination(client, db_session):
    template = TaskTemplate(id="tpl-list-page", name="tpl-list-page")
    db_session.add(template)
    db_session.add_all(
        [
            TaskInstance(
                id="inst-manual-pending",
                template_id=template.id,
                name="manual-pending",
                status=TaskStatus.PENDING,
            ),
            TaskInstance(
                id="inst-order-running",
                template_id=template.id,
                name="order-running",
                status=TaskStatus.RUNNING,
                source_order_id="order-1",
            ),
            TaskInstance(
                id="inst-manual-failed",
                template_id=template.id,
                name="manual-failed",
                status=TaskStatus.FAILED,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/instances", params={"page": 1, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_list_instances_filters_status_and_manual_only(client, db_session):
    template = TaskTemplate(id="tpl-list-filter", name="tpl-list-filter")
    db_session.add(template)
    db_session.add_all(
        [
            TaskInstance(
                id="inst-filter-manual-pending",
                template_id=template.id,
                name="manual-pending",
                status=TaskStatus.PENDING,
            ),
            TaskInstance(
                id="inst-filter-order-pending",
                template_id=template.id,
                name="order-pending",
                status=TaskStatus.PENDING,
                source_order_id="order-2",
            ),
            TaskInstance(
                id="inst-filter-manual-stopped",
                template_id=template.id,
                name="manual-stopped",
                status=TaskStatus.STOPPED,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        "/api/instances",
        params={"status": "pending", "manual_only": True, "page": 1, "page_size": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == ["inst-filter-manual-pending"]
