import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import settings
from docker_handler import DockerHandler
from health_checks import check_port, check_http, check_log, check_container

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

docker_handler = DockerHandler(settings.docker_socket, data_root=settings.agent_data_root)


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
    pull_policy: Optional[str] = None
    health_check: Optional[dict] = None


class ContainerStatusResponse(BaseModel):
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    status: str
    healthy: bool = False
    message: Optional[str] = None


class PortPreflightRequest(BaseModel):
    ports: Optional[dict[str, str]] = None
    network_mode: str = "bridge"
    exclude_container_name: Optional[str] = None


class PortsAvailableRequest(BaseModel):
    count: int = Field(ge=1, le=100)
    start: int = Field(default=18000, ge=1024, le=65535)
    end: int = Field(default=19999, ge=1024, le=65535)
    exclude: list[int] = Field(default_factory=list)
    network_mode: str = "host"


class ManagedContainerResponse(BaseModel):
    container_id: str
    container_name: str
    status: str
    image: str
    ports: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Node Agent starting on port {settings.agent_port}")
    yield
    logger.info("Node Agent shutting down")


app = FastAPI(
    title="Node Agent",
    description="Docker container control agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/containers/{task_id}/{node_id}/start")
async def start_container(
    task_id: str,
    node_id: str,
    request: ContainerStartRequest,
):
    container_name = f"{task_id}_{node_id}"

    success, container_id, error = docker_handler.start_container(
        container_name=container_name,
        task_id=task_id,
        node_id=node_id,
        image=request.image,
        command=request.command,
        env=request.env,
        volumes=request.volumes,
        volume_mounts=[m.model_dump() for m in request.volume_mounts] if request.volume_mounts else None,
        ports=request.ports,
        gpu_id=request.gpu_id,
        cpu_limit=request.cpu_limit,
        cpu_reservation=request.cpu_reservation,
        cpu_shares=request.cpu_shares,
        cpuset_cpus=request.cpuset_cpus,
        cpu_quota=request.cpu_quota,
        cpu_period=request.cpu_period,
        memory_limit=request.memory_limit,
        memory_reservation=request.memory_reservation,
        memory_swap_limit=request.memory_swap_limit,
        network_mode=request.network_mode,
        restart_policy=request.restart_policy,
        pull_policy=request.pull_policy,
    )

    if not success:
        raise HTTPException(status_code=500, detail=error)

    return {"container_id": container_id}


@app.post("/containers/{task_id}/{node_id}/stop")
async def stop_container(task_id: str, node_id: str):
    container_name = f"{task_id}_{node_id}"

    success, error = docker_handler.stop_container(container_name)

    if not success:
        raise HTTPException(status_code=500, detail=error)

    return {"message": "Container stopped"}


@app.delete("/containers/{task_id}/{node_id}")
async def delete_container(task_id: str, node_id: str):
    container_name = f"{task_id}_{node_id}"

    success, error = docker_handler.remove_container(container_name)

    if not success:
        raise HTTPException(status_code=500, detail=error)

    return {"message": "Container deleted"}


@app.get("/containers/{task_id}/{node_id}/status")
async def get_container_status(task_id: str, node_id: str):
    container_name = f"{task_id}_{node_id}"

    status, container_id = docker_handler.get_container_status(container_name)

    return ContainerStatusResponse(
        container_id=container_id,
        container_name=container_name,
        status=status,
        healthy=status == "running",
    )


@app.get("/containers/{task_id}/{node_id}/logs")
async def get_container_logs(task_id: str, node_id: str):
    container_name = f"{task_id}_{node_id}"

    logs, error = docker_handler.get_container_logs(container_name)

    if error:
        raise HTTPException(status_code=500, detail=error)

    return {"logs": logs}


@app.post("/preflight/ports")
async def preflight_ports(request: PortPreflightRequest):
    conflicts, warnings = docker_handler.find_port_binding_conflicts(
        ports=request.ports,
        exclude_container_name=request.exclude_container_name,
        network_mode=request.network_mode,
    )
    return {
        "ok": not conflicts,
        "conflicts": conflicts,
        "warnings": warnings,
    }


@app.post("/ports/available")
async def find_available_ports_endpoint(request: PortsAvailableRequest):
    """查找宿主机可用端口，供 Task Manager 自动分配使用。"""
    from port_utils import find_available_ports

    occupied = docker_handler.get_all_occupied_ports(network_mode=request.network_mode)
    ports = find_available_ports(
        count=request.count,
        start=request.start,
        end=request.end,
        exclude=request.exclude,
        occupied=occupied,
    )
    warnings = []
    if len(ports) < request.count:
        warnings.append(f"Only {len(ports)} available in range [{request.start}, {request.end}], requested {request.count}")
    return {
        "ports": ports,
        "range": {"start": request.start, "end": request.end},
        "count_requested": request.count,
        "count_found": len(ports),
        "warnings": warnings,
    }


@app.get("/containers/managed", response_model=list[ManagedContainerResponse])
async def list_managed_containers():
    return docker_handler.list_managed_containers()


@app.delete("/managed-containers/{container_name:path}")
async def delete_container_by_name(container_name: str):
    success, error = docker_handler.remove_container(container_name)
    if not success:
        raise HTTPException(status_code=500, detail=error)
    return {"message": "Container deleted"}


@app.get("/health-check/port/{task_id}/{node_id}")
async def health_check_port(task_id: str, node_id: str, port: int):
    container_name = f"{task_id}_{node_id}"

    healthy, message = await check_port(docker_handler, container_name, port)

    return {"healthy": healthy, "message": message}


@app.get("/health-check/http/{task_id}/{node_id}")
async def health_check_http(task_id: str, node_id: str, url: str):
    container_name = f"{task_id}_{node_id}"

    healthy, message = await check_http(docker_handler, container_name, url)

    return {"healthy": healthy, "message": message}


@app.get("/health-check/log/{task_id}/{node_id}")
async def health_check_log(task_id: str, node_id: str, keyword: str):
    container_name = f"{task_id}_{node_id}"

    healthy, message = await check_log(docker_handler, container_name, keyword)

    return {"healthy": healthy, "message": message}


@app.get("/health-check/container/{task_id}")
async def health_check_container(task_id: str, container: str):
    healthy, message = await check_container(docker_handler, task_id, container)

    return {"healthy": healthy, "message": message}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/resources")
async def get_host_resources():
    from runtime_resources import collect_host_resources

    return collect_host_resources()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.agent_port)
