from typing import Optional, Any

from pydantic import AliasChoices, BaseModel, Field, ConfigDict, field_validator, model_validator
from datetime import datetime, timedelta, UTC
from enums import TaskStatus, NodeStatus, HealthCheckType, DeploymentMode, OrderStatus, UserRole
from schemas.runtime import MacroDefSpec, PortDefSpec


def _apply_scheduled_defaults(values: dict) -> dict:
    """SCHEDULED 模式默认填充 start_time=now、end_time=start+settings.default_scheduled_duration_hours。"""
    if not isinstance(values, dict):
        return values
    mode = values.get("deployment_mode")
    if mode is None:
        mode = DeploymentMode.IMMEDIATE
    if isinstance(mode, str):
        try:
            mode = DeploymentMode(mode)
        except ValueError:
            return values
    if mode != DeploymentMode.SCHEDULED:
        return values
    from config import settings  # 延迟导入避免循环

    start = values.get("scheduled_start_time") or datetime.now(UTC)
    values["scheduled_start_time"] = start
    if values.get("scheduled_end_time") is None:
        hours = max(1, int(settings.default_scheduled_duration_hours or 2))
        values["scheduled_end_time"] = start + timedelta(hours=hours)
    return values


class HealthCheckConfig(BaseModel):
    type: HealthCheckType
    timeout: int = 30
    interval: int = 5
    retry: int = 3
    url: Optional[str] = None
    port: Optional[int] = None
    keyword: Optional[str] = None
    container: Optional[str] = None


class TaskTemplateNodeBase(BaseModel):
    name: str
    image: str
    command: Optional[str] = None
    env: Optional[dict[str, str]] = None
    volumes: Optional[dict[str, Any]] = None
    volume_mounts: Optional[list[dict[str, Any]]] = None
    ports: Optional[dict[str, str]] = None
    port_defs: Optional[list[PortDefSpec]] = None
    gpu_id: Optional[str] = None
    cpu_limit: Optional[float] = None
    cpu_reservation: Optional[float] = None
    cpu_shares: Optional[int] = None
    cpuset_cpus: Optional[str] = None
    cpu_quota: Optional[int] = None
    cpu_period: Optional[int] = None
    memory_limit: Optional[str] = None
    memory_reservation: Optional[str] = None
    memory_swap_limit: Optional[str] = None
    network_mode: str = "host"
    restart_policy: str = "on-failure"
    health_check: Optional[dict[str, Any]] = None
    node_id: str


class TaskTemplateNodeCreate(TaskTemplateNodeBase):
    client_id: Optional[str] = None


class TaskTemplateNodeResponse(TaskTemplateNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str


class TaskTemplateEdgeCreate(BaseModel):
    from_node_id: str
    to_node_id: str


class TaskTemplateEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str
    from_node_id: str
    to_node_id: str


class TaskTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    macro_defs: Optional[list[MacroDefSpec]] = None


class TaskTemplateCreate(TaskTemplateBase):
    nodes: list[TaskTemplateNodeCreate]
    edges: list[TaskTemplateEdgeCreate]


class TaskTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    macro_defs: Optional[list[MacroDefSpec]] = None
    nodes: Optional[list[TaskTemplateNodeCreate]] = None
    edges: Optional[list[TaskTemplateEdgeCreate]] = None


class TaskTemplateResponse(TaskTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    nodes: list[TaskTemplateNodeResponse] = Field(default_factory=list)
    edges: list[TaskTemplateEdgeResponse] = Field(default_factory=list)


class TaskInstanceNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    template_node_id: str
    name: str
    image: str
    command: Optional[str] = None
    env: Optional[dict] = None
    volumes: Optional[dict] = None
    volume_mounts: Optional[list] = None
    ports: Optional[dict] = None
    port_defs: Optional[list] = None
    port_values: Optional[dict] = None
    gpu_id: Optional[str] = None
    cpu_limit: Optional[float] = None
    cpu_reservation: Optional[float] = None
    cpu_shares: Optional[int] = None
    cpuset_cpus: Optional[str] = None
    cpu_quota: Optional[int] = None
    cpu_period: Optional[int] = None
    memory_limit: Optional[str] = None
    memory_reservation: Optional[str] = None
    memory_swap_limit: Optional[str] = None
    network_mode: str
    restart_policy: str
    health_check: Optional[dict] = None
    node_id: str
    status: NodeStatus
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    error_message: Optional[str] = None
    business_address: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskInstanceBase(BaseModel):
    name: str


class TaskInstanceCreate(TaskInstanceBase):
    template_id: str
    deployment_mode: DeploymentMode = DeploymentMode.IMMEDIATE
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    auto_start: bool = False
    keep_after_stop: bool = False
    macro_values: Optional[dict[str, str]] = None
    node_overrides: list["TaskInstanceNodeOverride"] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _fill_scheduled_defaults(cls, values):
        return _apply_scheduled_defaults(values)


class TaskInstanceUpdate(BaseModel):
    name: Optional[str] = None
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: Optional[bool] = None
    macro_values: Optional[dict[str, str]] = None
    node_overrides: list["TaskInstanceNodeOverride"] = Field(default_factory=list)


class TaskInstanceSchedule(BaseModel):
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: Optional[bool] = None


class TaskInstanceResponse(TaskInstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str
    macro_values: Optional[dict] = None
    status: TaskStatus
    deployment_mode: Optional[DeploymentMode] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: bool = False
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    nodes: list[TaskInstanceNodeResponse] = Field(default_factory=list)


class TaskInstanceSimple(TaskInstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str
    status: TaskStatus
    deployment_mode: Optional[DeploymentMode] = None
    start_time: Optional[datetime] = None
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: bool = False
    error_message: Optional[str] = None
    created_at: datetime
    nodes: list["TaskInstanceNodeResponse"] = Field(default_factory=list)


class TaskEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    node_id: Optional[str] = None
    event_type: str
    old_status: Optional[str] = None
    new_status: str
    message: Optional[str] = None
    created_at: datetime


class BatchOperationRequest(BaseModel):
    order_ids: list[str] = Field(default_factory=list, description="要删除的工单 ID 列表")
    instance_ids: list[str] = Field(default_factory=list, description="废弃字段，请使用 order_ids（兼容旧调用方）")

    @field_validator('order_ids', mode='before')
    @classmethod
    def promote_instance_ids_to_order_ids(cls, v, info):
        # 如果 order_ids 为空但 instance_ids 有值，沿用 instance_ids（兼容旧调用方）
        values = info.data
        if not v and values.get('instance_ids'):
            return values['instance_ids']
        return v if v is not None else []


class BatchOperationResponse(BaseModel):
    succeeded: list[str]
    failed: dict[str, str]


class TaskInstanceNodeOverride(BaseModel):
    template_node_id: Optional[str] = None
    template_node_name: Optional[str] = None
    name: Optional[str] = None
    image: Optional[str] = None
    command: Optional[str] = None
    env: Optional[dict[str, str]] = None
    volumes: Optional[dict[str, Any]] = None
    volume_mounts: Optional[list[dict[str, Any]]] = None
    ports: Optional[dict[str, str]] = None
    port_values: Optional[dict[str, int]] = None
    gpu_id: Optional[str] = None
    cpu_limit: Optional[float] = None
    cpu_reservation: Optional[float] = None
    cpu_shares: Optional[int] = None
    cpuset_cpus: Optional[str] = None
    cpu_quota: Optional[int] = None
    cpu_period: Optional[int] = None
    memory_limit: Optional[str] = None
    memory_reservation: Optional[str] = None
    memory_swap_limit: Optional[str] = None
    network_mode: Optional[str] = None
    restart_policy: Optional[str] = None
    health_check: Optional[dict[str, Any]] = None
    node_id: Optional[str] = None


class InstancePreflightIssue(BaseModel):
    template_node_id: Optional[str] = None
    template_node_name: Optional[str] = None
    node_id: Optional[str] = None
    node_hostname: Optional[str] = None
    level: str
    message: str


class InstancePreflightResponse(BaseModel):
    ok: bool
    conflicts: list[InstancePreflightIssue] = Field(default_factory=list)
    warnings: list[InstancePreflightIssue] = Field(default_factory=list)


class TaskOrderCreate(BaseModel):
    external_task_id: Optional[str] = None
    template_id: str
    name: str
    description: Optional[str] = None
    deployment_mode: DeploymentMode = DeploymentMode.IMMEDIATE
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    auto_start: bool = False
    keep_after_stop: bool = False
    node_overrides: list[TaskInstanceNodeOverride] = Field(default_factory=list)
    extra: Optional[dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def _fill_scheduled_defaults(cls, values):
        return _apply_scheduled_defaults(values)


class TaskOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_task_id: Optional[str] = None
    template_id: str
    name: str
    description: Optional[str] = None
    deployment_mode: DeploymentMode
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    auto_start: bool
    keep_after_stop: bool = False
    runtime_config: Optional[dict] = None
    status: OrderStatus
    routing_status: Optional[str] = None
    source_name: Optional[str] = None
    destination_name: Optional[str] = None
    business_start_time: Optional[datetime] = None
    business_end_time: Optional[datetime] = None
    routing_input_dag: Optional[dict] = None
    materialized_instance_id: Optional[str] = None
    instance_exists: Optional[bool] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    task_type: Optional[str] = None
    routing_policy: Optional[str] = None


class TaskMetricReport(BaseModel):
    node_instance_id: Optional[str] = None
    metric_key: str
    metric_value: float
    unit: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    reported_at: Optional[datetime] = None


class TaskMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    template_id: str
    node_instance_id: Optional[str] = None
    metric_key: str
    metric_value: float
    unit: Optional[str] = None
    tags: Optional[dict] = None
    reported_at: datetime


class TemplateMetricSummary(BaseModel):
    template_id: str
    metric_key: str
    count: int
    avg: float
    min: float
    max: float


class BusinessObjective(BaseModel):
    metric_key: str
    operator: str = ">="
    target_value: float
    unit: Optional[str] = None


class RoutingResult(BaseModel):
    strategy: str = Field(
        default="resource_guarantee",
        validation_alias=AliasChoices("strategy", "routing_policy"),
    )
    placements: dict[str, str]
    estimated_metric: Optional[dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True)

    @property
    def routing_policy(self) -> str:
        return self.strategy


class BusinessTaskCreate(BaseModel):
    external_task_id: str
    task_type: str
    modality: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    data_profile: dict[str, Any]
    business_objective: BusinessObjective
    runtime_plan: dict[str, Any] = Field(default_factory=dict)
    resource_requirement: dict[str, Any] = Field(default_factory=dict)
    routing_result: RoutingResult
    result_storage: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: bool = False


class BusinessTaskResponse(BaseModel):
    order_id: str
    instance_id: str
    task_type: str
    status: str


class BusinessTaskListItem(BaseModel):
    order_id: str
    external_task_id: Optional[str] = None
    name: str
    task_type: Optional[str] = None
    modality: Optional[str] = None
    routing_policy: Optional[str] = None
    order_status: OrderStatus
    instance_id: Optional[str] = None
    instance_exists: Optional[bool] = None
    deployment_status: Optional[TaskStatus] = None
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    keep_after_stop: bool = False
    metric_key: Optional[str] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None
    business_success: Optional[bool] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class BusinessTaskListResponse(BaseModel):
    items: list[BusinessTaskListItem]
    total: int
    page: int
    page_size: int


class TaskOrderInstanceSummary(BaseModel):
    id: str
    status: TaskStatus
    node_count: int
    error_message: Optional[str] = None
    port_access_urls: Optional[dict[str, str]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskOrderEvaluationSummary(BaseModel):
    metric_key: str
    actual_value: float
    target_value: float
    unit: Optional[str] = None
    business_success: bool
    failure_reason: Optional[str] = None
    estimated_value: Optional[float] = None
    estimation_error_ratio: Optional[float] = None
    result_metadata: Optional[dict[str, Any]] = None


class TaskOrderDetailResponse(TaskOrderResponse):
    business_task: Optional[dict[str, Any]] = None
    routing_result: Optional[dict[str, Any]] = None
    instance: Optional[TaskOrderInstanceSummary] = None
    evaluation: Optional[TaskOrderEvaluationSummary] = None


class BusinessTemplateCatalogCreate(BaseModel):
    task_type: str
    modality: Optional[str] = None
    template_id: str
    source_node_name: str = "source"
    compute_node_name: str = "compute"
    sink_node_name: str = "sink"
    description: Optional[str] = None


class BusinessTemplateCatalogResponse(BusinessTemplateCatalogCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class BusinessObjectiveEvaluationResult(BaseModel):
    task_type: Optional[str] = None
    metric_key: str
    actual_value: float
    target_value: float
    operator: str
    unit: Optional[str] = None
    business_success: bool
    failure_reason: Optional[str] = None
    estimated_value: Optional[float] = None
    estimation_error_ratio: Optional[float] = None
    object_uris: list[str] = Field(default_factory=list)


class BusinessObjectiveEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    task_type: str
    routing_strategy: Optional[str] = None
    metric_key: str
    actual_value: float
    target_value: float
    operator: str
    unit: Optional[str] = None
    business_success: bool
    failure_reason: Optional[str] = None
    estimated_value: Optional[float] = None
    estimation_error_ratio: Optional[float] = None
    object_uris: Optional[dict] = None
    created_at: datetime


class TaskResultObjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    name: str
    uri: str
    content_type: Optional[str] = None
    created_at: datetime


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.USER


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: UserRole
    created_at: datetime


TaskInstanceCreate.model_rebuild()
