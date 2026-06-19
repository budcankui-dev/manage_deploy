import pytest
from sqlalchemy import select

from api.auth import hash_password
from enums import ConversationStatus, OrderStatus, RoutingStatus, TaskStatus, UserRole
from models import Conversation, IntentDraft, RoutingRequest, TaskInstance, TaskOrder, TaskTemplate, User


async def _create_user(db_session, username: str, role: UserRole = UserRole.USER) -> User:
    user = User(username=username, password_hash=hash_password("password123"), role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def _auth_headers(client, db_session, username: str, role: UserRole = UserRole.USER):
    user = await _create_user(db_session, username, role)
    response = await client.post("/api/auth/login", json={"username": username, "password": "password123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user


async def _create_order(db_session, order_id: str, owner: User | None, status: OrderStatus = OrderStatus.PENDING) -> TaskOrder:
    template = TaskTemplate(id=f"tpl-{order_id}", name=f"tpl-{order_id}", description="orders api test")
    db_session.add(template)
    await db_session.flush()
    order = TaskOrder(
        id=order_id,
        template_id=template.id,
        user_id=owner.id if owner else None,
        name=f"order-{order_id}",
        status=status,
        routing_status=RoutingStatus.PENDING.value,
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_delete_order_requires_login(client, db_session):
    await _create_order(db_session, "delete-requires-login", owner=None)

    response = await client.delete("/api/orders/delete-requires-login")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_requires_login(client, db_session):
    template = TaskTemplate(id="tpl-create-requires-login", name="tpl-create-requires-login")
    db_session.add(template)
    await db_session.commit()

    response = await client.post(
        "/api/orders",
        json={"template_id": template.id, "name": "未登录创建工单"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_binds_current_user(client, db_session):
    headers, owner = await _auth_headers(client, db_session, username="order-create-owner")
    template = TaskTemplate(id="tpl-create-bind-owner", name="tpl-create-bind-owner")
    db_session.add(template)
    await db_session.commit()

    response = await client.post(
        "/api/orders",
        headers=headers,
        json={"template_id": template.id, "name": "绑定当前用户工单"},
    )

    assert response.status_code == 200
    assert response.json()["owner_user_id"] == owner.id
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == response.json()["id"]))
    assert row.scalar_one().user_id == owner.id


@pytest.mark.asyncio
async def test_materialize_order_requires_login(client, db_session):
    await _create_order(db_session, "materialize-requires-login", owner=None)

    response = await client.post("/api/orders/materialize-requires-login/materialize")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_cannot_materialize_other_users_order(client, db_session):
    _owner_headers, owner = await _auth_headers(client, db_session, username="materialize-owner")
    other_headers, _other = await _auth_headers(client, db_session, username="materialize-other")
    await _create_order(db_session, "materialize-other-user-order", owner=owner)

    response = await client.post("/api/orders/materialize-other-user-order/materialize", headers=other_headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_materialize_pending_requires_admin(client, db_session):
    user_headers, _user = await _auth_headers(client, db_session, username="materialize-pending-user")

    response = await client.post("/api/orders/materialize/pending", headers=user_headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_delete_other_users_order(client, db_session):
    _owner_headers, owner = await _auth_headers(client, db_session, username="order-delete-owner")
    other_headers, _other = await _auth_headers(client, db_session, username="order-delete-other")
    await _create_order(db_session, "delete-other-user-order", owner=owner)

    response = await client.delete("/api/orders/delete-other-user-order", headers=other_headers)

    assert response.status_code == 403
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == "delete-other-user-order"))
    assert row.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_user_can_delete_own_order(client, db_session):
    headers, owner = await _auth_headers(client, db_session, username="order-delete-self")
    await _create_order(db_session, "delete-own-order", owner=owner)

    response = await client.delete("/api/orders/delete-own-order", headers=headers)

    assert response.status_code == 200
    assert response.json()["message"] == "工单已删除"
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == "delete-own-order"))
    assert row.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_admin_can_delete_other_users_order(client, db_session):
    _owner_headers, owner = await _auth_headers(client, db_session, username="admin-delete-owner")
    admin_headers, _admin = await _auth_headers(client, db_session, username="admin-delete-admin", role=UserRole.ADMIN)
    await _create_order(db_session, "admin-delete-other-order", owner=owner)

    response = await client.delete("/api/orders/admin-delete-other-order", headers=admin_headers)

    assert response.status_code == 200
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == "admin-delete-other-order"))
    assert row.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_user_delete_materialized_order_cleans_instance_before_deleting(client, db_session, monkeypatch):
    headers, owner = await _auth_headers(client, db_session, username="order-delete-materialized")
    order = await _create_order(db_session, "delete-materialized-order", owner=owner, status=OrderStatus.MATERIALIZED)
    conversation = Conversation(
        id="conversation-delete-materialized-order",
        user_id=owner.id,
        status=ConversationStatus.SUBMITTED,
        materialized_order_id=order.id,
    )
    draft = IntentDraft(
        id="draft-delete-materialized-order",
        conversation_id=conversation.id,
    )
    routing = RoutingRequest(
        id="routing-delete-materialized-order",
        conversation_id=conversation.id,
        order_id=order.id,
        intent_draft_id=draft.id,
        strategy="resource_guarantee",
        status="completed",
    )
    instance = TaskInstance(
        id="delete-materialized-instance",
        template_id=order.template_id,
        name="delete-materialized-instance",
        status=TaskStatus.RUNNING,
        source_order_id=order.id,
    )
    order.conversation_id = conversation.id
    order.routing_request_id = routing.id
    order.materialized_instance_id = instance.id
    db_session.add_all([conversation, draft, routing, instance])
    await db_session.commit()
    calls = []

    async def fake_cleanup(_db, cleaned_instance):
        calls.append(cleaned_instance.id)
        return []

    async def fake_cancel_all_schedules(self, instance_id):
        calls.append(f"schedule:{instance_id}")

    monkeypatch.setattr("api.orders.cleanup_instance_runtime", fake_cleanup)
    monkeypatch.setattr("api.orders.TaskScheduler.cancel_all_schedules", fake_cancel_all_schedules)

    response = await client.delete("/api/orders/delete-materialized-order", headers=headers)

    assert response.status_code == 200
    assert calls == ["schedule:delete-materialized-instance", "delete-materialized-instance"]
    order_row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    assert order_row.scalar_one_or_none() is None
    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance.id))
    assert instance_row.scalar_one_or_none() is None
    conversation_row = await db_session.execute(select(Conversation).where(Conversation.id == conversation.id))
    updated_conversation = conversation_row.scalar_one()
    assert updated_conversation.status == ConversationStatus.CANCELLED.value
    assert updated_conversation.materialized_order_id is None
    routing_row = await db_session.execute(select(RoutingRequest).where(RoutingRequest.id == routing.id))
    assert routing_row.scalar_one().order_id is None


@pytest.mark.asyncio
async def test_user_delete_materialized_order_keeps_record_when_runtime_cleanup_fails(client, db_session, monkeypatch):
    headers, owner = await _auth_headers(client, db_session, username="order-delete-cleanup-fails")
    order = await _create_order(db_session, "delete-cleanup-fails-order", owner=owner, status=OrderStatus.MATERIALIZED)
    instance = TaskInstance(
        id="delete-cleanup-fails-instance",
        template_id=order.template_id,
        name="delete-cleanup-fails-instance",
        status=TaskStatus.RUNNING,
        source_order_id=order.id,
    )
    order.materialized_instance_id = instance.id
    db_session.add(instance)
    await db_session.commit()

    async def fake_cleanup(_db, _instance):
        return ["compute: 删除容器失败"]

    async def fake_cancel_all_schedules(self, _instance_id):
        return None

    async def fake_emit_release(*_args, **_kwargs):
        raise AssertionError("cleanup 失败时不应释放路由资源")

    monkeypatch.setattr("api.orders.cleanup_instance_runtime", fake_cleanup)
    monkeypatch.setattr("api.orders.TaskScheduler.cancel_all_schedules", fake_cancel_all_schedules)
    monkeypatch.setattr("api.orders.emit_release_events_for_order", fake_emit_release)

    response = await client.delete("/api/orders/delete-cleanup-fails-order", headers=headers)

    assert response.status_code == 409
    assert "容器清理失败" in response.json()["detail"]
    order_row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    assert order_row.scalar_one_or_none() is not None
    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance.id))
    assert instance_row.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_admin_batch_delete_materialized_order_cleans_instance_before_deleting(client, db_session, monkeypatch):
    _owner_headers, owner = await _auth_headers(client, db_session, username="batch-delete-owner")
    admin_headers, _admin = await _auth_headers(client, db_session, username="batch-delete-admin", role=UserRole.ADMIN)
    order = await _create_order(db_session, "batch-delete-materialized-order", owner=owner, status=OrderStatus.MATERIALIZED)
    instance = TaskInstance(
        id="batch-delete-materialized-instance",
        template_id=order.template_id,
        name="batch-delete-materialized-instance",
        status=TaskStatus.RUNNING,
        source_order_id=order.id,
    )
    order.materialized_instance_id = instance.id
    db_session.add(instance)
    await db_session.commit()
    calls = []

    async def fake_cleanup(_db, cleaned_instance):
        calls.append(cleaned_instance.id)
        return []

    async def fake_cancel_all_schedules(self, instance_id):
        calls.append(f"schedule:{instance_id}")

    monkeypatch.setattr("api.orders.cleanup_instance_runtime", fake_cleanup)
    monkeypatch.setattr("api.orders.TaskScheduler.cancel_all_schedules", fake_cancel_all_schedules)

    response = await client.post(
        "/api/orders/batch/delete",
        headers=admin_headers,
        json={"order_ids": [order.id]},
    )

    assert response.status_code == 200
    assert response.json()["succeeded"] == [order.id]
    assert response.json()["failed"] == {}
    assert calls == ["schedule:batch-delete-materialized-instance", "batch-delete-materialized-instance"]
    order_row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    assert order_row.scalar_one_or_none() is None
    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance.id))
    assert instance_row.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_admin_batch_delete_keeps_order_when_runtime_cleanup_fails(client, db_session, monkeypatch):
    _owner_headers, owner = await _auth_headers(client, db_session, username="batch-delete-fail-owner")
    admin_headers, _admin = await _auth_headers(client, db_session, username="batch-delete-fail-admin", role=UserRole.ADMIN)
    order = await _create_order(db_session, "batch-delete-cleanup-fails-order", owner=owner, status=OrderStatus.MATERIALIZED)
    instance = TaskInstance(
        id="batch-delete-cleanup-fails-instance",
        template_id=order.template_id,
        name="batch-delete-cleanup-fails-instance",
        status=TaskStatus.RUNNING,
        source_order_id=order.id,
    )
    order.materialized_instance_id = instance.id
    db_session.add(instance)
    await db_session.commit()

    async def fake_cleanup(_db, _instance):
        return ["compute: 删除容器失败"]

    async def fake_cancel_all_schedules(self, _instance_id):
        return None

    monkeypatch.setattr("api.orders.cleanup_instance_runtime", fake_cleanup)
    monkeypatch.setattr("api.orders.TaskScheduler.cancel_all_schedules", fake_cancel_all_schedules)

    response = await client.post(
        "/api/orders/batch/delete",
        headers=admin_headers,
        json={"order_ids": [order.id]},
    )

    assert response.status_code == 200
    assert response.json()["succeeded"] == []
    assert "容器清理失败" in response.json()["failed"][order.id]
    order_row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    assert order_row.scalar_one_or_none() is not None
    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance.id))
    assert instance_row.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_admin_batch_cleanup_reports_runtime_cleanup_warnings_as_failure(client, db_session, monkeypatch):
    _owner_headers, owner = await _auth_headers(client, db_session, username="batch-cleanup-warning-owner")
    admin_headers, _admin = await _auth_headers(client, db_session, username="batch-cleanup-warning-admin", role=UserRole.ADMIN)
    order = await _create_order(db_session, "batch-cleanup-warning-order", owner=owner, status=OrderStatus.MATERIALIZED)
    instance = TaskInstance(
        id="batch-cleanup-warning-instance",
        template_id=order.template_id,
        name="batch-cleanup-warning-instance",
        status=TaskStatus.RUNNING,
        source_order_id=order.id,
    )
    order.materialized_instance_id = instance.id
    db_session.add(instance)
    await db_session.commit()

    async def fake_cleanup(_db, _instance):
        return ["compute: 删除容器失败"]

    async def fake_cancel_all_schedules(self, _instance_id):
        return None

    monkeypatch.setattr("api.orders.cleanup_instance_runtime", fake_cleanup)
    monkeypatch.setattr("api.orders.TaskScheduler.cancel_all_schedules", fake_cancel_all_schedules)

    response = await client.post(
        "/api/orders/batch/cleanup-instances",
        headers=admin_headers,
        json={"order_ids": [order.id]},
    )

    assert response.status_code == 200
    assert response.json()["succeeded"] == []
    assert "容器清理失败" in response.json()["failed"][order.id]
    order_row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
    assert order_row.scalar_one().status == OrderStatus.MATERIALIZED.value
    instance_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance.id))
    assert instance_row.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_user_can_cancel_pending_own_order_and_routing_request(client, db_session):
    headers, owner = await _auth_headers(client, db_session, username="order-cancel-self")
    order = await _create_order(db_session, "cancel-own-order", owner=owner)
    conversation = Conversation(
        id="conversation-cancel-own-order",
        user_id=owner.id,
        status=ConversationStatus.AWAITING_ROUTING,
        materialized_order_id=order.id,
    )
    draft = IntentDraft(
        id="draft-cancel-own-order",
        conversation_id=conversation.id,
    )
    routing = RoutingRequest(
        id="routing-cancel-own-order",
        conversation_id=conversation.id,
        order_id=order.id,
        intent_draft_id=draft.id,
        strategy="resource_guarantee",
        status="pending",
    )
    db_session.add_all([conversation, draft, routing])
    order.conversation_id = conversation.id
    order.routing_request_id = routing.id
    await db_session.commit()

    response = await client.post("/api/orders/cancel-own-order/cancel", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == OrderStatus.CANCELLED.value
    row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == "cancel-own-order"))
    cancelled_order = row.scalar_one()
    assert cancelled_order.status == OrderStatus.CANCELLED.value
    assert cancelled_order.routing_status == RoutingStatus.CANCELLED.value
    routing_row = await db_session.execute(select(RoutingRequest).where(RoutingRequest.id == routing.id))
    assert routing_row.scalar_one().status == "cancelled"
    conversation_row = await db_session.execute(select(Conversation).where(Conversation.id == conversation.id))
    assert conversation_row.scalar_one().status == ConversationStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_user_cannot_cancel_non_pending_order(client, db_session):
    headers, owner = await _auth_headers(client, db_session, username="order-cancel-completed")
    await _create_order(db_session, "cancel-completed-order", owner=owner, status=OrderStatus.COMPLETED)

    response = await client.post("/api/orders/cancel-completed-order/cancel", headers=headers)

    assert response.status_code == 400
