"""节点运行时字段合并与 Agent 请求构建。"""

from schemas import ContainerStartRequest

RUNTIME_OVERRIDE_FIELDS = (
    "volumes",
    "volume_mounts",
    "ports",
    "port_values",
    "gpu_id",
    "cpu_limit",
    "cpu_reservation",
    "cpu_shares",
    "cpuset_cpus",
    "cpu_quota",
    "cpu_period",
    "memory_limit",
    "memory_reservation",
    "memory_swap_limit",
    "network_mode",
    "restart_policy",
    "health_check",
    "node_id",
)


def pick_override(source, override, field: str):
    if override is None:
        return getattr(source, field, None)
    value = getattr(override, field, None)
    if value is not None:
        return value
    return getattr(source, field, None)


def apply_runtime_overrides(target, override) -> None:
    if not override:
        return
    for field in RUNTIME_OVERRIDE_FIELDS:
        value = getattr(override, field, None)
        if value is not None:
            setattr(target, field, value)


def build_container_start_request(node) -> ContainerStartRequest:
    volume_mounts = getattr(node, "volume_mounts", None)
    return ContainerStartRequest(
        image=node.image,
        command=node.command,
        env=node.env or {},
        volumes=node.volumes or {},
        volume_mounts=volume_mounts or None,
        ports=node.ports or {},
        gpu_id=node.gpu_id,
        cpu_limit=node.cpu_limit,
        cpu_reservation=getattr(node, "cpu_reservation", None),
        cpu_shares=getattr(node, "cpu_shares", None),
        cpuset_cpus=getattr(node, "cpuset_cpus", None),
        cpu_quota=getattr(node, "cpu_quota", None),
        cpu_period=getattr(node, "cpu_period", None),
        memory_limit=node.memory_limit,
        memory_reservation=getattr(node, "memory_reservation", None),
        memory_swap_limit=getattr(node, "memory_swap_limit", None),
        network_mode=node.network_mode,
        restart_policy=node.restart_policy,
        health_check=node.health_check,
    )
