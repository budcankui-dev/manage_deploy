from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_service_token
from database import get_db
from enums import ConversationStatus, ParseStatus, RoutingRequestStatus
from models import Conversation, IntentDraft, RoutingRequest, User
from schemas.conversation import RoutingRequestCreate, RoutingRequestResponse, RoutingResultCallback

router = APIRouter(prefix="/api", tags=["routing"])


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
    routing.placements = payload.placements
    routing.estimated_metric = payload.estimated_metric
    routing.external_routing_id = payload.external_routing_id
    routing.completed_at = datetime.utcnow()

    if payload.status == RoutingRequestStatus.COMPLETED and payload.placements:
        conversation.status = ConversationStatus.READY_TO_SUBMIT
    elif payload.status == RoutingRequestStatus.FAILED:
        conversation.status = ConversationStatus.FAILED

    conversation.updated_at = datetime.utcnow()
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
