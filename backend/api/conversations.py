from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import get_current_user
from database import get_db
from enums import ConversationStatus, MessageRole, ParseStatus, RoutingRequestStatus
from models import Conversation, ConversationMessage, IntentDraft, RoutingRequest, User
from schemas import (
    BusinessObjective,
    BusinessTaskCreate,
    BusinessTaskResponse,
    ConversationCreate,
    ConversationMessageCreate,
    ConversationResponse,
    ConversationSubmitResponse,
    ConversationSummary,
    IntentDraftUpdate,
    RoutingResult,
)
from services.intent_parser import validate_draft_fields
from services.intent_workflow import run_intent_workflow

from .business_tasks import create_business_task

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = Conversation(
        user_id=current_user.id,
        title=payload.title,
        status=ConversationStatus.DRAFTING,
    )
    db.add(conversation)
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_conversation_detail(db, conversation_id, current_user.id)


@router.post("/{conversation_id}/messages", response_model=ConversationResponse)
async def send_message(
    conversation_id: str,
    payload: ConversationMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    if conversation.status in {ConversationStatus.SUBMITTED, ConversationStatus.REJECTED}:
        raise HTTPException(status_code=400, detail="Conversation is closed")

    if not conversation.title:
        conversation.title = payload.content[:80]

    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=payload.content,
        )
    )

    latest_draft = await _get_latest_draft(db, conversation.id)
    existing = _draft_to_dict(latest_draft) if latest_draft else None
    parsed, _trace = run_intent_workflow(payload.content, existing)

    version = (latest_draft.version + 1) if latest_draft else 1
    draft = IntentDraft(
        conversation_id=conversation.id,
        version=version,
        task_type=parsed.task_type,
        modality=parsed.modality,
        data_profile=parsed.data_profile or None,
        business_objective=parsed.business_objective or None,
        runtime_plan=parsed.runtime_plan or None,
        resource_requirement=parsed.resource_requirement or None,
        validation_errors=parsed.validation_errors or None,
        parse_status=ParseStatus(parsed.parse_status),
    )
    db.add(draft)

    if parsed.parse_status == "rejected":
        conversation.status = ConversationStatus.REJECTED
    else:
        conversation.status = ConversationStatus.DRAFTING

    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=parsed.assistant_message,
        )
    )
    conversation.updated_at = datetime.utcnow()
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.patch("/{conversation_id}/draft", response_model=ConversationResponse)
async def update_draft(
    conversation_id: str,
    payload: IntentDraftUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    draft = await _get_latest_draft(db, conversation.id)
    if not draft:
        raise HTTPException(status_code=404, detail="Intent draft not found")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(draft, key, value)

    errors = validate_draft_fields(_draft_to_dict(draft))
    draft.validation_errors = errors or None
    if draft.parse_status != ParseStatus.REJECTED:
        draft.parse_status = ParseStatus.VALID if not errors else ParseStatus.INCOMPLETE
    conversation.status = ConversationStatus.DRAFTING
    conversation.updated_at = datetime.utcnow()
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/confirm-intent", response_model=ConversationResponse)
async def confirm_intent(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    draft = await _get_latest_draft(db, conversation.id)
    if not draft:
        raise HTTPException(status_code=404, detail="Intent draft not found")
    if draft.parse_status == ParseStatus.REJECTED:
        raise HTTPException(status_code=400, detail="Intent was rejected")
    errors = validate_draft_fields(_draft_to_dict(draft))
    if errors:
        draft.validation_errors = errors
        draft.parse_status = ParseStatus.INCOMPLETE
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    draft.parse_status = ParseStatus.VALID
    draft.validation_errors = None
    conversation.status = ConversationStatus.AWAITING_ROUTING
    conversation.updated_at = datetime.utcnow()
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/submit", response_model=ConversationSubmitResponse)
async def submit_conversation(
    conversation_id: str,
    auto_start: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    if conversation.status != ConversationStatus.READY_TO_SUBMIT:
        raise HTTPException(status_code=400, detail="Conversation is not ready to submit")

    draft = await _get_latest_draft(db, conversation.id)
    if not draft or draft.parse_status != ParseStatus.VALID:
        raise HTTPException(status_code=400, detail="Valid intent draft required")

    routing = await _get_latest_routing(db, conversation.id)
    if not routing or routing.status != RoutingRequestStatus.COMPLETED or not routing.placements:
        raise HTTPException(status_code=400, detail="Completed routing result required")

    business_payload = BusinessTaskCreate(
        external_task_id=conversation.id,
        task_type=draft.task_type,
        modality=draft.modality,
        name=conversation.title or f"{draft.task_type}-{conversation.id[:8]}",
        data_profile=draft.data_profile or {},
        business_objective=BusinessObjective(**draft.business_objective),
        runtime_plan=draft.runtime_plan or {},
        resource_requirement=draft.resource_requirement or {},
        routing_result=RoutingResult(
            strategy=routing.strategy,
            placements=routing.placements,
            estimated_metric=routing.estimated_metric,
        ),
        result_storage={"backend": "minio", "bucket": "task-results", "prefix": f"{conversation.id}/"},
        auto_start=auto_start,
    )

    result: BusinessTaskResponse = await create_business_task(business_payload, db)
    conversation.status = ConversationStatus.SUBMITTED
    conversation.materialized_order_id = result.order_id
    conversation.updated_at = datetime.utcnow()
    await db.flush()

    return ConversationSubmitResponse(
        conversation_id=conversation.id,
        order_id=result.order_id,
        instance_id=result.instance_id,
        task_type=result.task_type,
        status=result.status,
    )


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


async def _get_latest_routing(db: AsyncSession, conversation_id: str) -> RoutingRequest | None:
    result = await db.execute(
        select(RoutingRequest)
        .where(RoutingRequest.conversation_id == conversation_id)
        .order_by(RoutingRequest.created_at.desc())
    )
    return result.scalars().first()


async def _get_conversation_detail(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
) -> ConversationResponse:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    draft = await _get_latest_draft(db, conversation.id)
    routing = await _get_latest_routing(db, conversation.id)
    return ConversationResponse(
        id=conversation.id,
        task_id=conversation.id,
        user_id=conversation.user_id,
        status=conversation.status,
        title=conversation.title,
        materialized_order_id=conversation.materialized_order_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        workflow_trace=conversation.workflow_trace,
        messages=sorted(conversation.messages, key=lambda item: item.created_at),
        latest_draft=draft,
        latest_routing_request=routing,
    )


def _draft_to_dict(draft: IntentDraft) -> dict:
    return {
        "task_type": draft.task_type,
        "modality": draft.modality,
        "data_profile": draft.data_profile or {},
        "business_objective": draft.business_objective or {},
        "runtime_plan": draft.runtime_plan or {},
        "resource_requirement": draft.resource_requirement or {},
    }
