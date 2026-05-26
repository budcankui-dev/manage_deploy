import docker
from typing import Any, Optional
import logging
from collections import defaultdict
import re

logger = logging.getLogger(__name__)
MANAGED_CONTAINER_PATTERN = re.compile(r"^[0-9a-f-]{36}_[0-9a-f-]{36}$")


class DockerHandler:
    def __init__(self, socket_path: str = "unix:///var/run/docker.sock", data_root: str = "/var/lib/manage_deploy/tasks"):
        self.client = docker.DockerClient(base_url=socket_path)
        self.data_root = data_root

    def get_container(self, container_name: str) -> Optional[docker.models.containers.Container]:
        try:
            return self.client.containers.get(container_name)
        except docker.errors.NotFound:
            return None
        except docker.errors.APIError as e:
            logger.error(f"Error getting container {container_name}: {e}")
            return None

    @staticmethod
    def _is_managed_container(container: docker.models.containers.Container) -> bool:
        """检查容器是否属于本系统（通过 manage_deploy.* label 判断）。"""
        try:
            labels = (container.attrs.get("Config") or {}).get("Labels") or {}
            return any(k.startswith("manage_deploy.") for k in labels)
        except Exception:
            return False

    def start_container(
        self,
        container_name: str,
        task_id: str,
        node_id: str,
        image: str,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        volumes: Optional[dict] = None,
        volume_mounts: Optional[list] = None,
        ports: Optional[dict] = None,
        gpu_id: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        cpu_reservation: Optional[float] = None,
        cpu_shares: Optional[int] = None,
        cpuset_cpus: Optional[str] = None,
        cpu_quota: Optional[int] = None,
        cpu_period: Optional[int] = None,
        memory_limit: Optional[str] = None,
        memory_reservation: Optional[str] = None,
        memory_swap_limit: Optional[str] = None,
        network_mode: str = "host",
        restart_policy: str = "on-failure",
    ) -> tuple[bool, Optional[str], Optional[str]]:
        from runtime_resources import parse_gpu_spec, build_resource_kwargs, resolve_mounts
        from port_utils import extract_host_ports, format_host_ports_label

        try:
            existing = self.get_container(container_name)
            if existing:
                existing.reload()
                if existing.status == "running":
                    return True, existing.id, None
                if self._is_managed_container(existing):
                    existing.remove(force=True)
                else:
                    logger.warning("Refusing to remove non-managed container: %s", container_name)
                    return False, None, f"Container {container_name} already exists but is not managed by this system"

            env_list = [f"{k}={v}" for k, v in (env or {}).items()]

            port_bindings = None
            host_ports = extract_host_ports(ports, network_mode)
            if ports and network_mode != "host":
                port_bindings = {}
                for container_port, host_port in ports.items():
                    port_bindings[f"{container_port}/tcp"] = host_port

            labels = {
                "manage_deploy.task_id": task_id,
                "manage_deploy.node_id": node_id,
                "manage_deploy.network_mode": network_mode,
            }
            if host_ports:
                labels["manage_deploy.host_ports"] = format_host_ports_label(host_ports)

            device_requests = parse_gpu_spec(gpu_id)
            resource_kw = build_resource_kwargs(
                cpu_limit=cpu_limit,
                cpu_reservation=cpu_reservation,
                cpu_shares=cpu_shares,
                cpuset_cpus=cpuset_cpus,
                cpu_quota=cpu_quota,
                cpu_period=cpu_period,
                memory_limit=memory_limit,
                memory_reservation=memory_reservation,
                memory_swap_limit=memory_swap_limit,
            )

            mounts = resolve_mounts(
                task_id=task_id,
                node_id=node_id,
                volumes=volumes,
                volume_mounts=volume_mounts,
                data_root=self.data_root,
                docker_client=self.client,
            )

            run_kwargs: dict[str, Any] = {
                "image": image,
                "name": container_name,
                "command": command,
                "environment": env_list,
                "ports": port_bindings,
                "network_mode": network_mode,
                "restart_policy": {"Name": restart_policy},
                "labels": labels,
                "detach": True,
                **resource_kw,
            }
            if device_requests:
                run_kwargs["device_requests"] = device_requests
            if mounts:
                run_kwargs["mounts"] = mounts

            self.client.containers.run(**run_kwargs)

            container = self.get_container(container_name)
            if container:
                return True, container.id, None
            return False, None, "Container not found after start"
        except docker.errors.ImageNotFound:
            return False, None, f"Image not found: {image}"
        except docker.errors.APIError as e:
            return False, None, str(e)
        except ValueError as e:
            return False, None, str(e)

    def stop_container(self, container_name: str, timeout: int = 5) -> tuple[bool, Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return True, None

            container.reload()

            if container.status in {"running", "restarting", "paused"}:
                if not self._is_managed_container(container):
                    logger.warning("Refusing to stop non-managed container: %s", container_name)
                    return True, None
                try:
                    container.stop(timeout=timeout)
                except (docker.errors.APIError, Exception):
                    try:
                        container.kill()
                    except docker.errors.APIError as e:
                        return False, str(e)
                return True, None

            return True, None
        except docker.errors.APIError as e:
            return False, str(e)

    def remove_container(self, container_name: str) -> tuple[bool, Optional[str]]:
        try:
            container = self.get_container(container_name)
            if not container:
                return True, None

            if not self._is_managed_container(container):
                logger.warning("Refusing to remove non-managed container: %s", container_name)
                return True, None

            container.reload()
            if container.status in {"running", "restarting", "paused"}:
                try:
                    container.kill()
                except docker.errors.APIError:
                    pass

            container.remove(force=True)
            return True, None
        except docker.errors.APIError as e:
            return False, str(e)

    def _collect_declared_host_ports(
        self,
        exclude_container_name: Optional[str] = None,
    ) -> dict[str, list[str]]:
        """已登记（label）的 host 端口占用。"""
        claimed: dict[str, list[str]] = defaultdict(list)
        try:
            for container in self.client.containers.list(all=True):
                if exclude_container_name and container.name == exclude_container_name:
                    continue
                try:
                    container.reload()
                except docker.errors.APIError:
                    continue

                labels = (container.attrs.get("Config") or {}).get("Labels") or {}
                label_ports = labels.get("manage_deploy.host_ports", "")
                if label_ports:
                    for port in label_ports.split(","):
                        port_text = port.strip()
                        if port_text:
                            claimed[port_text].append(container.name)
                    continue

                host_config = container.attrs.get("HostConfig") or {}
                if host_config.get("NetworkMode") == "host" and MANAGED_CONTAINER_PATTERN.match(container.name):
                    # 兼容旧容器：无 label 时跳过，避免误报
                    pass

                bindings = host_config.get("PortBindings") or {}
                for host_bindings in bindings.values():
                    for host_binding in host_bindings or []:
                        host_port = str(host_binding.get("HostPort") or "").strip()
                        if host_port:
                            claimed[host_port].append(container.name)
        except docker.errors.APIError as e:
            logger.error(f"Error collecting host ports: {e}")
        return claimed

    def find_port_binding_conflicts(
        self,
        ports: Optional[dict[str, str]],
        exclude_container_name: Optional[str] = None,
        network_mode: str = "bridge",
    ) -> tuple[list[str], list[str]]:
        from port_utils import extract_host_ports, is_host_port_in_use

        conflicts: list[str] = []
        warnings: list[str] = []

        requested = extract_host_ports(ports, network_mode)
        if network_mode == "host" and not requested:
            warnings.append("host 模式建议填写宿主机监听端口，以便冲突检查并注入 PEER_* 变量供其他节点使用。")
            return conflicts, warnings

        if not requested:
            return conflicts, warnings

        declared = self._collect_declared_host_ports(exclude_container_name)

        for host_port in requested:
            port_text = str(host_port)
            owners = declared.get(port_text, [])
            if owners:
                conflicts.append(f"宿主机端口 {port_text} 已被容器登记占用: {', '.join(owners)}")
                continue
            if is_host_port_in_use(host_port):
                conflicts.append(f"宿主机端口 {port_text} 当前已被进程监听")

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
        from port_utils import is_host_port_in_use

        try:
            container = self.get_container(container_name)
            if not container or container.status != "running":
                return False

            host_config = container.attrs.get("HostConfig") or {}
            if host_config.get("NetworkMode") == "host":
                return is_host_port_in_use(port)

            container_port = f"{port}/tcp"
            port_map = container.ports or {}
            bindings = port_map.get(container_port, [])
            return len(bindings) > 0
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
