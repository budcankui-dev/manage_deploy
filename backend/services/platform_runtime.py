"""平台注入容器环境变量与实例级 scratch 挂载。"""

from __future__ import annotations

from typing import Any

from config import settings
from schemas import ContainerStartRequest


def build_platform_env(instance_id: str, node_instance_id: str) -> dict[str, str]:
    manager_url = settings.manager_public_url
    if not manager_url:
        # `resolve_manager_public_url()` runs in the lifespan startup hook.
        # If we land here the lookup failed silently (e.g. someone called this
        # outside of FastAPI lifespan, like a script). Fail loud rather than
        # ship workers with a broken callback URL.
        raise RuntimeError(
            "settings.manager_public_url is unset; resolve_manager_public_url() "
            "must run before container env is built (normally during FastAPI lifespan startup)."
        )
    env = {
        "TASK_INSTANCE_ID": instance_id,
        "TASK_NODE_INSTANCE_ID": node_instance_id,
        "MANAGER_API_BASE": manager_url.rstrip("/"),
        "MINIO_ENDPOINT": settings.minio_endpoint.rstrip("/"),
        "MINIO_BUCKET": settings.minio_bucket,
    }
    if settings.minio_access_key:
        env["MINIO_ACCESS_KEY"] = settings.minio_access_key
    if settings.minio_secret_key:
        env["MINIO_SECRET_KEY"] = settings.minio_secret_key
    if settings.service_api_token:
        env["SERVICE_API_TOKEN"] = settings.service_api_token
    return env


def merge_platform_env(
    instance_id: str,
    node_instance_id: str,
    runtime_env: dict[str, str],
) -> dict[str, str]:
    merged = dict(runtime_env)
    merged.update(build_platform_env(instance_id, node_instance_id))
    return merged


def scratch_host_path(instance_id: str) -> str:
    root = settings.platform_scratch_root.rstrip("/")
    return f"{root}/{instance_id}/scratch"


def apply_scratch_bind_mount(request: ContainerStartRequest, instance_id: str) -> None:
    """三节点共享同一实例级 host 目录（同 agent 上 bind 有效）。"""
    host_path = scratch_host_path(instance_id)
    volumes = dict(request.volumes or {})
    volumes["/scratch"] = host_path
    request.volumes = volumes


def apply_platform_runtime(
    request: ContainerStartRequest,
    instance_id: str,
    node_instance_id: str,
    runtime_env: dict[str, str],
    *,
    enable_scratch: bool = False,
) -> dict[str, str]:
    if enable_scratch:
        apply_scratch_bind_mount(request, instance_id)
    # Start with runtime_env (contains peer_env + local_port_env + macros + user_env)
    merged = dict(runtime_env)
    # Overlay platform env (TASK_INSTANCE_ID, MANAGER_API_BASE, etc.)
    merged.update(build_platform_env(instance_id, node_instance_id))
    return merged
