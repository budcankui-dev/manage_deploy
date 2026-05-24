from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from enums import ConversationStatus, MessageRole, ParseStatus, RoutingRequestStatus


class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8192)


class IntentDraftUpdate(BaseModel):
    task_type: Optional[str] = None
    modality: Optional[str] = None
    data_profile: Optional[dict[str, Any]] = None
    business_objective: Optional[dict[str, Any]] = None
    runtime_plan: Optional[dict[str, Any]] = None
    resource_requirement: Optional[dict[str, Any]] = None


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime


class IntentDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    version: int
    task_type: Optional[str] = None
    modality: Optional[str] = None
    data_profile: Optional[dict[str, Any]] = None
    business_objective: Optional[dict[str, Any]] = None
    runtime_plan: Optional[dict[str, Any]] = None
    resource_requirement: Optional[dict[str, Any]] = None
    validation_errors: Optional[list[str]] = None
    parse_status: ParseStatus
    created_at: datetime


class RoutingRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    intent_draft_id: str
    strategy: str
    status: RoutingRequestStatus
    placements: Optional[dict[str, str]] = None
    estimated_metric: Optional[dict[str, Any]] = None
    external_routing_id: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    status: ConversationStatus
    title: Optional[str] = None
    materialized_order_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)
    latest_draft: Optional[IntentDraftResponse] = None
    latest_routing_request: Optional[RoutingRequestResponse] = None


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: ConversationStatus
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class RoutingRequestCreate(BaseModel):
    conversation_id: str
    strategy: str = "resource_guarantee"


class RoutingResultCallback(BaseModel):
    status: RoutingRequestStatus
    strategy: Optional[str] = None
    placements: Optional[dict[str, str]] = None
    estimated_metric: Optional[dict[str, Any]] = None
    external_routing_id: Optional[str] = None
    error_message: Optional[str] = None


class ConversationSubmitResponse(BaseModel):
    conversation_id: str
    order_id: str
    instance_id: str
    task_type: str
    status: str
