"""启动容器前组合 env / command。"""

from __future__ import annotations

from typing import Optional

from config import settings
from models import Node as NodeModel, TaskInstance, TaskInstanceNode, TaskTemplate
from services.macro_resolver import apply_macros_to_env, merge_macro_values, substitute_macros
from services.port_plan import build_local_port_env, build_peer_env_for_node


def compose_container_runtime(
    instance: TaskInstance,
    template: TaskTemplate,
    node: TaskInstanceNode,
    all_nodes: list[TaskInstanceNode],
    machines: dict[str, NodeModel],
) -> tuple[Optional[str], dict[str, str]]:
    macros = merge_macro_values(template.macro_defs, instance.macro_values)
    peer_env = build_peer_env_for_node(
        node,
        all_nodes,
        machines,
        prefer_ipv6=settings.prefer_business_ipv6,
    )
    local_port_env = build_local_port_env(node.name, node.port_values)
    substitution_ctx = {**macros, **peer_env, **local_port_env}

    user_env = apply_macros_to_env(node.env, substitution_ctx)
    merged_env = {**macros, **peer_env, **local_port_env, **user_env}
    command = substitute_macros(node.command, substitution_ctx)
    return command, merged_env
