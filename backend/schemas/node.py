from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class NodeBase(BaseModel):
    hostname: str
    agent_address: str
    management_ip: str
    business_ip: str


class NodeCreate(NodeBase):
    pass


class NodeUpdate(BaseModel):
    hostname: Optional[str] = None
    agent_address: Optional[str] = None
    management_ip: Optional[str] = None
    business_ip: Optional[str] = None


class NodeResponse(NodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class NodeSimple(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hostname: str
    agent_address: str
    management_ip: str
    business_ip: str


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
