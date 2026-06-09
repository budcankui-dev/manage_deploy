from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.orders import RoutingResultPayload, receive_routing_result as receive_order_routing_result
from api.auth import get_current_user, require_service_token
from database import get_db
from enums import ConversationStatus, ParseStatus, RoutingRequestStatus, RoutingStatus
from models import Conversation, IntentDraft, RoutingRequest, TaskOrder, User
from schemas.conversation import RoutingRequestCreate, RoutingRequestResponse, RoutingResultCallback
from services.order_materialize import materialize_after_routing

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


@router.get("/routing-orders", response_model=list[RoutingOrderResponse])
async def list_routing_orders(
    status: RoutingStatus = Query(RoutingStatus.PENDING),
    benchmark_run_id: str | None = Query(None),
    task_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _service: None = Depends(require_service_token),
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
    _service: None = Depends(require_service_token),
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


@router.post("/routing-orders/{order_id}/result")
async def receive_routing_order_result(
    order_id: str,
    payload: RoutingResultPayload,
    db: AsyncSession = Depends(get_db),
    _service: None = Depends(require_service_token),
):
    """Receive placements from an external router for a TaskOrder."""
    return await receive_order_routing_result(order_id=order_id, payload=payload, db=db)


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
    _service: None = Depends(require_service_token),
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
    _service: None = Depends(require_service_token),
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
    _service: None = Depends(require_service_token),
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
