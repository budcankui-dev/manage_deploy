import json
from datetime import datetime
from typing import AsyncGenerator
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from api.auth import get_current_user
from api.orders import RoutingPlacement, RoutingResultPayload
from config import settings
from database import async_session_maker, get_db
from enums import ConversationStatus, DeploymentMode, MessageRole, OrderStatus, ParseStatus, RoutingRequestStatus, RoutingStatus
from models import BusinessTemplateCatalog, Conversation, ConversationMessage, IntentDraft, Node, RoutingRequest, TaskOrder, User
from schemas import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationResponse,
    ConversationSubmitResponse,
    ConversationSummary,
    IntentDraftResponse,
    IntentDraftUpdate,
)
from services.intent_parser import validate_draft_fields
from services.intent_workflow import run_intent_workflow
from services.endpoint_resolver import EndpointResolutionError, ResolvedEndpoint, is_user_endpoint_node, resolve_user_endpoint
from services.routing_payload_builder import build_routing_payload
from services.system_settings import (
    get_runtime_settings,
    modality_priority_map_from_settings,
    routing_resource_options_from_settings,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

DEFAULT_DESTINATION_PORT_BY_TASK_TYPE = {
    "high_throughput_matmul": 9000,
    "low_latency_video_pipeline": 9100,
}


def _node_kind(node: Node) -> str:
    return str(node.node_kind or "worker").lower()


def _is_demo_compute_candidate(node: Node) -> bool:
    return (
        bool(node.is_schedulable)
        and bool(node.is_routable)
        and node.deleted_at is None
        and _node_kind(node) in {"worker", "both"}
    )


def _prefer_gpu_nodes(nodes: list[Node]) -> list[Node]:
    with_gpu = [node for node in nodes if int(node.gpu_count or 0) > 0]
    return with_gpu or nodes


def _node_endpoint_payload(node: Node | None) -> dict[str, str | None] | None:
    if not node:
        return None
    return {
        "hostname": node.hostname,
        "display_name": node.display_name,
        "topology_node_id": node.topology_node_id,
        "topology_zone": node.topology_zone,
        "management_ip": node.management_ip,
        "business_ip": node.business_ip,
        "business_ipv6": node.business_ipv6,
        "node_kind": node.node_kind,
    }


async def _endpoint_map_for_names(db: AsyncSession, names: list[str | None]) -> dict[str, dict[str, str | None]]:
    clean_names = sorted({name for name in names if name})
    if not clean_names:
        return {}
    rows = await db.execute(select(Node).where(Node.hostname.in_(clean_names), Node.deleted_at.is_(None)))
    return {node.hostname: _node_endpoint_payload(node) for node in rows.scalars().all()}


async def _valid_user_endpoint_names(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(Node).where(Node.deleted_at.is_(None)).order_by(Node.hostname.asc()))
    return [node.hostname for node in rows.scalars().all() if is_user_endpoint_node(node)]


def _callback_url_from_runtime_plan(runtime_plan: dict | None) -> str | None:
    if not isinstance(runtime_plan, dict):
        return None
    value = runtime_plan.get("callback_url")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_callback_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="目的端接收地址必须是 http:// 或 https:// 开头的完整 URL")
    if parsed.path in {"", "/"}:
        return text.rstrip("/") + "/callback"
    return text


def _runtime_value(runtime_plan: dict | None, key: str):
    if not isinstance(runtime_plan, dict):
        return None
    return runtime_plan.get(key)


def _destination_port_from_runtime_plan(runtime_plan: dict | None) -> int | None:
    value = _runtime_value(runtime_plan, "destination_port")
    if value in (None, ""):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _default_destination_port_for_task(task_type: str | None) -> int | None:
    return DEFAULT_DESTINATION_PORT_BY_TASK_TYPE.get(str(task_type or ""))


def _effective_destination_port(task_type: str | None, runtime_plan: dict | None) -> int | None:
    if isinstance(runtime_plan, dict) and runtime_plan.get("destination_port_disabled"):
        return None
    if _callback_url_from_runtime_plan(runtime_plan) and _destination_port_from_runtime_plan(runtime_plan) is None:
        return None
    return _destination_port_from_runtime_plan(runtime_plan) or _default_destination_port_for_task(task_type)


def _effective_callback_url(
    task_type: str | None,
    runtime_plan: dict | None,
    destination_endpoint: ResolvedEndpoint | None,
) -> str | None:
    explicit = _callback_url_from_runtime_plan(runtime_plan)
    if explicit:
        return explicit
    port = _effective_destination_port(task_type, runtime_plan)
    if destination_endpoint and port:
        return _callback_url_for_destination(destination_endpoint, port)
    return None


def _route_only_from_runtime_plan(runtime_plan: dict | None) -> bool:
    return bool(_runtime_value(runtime_plan, "route_only"))


def _endpoint_dict(endpoint: ResolvedEndpoint | None) -> dict | None:
    return endpoint.model_dump() if endpoint else None


def _preferred_business_host(endpoint: ResolvedEndpoint) -> str | None:
    if settings.prefer_business_ipv6:
        return endpoint.business_ipv6 or endpoint.business_ip
    return endpoint.business_ip or endpoint.business_ipv6


def _callback_url_for_destination(endpoint: ResolvedEndpoint, port: int) -> str:
    host = _preferred_business_host(endpoint)
    if not host:
        raise EndpointResolutionError("Destination endpoint has no data-plane IP")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/callback"


async def _resolve_endpoint_from_plan(
    db: AsyncSession,
    runtime_plan: dict | None,
    key: str,
) -> ResolvedEndpoint | None:
    value = _runtime_value(runtime_plan, key)
    if not value:
        return None
    return await resolve_user_endpoint(db, str(value))


async def _resolve_endpoint_from_plan_or_name(
    db: AsyncSession,
    runtime_plan: dict | None,
    key: str,
    fallback_name: str | None,
) -> ResolvedEndpoint | None:
    endpoint = await _resolve_endpoint_from_plan(db, runtime_plan, key)
    if endpoint:
        return endpoint
    if not fallback_name:
        return None
    try:
        return await resolve_user_endpoint(db, fallback_name)
    except EndpointResolutionError:
        return None


async def _require_endpoint_from_plan_or_name(
    db: AsyncSession,
    runtime_plan: dict | None,
    key: str,
    fallback_name: str | None,
    label: str,
) -> ResolvedEndpoint:
    value = _runtime_value(runtime_plan, key) or fallback_name
    if not value:
        raise HTTPException(status_code=400, detail=f"{label}不能为空，请填写已登记的终端别名、拓扑节点 ID 或业务面 IP")
    try:
        return await resolve_user_endpoint(db, str(value))
    except EndpointResolutionError as exc:
        raise HTTPException(status_code=400, detail=f"{label}不可用：{exc}") from exc


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

    # Source/destination slots only accept operator-managed endpoint nodes.
    valid_nodes = await _valid_user_endpoint_names(db)

    runtime_settings = await get_runtime_settings(db)
    parsed, _trace = await run_intent_workflow(
        payload.content,
        existing,
        valid_nodes,
        runtime_settings=runtime_settings,
    )

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
    await db.commit()
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

    # Source/destination slots only accept operator-managed endpoint nodes.
    valid_nodes = await _valid_user_endpoint_names(db)

    # Structured parse happens before streaming so the user-visible response is
    # derived from validated parameters, not from a free-form LLM guess.
    runtime_settings = await get_runtime_settings(db)
    parsed, _trace = await run_intent_workflow(
        payload.content,
        existing,
        valid_nodes,
        runtime_settings=runtime_settings,
    )

    # Capture primitive IDs needed inside the generator
    conv_id = conversation.id

    async def _event_stream() -> AsyncGenerator[str, None]:
        import logging
        log = logging.getLogger(__name__)

        assistant_content = parsed.assistant_message or "已完成参数解析。"
        for start in range(0, len(assistant_content), 12):
            token = assistant_content[start:start + 12]
            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

        # After streaming: persist using a FRESH session.
        try:
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

    fields_set = payload.model_fields_set
    updates = payload.model_dump(exclude_unset=True)
    runtime_plan = dict(draft.runtime_plan or {})
    source_endpoint_input = updates.pop("source_endpoint_input", None)
    destination_endpoint_input = updates.pop("destination_endpoint_input", None)
    destination_port_was_set = "destination_port" in fields_set
    destination_port = updates.pop("destination_port", None)
    route_only = updates.pop("route_only", None)
    callback_url_was_set = "callback_url" in fields_set
    callback_url = updates.pop("callback_url", None)

    if source_endpoint_input is not None:
        text = str(source_endpoint_input).strip()
        if text:
            try:
                resolved = await resolve_user_endpoint(db, text)
            except EndpointResolutionError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            runtime_plan["source_endpoint_input"] = text
            draft.source_name = resolved.topology_alias
        else:
            runtime_plan.pop("source_endpoint_input", None)

    if destination_endpoint_input is not None:
        text = str(destination_endpoint_input).strip()
        if text:
            try:
                resolved = await resolve_user_endpoint(db, text)
            except EndpointResolutionError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            runtime_plan["destination_endpoint_input"] = text
            draft.destination_name = resolved.topology_alias
        else:
            runtime_plan.pop("destination_endpoint_input", None)

    if destination_port_was_set:
        if destination_port is None:
            runtime_plan.pop("destination_port", None)
            runtime_plan.pop("callback_url", None)
            runtime_plan["destination_port_disabled"] = True
        else:
            try:
                port = int(destination_port)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="目的端口必须是 1-65535 之间的整数")
            if port < 1 or port > 65535:
                raise HTTPException(status_code=400, detail="目的端口必须是 1-65535 之间的整数")
            runtime_plan["destination_port"] = port
            runtime_plan.pop("destination_port_disabled", None)

    if route_only is not None:
        runtime_plan["route_only"] = bool(route_only)

    if callback_url_was_set:
        if callback_url is None:
            runtime_plan.pop("callback_url", None)
        else:
            normalized_callback_url = _normalize_callback_url(callback_url)
            if normalized_callback_url:
                runtime_plan["callback_url"] = normalized_callback_url
            else:
                runtime_plan.pop("callback_url", None)

    if destination_endpoint_input is not None or destination_port_was_set:
        try:
            destination_endpoint = await _resolve_endpoint_from_plan(db, runtime_plan, "destination_endpoint_input")
        except EndpointResolutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        port = _effective_destination_port(draft.task_type, runtime_plan)
        if destination_endpoint and port and not callback_url_was_set:
            runtime_plan["callback_url"] = _callback_url_for_destination(destination_endpoint, port)
        elif not port and not callback_url_was_set:
            runtime_plan.pop("callback_url", None)

    draft.runtime_plan = runtime_plan or None
    flag_modified(draft, "runtime_plan")
    for key, value in updates.items():
        setattr(draft, key, value)

    errors = validate_draft_fields(_draft_to_dict(draft))
    draft.validation_errors = errors or None
    if draft.parse_status != ParseStatus.REJECTED:
        draft.parse_status = ParseStatus.VALID if not errors else ParseStatus.INCOMPLETE
    conversation.status = ConversationStatus.DRAFTING
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    # The client may immediately refetch or confirm the draft after this PATCH.
    # Commit before returning so callback/endpoint updates are not subject to the
    # FastAPI yield-dependency cleanup timing.
    await db.commit()
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
    source_endpoint = await _require_endpoint_from_plan_or_name(
        db,
        draft.runtime_plan,
        "source_endpoint_input",
        draft.source_name,
        "源端点",
    )
    destination_endpoint = await _require_endpoint_from_plan_or_name(
        db,
        draft.runtime_plan,
        "destination_endpoint_input",
        draft.destination_name,
        "目的端点",
    )
    destination_port = _effective_destination_port(draft.task_type, draft.runtime_plan)
    callback_url = _effective_callback_url(draft.task_type, draft.runtime_plan, destination_endpoint)
    route_only = _route_only_from_runtime_plan(draft.runtime_plan)
    deployable_roles = [] if route_only else ["compute"]
    business_task_config = {
        "task_type": draft.task_type,
        "modality": draft.modality,
        "source_name": draft.source_name,
        "destination_name": draft.destination_name,
        "data_profile": draft.data_profile,
        "runtime_plan": draft.runtime_plan,
        "business_objective": draft.business_objective,
    }
    platform_deployment = {
        "mode": "route_only" if route_only else "user_access_demo",
        "deployable_roles": deployable_roles,
        "endpoint_policy": "source/sink are external user access endpoints by default",
    }
    external_endpoints = {}
    if source_endpoint:
        business_task_config["source_endpoint"] = _endpoint_dict(source_endpoint)
        external_endpoints["source"] = _endpoint_dict(source_endpoint)
    if destination_endpoint:
        sink_endpoint = _endpoint_dict(destination_endpoint) or {}
        if destination_port:
            sink_endpoint["business_port"] = destination_port
        business_task_config["destination_endpoint"] = sink_endpoint
        external_endpoints["sink"] = dict(sink_endpoint)
    if callback_url:
        business_task_config["callback_url"] = callback_url
        external_endpoints.setdefault("sink", {})["callback_url"] = callback_url
    if external_endpoints:
        platform_deployment["external_endpoints"] = external_endpoints
    order.runtime_config = {
        "business_task": business_task_config,
        "platform_deployment": platform_deployment,
    }
    try:
        db.add(order)
        await db.flush()
    except Exception as exc:
        if "Duplicate entry" in str(exc) or "UNIQUE constraint" in str(exc) or "IntegrityError" in type(exc).__name__:
            raise HTTPException(status_code=409, detail="工单已创建，请勿重复提交")
        raise

    runtime_settings = await get_runtime_settings(db)
    modality_priority_map = modality_priority_map_from_settings(runtime_settings)
    resource_options = routing_resource_options_from_settings(runtime_settings)

    # 生成外部路由 DAG payload，并同步作为工单路由输入，避免页面与路由请求出现两套 DAG。
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
        modality_priority_map=modality_priority_map,
        routing_strategy=(draft.runtime_plan or {}).get("routing_strategy"),
        callback_url=callback_url,
        source_endpoint=_endpoint_dict(source_endpoint),
        destination_endpoint=_endpoint_dict(destination_endpoint),
        destination_port=destination_port,
        deployable_roles=deployable_roles,
        **resource_options,
    )
    order.routing_input_dag = input_payload
    effective_resource_requirement = {
        str(node.get("task_node_id")): node.get("resources")
        for node in input_payload.get("nodes", [])
        if isinstance(node, dict)
        and node.get("task_node_id")
        and isinstance(node.get("resources"), dict)
    }
    if effective_resource_requirement:
        order.runtime_config["business_task"]["resource_requirement"] = effective_resource_requirement

    # 创建 RoutingRequest
    routing = RoutingRequest(
        conversation_id=conversation.id,
        order_id=order.id,
        intent_draft_id=draft.id,
        strategy=(draft.runtime_plan or {}).get("routing_strategy") or "resource_guarantee",
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

    if runtime_settings.get("benchmark_routing_mode") == "internal_auto":
        await _apply_platform_managed_route(db, conversation, order, start_deployment=False)

    await db.commit()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/cancel", response_model=ConversationResponse)
async def cancel_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)

    allowed = {ConversationStatus.AWAITING_ROUTING, ConversationStatus.READY_TO_SUBMIT}
    if conversation.status not in allowed:
        raise HTTPException(status_code=400, detail=f"当前状态不可取消：{conversation.status}")

    conversation.status = ConversationStatus.CANCELLED

    if conversation.materialized_order_id:
        order_row = await db.execute(
            select(TaskOrder).where(TaskOrder.id == conversation.materialized_order_id)
        )
        order = order_row.scalar_one_or_none()
        if order:
            order.status = OrderStatus.CANCELLED
            order.routing_status = RoutingStatus.CANCELLED.value

    await db.commit()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


@router.post("/{conversation_id}/demo-route", response_model=ConversationResponse)
async def demo_route_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Use the platform-managed routing path for a single user order."""
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)
    if conversation.status not in {ConversationStatus.AWAITING_ROUTING, ConversationStatus.READY_TO_SUBMIT}:
        raise HTTPException(status_code=400, detail=f"当前状态不可执行部署流程：{conversation.status}")
    if not conversation.materialized_order_id:
        raise HTTPException(status_code=400, detail="请先确认意图并创建工单")

    order = (
        await db.execute(
            select(TaskOrder).where(
                TaskOrder.id == conversation.materialized_order_id,
                TaskOrder.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="工单不存在")
    await _apply_platform_managed_route(db, conversation, order, start_deployment=True)
    await db.commit()
    return await _get_conversation_detail(db, conversation.id, current_user.id)


async def _apply_platform_managed_route(
    db: AsyncSession,
    conversation: Conversation,
    order: TaskOrder,
    *,
    start_deployment: bool = True,
) -> None:
    """Apply the built-in compute placement for user-access demo orders."""
    if order.materialized_instance_id:
        conversation.status = ConversationStatus.SUBMITTED
        conversation.updated_at = datetime.utcnow()
        return

    nodes = (
        await db.execute(
            select(Node)
            .where(
                Node.is_schedulable == True,
                Node.is_routable == True,
                Node.deleted_at.is_(None),
            )
            .order_by(Node.hostname.asc())
        )
    ).scalars().all()
    compute_nodes = [node for node in nodes if _is_demo_compute_candidate(node)]
    if not compute_nodes:
        raise HTTPException(status_code=400, detail="没有可用计算节点，无法执行部署流程")

    source_destination = {name for name in (order.source_name, order.destination_name) if name}
    preferred_compute = [node for node in compute_nodes if node.hostname not in source_destination]
    compute_candidates = _prefer_gpu_nodes(preferred_compute or compute_nodes)
    # Import lazily to avoid coupling the conversation module to order router setup.
    from api.orders import receive_routing_result as receive_order_routing_result

    runtime_config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    platform_deployment = runtime_config.get("platform_deployment") if isinstance(runtime_config.get("platform_deployment"), dict) else {}
    if start_deployment and platform_deployment.get("mode") == "route_only":
        platform_deployment = {
            **platform_deployment,
            "mode": "user_access_demo",
            "deployable_roles": ["compute"],
        }
        runtime_config["platform_deployment"] = platform_deployment
        runtime_config["manual_start_required"] = False
        runtime_config["deployment_required"] = True
        order.runtime_config = runtime_config
        order.routing_status = RoutingStatus.PENDING.value
        flag_modified(order, "runtime_config")

    last_conflict: HTTPException | None = None
    for compute_node in compute_candidates:
        try:
            await receive_order_routing_result(
                order_id=order.id,
                payload=RoutingResultPayload(
                    strategy="platform_managed",
                    selected_strategy="系统自动分配",
                    external_routing_id=f"platform-route-{conversation.id[:8]}",
                    placements=[
                        RoutingPlacement(
                            task_node_id="compute",
                            topology_node_id=compute_node.hostname,
                            gpu_device="0",
                        )
                    ],
                    metadata={
                        "mode": "platform_managed_route",
                        "description": "平台按当前可调度节点完成一次部署流程。",
                        "selected_compute": compute_node.hostname,
                    },
                    require_network_ready=False,
                ),
                db=db,
            )
            return
        except HTTPException as exc:
            if exc.status_code == 409 and "GPU slot conflict" in str(exc.detail):
                last_conflict = exc
                continue
            raise

    if last_conflict:
        raise HTTPException(status_code=409, detail="所有可用计算节点的 GPU 均已被当前时间窗口内的任务占用，请释放旧任务后重试")
    raise HTTPException(status_code=400, detail="没有可用计算节点，无法执行部署流程")


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

    order = None
    if conversation.materialized_order_id:
        order = (
            await db.execute(select(TaskOrder).where(TaskOrder.id == conversation.materialized_order_id))
        ).scalar_one_or_none()
    if order is None:
        order = (
            await db.execute(select(TaskOrder).where(TaskOrder.conversation_id == conversation.id))
        ).scalars().first()
    if order is None:
        raise HTTPException(status_code=400, detail="未找到已创建的工单，请先确认意图并等待路由结果")
    if not order.materialized_instance_id:
        raise HTTPException(status_code=400, detail="当前工单无需平台部署或尚未完成物化，不能提交启动")

    conversation.status = ConversationStatus.SUBMITTED
    conversation.materialized_order_id = order.id
    conversation.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    await db.flush()

    return ConversationSubmitResponse(
        conversation_id=conversation.id,
        order_id=order.id,
        instance_id=order.materialized_instance_id,
        task_type=draft.task_type,
        status=str(order.status),
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
    draft_response = None
    if draft:
        draft_response = IntentDraftResponse.model_validate(draft)
        endpoints = await _endpoint_map_for_names(db, [draft.source_name, draft.destination_name])
        source_endpoint = None
        destination_endpoint = None
        try:
            source_endpoint = await _resolve_endpoint_from_plan_or_name(
                db,
                draft.runtime_plan,
                "source_endpoint_input",
                draft.source_name,
            )
            destination_endpoint = await _resolve_endpoint_from_plan_or_name(
                db,
                draft.runtime_plan,
                "destination_endpoint_input",
                draft.destination_name,
            )
        except EndpointResolutionError:
            source_endpoint = None
            destination_endpoint = None
        draft_response.callback_url = _effective_callback_url(
            draft.task_type,
            draft.runtime_plan,
            destination_endpoint,
        )
        draft_response.source_endpoint = _endpoint_dict(source_endpoint) or endpoints.get(draft.source_name or "")
        draft_response.destination_endpoint = _endpoint_dict(destination_endpoint) or endpoints.get(draft.destination_name or "")
        if draft.parse_status == ParseStatus.VALID:
            runtime_settings = await get_runtime_settings(db)
            resource_options = routing_resource_options_from_settings(runtime_settings)
            deployable_roles = [] if _route_only_from_runtime_plan(draft.runtime_plan) else ["compute"]
            draft_response.routing_dag_preview = build_routing_payload(
                order_id=conversation.id,
                order_name=conversation.title or f"{draft.task_type}-{conversation.id[:8]}",
                task_type=draft.task_type,
                modality=draft.modality,
                source_name=draft.source_name,
                destination_name=draft.destination_name,
                business_start_time=draft.business_start_time,
                business_end_time=draft.business_end_time,
                data_profile=draft.data_profile,
                resource_requirement=draft.resource_requirement,
                modality_priority_map=modality_priority_map_from_settings(runtime_settings),
                routing_strategy=(draft.runtime_plan or {}).get("routing_strategy"),
                callback_url=draft_response.callback_url,
                source_endpoint=_endpoint_dict(source_endpoint),
                destination_endpoint=_endpoint_dict(destination_endpoint),
                destination_port=_effective_destination_port(draft.task_type, draft.runtime_plan),
                deployable_roles=deployable_roles,
                **resource_options,
            )
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
        latest_draft=draft_response,
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
        "callback_url": _callback_url_from_runtime_plan(draft.runtime_plan),
        "resource_requirement": draft.resource_requirement or {},
    }
