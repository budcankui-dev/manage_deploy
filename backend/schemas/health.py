from pydantic import BaseModel, Field
from typing import Any, Optional


class HealthStatus(BaseModel):
    healthy: bool
    message: Optional[str] = None


class ContainerStatus(BaseModel):
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    status: str
    healthy: bool = False
    message: Optional[str] = None


class VolumeMountPayload(BaseModel):
    target: str
    type: str = "bind"
    source: str = ""
    auto_create: bool = True
    read_only: bool = False


class ContainerStartRequest(BaseModel):
    image: str
    command: Optional[str] = None
    env: Optional[dict[str, str]] = None
    volumes: Optional[dict[str, Any]] = None
    volume_mounts: Optional[list[VolumeMountPayload]] = None
    ports: Optional[dict[str, str]] = None
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
    health_check: Optional[dict] = None


class ContainerLogsResponse(BaseModel):
    logs: str
