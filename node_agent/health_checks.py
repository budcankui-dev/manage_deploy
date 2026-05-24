import socket
import httpx
from typing import Optional
from docker_handler import DockerHandler


class HealthCheckError(Exception):
    pass


async def check_port(handler: DockerHandler, container_name: str, port: int) -> tuple[bool, Optional[str]]:
    try:
        container = handler.get_container(container_name)
        if not container:
            return False, "Container not found"
        if container.status != "running":
            return False, f"Container status: {container.status}"

        is_open = handler.is_port_open(container_name, port)
        if is_open:
            return True, None
        return False, f"Port {port} not open"
    except Exception as e:
        return False, str(e)


async def check_http(
    handler: DockerHandler, container_name: str, url: str
) -> tuple[bool, Optional[str]]:
    try:
        container = handler.get_container(container_name)
        if not container:
            return False, "Container not found"
        if container.status != "running":
            return False, f"Container status: {container.status}"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            if 200 <= response.status_code < 300:
                return True, None
            return False, f"HTTP {response.status_code}"
    except httpx.RequestError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


async def check_log(
    handler: DockerHandler, container_name: str, keyword: str
) -> tuple[bool, Optional[str]]:
    try:
        container = handler.get_container(container_name)
        if not container:
            return False, "Container not found"
        if container.status != "running":
            return False, f"Container status: {container.status}"

        found = handler.container_has_keyword(container_name, keyword)
        if found:
            return True, None
        return False, f"Keyword '{keyword}' not found in logs"
    except Exception as e:
        return False, str(e)


async def check_container(
    handler: DockerHandler, task_id: str, container_name: str
) -> tuple[bool, Optional[str]]:
    try:
        full_name = f"{task_id}_{container_name}"
        is_running = handler.is_container_running(full_name)
        if is_running:
            return True, None
        return False, f"Container {full_name} not running"
    except Exception as e:
        return False, str(e)