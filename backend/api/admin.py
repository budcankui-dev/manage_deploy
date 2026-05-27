"""管理员专用 API。

提供跨用户的对话审计、路由审计、用户管理和意图解析测试能力。
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import get_current_user, hash_password, require_admin
from database import get_db
from enums import RoutingRequestStatus, UserRole
from models import Conversation, ConversationMessage, IntentDraft, RoutingRequest, TaskOrder, User
from schemas import UserResponse
from schemas.conversation import (
    ConversationResponse,
    ConversationSummary,
    IntentDraftResponse,
    RoutingRequestResponse,
)
from services.intent_parser import parse_intent, ParseResult

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ─── 用户管理 ───────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    return {"ok": True}


@router.post("/users", response_model=UserResponse)
async def admin_create_user(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    username = payload.get("username")
    password = payload.get("password")
    role_str = payload.get("role", UserRole.USER)
    if not username or not password:
        raise HTTPException(status_code=422, detail="username and password are required")
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="username already exists")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role_str}")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def admin_update_user(
    user_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if "role" in payload:
        try:
            user.role = UserRole(payload["role"])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid role: {payload['role']}")
    if "password" in payload and payload["password"]:
        user.password_hash = hash_password(payload["password"])
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    order_count_r = await db.execute(
        select(func.count()).select_from(TaskOrder).where(TaskOrder.user_id == user_id)
    )
    order_count = order_count_r.scalar_one()
    conv_count_r = await db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )
    conv_count = conv_count_r.scalar_one()
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at,
        "order_count": order_count,
        "conversation_count": conv_count,
    }

# ─── 对话审计 ───────────────────────────────────────────────

@router.get("/conversations")
async def list_all_conversations(
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(Conversation).order_by(Conversation.updated_at.desc())
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    if status:
        query = query.where(Conversation.status == status)
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    drafts_r = await db.execute(
        select(IntentDraft).where(IntentDraft.conversation_id == conversation_id)
        .order_by(IntentDraft.version.desc())
    )
    drafts = drafts_r.scalars().all()
    routing_r = await db.execute(
        select(RoutingRequest).where(RoutingRequest.conversation_id == conversation_id)
        .order_by(RoutingRequest.created_at.desc())
    )
    routings = routing_r.scalars().all()
    return {
        "conversation": conv,
        "messages": sorted(conv.messages, key=lambda m: m.created_at),
        "drafts": drafts,
        "routing_requests": routings,
    }


# ─── 路由审计 ───────────────────────────────────────────────

@router.get("/routing-requests")
async def list_all_routing_requests(
    status: str | None = Query(None),
    order_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(RoutingRequest).where(RoutingRequest.deleted_at.is_(None))
    if status:
        query = query.where(RoutingRequest.status == status)
    if order_id:
        query = query.where(RoutingRequest.order_id == order_id)
    query = query.order_by(RoutingRequest.created_at.desc())
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ─── 工单审计 ───────────────────────────────────────────────

@router.get("/orders")
async def list_all_orders(
    user_id: str | None = Query(None),
    routing_status: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(TaskOrder).where(TaskOrder.deleted_at.is_(None))
    if user_id:
        query = query.where(TaskOrder.user_id == user_id)
    if routing_status:
        query = query.where(TaskOrder.routing_status == routing_status)
    if status:
        query = query.where(TaskOrder.status == status)
    query = query.order_by(TaskOrder.created_at.desc())
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ─── 意图解析测试 ─────────────────────────────────────────────

@router.post("/intent-parser/parse-one")
async def parse_one(
    payload: dict[str, Any],
    _admin: User = Depends(require_admin),
):
    """管理员测试单条意图解析。"""
    utterance = payload.get("utterance", "")
    context = payload.get("context")
    result = parse_intent(utterance, context)
    return {
        "task_type": result.task_type,
        "modality": result.modality,
        "source_name": result.source_name,
        "destination_name": result.destination_name,
        "business_start_time": str(result.business_start_time) if result.business_start_time else None,
        "business_end_time": str(result.business_end_time) if result.business_end_time else None,
        "data_profile": result.data_profile,
        "business_objective": result.business_objective,
        "parse_status": result.parse_status,
        "validation_errors": result.validation_errors,
        "assistant_message": result.assistant_message,
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
    }