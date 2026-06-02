from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.auth import get_current_user
from database import get_db
from enums import DeploymentMode, OrderStatus, RoutingStatus
from models import BusinessTemplateCatalog, Node as NodeModel, TaskInstance, TaskInstanceNode, TaskOrder, User
from schemas import (
    BatchOperationRequest,
    BatchOperationResponse,
    TaskInstanceCreate,
    TaskInstanceNodeOverride,
    TaskOrderCreate,
    TaskOrderDetailResponse,
    TaskOrderEvaluationSummary,
    TaskOrderInstanceSummary,
    TaskOrderResponse,
)
from services.business_task_query import get_order_detail_context
from services.order_materialize import _resolve_node_id
from services.order_sync import purge_order_instance_artifacts, reconcile_orphan_orders
from services.port_plan import format_service_url, get_business_address
from services.scheduler import TaskScheduler

from .instances import _create_instance_from_template

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _order_to_response(order: TaskOrder, instance_exists: bool | None = None) -> TaskOrderResponse:
    rc = order.runtime_config or {}
    bt = rc.get("business_task") or {}
    rp = bt.get("runtime_plan") or {}
    data = TaskOrderResponse.model_validate(order)
    updates = {
        "task_type": bt.get("task_type"),
        "routing_policy": bt.get("routing_policy") or rp.get("routing_strategy"),
    }
    if instance_exists is not None:
        updates["instance_exists"] = instance_exists
    return data.model_copy(update=updates)


async def _instance_exists(db: AsyncSession, instance_id: str | None) -> bool | None:
    if not instance_id:
        return None
    row = await db.execute(select(TaskInstance.id).where(TaskInstance.id == instance_id))
    return row.scalar_one_or_none() is not None


@router.post("", response_model=TaskOrderResponse)
async def create_order(payload: TaskOrderCreate, db: AsyncSession = Depends(get_db)):
    if payload.external_task_id:
        exists = await db.execute(
            select(TaskOrder).where(TaskOrder.external_task_id == payload.external_task_id)
        )
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="external_task_id already exists")

    runtime_config = {"node_overrides": [item.model_dump() for item in payload.node_overrides], "extra": payload.extra}
    order = TaskOrder(
        external_task_id=payload.external_task_id,
        template_id=payload.template_id,
        name=payload.name,
        description=payload.description,
        deployment_mode=payload.deployment_mode,
        scheduled_start_time=payload.scheduled_start_time,
        scheduled_end_time=payload.scheduled_end_time,
        auto_start=payload.auto_start,
        runtime_config=runtime_config,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _order_to_response(order)


@router.get("", response_model=list[TaskOrderResponse])
async def list_orders(
    status: OrderStatus | None = None,
    include_cancelled: bool = False,
    reconcile: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if reconcile:
        if await reconcile_orphan_orders(db):
            await db.commit()

    query = select(TaskOrder).where(TaskOrder.user_id == current_user.id)
    if status:
        query = query.where(TaskOrder.status == status)
    elif not include_cancelled:
        query = query.where(TaskOrder.status != OrderStatus.CANCELLED)
    rows = await db.execute(query.order_by(TaskOrder.created_at.desc()))
    orders = rows.scalars().all()

    responses: list[TaskOrderResponse] = []
    for order in orders:
        exists = await _instance_exists(db, order.materialized_instance_id)
        responses.append(_order_to_response(order, instance_exists=exists))
    return responses


@router.get("/{order_id}", response_model=TaskOrderDetailResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order, instance, evaluation = await get_order_detail_context(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    config = order.runtime_config or {}
    business_task = config.get("business_task")
    routing_result = config.get("routing_result")

    instance_exists = await _instance_exists(db, order.materialized_instance_id)
    base = _order_to_response(order, instance_exists=instance_exists)
    detail = TaskOrderDetailResponse.model_validate(base.model_dump())
    detail.business_task = business_task if isinstance(business_task, dict) else None
    detail.routing_result = routing_result if isinstance(routing_result, dict) else None

    if instance:
        # Build port_access_urls from instance nodes
        port_access_urls: dict[str, str] = {}
        inst_nodes_result = await db.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance.id)
        )
        inst_nodes = inst_nodes_result.scalars().all()
        for inst_node in inst_nodes:
            if not inst_node.port_values:
                continue
            machine = (await db.execute(
                select(NodeModel).where(NodeModel.id == inst_node.node_id)
            )).scalar_one_or_none()
            if not machine:
                continue
            biz_addr = get_business_address(machine)
            for port_name, port_val in inst_node.port_values.items():
                try:
                    port_int = int(port_val)
                except (TypeError, ValueError):
                    continue
                key = f"{inst_node.name}/{port_name}"
                port_access_urls[key] = format_service_url(biz_addr, port_int)

        detail.instance = TaskOrderInstanceSummary(
            id=instance.id,
            status=instance.status,
            node_count=len(instance.nodes or []),
            error_message=instance.error_message,
            port_access_urls=port_access_urls or None,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )
    if evaluation:
        object_uris = evaluation.object_uris if isinstance(evaluation.object_uris, dict) else {}
        result_metadata = object_uris.get("result_metadata")
        if not isinstance(result_metadata, dict):
            result_metadata = None
        detail.evaluation = TaskOrderEvaluationSummary(
            metric_key=evaluation.metric_key,
            actual_value=evaluation.actual_value,
            target_value=evaluation.target_value,
            unit=evaluation.unit,
            business_success=evaluation.business_success,
            failure_reason=evaluation.failure_reason,
            estimated_value=evaluation.estimated_value,
            estimation_error_ratio=evaluation.estimation_error_ratio,
            result_metadata=result_metadata,
        )
    return detail


@router.delete("/{order_id}")
async def delete_order(order_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await purge_order_instance_artifacts(db, order.materialized_instance_id)
    await db.delete(order)
    await db.commit()
    return {"message": "Order deleted"}


@router.post("/batch/delete", response_model=BatchOperationResponse)
async def batch_delete_orders(request: BatchOperationRequest, db: AsyncSession = Depends(get_db)):
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for order_id in request.order_ids:
        try:
            row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
            order = row.scalar_one_or_none()
            if not order:
                failed[order_id] = "Order not found"
                continue
            await purge_order_instance_artifacts(db, order.materialized_instance_id)
            await db.delete(order)
            succeeded.append(order_id)
        except Exception as exc:
            failed[order_id] = str(exc)
    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/{order_id}/materialize", response_model=dict)
async def materialize_order(order_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Order is cancelled")

    config = order.runtime_config or {}
    try:
        instance = TaskInstanceCreate(
            template_id=order.template_id,
            name=order.name,
            deployment_mode=order.deployment_mode,
            scheduled_start_time=order.scheduled_start_time,
            scheduled_end_time=order.scheduled_end_time,
            auto_start=order.auto_start,
            node_overrides=config.get("node_overrides", []),
        )
        created = await _create_instance_from_template(db, instance, source_order_id=order.id)
        order.materialized_instance_id = created.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
        await db.commit()
        return {"order_id": order.id, "instance_id": created.id, "status": "materialized"}
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = str(exc)
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Materialization failed: {exc}") from exc


@router.post("/materialize/pending", response_model=dict)
async def materialize_pending_orders(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(TaskOrder).where(TaskOrder.status == OrderStatus.PENDING).order_by(TaskOrder.created_at.asc())
    )
    orders = rows.scalars().all()
    success = []
    failed = {}
    for order in orders:
        try:
            config = order.runtime_config or {}
            instance = TaskInstanceCreate(
                template_id=order.template_id,
                name=order.name,
                deployment_mode=order.deployment_mode,
                scheduled_start_time=order.scheduled_start_time,
                scheduled_end_time=order.scheduled_end_time,
                auto_start=order.auto_start,
                node_overrides=config.get("node_overrides", []),
            )
            created = await _create_instance_from_template(db, instance, source_order_id=order.id)
            order.materialized_instance_id = created.id
            order.status = OrderStatus.MATERIALIZED
            order.error_message = None
            success.append(order.id)
        except Exception as exc:
            order.status = OrderStatus.FAILED
            order.error_message = str(exc)
            failed[order.id] = str(exc)
        await db.commit()
    return {"succeeded": success, "failed": failed}


class RoutingPlacement(BaseModel):
    node_id: str
    worker_host: str
    gpu_device: Optional[str] = None


class RoutingResultPayload(BaseModel):
    placements: list[RoutingPlacement]


@router.post("/{order_id}/routing-result")
async def receive_routing_result(
    order_id: str,
    payload: RoutingResultPayload,
    db: AsyncSession = Depends(get_db),
):
    """接收外部路由系统的计算结果（节点放置 + GPU 分配），并自动物化实例。"""
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.materialized_instance_id:
        raise HTTPException(status_code=409, detail="Routing result already processed")

    # Persist routing result
    order.routing_status = RoutingStatus.COMPLETED.value
    rc = order.runtime_config or {}
    rc["routing_result"] = {"placements": [p.model_dump() for p in payload.placements]}
    order.runtime_config = rc
    flag_modified(order, "runtime_config")

    # Resolve role -> template_node_name from catalog
    catalog_row = await db.execute(
        select(BusinessTemplateCatalog).where(
            BusinessTemplateCatalog.template_id == order.template_id
        )
    )
    catalog = catalog_row.scalar_one_or_none()
    role_node_names = {
        "source": catalog.source_node_name if catalog else None,
        "compute": catalog.compute_node_name if catalog else None,
        "worker": catalog.compute_node_name if catalog else None,
        "sink": catalog.sink_node_name if catalog else None,
    }

    # Build node_overrides from placements list
    overrides: list[TaskInstanceNodeOverride] = []
    for placement in payload.placements:
        role = placement.node_id  # node_id field carries the role name from router
        template_node_name = role_node_names.get(role) if catalog else role
        if template_node_name is None:
            template_node_name = role

        try:
            resolved_node_id = await _resolve_node_id(db, placement.worker_host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        env: dict[str, str] = {
            "TASK_ROLE": role,
            "SOURCE_NAME": order.source_name or "",
            "DESTINATION_NAME": order.destination_name or "",
        }
        # Inject business task env vars from runtime_config
        bt = (order.runtime_config or {}).get("business_task", {})
        if bt:
            import json
            env["TASK_TYPE"] = bt.get("task_type") or ""
            env["DATA_PROFILE"] = json.dumps(bt.get("data_profile") or {})
            env["BUSINESS_OBJECTIVE"] = json.dumps(bt.get("business_objective") or {})
            env["RUNTIME_PLAN"] = json.dumps(bt.get("runtime_plan") or {})
            env["TASK_INSTANCE_ID"] = order.id  # will be updated after instance creation
        if placement.gpu_device is not None:
            env["GPU_DEVICE"] = placement.gpu_device

        overrides.append(TaskInstanceNodeOverride(
            template_node_name=template_node_name,
            node_id=resolved_node_id,
            env=env,
        ))

    # Create instance
    instance_create = TaskInstanceCreate(
        template_id=order.template_id,
        name=order.name,
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=order.business_start_time,
        scheduled_end_time=order.business_end_time,
        auto_start=False,
        keep_after_stop=order.keep_after_stop,
        node_overrides=overrides,
    )
    instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)

    # Update TASK_INSTANCE_ID in each node's env now that we have the real instance id
    for node in instance.nodes:
        if node.env and node.env.get("TASK_INSTANCE_ID") == order.id:
            node.env = {**node.env, "TASK_INSTANCE_ID": instance.id}
            flag_modified(node, "env")

    # Register scheduled jobs
    ts = TaskScheduler()
    if order.business_start_time:
        await ts.schedule_task_start(instance.id, order.business_start_time)
    if order.business_end_time:
        await ts.schedule_task_end(instance.id, order.business_end_time)

    order.materialized_instance_id = instance.id
    order.status = OrderStatus.MATERIALIZED

    await db.commit()
    return {"status": "ok", "order_id": order_id, "routing_status": "completed", "instance_id": instance.id}
