from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class NodeBase(BaseModel):
    hostname: str
    display_name: Optional[str] = None
    topology_node_id: Optional[str] = None
    topology_zone: Optional[str] = None
    agent_address: str
    management_ip: str
    business_ip: str
    business_ipv6: Optional[str] = None
    gpu_count: int = Field(default=0, ge=0)
    gpu_model: Optional[str] = None
    gpu_memory_mb: Optional[int] = Field(default=None, ge=0)
    cpu_model: Optional[str] = None
    cpu_cores: Optional[int] = Field(default=None, ge=0)
    memory_mb: Optional[int] = Field(default=None, ge=0)
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    resource_note: Optional[str] = None


class NodeCreate(NodeBase):
    node_kind: Optional[str] = None
    is_schedulable: bool = True
    is_routable: bool = True


class NodeUpdate(BaseModel):
    hostname: Optional[str] = None
    display_name: Optional[str] = None
    topology_node_id: Optional[str] = None
    topology_zone: Optional[str] = None
    agent_address: Optional[str] = None
    management_ip: Optional[str] = None
    business_ip: Optional[str] = None
    business_ipv6: Optional[str] = None
    gpu_count: Optional[int] = Field(default=None, ge=0)
    gpu_model: Optional[str] = None
    gpu_memory_mb: Optional[int] = Field(default=None, ge=0)
    cpu_model: Optional[str] = None
    cpu_cores: Optional[int] = Field(default=None, ge=0)
    memory_mb: Optional[int] = Field(default=None, ge=0)
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    resource_note: Optional[str] = None
    node_kind: Optional[str] = None
    is_schedulable: Optional[bool] = None
    is_routable: Optional[bool] = None


class NodeResponse(NodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_kind: Optional[str] = None
    display_name: Optional[str] = None
    topology_node_id: Optional[str] = None
    topology_zone: Optional[str] = None
    is_schedulable: bool = True
    is_routable: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


class NodeSimple(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hostname: str
    display_name: Optional[str] = None
    topology_node_id: Optional[str] = None
    topology_zone: Optional[str] = None
    agent_address: str
    management_ip: str
    business_ip: str
    business_ipv6: Optional[str] = None
    gpu_count: int = 0
    gpu_model: Optional[str] = None
    gpu_memory_mb: Optional[int] = None
    cpu_model: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_mb: Optional[int] = None
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    resource_note: Optional[str] = None
    node_kind: Optional[str] = None
    is_schedulable: bool = True
    is_routable: bool = True


class OrphanContainerResponse(BaseModel):
    container_id: str
    container_name: str
    status: str
    image: str
    ports: Optional[dict] = None
    reason: str


class OrphanCleanupRequest(BaseModel):
    container_names: list[str] = Field(default_factory=list)


class OrphanCleanupResponse(BaseModel):
    succeeded: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
