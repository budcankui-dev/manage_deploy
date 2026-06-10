from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import RoutingResourceEvent, TaskOrder


def _runtime_config(order: TaskOrder) -> dict[str, Any]:
    return order.runtime_config if isinstance(order.runtime_config, dict) else {}


def _routing_result(order: TaskOrder) -> dict[str, Any]:
    config = _runtime_config(order)
    result = config.get("routing_result")
    return result if isinstance(result, dict) else {}


def _benchmark_run_id(order: TaskOrder) -> str | None:
    benchmark = _runtime_config(order).get("benchmark")
    if isinstance(benchmark, dict) and benchmark.get("run_id"):
        return str(benchmark["run_id"])
    return None


def _task_type(order: TaskOrder) -> str | None:
    business_task = _runtime_config(order).get("business_task")
    if isinstance(business_task, dict) and business_task.get("task_type"):
        return str(business_task["task_type"])
    return None


def _placements(order: TaskOrder) -> list[dict[str, Any]]:
    placements = _routing_result(order).get("placements")
    if isinstance(placements, list):
        return [item for item in placements if isinstance(item, dict)]
    if isinstance(placements, dict):
        rows: list[dict[str, Any]] = []
        for role, value in placements.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("node_id", role)
                rows.append(row)
            elif value:
                rows.append({"node_id": role, "worker_host": str(value)})
        return rows
    return []


def _gpu_ids(placement: dict[str, Any]) -> list[str]:
    if placement.get("gpu_device") is not None:
        return [str(placement["gpu_device"])]
    if placement.get("gpu_id") is not None:
        return [str(placement["gpu_id"])]
    indices = placement.get("gpu_indices")
    if isinstance(indices, list):
        return [str(item) for item in indices if item is not None]
    return []


def _worker_host(placement: dict[str, Any]) -> str | None:
    value = placement.get("worker_host") or placement.get("node_name") or placement.get("hostname")
    return str(value) if value else None


def _pending_event_exists(
    db: AsyncSession,
    *,
    order_id: str,
    node_hostname: str,
    resource_kind: str,
    resource_id: str,
) -> bool:
    for item in db.new:
        if not isinstance(item, RoutingResourceEvent):
            continue
        if (
            item.event_type == "release"
            and item.order_id == order_id
            and item.node_hostname == node_hostname
            and item.resource_kind == resource_kind
            and item.resource_id == resource_id
        ):
            return True
    return False


async def emit_release_events_for_order(
    db: AsyncSession,
    order: TaskOrder,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Record idempotent GPU release events for the order's compute placement."""
    routing_result = _routing_result(order)
    external_routing_id = routing_result.get("external_routing_id")
    emitted = 0

    for placement in _placements(order):
        role = str(placement.get("node_id") or placement.get("role") or "").lower()
        if role not in {"compute", "worker", "infer", "train"}:
            continue
        node_hostname = _worker_host(placement)
        if not node_hostname:
            continue
        for gpu_id in _gpu_ids(placement):
            if _pending_event_exists(
                db,
                order_id=order.id,
                node_hostname=node_hostname,
                resource_kind="gpu",
                resource_id=gpu_id,
            ):
                continue
            existing = await db.execute(
                select(RoutingResourceEvent).where(
                    RoutingResourceEvent.event_type == "release",
                    RoutingResourceEvent.order_id == order.id,
                    RoutingResourceEvent.node_hostname == node_hostname,
                    RoutingResourceEvent.resource_kind == "gpu",
                    RoutingResourceEvent.resource_id == gpu_id,
                )
            )
            if existing.scalar_one_or_none():
                continue
            db.add(
                RoutingResourceEvent(
                    event_type="release",
                    order_id=order.id,
                    job_id=order.id,
                    external_routing_id=str(external_routing_id) if external_routing_id else None,
                    benchmark_run_id=_benchmark_run_id(order),
                    task_type=_task_type(order),
                    node_hostname=node_hostname,
                    resource_kind="gpu",
                    resource_id=gpu_id,
                    amount=1,
                    reason=reason,
                    event_metadata=metadata or {},
                )
            )
            emitted += 1
    return emitted


async def emit_release_events_for_instance(
    db: AsyncSession,
    instance_id: str | None,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    if not instance_id:
        return 0
    result = await db.execute(select(TaskOrder).where(TaskOrder.materialized_instance_id == instance_id))
    emitted = 0
    for order in result.scalars().all():
        emitted += await emit_release_events_for_order(db, order, reason=reason, metadata=metadata)
    return emitted
