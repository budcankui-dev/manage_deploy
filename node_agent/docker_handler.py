import docker
from typing import Optional
import logging
from collections import defaultdict
import re

from docker.types import DeviceRequest

logger = logging.getLogger(__name__)
MANAGED_CONTAINER_PATTERN = re.compile(r"^[0-9a-f-]{36}_[0-9a-f-]{36}$")


class DockerHandler:
    def __init__(self, socket_path: str = "unix:///var/run/docker.sock"):
        self.client = docker.DockerClient(base_url=socket_path)

    def get_container(self, container_name: str) -> Optional[docker.models.containers.Container]:
        try:
            for container in self.client.containers.list(all=True):
                if container.name == container_name:
                    return container
            return None
        except docker.errors.APIError as e:
            logger.error(f"Error getting container {container_name}: {e}")
            return None

    def start_container(
        self,
        container_name: str,
        image: str,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        volumes: Optional[dict] = None,
        ports: Optional[dict] = None,
        gpu_id: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        memory_limit: Optional[str] = None,
        network_mode: str = "host",
        restart_policy: str = "on-failure",
    ) -> tuple[bool, Optional[str], Optional[str]]:
        try:
            existing = self.get_container(container_name)
            if existing:
                existing.reload()
                if existing.status == "running":
                    return True, existing.id, None

                # Recreate non-running containers so updated runtime parameters
                # are applied on the next start instead of reusing stale config.
                existing.remove(force=True)

            env_list = [f"{k}={v}" for k, v in (env or {}).items()]

            binds = None
            if volumes:
                binds = {v: {"bind": k} for k, v in volumes.items()}

            port_bindings = None
            if ports:
                port_bindings = {}
                for container_port, host_port in ports.items():
                    port_bindings[f"{container_port}/tcp"] = host_port

            device_requests = None
            if gpu_id:
                device_requests = [
                    DeviceRequest(
                        device_ids=[gpu_id],
                        capabilities=[["gpu"]],
                    )
                ]

            nano_cpus = None
            if cpu_limit and cpu_limit > 0:
                nano_cpus = int(cpu_limit * 1_000_000_000)

            self.client.containers.run(
                image,
                name=container_name,
                command=command,
                environment=env_list,
                volumes=binds,
                ports=port_bindings,
                device_requests=device_requests,
                nano_cpus=nano_cpus,
                mem_limit=memory_limit or None,
                network_mode=network_mode,
                restart_policy={"Name": restart_policy},
                detach=True,
            )

            container = self.get_container(container_name)
            if container:
                return True, container.id, None
            return False, None, "Container not found after start"
        except docker.errors.ImageNotFound:
            return False, None, f"Image not found: {image}"
        except docker.errors.APIError as e:
            return False, None, str(e)

    def stop_container(self, container_name: str) -> tuple[bool, Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return True, None

            container.reload()

            if container.status in {"running", "restarting", "paused"}:
                try:
                    container.stop(timeout=30)
                except docker.errors.APIError:
                    container.kill()
                return True, None

            return True, None
        except docker.errors.APIError as e:
            return False, str(e)

    def remove_container(self, container_name: str) -> tuple[bool, Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return True, None

            container.reload()
            if container.status in {"running", "restarting", "paused"}:
                try:
                    container.stop(timeout=30)
                except docker.errors.APIError:
                    container.kill()

            container.remove(force=True)
            return True, None
        except docker.errors.APIError as e:
            return False, str(e)

    def find_port_binding_conflicts(
        self,
        ports: Optional[dict[str, str]],
        exclude_container_name: Optional[str] = None,
        network_mode: str = "bridge",
    ) -> tuple[list[str], list[str]]:
        conflicts: list[str] = []
        warnings: list[str] = []

        if network_mode == "host":
            warnings.append("host 网络模式下无法静态预检容器内部实际监听端口，请避免同节点部署会占用相同业务端口的镜像。")

        if not ports:
            return conflicts, warnings

        requested_host_ports = {str(host_port).strip() for host_port in ports.values() if str(host_port).strip()}
        if not requested_host_ports:
            return conflicts, warnings

        current_bindings: dict[str, list[str]] = defaultdict(list)
        try:
            for container in self.client.containers.list(all=True):
                if exclude_container_name and container.name == exclude_container_name:
                    continue
                try:
                    container.reload()
                    bindings = (container.attrs.get("HostConfig") or {}).get("PortBindings") or {}
                    for host_bindings in bindings.values():
                        for host_binding in host_bindings or []:
                            host_port = str(host_binding.get("HostPort") or "").strip()
                            if host_port:
                                current_bindings[host_port].append(container.name)
                except docker.errors.APIError:
                    continue
        except docker.errors.APIError as e:
            return [f"无法读取当前 Docker 端口绑定: {e}"], warnings

        for host_port in sorted(requested_host_ports):
            owners = current_bindings.get(host_port, [])
            if owners:
                conflicts.append(f"宿主机端口 {host_port} 已被容器占用: {', '.join(owners)}")

        return conflicts, warnings

    def list_managed_containers(self) -> list[dict]:
        items: list[dict] = []
        try:
            for container in self.client.containers.list(all=True):
                if not MANAGED_CONTAINER_PATTERN.match(container.name):
                    continue
                try:
                    container.reload()
                except docker.errors.APIError:
                    pass
                items.append(
                    {
                        "container_id": container.id,
                        "container_name": container.name,
                        "status": container.status,
                        "image": container.image.tags[0] if container.image.tags else container.image.short_id,
                        "ports": container.ports,
                    }
                )
        except docker.errors.APIError as e:
            logger.error(f"Error listing managed containers: {e}")
            raise
        return items

    def get_container_status(self, container_name: str) -> tuple[str, Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return "not_found", None
            return container.status, container.id
        except docker.errors.APIError as e:
            return "error", str(e)

    def get_container_logs(
        self, container_name: str, tail: int = 100
    ) -> tuple[Optional[str], Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return None, "Container not found"

            logs = container.logs(tail=tail, timestamps=True).decode("utf-8")
            return logs, None
        except docker.errors.APIError as e:
            return None, str(e)

    def is_port_open(self, container_name: str, port: int) -> bool:
        try:
            container = self.get_container(container_name)
            if not container or container.status != "running":
                return False

            container_port = f"{port}/tcp"
            ports = container.ports.get(container_port, [])
            return len(ports) > 0
        except Exception:
            return False

    def container_has_keyword(
        self, container_name: str, keyword: str, since: int = 60
    ) -> bool:
        try:
            container = self.get_container(container_name)
            if not container or container.status != "running":
                return False

            logs = container.logs(
                since=since, stdout=True, stderr=True
            ).decode("utf-8")
            return keyword in logs
        except Exception:
            return False

    def is_container_running(self, check_container_name: str) -> bool:
        try:
            for container in self.client.containers.list():
                if container.name == check_container_name and container.status == "running":
                    return True
            return False
        except docker.errors.APIError:
            return False
