import pytest
from sqlalchemy import select

from enums import OrderStatus
from models import TaskInstance, TaskOrder
from services.order_sync import mark_orders_cancelled_for_instance, reconcile_orphan_orders


@pytest.mark.asyncio
async def test_delete_instance_cancels_linked_order(client, db_session):
  """删除实例应同步取消 task_orders，避免批量任务页残留。"""
  from models import TaskTemplate
  from enums import TaskStatus

  template = TaskTemplate(name="tpl-order-sync", description="test")
  db_session.add(template)
  await db_session.flush()

  order = TaskOrder(
      external_task_id="ext-sync-001",
      template_id=template.id,
      name="sync-test-order",
      status=OrderStatus.MATERIALIZED,
      materialized_instance_id="inst-to-delete",
  )
  instance = TaskInstance(
      id="inst-to-delete",
      template_id=template.id,
      name="sync-test-instance",
      status=TaskStatus.STOPPED,
      source_order_id=order.id,
  )
  db_session.add(order)
  db_session.add(instance)
  await db_session.commit()

  resp = await client.delete("/api/instances/inst-to-delete")
  assert resp.status_code == 200

  row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == order.id))
  updated = row.scalar_one()
  assert updated.status == OrderStatus.CANCELLED
  assert updated.materialized_instance_id is None

  inst_row = await db_session.execute(select(TaskInstance).where(TaskInstance.id == "inst-to-delete"))
  assert inst_row.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_reconcile_orphan_orders(db_session):
  template_id = "tpl-orphan"
  from models import TaskTemplate

  db_session.add(TaskTemplate(id=template_id, name="orphan-tpl", description=""))
  await db_session.flush()

  order = TaskOrder(
      id="order-orphan-1",
      template_id=template_id,
      name="orphan",
      status=OrderStatus.MATERIALIZED,
      materialized_instance_id="ghost-instance",
  )
  db_session.add(order)
  await db_session.commit()

  fixed = await reconcile_orphan_orders(db_session)
  await db_session.commit()

  assert fixed == 1
  row = await db_session.execute(select(TaskOrder).where(TaskOrder.id == "order-orphan-1"))
  updated = row.scalar_one()
  assert updated.status == OrderStatus.CANCELLED
  assert updated.materialized_instance_id is None
