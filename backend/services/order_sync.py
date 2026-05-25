"""TaskOrder 与 TaskInstance 生命周期同步。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enums import OrderStatus
from models import BusinessObjectiveEvaluation, TaskInstance, TaskOrder, TaskResultObject


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
    """删除工单前清理该实例关联的评估与结果对象。"""
    if not instance_id:
        return
    eval_rows = await db.execute(
        select(BusinessObjectiveEvaluation).where(
            BusinessObjectiveEvaluation.instance_id == instance_id
        )
    )
    for row in eval_rows.scalars():
        await db.delete(row)
    result_rows = await db.execute(
        select(TaskResultObject).where(TaskResultObject.instance_id == instance_id)
    )
    for row in result_rows.scalars():
        await db.delete(row)
