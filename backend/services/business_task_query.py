from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from enums import OrderStatus, TaskStatus
from models import BusinessObjectiveEvaluation, TaskInstance, TaskMetric, TaskOrder, User
from schemas import BusinessTaskListItem, BusinessTaskListResponse
from services.routing_policy import VALID_ROUTING_POLICIES, normalize_routing_policy

ACCEPTANCE_REQUIRED_EVALUATED_COUNT = 30
ACCEPTANCE_REQUIRED_SUCCESS_RATE = 0.9


@dataclass
class BusinessTaskListFilters:
    page: int = 1
    page_size: int = 20
    task_type: str | None = None
    is_benchmark: bool | None = None
    benchmark_run_id: str | None = None
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


def _extract_benchmark_run_id(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    benchmark = config.get("benchmark")
    if isinstance(benchmark, dict):
        value = benchmark.get("run_id")
        return str(value) if value else None
    return None


def _routing_policy_from_order(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    business_task = _extract_business_task(order)
    runtime_plan = business_task.get("runtime_plan") if isinstance(business_task, dict) else {}
    task_routing_policy = None
    if isinstance(runtime_plan, dict):
        task_routing_policy = normalize_routing_policy(runtime_plan.get("routing_strategy"))
    if not task_routing_policy and isinstance(business_task, dict):
        task_routing_policy = normalize_routing_policy(business_task.get("routing_strategy"))

    routing = config.get("routing_result")
    if isinstance(routing, dict):
        value = routing.get("strategy") or routing.get("selected_strategy") or routing.get("routing_policy")
        if normalized := normalize_routing_policy(value):
            return normalized
        if task_routing_policy:
            return task_routing_policy
    if not business_task:
        return None
    routing = business_task.get("routing_result") or {}
    return (
        routing.get("strategy") if routing.get("strategy") in VALID_ROUTING_POLICIES else None
    ) or (
        routing.get("selected_strategy") if routing.get("selected_strategy") in VALID_ROUTING_POLICIES else None
    ) or (
        routing.get("routing_policy") if routing.get("routing_policy") in VALID_ROUTING_POLICIES else None
    ) or task_routing_policy


def _business_priority_from_order(order: TaskOrder, business_task: dict[str, Any] | None = None) -> int | None:
    routing_dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    priority = routing_dag.get("priority")
    if priority is None:
        task = business_task or _extract_business_task(order) or {}
        priority = task.get("priority")
    try:
        return int(priority) if priority is not None else None
    except (TypeError, ValueError):
        return None


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
    if filters.is_benchmark is not None and bool(order.is_benchmark) != filters.is_benchmark:
        return False
    if filters.benchmark_run_id and _extract_benchmark_run_id(order) != filters.benchmark_run_id:
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
    owner: User | None = None,
    metric: TaskMetric | None = None,
) -> BusinessTaskListItem:
    objective = business_task.get("business_objective") or {}
    return BusinessTaskListItem(
        order_id=order.id,
        external_task_id=order.external_task_id or business_task.get("external_task_id"),
        name=order.name,
        owner_user_id=order.user_id,
        owner_username=owner.username if owner else None,
        task_type=business_task.get("task_type"),
        is_benchmark=bool(order.is_benchmark),
        benchmark_run_id=_extract_benchmark_run_id(order),
        modality=business_task.get("modality"),
        routing_policy=_routing_policy_from_order(order),
        business_priority=_business_priority_from_order(order, business_task),
        order_status=order.status,
        instance_id=order.materialized_instance_id,
        instance_exists=instance_exists,
        deployment_status=instance.status if instance else None,
        scheduled_start_time=instance.scheduled_start_time if instance else order.scheduled_start_time,
        scheduled_end_time=instance.scheduled_end_time if instance else order.scheduled_end_time,
        keep_after_stop=bool(instance.keep_after_stop) if instance else bool(order.keep_after_stop),
        metric_key=evaluation.metric_key if evaluation else objective.get("metric_key"),
        target_value=evaluation.target_value if evaluation else objective.get("target_value"),
        actual_value=evaluation.actual_value if evaluation else (metric.metric_value if metric else None),
        unit=evaluation.unit if evaluation else (metric.unit if metric and metric.unit else objective.get("unit")),
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


async def _latest_metrics(
    db: AsyncSession,
    instance_ids: list[str],
    business_task_by_instance: dict[str, dict[str, Any]],
) -> dict[str, TaskMetric]:
    if not instance_ids:
        return {}
    metric_keys = {
        objective.get("metric_key")
        for task in business_task_by_instance.values()
        if isinstance((objective := task.get("business_objective") or {}), dict)
        and objective.get("metric_key")
    }
    if not metric_keys:
        return {}
    rows = await db.execute(
        select(TaskMetric)
        .where(
            TaskMetric.instance_id.in_(instance_ids),
            TaskMetric.metric_key.in_(metric_keys),
        )
        .order_by(TaskMetric.instance_id.asc(), TaskMetric.reported_at.desc(), TaskMetric.id.desc())
    )
    result: dict[str, TaskMetric] = {}
    for row in rows.scalars():
        task = business_task_by_instance.get(row.instance_id) or {}
        objective = task.get("business_objective") or {}
        if row.metric_key != objective.get("metric_key"):
            continue
        if row.instance_id not in result:
            result[row.instance_id] = row
    return result


async def _instances_by_ids(db: AsyncSession, instance_ids: list[str]) -> dict[str, TaskInstance]:
    if not instance_ids:
        return {}
    rows = await db.execute(select(TaskInstance).where(TaskInstance.id.in_(instance_ids)))
    return {row.id: row for row in rows.scalars()}


async def _users_by_ids(db: AsyncSession, user_ids: list[str]) -> dict[str, User]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User).where(User.id.in_(user_ids)))
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
    business_task_by_instance = {
        order.materialized_instance_id: business_task
        for order, business_task in candidate_orders
        if order.materialized_instance_id
    }
    metric_map = await _latest_metrics(db, instance_ids, business_task_by_instance)

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
    user_ids = [order.user_id for order, _ in page_rows if order.user_id]
    user_map = await _users_by_ids(db, user_ids)

    items: list[BusinessTaskListItem] = []
    for order, business_task in page_rows:
        instance = instance_map.get(order.materialized_instance_id or "")
        evaluation = eval_map.get(order.materialized_instance_id or "")
        metric = metric_map.get(order.materialized_instance_id or "")
        instance_exists = None
        if order.materialized_instance_id:
            instance_exists = instance is not None
        items.append(
            _build_list_item(
                order,
                business_task,
                instance,
                evaluation,
                instance_exists,
                user_map.get(order.user_id or ""),
                metric,
            )
        )

    return BusinessTaskListResponse(items=items, total=total, page=page, page_size=page_size)


async def summarize_business_tasks(
    db: AsyncSession,
    include_cancelled: bool = False,
    is_benchmark: bool | None = None,
    benchmark_run_id: str | None = None,
    task_type: str | None = None,
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
        if benchmark_run_id and _extract_benchmark_run_id(order) != benchmark_run_id:
            continue
        business_task = _extract_business_task(order)
        if task_type and business_task and business_task.get("task_type") != task_type:
            continue
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

    rows: list[dict[str, Any]] = []
    for (task_type, routing_strategy), bucket in sorted(groups.items()):
        evaluated_count = bucket["evaluated_count"]
        success_rate = bucket["success_count"] / evaluated_count if evaluated_count else None
        sample_count_passed = evaluated_count >= ACCEPTANCE_REQUIRED_EVALUATED_COUNT
        success_rate_passed = (
            success_rate is not None
            and success_rate >= ACCEPTANCE_REQUIRED_SUCCESS_RATE
        )
        rows.append(
            {
                "task_type": task_type,
                "routing_strategy": routing_strategy,
                "count": bucket["count"],
                "evaluated_count": evaluated_count,
                "success_count": bucket["success_count"],
                "business_success_rate": success_rate,
                "required_evaluated_count": ACCEPTANCE_REQUIRED_EVALUATED_COUNT,
                "required_success_rate": ACCEPTANCE_REQUIRED_SUCCESS_RATE,
                "sample_count_passed": sample_count_passed,
                "success_rate_passed": success_rate_passed,
                "acceptance_passed": sample_count_passed and success_rate_passed,
            }
        )
    return rows


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
        eval_map = await _latest_evaluations(db, [order.materialized_instance_id])
        evaluation = eval_map.get(order.materialized_instance_id)
    return order, instance, evaluation
