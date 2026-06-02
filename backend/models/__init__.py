import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, String, DateTime, func, ForeignKey
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from enums import TaskStatus, NodeStatus, DeploymentMode, OrderStatus, UserRole, ConversationStatus, ParseStatus, MessageRole, RoutingRequestStatus, RoutingStatus, NodeKind


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    agent_address: Mapped[str] = mapped_column(String(512), nullable=False)
    management_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    business_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    business_ipv6: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    node_kind: Mapped[str] = mapped_column(String(50), default=NodeKind.WORKER)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_schedulable: Mapped[bool] = mapped_column(default=True, server_default="1")
    is_routable: Mapped[bool] = mapped_column(default=True, server_default="1")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    task_instance_nodes: Mapped[list["TaskInstanceNode"]] = relationship(
        "TaskInstanceNode", back_populates="node"
    )


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    macro_defs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    instances: Mapped[list["TaskInstance"]] = relationship(
        "TaskInstance", back_populates="template"
    )
    nodes: Mapped[list["TaskTemplateNode"]] = relationship(
        "TaskTemplateNode", back_populates="template", cascade="all, delete-orphan"
    )
    edges: Mapped[list["TaskTemplateEdge"]] = relationship(
        "TaskTemplateEdge", cascade="all, delete-orphan"
    )


class TaskTemplateNode(Base):
    __tablename__ = "task_template_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_templates.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    command: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    env: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    volumes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    volume_mounts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ports: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    port_defs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    gpu_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cpu_limit: Mapped[Optional[float]] = mapped_column(nullable=True)
    cpu_reservation: Mapped[Optional[float]] = mapped_column(nullable=True)
    cpu_shares: Mapped[Optional[int]] = mapped_column(nullable=True)
    cpuset_cpus: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cpu_quota: Mapped[Optional[int]] = mapped_column(nullable=True)
    cpu_period: Mapped[Optional[int]] = mapped_column(nullable=True)
    memory_limit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_reservation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_swap_limit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    network_mode: Mapped[str] = mapped_column(String(50), default="host")
    restart_policy: Mapped[str] = mapped_column(String(50), default="on-failure")
    health_check: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id"), nullable=False)

    template: Mapped["TaskTemplate"] = relationship(
        "TaskTemplate", back_populates="nodes"
    )
    outgoing_edges: Mapped[list["TaskTemplateEdge"]] = relationship(
        "TaskTemplateEdge",
        foreign_keys="TaskTemplateEdge.from_node_id",
        back_populates="from_node",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["TaskTemplateEdge"]] = relationship(
        "TaskTemplateEdge",
        foreign_keys="TaskTemplateEdge.to_node_id",
        back_populates="to_node",
        cascade="all, delete-orphan",
    )


class TaskTemplateEdge(Base):
    __tablename__ = "task_template_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_templates.id"), nullable=False)
    from_node_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_template_nodes.id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_template_nodes.id"), nullable=False)

    from_node: Mapped["TaskTemplateNode"] = relationship(
        "TaskTemplateNode",
        foreign_keys=[from_node_id],
        back_populates="outgoing_edges",
    )
    to_node: Mapped["TaskTemplateNode"] = relationship(
        "TaskTemplateNode",
        foreign_keys=[to_node_id],
        back_populates="incoming_edges",
    )


class TaskInstance(Base):
    __tablename__ = "task_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_templates.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(String(50), default=TaskStatus.PENDING)
    deployment_mode: Mapped[DeploymentMode] = mapped_column(String(50), default=DeploymentMode.IMMEDIATE)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scheduled_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scheduled_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("task_orders.id"), nullable=True)
    macro_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    keep_after_stop: Mapped[bool] = mapped_column(default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    template: Mapped["TaskTemplate"] = relationship("TaskTemplate", back_populates="instances")
    nodes: Mapped[list["TaskInstanceNode"]] = relationship(
        "TaskInstanceNode", back_populates="instance", cascade="all, delete-orphan"
    )
    edges: Mapped[list["TaskInstanceEdge"]] = relationship(
        "TaskInstanceEdge", cascade="all, delete-orphan"
    )


class TaskInstanceNode(Base):
    __tablename__ = "task_instance_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_instances.id"), nullable=False)
    template_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    command: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    env: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    volumes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    volume_mounts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ports: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    port_defs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    port_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    gpu_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cpu_limit: Mapped[Optional[float]] = mapped_column(nullable=True)
    cpu_reservation: Mapped[Optional[float]] = mapped_column(nullable=True)
    cpu_shares: Mapped[Optional[int]] = mapped_column(nullable=True)
    cpuset_cpus: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cpu_quota: Mapped[Optional[int]] = mapped_column(nullable=True)
    cpu_period: Mapped[Optional[int]] = mapped_column(nullable=True)
    memory_limit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_reservation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_swap_limit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    network_mode: Mapped[str] = mapped_column(String(50), default="host")
    restart_policy: Mapped[str] = mapped_column(String(50), default="on-failure")
    health_check: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id"), nullable=False)
    status: Mapped[NodeStatus] = mapped_column(String(50), default=NodeStatus.PENDING)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    container_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    instance: Mapped["TaskInstance"] = relationship("TaskInstance", back_populates="nodes")
    node: Mapped["Node"] = relationship("Node", back_populates="task_instance_nodes")


class TaskInstanceEdge(Base):
    __tablename__ = "task_instance_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_instances.id"), nullable=False)
    from_node_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_instance_nodes.id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_instance_nodes.id"), nullable=False)


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TaskOrder(Base):
    __tablename__ = "task_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    external_task_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=True)
    intent_draft_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("intent_drafts.id"), nullable=True)
    routing_request_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("routing_requests.id"), nullable=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_templates.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    destination_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    business_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deployment_mode: Mapped[DeploymentMode] = mapped_column(String(50), default=DeploymentMode.IMMEDIATE)
    scheduled_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scheduled_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    auto_start: Mapped[bool] = mapped_column(default=False)
    keep_after_stop: Mapped[bool] = mapped_column(default=False, server_default="0")
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    runtime_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(String(50), default=OrderStatus.PENDING)
    routing_status: Mapped[str] = mapped_column(String(50), default=RoutingStatus.NOT_REQUIRED)
    routing_input_dag: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    materialized_instance_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )


class TaskMetric(Base):
    __tablename__ = "task_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_instance_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    metric_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class BusinessTemplateCatalog(Base):
    __tablename__ = "business_template_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_type: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    modality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_templates.id"), nullable=False)
    source_node_name: Mapped[str] = mapped_column(String(255), default="source")
    compute_node_name: Mapped[str] = mapped_column(String(255), default="compute")
    sink_node_name: Mapped[str] = mapped_column(String(255), default="sink")
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )


class BusinessObjectiveEvaluation(Base):
    __tablename__ = "business_objective_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    routing_strategy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    metric_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    actual_value: Mapped[float] = mapped_column(nullable=False)
    target_value: Mapped[float] = mapped_column(nullable=False)
    operator: Mapped[str] = mapped_column(String(8), default="<=")
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    business_success: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    estimated_value: Mapped[Optional[float]] = mapped_column(nullable=True)
    estimation_error_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    object_uris: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class TaskResultObject(Base):
    __tablename__ = "task_result_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class UserUploadedObject(Base):
    __tablename__ = "user_uploaded_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(50), default=UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="user"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[ConversationStatus] = mapped_column(String(50), default=ConversationStatus.DRAFTING)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    materialized_order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("task_orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage", back_populates="conversation", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["IntentDraft"]] = relationship(
        "IntentDraft", back_populates="conversation", cascade="all, delete-orphan"
    )
    routing_requests: Mapped[list["RoutingRequest"]] = relationship(
        "RoutingRequest", back_populates="conversation", cascade="all, delete-orphan"
    )

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def workflow_trace(self) -> dict:
        return {"engine": "rule_parser"}


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[MessageRole] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(String(8192), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class IntentDraft(Base):
    __tablename__ = "intent_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(default=1)
    task_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    destination_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    business_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    data_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    business_objective: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    runtime_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resource_requirement: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    parse_status: Mapped[ParseStatus] = mapped_column(String(50), default=ParseStatus.INCOMPLETE)
    parser_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_llm_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    normalized_intent: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="drafts")


class RoutingRequest(Base):
    __tablename__ = "routing_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("task_orders.id"), nullable=True, index=True)
    intent_draft_id: Mapped[str] = mapped_column(String(36), ForeignKey("intent_drafts.id"), nullable=False)
    strategy: Mapped[str] = mapped_column(String(255), default="resource_guarantee")
    status: Mapped[RoutingRequestStatus] = mapped_column(String(50), default=RoutingRequestStatus.PENDING)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    destination_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    business_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    input_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    placements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    estimated_metric: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    requested_strategies: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selected_strategy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_routing_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="routing_requests")


class NodeBaseline(Base):
    """节点基线性能表：每个节点 + task_type + metric_key 的基准值（3次取中位数）。"""
    __tablename__ = "node_baselines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_value: Mapped[float] = mapped_column(nullable=False)
    operator: Mapped[str] = mapped_column(String(8), default=">=")
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    run_count: Mapped[int] = mapped_column(default=3)
    raw_values: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
