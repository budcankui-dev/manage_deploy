"""SCHEDULED 实例到期自动收尾流程。

`auto_cleanup_instance` 在调度器触发到期 stop 之后被调用：
1. 顺序删除每个节点的容器（不会并发，避免 AsyncSession flush 冲突）。
2. 通过 `purge_order_instance_artifacts` 物理删除实例（含 nodes/edges/events/eval/results）。

失败不抛异常：写 TaskEvent + 日志，确保后续调度不被阻塞。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models import TaskEvent, TaskInstance
from enums import NodeStatus
from services.dag_executor import DAGExecutor
from services.order_sync import purge_order_instance_artifacts
from services.routing_resource_events import emit_release_events_for_instance

logger = logging.getLogger(__name__)


async def cleanup_instance_runtime(db: AsyncSession, instance: TaskInstance) -> list[str]:
    """顺序调用 DAGExecutor.remove_node 删除每个节点的容器（与 api/instances.py 共用逻辑）。"""
    executor = DAGExecutor(db)
    errors: list[str] = []
    for node in instance.nodes:
        has_container = bool(node.container_id or node.container_name)
        may_have_runtime = node.status in {
            NodeStatus.STARTING,
            NodeStatus.RUNNING,
            NodeStatus.READY,
            NodeStatus.STOPPING,
        }
        if not has_container and not may_have_runtime:
            continue
        success, error = await executor.remove_node(node)
        if not success:
            errors.append(f"{node.name}: {error or 'Unknown error'}")
    return errors


async def auto_cleanup_instance(db: AsyncSession, instance: TaskInstance) -> list[str]:
    """SCHEDULED 到期自动收尾（keep_after_stop=False 时调用）。

    - 调用方负责处理 commit / rollback；本函数仅 flush。
    - 任意失败写 TaskEvent + 日志，不抛异常，避免阻塞 APScheduler 其他任务。
    """
    instance_id = instance.id
    warnings: list[str] = []

    try:
        warnings = await cleanup_instance_runtime(db, instance)
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_cleanup_instance: runtime cleanup failed for %s", instance_id)
        warnings.append(f"runtime cleanup failed: {exc}")
        try:
            db.add(
                TaskEvent(
                    instance_id=instance_id,
                    event_type="auto_cleanup_error",
                    old_status=str(getattr(instance, "status", "")),
                    new_status="cleanup_failed",
                    message=str(exc),
                )
            )
            await db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("auto_cleanup_instance: failed to record TaskEvent")

    try:
        await emit_release_events_for_instance(
            db,
            instance_id,
            reason="auto_cleanup",
            metadata={"source": "instance_lifecycle"},
        )
        await purge_order_instance_artifacts(db, instance_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_cleanup_instance: purge failed for %s", instance_id)
        warnings.append(f"purge failed: {exc}")

    return warnings


__all__ = ["auto_cleanup_instance", "cleanup_instance_runtime"]
