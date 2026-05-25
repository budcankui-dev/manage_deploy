"""TaskOrder 与 TaskInstance 生命周期同步。"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from enums import OrderStatus
from models import (
    BusinessObjectiveEvaluation,
    TaskInstance,
    TaskInstanceEdge,
    TaskInstanceNode,
    TaskOrder,
    TaskResultObject,
    TaskEvent,
)


async def mark_orders_cancelled_for_instance(db: AsyncSession, instance_id: str) -> int:
    """删除/撤销实例时，将关联工单标记为已取消并解除 instance 引用。"""
    result = await db.execute(
        select(TaskOrder).where(TaskOrder.materialized_instance_id == instance_id)
    )
    orders = result.scalars().all()
    for order in orders:
        order.status = OrderStatus.CANCELLED
        order.materialized_instance_id = None
        order.error_message = order.error_message or f"关联实例 {instance_id} 已删除"
    return len(orders)


async def reconcile_orphan_orders(db: AsyncSession) -> int:
    """将 materialized 但实例已不存在的工单修正为 cancelled（历史脏数据）。"""
    result = await db.execute(
        select(TaskOrder).where(TaskOrder.status == OrderStatus.MATERIALIZED)
    )
    orders = result.scalars().all()
    fixed = 0
    for order in orders:
        if not order.materialized_instance_id:
            continue
        inst = await db.execute(
            select(TaskInstance.id).where(TaskInstance.id == order.materialized_instance_id)
        )
        if inst.scalar_one_or_none() is None:
            order.status = OrderStatus.CANCELLED
            orphan_id = order.materialized_instance_id
            order.materialized_instance_id = None
            order.error_message = order.error_message or f"关联实例 {orphan_id} 已不存在"
            fixed += 1
    return fixed


async def purge_order_instance_artifacts(db: AsyncSession, instance_id: str | None) -> None:
    """
    删除工单前清理该实例关联的所有数据（幂等）。

    FK 依赖链：
      task_instances → task_instance_nodes(instance_id)
                    → task_instance_edges(from_node_id, to_node_id)
                    → task_events(node_instance_id)
      另：BusinessObjectiveEvaluation.instance_id, TaskResultObject.instance_id

    按依赖顺序（从叶到根）执行删除，无 cascade 的手动清理。
    """
    if not instance_id:
        return

    # 先收集 node IDs（用于清理叶子节点的外键引用）
    node_rows = await db.execute(
        select(TaskInstance)
        .where(TaskInstance.id == instance_id)
        .options(selectinload(TaskInstance.nodes))
    )
    instance = node_rows.scalar_one_or_none()
    if not instance:
        return  # 实例已不存在，幂等

    node_ids = [n.id for n in (instance.nodes or [])]

    # 1. task_events — 引用 task_instances.instance_id
    await db.execute(
        delete(TaskEvent).where(TaskEvent.instance_id == instance_id)
    )

    # 2. task_instance_edges — 引用 task_instance_nodes
    if node_ids:
        await db.execute(
            delete(TaskInstanceEdge).where(
                (TaskInstanceEdge.from_node_id.in_(node_ids))
                | (TaskInstanceEdge.to_node_id.in_(node_ids))
            )
        )

    # 3. task_instance_nodes — 引用 task_instances
    await db.execute(
        delete(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id)
    )

    # 4. evaluation + result_objects
    await db.execute(
        delete(BusinessObjectiveEvaluation).where(
            BusinessObjectiveEvaluation.instance_id == instance_id
        )
    )
    await db.execute(
        delete(TaskResultObject).where(TaskResultObject.instance_id == instance_id)
    )

    # 5. TaskInstance 本身
    await db.execute(delete(TaskInstance).where(TaskInstance.id == instance_id))