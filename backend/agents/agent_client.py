import logging
from typing import Optional

import httpx

from config import settings
from schemas import ContainerStartRequest, ContainerStatus, ContainerLogsResponse

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self, timeout: int | None = None, agent_port: int = 8001):
        self.timeout = timeout if timeout is not None else settings.agent_request_timeout
        self.agent_port = agent_port

    def _build_url(self, endpoint: str, path: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return f"{endpoint.rstrip('/')}{path}"
        return f"http://{endpoint}:{self.agent_port}{path}"

    async def start_container(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
        container_name: str,
        request: ContainerStartRequest,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, f"/containers/{task_id}/{node_id}/start")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=request.model_dump())
                if response.status_code == 200:
                    return True, response.json()
                else:
                    return False, {
                        "error": response.text,
                        "status_code": response.status_code,
                    }
        except httpx.RequestError as e:
            return False, {"error": str(e), "status_code": None}

    async def stop_container(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, f"/containers/{task_id}/{node_id}/stop")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url)
                if response.status_code == 200:
                    return True, response.json()
                else:
                    return False, {
                        "error": response.text,
                        "status_code": response.status_code,
                    }
        except httpx.RequestError as e:
            return False, {"error": str(e), "status_code": None}

    async def delete_container(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, f"/containers/{task_id}/{node_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(url)
                if response.status_code == 200:
                    return True, response.json()
                else:
                    return False, {
                        "error": response.text,
                        "status_code": response.status_code,
                    }
        except httpx.RequestError as e:
            return False, {"error": str(e), "status_code": None}

    async def get_container_status(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
    ) -> tuple[str, bool, Optional[str]]:
        url = self._build_url(management_ip, f"/containers/{task_id}/{node_id}/status")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    return (
                        data.get("status", "unknown"),
                        data.get("healthy", False),
                        data.get("message"),
                    )
                else:
                    return "unknown", False, response.text
        except httpx.RequestError as e:
            return "unknown", False, str(e)

    async def get_container_logs(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        url = self._build_url(management_ip, f"/containers/{task_id}/{node_id}/logs")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("logs", ""), None
                else:
                    return None, response.text
        except httpx.RequestError as e:
            return None, str(e)

    async def check_port(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
        port: int,
    ) -> tuple[bool, Optional[str]]:
        url = self._build_url(management_ip, f"/health-check/port/{task_id}/{node_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"port": port})
                if response.status_code == 200:
                    data = response.json()
                    return data.get("healthy", False), data.get("message")
                else:
                    return False, response.text
        except httpx.RequestError as e:
            return False, str(e)

    async def check_http(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
        url: str,
    ) -> tuple[bool, Optional[str]]:
        check_url = self._build_url(management_ip, f"/health-check/http/{task_id}/{node_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(check_url, params={"url": url})
                if response.status_code == 200:
                    data = response.json()
                    return data.get("healthy", False), data.get("message")
                else:
                    return False, response.text
        except httpx.RequestError as e:
            return False, str(e)

    async def check_log(
        self,
        management_ip: str,
        task_id: str,
        node_id: str,
        keyword: str,
    ) -> tuple[bool, Optional[str]]:
        url = self._build_url(management_ip, f"/health-check/log/{task_id}/{node_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"keyword": keyword})
                if response.status_code == 200:
                    data = response.json()
                    return data.get("healthy", False), data.get("message")
                else:
                    return False, response.text
        except httpx.RequestError as e:
            return False, str(e)

    async def check_container_running(
        self,
        management_ip: str,
        task_id: str,
        container_name: str,
    ) -> tuple[bool, Optional[str]]:
        url = self._build_url(management_ip, f"/health-check/container/{task_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"container": container_name})
                if response.status_code == 200:
                    data = response.json()
                    return data.get("healthy", False), data.get("message")
                else:
                    return False, response.text
        except httpx.RequestError as e:
            return False, str(e)

    async def preflight_ports(
        self,
        management_ip: str,
        ports: Optional[dict[str, str]],
        network_mode: str,
        exclude_container_name: Optional[str] = None,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, "/preflight/ports")
        payload = {
            "ports": ports or {},
            "network_mode": network_mode,
            "exclude_container_name": exclude_container_name,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    return True, response.json()
                return False, {
                    "error": response.text,
                    "status_code": response.status_code,
                }
        except httpx.RequestError as e:
            return False, {"error": str(e), "status_code": None}

    async def list_managed_containers(
        self,
        management_ip: str,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, "/containers/managed")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return True, {"containers": response.json()}
                return False, {"error": response.text}
        except httpx.RequestError as e:
            return False, {"error": str(e)}

    async def delete_container_by_name(
        self,
        management_ip: str,
        container_name: str,
    ) -> tuple[bool, dict]:
        url = self._build_url(management_ip, f"/managed-containers/{container_name}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(url)
                if response.status_code == 200:
                    return True, response.json()
                return False, {"error": response.text}
        except httpx.RequestError as e:
            return False, {"error": str(e)}
