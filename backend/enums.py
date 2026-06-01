from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    EXPIRED = "expired"


class NodeStatus(str, Enum):
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class HealthCheckType(str, Enum):
    PORT = "port"
    HTTP = "http"
    LOG = "log"
    CONTAINER = "container"


class DeploymentMode(str, Enum):
    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"


class OrderStatus(str, Enum):
    PENDING = "pending"
    MATERIALIZED = "materialized"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ORPHANED = "orphaned"


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class ConversationStatus(str, Enum):
    DRAFTING = "drafting"
    AWAITING_ROUTING = "awaiting_routing"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParseStatus(str, Enum):
    INCOMPLETE = "incomplete"
    VALID = "valid"
    REJECTED = "rejected"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class RoutingRequestStatus(str, Enum):
    PENDING = "pending"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RoutingStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeKind(str, Enum):
    WORKER = "worker"
    TERMINAL = "terminal"
    ROUTER = "router"
    SWITCH = "switch"
    STORAGE = "storage"
    UNKNOWN = "unknown"
