from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from api.orders import RoutingResultPayload, receive_routing_result as receive_order_routing_result
from api.auth import get_current_user
from database import get_db
from enums import ConversationStatus, OrderStatus, ParseStatus, RoutingRequestStatus, RoutingStatus, TaskStatus
from models import Conversation, IntentDraft, RoutingRequest, RoutingResourceEvent, TaskInstance, TaskOrder, User
from schemas.conversation import RoutingRequestCreate, RoutingRequestResponse, RoutingResultCallback
from services.dag_executor import DAGExecutor
from services.order_materialize import materialize_after_routing
from services.routing_network import mark_network_ready, network_ready_required
from services.scheduler import TaskScheduler

router = APIRouter(prefix="/api", tags=["routing"])


class RoutingOrderResponse(BaseModel):
    order_id: str
    name: str
    routing_status: str
    source_name: str | None = None
    destination_name: str | None = None
    business_start_time: datetime | None = None
    business_end_time: datetime | None = None
    routing_input_dag: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None


class RoutingStatusUpdatePayload(BaseModel):
    reason: str | None = None
    metadata: dict[str, Any] | None = None


class RoutingResourceEventResponse(BaseModel):
    id: int
    event_type: str
    order_id: str
    job_id: str
    external_routing_id: str | None = None
    benchmark_run_id: str | None = None
    task_type: str | None = None
    node_hostname: str
    resource_kind: str
    resource_id: str
    amount: int
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    router_ack_at: datetime | None = None
    created_at: datetime | None = None


class RoutingResourceAckPayload(BaseModel):
    ids: list[int]


class NetworkReadyPayload(BaseModel):
    metadata: dict[str, Any] | None = None
    auto_start: bool = True


def _benchmark_run_id(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    benchmark = config.get("benchmark")
    if isinstance(benchmark, dict):
        value = benchmark.get("run_id")
        return str(value) if value else None
    return None


def _benchmark_task_type(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        value = business_task.get("task_type")
        return str(value) if value else None
    return None


def _routing_order_response(order: TaskOrder) -> RoutingOrderResponse:
    routing_status = order.routing_status.value if hasattr(order.routing_status, "value") else str(order.routing_status)
    return RoutingOrderResponse(
        order_id=order.id,
        name=order.name,
        routing_status=routing_status,
        source_name=order.source_name,
        destination_name=order.destination_name,
        business_start_time=order.business_start_time,
        business_end_time=order.business_end_time,
        routing_input_dag=order.routing_input_dag,
        runtime_config=order.runtime_config,
    )


def _resource_event_response(event: RoutingResourceEvent) -> RoutingResourceEventResponse:
    return RoutingResourceEventResponse(
        id=event.id,
        event_type=event.event_type,
        order_id=event.order_id,
        job_id=event.job_id,
        external_routing_id=event.external_routing_id,
        benchmark_run_id=event.benchmark_run_id,
        task_type=event.task_type,
        node_hostname=event.node_hostname,
        resource_kind=event.resource_kind,
        resource_id=event.resource_id,
        amount=event.amount,
        reason=event.reason,
        metadata=event.event_metadata,
        router_ack_at=event.router_ack_at,
        created_at=event.created_at,
    )


@router.get("/routing-orders", response_model=list[RoutingOrderResponse])
async def list_routing_orders(
    status: RoutingStatus = Query(RoutingStatus.PENDING),
    benchmark_run_id: str | None = Query(None),
    task_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """HTTP interface for external routers to list pending task orders."""
    result = await db.execute(
        select(TaskOrder)
        .where(
            TaskOrder.deleted_at.is_(None),
            TaskOrder.routing_status == status.value,
        )
        .order_by(TaskOrder.created_at.asc())
    )
    orders = result.scalars().all()
    if benchmark_run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == benchmark_run_id]
    if task_type:
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]
    return [_routing_order_response(order) for order in orders[:limit]]


@router.patch("/routing-orders/{order_id}/claim", response_model=RoutingOrderResponse)
async def claim_routing_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Claim a TaskOrder for external route computation."""
    result = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.routing_status != RoutingStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Cannot claim: current status is {order.routing_status}")

    order.routing_status = RoutingStatus.COMPUTING.value
    await db.commit()
    await db.refresh(order)
    return _routing_order_response(order)


@router.patch("/routing-orders/{order_id}/requeue", response_model=RoutingOrderResponse)
async def requeue_routing_order(
    order_id: str,
    payload: RoutingStatusUpdatePayload | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return a claimed order to pending when router capacity is temporarily unavailable."""
    result = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.routing_status != RoutingStatus.COMPUTING.value:
        raise HTTPException(status_code=409, detail=f"Cannot requeue: current status is {order.routing_status}")

    reason = payload.reason if payload else None
    order.routing_status = RoutingStatus.PENDING.value
    order.error_message = reason
    await db.commit()
    await db.refresh(order)
    return _routing_order_response(order)


@router.patch("/routing-orders/{order_id}/fail", response_model=RoutingOrderResponse)
async def fail_routing_order(
    order_id: str,
    payload: RoutingStatusUpdatePayload | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark an order as routing failed when no feasible placement can be produced."""
    result = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.routing_status == RoutingStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Cannot fail: routing result already completed")

    reason = payload.reason if payload else None
    order.routing_status = RoutingStatus.FAILED.value
    order.error_message = reason
    await db.commit()
    await db.refresh(order)
    return _routing_order_response(order)


@router.post("/routing-orders/{order_id}/result")
async def receive_routing_order_result(
    order_id: str,
    payload: RoutingResultPayload,
    db: AsyncSession = Depends(get_db),
):
    """Receive placements from an external router for a TaskOrder."""
    return await receive_order_routing_result(order_id=order_id, payload=payload, db=db)


@router.post("/routing-orders/{order_id}/network-ready")
async def confirm_routing_order_network_ready(
    order_id: str,
    payload: NetworkReadyPayload | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Confirm that the external router has installed flow rules/QoS for an order."""
    payload = payload or NetworkReadyPayload()
    row = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = row.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.routing_status not in {
        RoutingStatus.NETWORK_BINDING_READY.value,
        RoutingStatus.COMPLETED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot mark network ready when routing_status is '{order.routing_status}'",
        )

    already_ready = not network_ready_required(order)
    mark_network_ready(order, payload.metadata)
    order.routing_status = RoutingStatus.COMPLETED.value
    flag_modified(order, "runtime_config")

    instance: TaskInstance | None = None
    if order.materialized_instance_id:
        instance = (
            await db.execute(select(TaskInstance).where(TaskInstance.id == order.materialized_instance_id))
        ).scalar_one_or_none()

    now = datetime.utcnow()
    start_time = order.business_start_time or order.scheduled_start_time
    end_time = order.business_end_time or order.scheduled_end_time
    start_action = "none"
    start_error: str | None = None

    if instance and end_time and end_time <= now:
        instance.status = TaskStatus.EXPIRED
        instance.error_message = "业务结束时间已过，network-ready 到达后不再启动"
        order.status = OrderStatus.FAILED
        order.error_message = instance.error_message
        start_action = "expired"
        await db.commit()
    else:
        await db.commit()

        if instance and payload.auto_start:
            scheduler = TaskScheduler()
            try:
                if start_time and start_time > now:
                    await scheduler.schedule_task_start(instance.id, start_time)
                    start_action = "scheduled"
                else:
                    executor = DAGExecutor(db)
                    success, error = await executor.execute_dag_start(instance.id)
                    if success:
                        start_action = "started"
                    else:
                        start_action = "start_failed"
                        start_error = error or "Unknown error"
                if end_time and end_time > now:
                    await scheduler.schedule_task_end(instance.id, end_time)
            except Exception as exc:
                start_action = "start_failed"
                start_error = str(exc)

    return {
        "status": "ok",
        "order_id": order_id,
        "routing_status": RoutingStatus.COMPLETED.value,
        "instance_id": order.materialized_instance_id,
        "network_ready": True,
        "already_ready": already_ready,
        "auto_start": payload.auto_start,
        "start_action": start_action,
        "start_error": start_error,
    }


@router.get("/routing-resource-events", response_model=list[RoutingResourceEventResponse])
async def list_routing_resource_events(
    event_type: str = Query("release"),
    unacked: bool = Query(True),
    benchmark_run_id: str | None = Query(None),
    task_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List platform resource-release events for the external router to consume."""
    query = select(RoutingResourceEvent).where(RoutingResourceEvent.event_type == event_type)
    if unacked:
        query = query.where(RoutingResourceEvent.router_ack_at.is_(None))
    if benchmark_run_id:
        query = query.where(RoutingResourceEvent.benchmark_run_id == benchmark_run_id)
    if task_type:
        query = query.where(RoutingResourceEvent.task_type == task_type)
    result = await db.execute(query.order_by(RoutingResourceEvent.created_at.asc()).limit(limit))
    return [_resource_event_response(event) for event in result.scalars().all()]


@router.post("/routing-resource-events/ack")
async def ack_routing_resource_events(
    payload: RoutingResourceAckPayload,
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge resource-release events after the router has added capacity back."""
    if not payload.ids:
        return {"acked": 0, "ids": []}
    result = await db.execute(
        select(RoutingResourceEvent).where(
            RoutingResourceEvent.id.in_(payload.ids),
            RoutingResourceEvent.router_ack_at.is_(None),
        )
    )
    now = datetime.utcnow()
    events = result.scalars().all()
    for event in events:
        event.router_ack_at = now
    await db.commit()
    return {"acked": len(events), "ids": [event.id for event in events]}


@router.post("/routing-requests", response_model=RoutingRequestResponse)
async def create_routing_request(
    payload: RoutingRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, payload.conversation_id, current_user.id)
    if conversation.status not in {ConversationStatus.AWAITING_ROUTING, ConversationStatus.READY_TO_SUBMIT}:
        raise HTTPException(status_code=400, detail="Confirm intent before requesting routing")

    draft = await _get_latest_draft(db, conversation.id)
    if not draft or draft.parse_status != ParseStatus.VALID:
        raise HTTPException(status_code=400, detail="Valid intent draft required")

    routing = RoutingRequest(
        conversation_id=conversation.id,
        intent_draft_id=draft.id,
        strategy=payload.strategy,
        status=RoutingRequestStatus.PENDING,
    )
    db.add(routing)
    conversation.status = ConversationStatus.AWAITING_ROUTING
    conversation.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(routing)
    return routing


@router.get("/routing-requests/{routing_request_id}", response_model=RoutingRequestResponse)
async def get_routing_request(
    routing_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    routing = await _get_routing_for_user(db, routing_request_id, current_user.id)
    return routing


@router.post("/routing-results/{routing_request_id}", response_model=RoutingRequestResponse)
async def receive_routing_result(
    routing_request_id: str,
    payload: RoutingResultCallback,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RoutingRequest).where(RoutingRequest.id == routing_request_id))
    routing = result.scalar_one_or_none()
    if not routing:
        raise HTTPException(status_code=404, detail="Routing request not found")

    conversation_result = await db.execute(
        select(Conversation).where(Conversation.id == routing.conversation_id)
    )
    conversation = conversation_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    routing.status = payload.status
    if payload.strategy:
        routing.strategy = payload.strategy
    if payload.selected_strategy:
        routing.selected_strategy = payload.selected_strategy
    routing.placements = payload.placements
    routing.estimated_metric = payload.estimated_metric
    routing.external_routing_id = payload.external_routing_id
    routing.error_message = payload.error_message
    if payload.result_payload or payload.metadata:
        result_payload = dict(payload.result_payload or {})
        if payload.metadata:
            result_payload["metadata"] = payload.metadata
        routing.result_payload = result_payload
    routing.completed_at = datetime.utcnow()

    if payload.status == RoutingRequestStatus.COMPLETED and payload.placements:
        conversation.status = ConversationStatus.READY_TO_SUBMIT
    elif payload.status == RoutingRequestStatus.FAILED:
        conversation.status = ConversationStatus.FAILED

    # 同步更新关联的 TaskOrder routing_status
    if routing.order_id:
        order_result = await db.execute(select(TaskOrder).where(TaskOrder.id == routing.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.routing_status = payload.status.value
            # 路由完成后自动物化实例
            if payload.status == RoutingRequestStatus.COMPLETED and payload.placements:
                await materialize_after_routing(db, order, routing)

    conversation.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(routing)
    return routing


@router.get("/routing-requests", response_model=list[RoutingRequestResponse])
async def list_routing_requests(
    status: RoutingRequestStatus | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """供外部路由系统扫描待计算的路由请求。"""
    query = select(RoutingRequest).where(RoutingRequest.deleted_at.is_(None))
    if status:
        query = query.where(RoutingRequest.status == status)
    query = query.order_by(RoutingRequest.created_at.asc())
    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/routing-requests/{routing_request_id}/claim", response_model=RoutingRequestResponse)
async def claim_routing_request(
    routing_request_id: str,
    db: AsyncSession = Depends(get_db),
):
    """外部路由系统领取任务，标记为 computing。"""
    result = await db.execute(select(RoutingRequest).where(RoutingRequest.id == routing_request_id))
    routing = result.scalar_one_or_none()
    if not routing:
        raise HTTPException(status_code=404, detail="Routing request not found")
    if routing.status != RoutingRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Cannot claim: current status is {routing.status.value}")

    routing.status = RoutingRequestStatus.COMPUTING
    if routing.order_id:
        order_result = await db.execute(select(TaskOrder).where(TaskOrder.id == routing.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.routing_status = "computing"
    await db.flush()
    await db.refresh(routing)
    return routing


async def _get_owned_conversation(db: AsyncSession, conversation_id: str, user_id: str) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def _get_latest_draft(db: AsyncSession, conversation_id: str) -> IntentDraft | None:
    result = await db.execute(
        select(IntentDraft)
        .where(IntentDraft.conversation_id == conversation_id)
        .order_by(IntentDraft.version.desc())
    )
    return result.scalars().first()


async def _get_routing_for_user(db: AsyncSession, routing_request_id: str, user_id: str) -> RoutingRequest:
    result = await db.execute(
        select(RoutingRequest)
        .join(Conversation, Conversation.id == RoutingRequest.conversation_id)
        .where(RoutingRequest.id == routing_request_id, Conversation.user_id == user_id)
    )
    routing = result.scalar_one_or_none()
    if not routing:
        raise HTTPException(status_code=404, detail="Routing request not found")
    return routing
