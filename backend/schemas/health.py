from pydantic import BaseModel
from typing import Optional


class HealthStatus(BaseModel):
    healthy: bool
    message: Optional[str] = None


class ContainerStatus(BaseModel):
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    status: str
    healthy: bool = False
    message: Optional[str] = None


class ContainerStartRequest(BaseModel):
    image: str
    command: Optional[str] = None
    env: Optional[dict[str, str]] = None
    volumes: Optional[dict[str, str]] = None
    ports: Optional[dict[str, str]] = None
    gpu_id: Optional[str] = None
    cpu_limit: Optional[float] = None
    memory_limit: Optional[str] = None
    network_mode: str = "host"
    restart_policy: str = "on-failure"
    health_check: Optional[dict] = None


class ContainerLogsResponse(BaseModel):
    logs: str
