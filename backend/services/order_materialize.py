"""路由完成后的工单物化服务。

当外部路由系统回写 placements 后，本模块负责：
1. 根据 placements 构建 node_overrides
2. 调用 _create_instance_from_template 物化实例
3. 更新 TaskOrder 状态
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from config import settings
from enums import DeploymentMode, OrderStatus
from models import BusinessTemplateCatalog, Node as NodeModel, RoutingRequest, TaskOrder
from schemas import TaskInstanceCreate, TaskInstanceNodeOverride
from services.time_utils import business_now

logger = logging.getLogger(__name__)


async def materialize_after_routing(
    db: AsyncSession,
    order: TaskOrder,
    routing: RoutingRequest,
) -> str | None:
    """路由完成后物化实例。返回 instance_id 或 None（失败时）。"""
    if not routing.placements:
        order.status = OrderStatus.FAILED
        order.error_message = "Routing completed but no placements provided"
        return None

    business_task = (order.runtime_config or {}).get("business_task") or {}
    task_type = business_task.get("task_type")
    catalog_query = select(BusinessTemplateCatalog).where(
        BusinessTemplateCatalog.template_id == order.template_id
    )
    if task_type:
        catalog_query = catalog_query.where(BusinessTemplateCatalog.task_type == task_type)
    catalog_result = await db.execute(catalog_query)
    catalog = catalog_result.scalars().first()
    if not catalog:
        order.status = OrderStatus.FAILED
        order.error_message = f"No catalog entry for template_id={order.template_id}"
        return None

    role_node_names = {
        "source": catalog.source_node_name,
        "compute": catalog.compute_node_name,
        "sink": catalog.sink_node_name,
    }

    try:
        overrides = await _build_overrides(db, order, routing, role_node_names)
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = f"Failed to build overrides: {exc}"
        logger.exception("materialize_after_routing: build overrides failed")
        return None

    now = business_now()
    hours = max(1, int(settings.default_scheduled_duration_hours or 2))
    end_time = order.scheduled_end_time or order.business_end_time or (now + timedelta(hours=hours))
    start_time = order.scheduled_start_time or order.business_start_time or now

    instance_create = TaskInstanceCreate(
        template_id=order.template_id,
        name=order.name,
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=start_time,
        scheduled_end_time=end_time,
        auto_start=False,
        keep_after_stop=order.keep_after_stop,
        node_overrides=overrides,
    )

    from api.instances import _create_instance_from_template

    try:
        instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)
        for node in instance.nodes:
            if node.env and node.env.get("TASK_INSTANCE_ID") == order.id:
                node.env = {**node.env, "TASK_INSTANCE_ID": instance.id}
                flag_modified(node, "env")
        order.materialized_instance_id = instance.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
        rc = order.runtime_config or {}
        rc["routing_result"] = {
            "strategy": routing.selected_strategy or routing.strategy,
            "placements": routing.placements,
            "estimated_metric": routing.estimated_metric,
            "external_routing_id": routing.external_routing_id,
        }
        order.runtime_config = rc
        flag_modified(order, "runtime_config")
        logger.info(f"Order {order.id} materialized as instance {instance.id}")
        return instance.id
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = str(exc)
        logger.exception(f"materialize_after_routing failed for order {order.id}")
        return None


async def _build_overrides(
    db: AsyncSession,
    order: TaskOrder,
    routing: RoutingRequest,
    role_node_names: dict[str, str],
) -> list[TaskInstanceNodeOverride]:
    """根据路由 placements 构建 node_overrides。"""
    placements = routing.placements or {}
    overrides: list[TaskInstanceNodeOverride] = []

    business_task = (order.runtime_config or {}).get("business_task") or {}
    shared_env = {
        "TASK_TYPE": business_task.get("task_type") or order.name,
        "SOURCE_NAME": order.source_name or "",
        "DESTINATION_NAME": order.destination_name or "",
    }
    if business_task.get("data_profile"):
        shared_env["DATA_PROFILE"] = json.dumps(business_task["data_profile"])
    if business_task.get("business_objective"):
        shared_env["BUSINESS_OBJECTIVE"] = json.dumps(business_task["business_objective"])
    if business_task.get("runtime_plan"):
        shared_env["RUNTIME_PLAN"] = json.dumps(business_task["runtime_plan"])

    for role, template_node_name in role_node_names.items():
        placement = placements.get(role)
        if role == "compute" and placement is None:
            placement = placements.get("worker")
        raw_node_id = _placement_node_name(placement)
        if not raw_node_id:
            continue

        node_id = await _resolve_node_id(db, raw_node_id)
        env = dict(shared_env)
        env["TASK_ROLE"] = role
        env["TASK_INSTANCE_ID"] = order.id
        gpu_id = _placement_gpu_id(placement)
        if gpu_id is not None:
            env["GPU_DEVICE"] = gpu_id
        overrides.append(
            TaskInstanceNodeOverride(
                template_node_name=template_node_name,
                node_id=node_id,
                env=env,
                gpu_id=gpu_id,
            )
        )

    return overrides


def _placement_node_name(placement: Any) -> str | None:
    """Support both simple and rich external router placement payloads."""
    if isinstance(placement, str):
        return placement
    if isinstance(placement, dict):
        for key in ("topology_node_id", "node_name", "worker_host", "hostname", "node_id"):
            value = placement.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _placement_gpu_id(placement: Any) -> str | None:
    if not isinstance(placement, dict):
        return None
    gpu_device = placement.get("gpu_device")
    if gpu_device is not None:
        return str(gpu_device)
    gpu_indices = placement.get("gpu_indices")
    if isinstance(gpu_indices, list) and gpu_indices:
        return str(gpu_indices[0])
    return None


async def _resolve_node_id(db: AsyncSession, raw: str) -> str:
    """将 hostname 或 UUID 解析为 node UUID。"""
    import re
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    if uuid_pattern.match(raw):
        return raw

    # 先按 display_name 查找
    result = await db.execute(
        select(NodeModel).where(NodeModel.display_name == raw)
    )
    node = result.scalar_one_or_none()
    if node:
        return node.id

    # 再按 hostname 查找
    result = await db.execute(
        select(NodeModel).where(NodeModel.hostname == raw)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise ValueError(f"Node not found: {raw}")
    return node.id
