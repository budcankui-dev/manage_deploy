"""路由完成后的工单物化服务。

当外部路由系统回写 placements 后，本模块负责：
1. 根据 placements 构建 node_overrides
2. 调用 _create_instance_from_template 物化实例
3. 更新 TaskOrder 状态
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from enums import DeploymentMode, OrderStatus
from models import BusinessTemplateCatalog, Node as NodeModel, RoutingRequest, TaskOrder
from schemas import TaskInstanceCreate, TaskInstanceNodeOverride

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

    catalog_result = await db.execute(
        select(BusinessTemplateCatalog).where(
            BusinessTemplateCatalog.template_id == order.template_id
        )
    )
    catalog = catalog_result.scalar_one_or_none()
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

    now = datetime.utcnow()
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
        order.materialized_instance_id = instance.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
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

    shared_env = {
        "TASK_TYPE": order.name,
        "SOURCE_NAME": order.source_name or "",
        "DESTINATION_NAME": order.destination_name or "",
    }

    for role, template_node_name in role_node_names.items():
        raw_node_id = placements.get(role)
        if not raw_node_id:
            continue

        node_id = await _resolve_node_id(db, raw_node_id)
        env = dict(shared_env)
        env["TASK_ROLE"] = role
        overrides.append(
            TaskInstanceNodeOverride(
                template_node_name=template_node_name,
                node_id=node_id,
                env=env,
            )
        )

    return overrides


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
