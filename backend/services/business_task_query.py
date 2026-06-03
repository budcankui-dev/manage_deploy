from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from enums import OrderStatus, TaskStatus
from models import BusinessObjectiveEvaluation, TaskInstance, TaskOrder
from schemas import BusinessTaskListItem, BusinessTaskListResponse


@dataclass
class BusinessTaskListFilters:
    page: int = 1
    page_size: int = 20
    task_type: str | None = None
    routing_policy: str | None = None
    order_status: OrderStatus | None = None
    deployment_status: TaskStatus | None = None
    business_success: bool | None = None
    q: str | None = None
    include_cancelled: bool = False


def _extract_business_task(order: TaskOrder) -> dict[str, Any] | None:
    config = order.runtime_config or {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        return business_task
    return None


def _routing_policy_from_order(order: TaskOrder) -> str | None:
    business_task = _extract_business_task(order)
    if not business_task:
        return None
    routing = business_task.get("routing_result") or {}
    return (
        routing.get("strategy")
        or routing.get("routing_policy")
        or (business_task.get("runtime_plan") or {}).get("routing_strategy")
    )


def _matches_filters(
    order: TaskOrder,
    business_task: dict[str, Any],
    instance: TaskInstance | None,
    evaluation: BusinessObjectiveEvaluation | None,
    filters: BusinessTaskListFilters,
) -> bool:
    if not filters.include_cancelled and order.status == OrderStatus.CANCELLED:
        return False
    if filters.order_status and order.status != filters.order_status:
        return False
    if filters.task_type and business_task.get("task_type") != filters.task_type:
        return False
    routing_policy = _routing_policy_from_order(order)
    if filters.routing_policy and routing_policy != filters.routing_policy:
        return False
    if filters.deployment_status:
        if not instance or instance.status != filters.deployment_status:
            return False
    if filters.business_success is not None:
        if not evaluation or evaluation.business_success != filters.business_success:
            return False
    if filters.q:
        needle = filters.q.strip().lower()
        haystacks = [
            order.name or "",
            order.external_task_id or "",
            business_task.get("name") or "",
            business_task.get("external_task_id") or "",
        ]
        if not any(needle in value.lower() for value in haystacks if value):
            return False
    return True


def _build_list_item(
    order: TaskOrder,
    business_task: dict[str, Any],
    instance: TaskInstance | None,
    evaluation: BusinessObjectiveEvaluation | None,
    instance_exists: bool | None,
) -> BusinessTaskListItem:
    objective = business_task.get("business_objective") or {}
    return BusinessTaskListItem(
        order_id=order.id,
        external_task_id=order.external_task_id or business_task.get("external_task_id"),
        name=order.name,
        task_type=business_task.get("task_type"),
        modality=business_task.get("modality"),
        routing_policy=_routing_policy_from_order(order),
        order_status=order.status,
        instance_id=order.materialized_instance_id,
        instance_exists=instance_exists,
        deployment_status=instance.status if instance else None,
        scheduled_start_time=instance.scheduled_start_time if instance else order.scheduled_start_time,
        scheduled_end_time=instance.scheduled_end_time if instance else order.scheduled_end_time,
        keep_after_stop=bool(instance.keep_after_stop) if instance else bool(order.keep_after_stop),
        metric_key=evaluation.metric_key if evaluation else objective.get("metric_key"),
        target_value=evaluation.target_value if evaluation else objective.get("target_value"),
        actual_value=evaluation.actual_value if evaluation else None,
        unit=evaluation.unit if evaluation else objective.get("unit"),
        business_success=evaluation.business_success if evaluation else None,
        created_at=order.created_at,
        updated_at=order.updated_at or (instance.updated_at if instance else None),
    )


async def _latest_evaluations(
    db: AsyncSession, instance_ids: list[str]
) -> dict[str, BusinessObjectiveEvaluation]:
    if not instance_ids:
        return {}
    rows = await db.execute(
        select(BusinessObjectiveEvaluation)
        .where(BusinessObjectiveEvaluation.instance_id.in_(instance_ids))
        .order_by(
            BusinessObjectiveEvaluation.instance_id.asc(),
            BusinessObjectiveEvaluation.created_at.desc(),
        )
    )
    result: dict[str, BusinessObjectiveEvaluation] = {}
    for row in rows.scalars():
        if row.instance_id not in result:
            result[row.instance_id] = row
    return result


async def _instances_by_ids(db: AsyncSession, instance_ids: list[str]) -> dict[str, TaskInstance]:
    if not instance_ids:
        return {}
    rows = await db.execute(select(TaskInstance).where(TaskInstance.id.in_(instance_ids)))
    return {row.id: row for row in rows.scalars()}


async def list_business_tasks(
    db: AsyncSession,
    filters: BusinessTaskListFilters,
    user_id: str | None = None,
) -> BusinessTaskListResponse:
    """
    列出业务工单。

    SQL WHERE 层：order_status、include_cancelled、runtime_config IS NOT NULL。
    Python 内存过滤：task_type、routing_policy、deployment_status、
    business_success、q（这些需要 JSON 解析或跨表数据）。
    分页：先全量过滤再 offset/limit，保证 total 准确。
    """
    # Base query — SQL-level filters applied here
    query = (
        select(TaskOrder)
        .where(TaskOrder.runtime_config.isnot(None))
        .order_by(TaskOrder.created_at.desc())
    )
    if user_id is not None:
        query = query.where(TaskOrder.user_id == user_id)
    if filters.order_status:
        query = query.where(TaskOrder.status == filters.order_status)
    elif not filters.include_cancelled:
        query = query.where(TaskOrder.status != OrderStatus.CANCELLED)

    rows = await db.execute(query)
    candidate_orders: list[tuple[TaskOrder, dict[str, Any]]] = []
    for order in rows.scalars():
        business_task = _extract_business_task(order)
        if business_task:
            candidate_orders.append((order, business_task))

    # Eager-load all needed instances and evaluations in 2 queries
    instance_ids = [
        order.materialized_instance_id
        for order, _ in candidate_orders
        if order.materialized_instance_id
    ]
    instance_map = await _instances_by_ids(db, instance_ids)
    eval_map = await _latest_evaluations(db, instance_ids)

    # Python-level filters (JSON extraction / cross-table)
    filtered: list[tuple[TaskOrder, dict[str, Any]]] = []
    for order, business_task in candidate_orders:
        instance = instance_map.get(order.materialized_instance_id or "")
        evaluation = eval_map.get(order.materialized_instance_id or "")
        if _matches_filters(order, business_task, instance, evaluation, filters):
            filtered.append((order, business_task))

    # Pagination
    total = len(filtered)
    page = max(filters.page, 1)
    page_size = min(max(filters.page_size, 1), 100)
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]

    items: list[BusinessTaskListItem] = []
    for order, business_task in page_rows:
        instance = instance_map.get(order.materialized_instance_id or "")
        evaluation = eval_map.get(order.materialized_instance_id or "")
        instance_exists = None
        if order.materialized_instance_id:
            instance_exists = instance is not None
        items.append(
            _build_list_item(order, business_task, instance, evaluation, instance_exists)
        )

    return BusinessTaskListResponse(items=items, total=total, page=page, page_size=page_size)


async def summarize_business_tasks(
    db: AsyncSession,
    include_cancelled: bool = False,
    is_benchmark: bool | None = None,
) -> list[dict[str, Any]]:
    query = select(TaskOrder).where(TaskOrder.runtime_config.isnot(None))
    if not include_cancelled:
        query = query.where(TaskOrder.status != OrderStatus.CANCELLED)
    if is_benchmark is not None:
        query = query.where(TaskOrder.is_benchmark == is_benchmark)
    rows = await db.execute(query)
    business_orders: list[tuple[TaskOrder, dict[str, Any]]] = []
    for order in rows.scalars():
        if not include_cancelled and order.status == OrderStatus.CANCELLED:
            continue
        business_task = _extract_business_task(order)
        if business_task:
            business_orders.append((order, business_task))

    instance_ids = [
        order.materialized_instance_id
        for order, _ in business_orders
        if order.materialized_instance_id
    ]
    eval_map = await _latest_evaluations(db, instance_ids)

    groups: dict[tuple[str, str | None], dict[str, int]] = {}
    for order, business_task in business_orders:
        task_type = business_task.get("task_type") or "unknown"
        routing_strategy = _routing_policy_from_order(order)
        key = (task_type, routing_strategy)
        bucket = groups.setdefault(
            key, {"count": 0, "success_count": 0, "evaluated_count": 0}
        )
        bucket["count"] += 1
        evaluation = eval_map.get(order.materialized_instance_id or "")
        if evaluation is not None:
            bucket["evaluated_count"] += 1
            if evaluation.business_success:
                bucket["success_count"] += 1

    return [
        {
            "task_type": task_type,
            "routing_strategy": routing_strategy,
            "count": bucket["count"],
            "evaluated_count": bucket["evaluated_count"],
            "success_count": bucket["success_count"],
            "business_success_rate": (
                bucket["success_count"] / bucket["evaluated_count"]
                if bucket["evaluated_count"]
                else None
            ),
        }
        for (task_type, routing_strategy), bucket in sorted(groups.items())
    ]


async def get_order_detail_context(
    db: AsyncSession, order_id: str
) -> tuple[TaskOrder, TaskInstance | None, BusinessObjectiveEvaluation | None]:
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        return None, None, None  # type: ignore[return-value]

    instance = None
    evaluation = None
    if order.materialized_instance_id:
        inst_row = await db.execute(
            select(TaskInstance)
            .where(TaskInstance.id == order.materialized_instance_id)
            .options(selectinload(TaskInstance.nodes))
        )
        instance = inst_row.scalar_one_or_none()
        if instance:
            eval_map = await _latest_evaluations(db, [instance.id])
            evaluation = eval_map.get(instance.id)
    return order, instance, evaluation
