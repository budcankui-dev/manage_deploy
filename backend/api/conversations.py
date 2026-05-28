import json
from datetime import datetime
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import get_current_user
from database import async_session_maker, get_db
from enums import ConversationStatus, DeploymentMode, MessageRole, OrderStatus, ParseStatus, RoutingRequestStatus, RoutingStatus
from models import BusinessTemplateCatalog, Conversation, ConversationMessage, IntentDraft, Node, RoutingRequest, TaskOrder, User
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
from services.llm_intent_parser import _build_messages, _build_chat_messages, stream_qwen_tokens, parse_intent_llm
from services.routing_payload_builder import build_routing_payload
from services.dag_builder import build_matmul_dag

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
    await db.commit()
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

    # Query available node names for validation
    nodes_result = await db.execute(
        select(Node.hostname).where(Node.deleted_at.is_(None))
    )
    valid_nodes = [row[0] for row in nodes_result.fetchall()]

    parsed, _trace = await run_intent_workflow(payload.content, existing, valid_nodes)

    version = (latest_draft.version + 1) if latest_draft else 1
    draft = IntentDraft(
        conversation_id=conversation.id,
        version=version,
        task_type=parsed.task_type,
        modality=parsed.modality,
        source_name=parsed.source_name,
        destination_name=parsed.destination_name,
        business_start_time=parsed.business_start_time,
        business_end_time=parsed.business_end_time,
        data_profile=parsed.data_profile or None,
        business_objective=parsed.business_objective or None,
        runtime_plan=parsed.runtime_plan or None,
        resource_requirement=parsed.resource_requirement or None,
        validation_errors=parsed.validation_errors or None,
        parse_status=ParseStatus(parsed.parse_status),
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        raw_llm_response=_trace.get("raw_llm_response"),
        confidence=_trace.get("raw_llm_response", {}).get("confidence") if isinstance(_trace.get("raw_llm_response"), dict) else None,
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
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: str,
    payload: ConversationMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream assistant reply token-by-token via SSE, then persist the full
    intent parse and draft after streaming completes.

    All DB reads happen BEFORE returning StreamingResponse so the Depends(get_db)
    session is still open.  The generator captures only primitive values and uses
    a fresh async_session_maker() session for the post-stream DB writes, because
    FastAPI closes the Depends session as soon as the route handler returns.
    """
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    if conversation.status in {ConversationStatus.SUBMITTED, ConversationStatus.REJECTED}:
        raise HTTPException(status_code=400, detail="Conversation is closed")

    # Update title while the session is still open
    if not conversation.title:
        conversation.title = payload.content[:80]
        await db.flush()

    # Save user message and commit BEFORE returning StreamingResponse,
    # because the Depends session commits only after streaming completes,
    # but the frontend may call GET before that.
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=payload.content,
        )
    )
    await db.commit()

    # Read draft while the session is still open; capture as plain dict
    latest_draft = await _get_latest_draft(db, conversation.id)
    existing = _draft_to_dict(latest_draft) if latest_draft else None
    next_version = (latest_draft.version + 1) if latest_draft else 1

    # Query available node names for validation
    nodes_result = await db.execute(
        select(Node.hostname).where(Node.deleted_at.is_(None))
    )
    valid_nodes = [row[0] for row in nodes_result.fetchall()]

    # Build chat messages for streaming (natural language, no JSON schema)
    chat_messages = _build_chat_messages(payload.content, existing, valid_nodes)

    # Capture primitive IDs needed inside the generator
    conv_id = conversation.id
    user_content = payload.content

    async def _event_stream() -> AsyncGenerator[str, None]:
        import logging
        log = logging.getLogger(__name__)

        accumulated = ""
        try:
            async for token in stream_qwen_tokens(chat_messages):
                accumulated += token
                yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            log.exception("SSE token stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        # After streaming: run structured parse then persist using a FRESH session
        try:
            parsed, _trace = await run_intent_workflow(user_content, existing, valid_nodes)

            async with async_session_maker() as session:
                async with session.begin():
                    draft = IntentDraft(
                        conversation_id=conv_id,
                        version=next_version,
                        task_type=parsed.task_type,
                        modality=parsed.modality,
                        source_name=parsed.source_name,
                        destination_name=parsed.destination_name,
                        business_start_time=parsed.business_start_time,
                        business_end_time=parsed.business_end_time,
                        data_profile=parsed.data_profile or None,
                        business_objective=parsed.business_objective or None,
                        runtime_plan=parsed.runtime_plan or None,
                        resource_requirement=parsed.resource_requirement or None,
                        validation_errors=parsed.validation_errors or None,
                        parse_status=ParseStatus(parsed.parse_status),
                        parser_name=parsed.parser_name,
                        parser_version=parsed.parser_version,
                        raw_llm_response=_trace.get("raw_llm_response"),
                        confidence=(
                            _trace.get("raw_llm_response", {}).get("confidence")
                            if isinstance(_trace.get("raw_llm_response"), dict)
                            else None
                        ),
                    )
                    session.add(draft)

                    new_status = (
                        ConversationStatus.REJECTED
                        if parsed.parse_status == "rejected"
                        else ConversationStatus.DRAFTING
                    )
                    assistant_content = accumulated if accumulated else parsed.assistant_message
                    session.add(
                        ConversationMessage(
                            conversation_id=conv_id,
                            role=MessageRole.ASSISTANT,
                            content=assistant_content,
                        )
                    )

                    # Update conversation status + timestamp
                    conv_row = await session.get(Conversation, conv_id)
                    if conv_row:
                        conv_row.status = new_status
                        conv_row.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)

            done_payload = {
                "type": "done",
                "draft": {
                    "task_type": parsed.task_type,
                    "modality": parsed.modality,
                    "source_name": parsed.source_name,
                    "destination_name": parsed.destination_name,
                    "business_start_time": parsed.business_start_time.isoformat() if parsed.business_start_time else None,
                    "business_end_time": parsed.business_end_time.isoformat() if parsed.business_end_time else None,
                    "data_profile": parsed.data_profile,
                    "runtime_plan": parsed.runtime_plan,
                    "parse_status": parsed.parse_status,
                    "validation_errors": parsed.validation_errors or [],
                    "assistant_message": assistant_content,
                },
                "conversation_status": new_status.value,
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            log.exception("SSE post-stream parse error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/confirm-intent", response_model=ConversationResponse)
async def confirm_intent(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认意图后创建 TaskOrder + RoutingRequest（方案 B：先创建工单再路由）。"""
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    if conversation.materialized_order_id or conversation.status == ConversationStatus.AWAITING_ROUTING:
        raise HTTPException(status_code=409, detail="工单已创建，请勿重复提交")
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

    # 查找业务模板
    catalog_result = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == draft.task_type)
    )
    catalog = catalog_result.scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=400, detail=f"未找到 task_type={draft.task_type} 对应的业务模板")

    # 创建 TaskOrder（直接关联 user_id）
    order = TaskOrder(
        id=conversation.id,
        user_id=current_user.id,
        conversation_id=conversation.id,
        intent_draft_id=draft.id,
        template_id=catalog.template_id,
        name=conversation.title or f"{draft.task_type}-{conversation.id[:8]}",
        source_name=draft.source_name,
        destination_name=draft.destination_name,
        business_start_time=draft.business_start_time,
        business_end_time=draft.business_end_time,
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=draft.business_start_time,
        scheduled_end_time=draft.business_end_time,
        status=OrderStatus.PENDING,
        routing_status=RoutingStatus.PENDING,
    )
    order.runtime_config = {
        "business_task": {
            "task_type": draft.task_type,
            "modality": draft.modality,
            "source_name": draft.source_name,
            "destination_name": draft.destination_name,
            "data_profile": draft.data_profile,
            "runtime_plan": draft.runtime_plan,
            "business_objective": draft.business_objective,
        }
    }
    try:
        db.add(order)
        await db.flush()
    except Exception as exc:
        if "Duplicate entry" in str(exc) or "UNIQUE constraint" in str(exc) or "IntegrityError" in type(exc).__name__:
            raise HTTPException(status_code=409, detail="工单已创建，请勿重复提交")
        raise

    # 生成路由 DAG 并写入工单
    dp = draft.data_profile or {}
    rp = draft.runtime_plan or {}
    dag = build_matmul_dag(
        order_id=order.id,
        source_name=draft.source_name,
        destination_name=draft.destination_name,
        business_start_time=draft.business_start_time,
        business_end_time=draft.business_end_time,
        matrix_size=dp.get("matrix_size"),
        batch_count=dp.get("batch_count"),
        routing_strategy=rp.get("routing_strategy"),
    )
    order.routing_input_dag = dag

    # 生成外部路由 DAG payload
    input_payload = build_routing_payload(
        order_id=order.id,
        order_name=order.name,
        task_type=draft.task_type,
        modality=draft.modality,
        source_name=draft.source_name,
        destination_name=draft.destination_name,
        business_start_time=draft.business_start_time,
        business_end_time=draft.business_end_time,
        data_profile=draft.data_profile,
        resource_requirement=draft.resource_requirement,
    )

    # 创建 RoutingRequest
    routing = RoutingRequest(
        conversation_id=conversation.id,
        order_id=order.id,
        intent_draft_id=draft.id,
        strategy="resource_guarantee",
        status=RoutingRequestStatus.PENDING,
        source_name=draft.source_name,
        destination_name=draft.destination_name,
        business_start_time=draft.business_start_time,
        business_end_time=draft.business_end_time,
        input_payload=input_payload,
    )
    db.add(routing)
    await db.flush()

    # 回填关联
    order.routing_request_id = routing.id
    conversation.status = ConversationStatus.AWAITING_ROUTING
    conversation.materialized_order_id = order.id
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    await db.flush()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)

    # 先删 routing_requests（其 intent_draft_id NOT NULL，无法置 null）
    rr_rows = await db.execute(select(RoutingRequest).where(RoutingRequest.conversation_id == conversation_id))
    for rr in rr_rows.scalars().all():
        await db.delete(rr)

    # 保留工单，只解除 FK 引用
    orders = await db.execute(select(TaskOrder).where(TaskOrder.conversation_id == conversation_id))
    for order in orders.scalars().all():
        order.conversation_id = None

    await db.flush()
    await db.delete(conversation)
    await db.flush()


@router.post("/{conversation_id}/submit", response_model=ConversationSubmitResponse)
async def submit_conversation(
    conversation_id: str,
    auto_start: bool = False,
    scheduled_end_time=None,
    keep_after_stop: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交意图。后端会强制转换为 SCHEDULED 模式，并填充 end_time（默认 start + 2h）。

    `auto_start` 字段保留接口兼容，目前在 SCHEDULED 路径下被忽略。
    """
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
        scheduled_end_time=scheduled_end_time,
        keep_after_stop=keep_after_stop,
    )

    result: BusinessTaskResponse = await create_business_task(business_payload, db)
    conversation.status = ConversationStatus.SUBMITTED
    conversation.materialized_order_id = result.order_id
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
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
        "source_name": draft.source_name,
        "destination_name": draft.destination_name,
        "business_start_time": draft.business_start_time,
        "business_end_time": draft.business_end_time,
        "data_profile": draft.data_profile or {},
        "business_objective": draft.business_objective or {},
        "runtime_plan": draft.runtime_plan or {},
        "resource_requirement": draft.resource_requirement or {},
    }
