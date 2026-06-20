import asyncio
import logging
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    TaskInstance,
    TaskInstanceNode,
    TaskInstanceEdge,
    Node as NodeModel,
    TaskTemplate,
    TaskEvent,
)
from enums import TaskStatus, NodeStatus
from schemas import ContainerStartRequest
from services.runtime_fields import build_container_start_request
from services.runtime_composer import compose_container_runtime
from services.time_utils import business_now
from agents.agent_client import AgentClient

logger = logging.getLogger(__name__)


def _format_agent_error(result: dict) -> str:
    """Compact, truncated representation of a non-2xx node_agent response."""
    status = result.get("status_code")
    raw_body = result.get("error", "")
    body = str(raw_body)[:500] if raw_body is not None else ""
    if status is None:
        return f"node_agent unreachable: {body}" if body else "node_agent unreachable"
    return f"node_agent http {status}: {body}" if body else f"node_agent http {status}"


def _default_session_maker() -> Callable[[], Any]:
    """Lazy-imported default `async_session_maker` so tests can patch it."""
    from database import async_session_maker

    return async_session_maker


async def record_agent_failure_event_independent(
    *,
    instance_id: str,
    node_id: Optional[str],
    node_status: Optional[Any],
    operation: str,
    result: dict,
    session_maker: Optional[Callable[[], Any]] = None,
) -> None:
    """Write a `node_agent_error` task_event in an INDEPENDENT session.

    Use this from preflight-time call sites where the surrounding FastAPI
    request may still raise `HTTPException` and rollback its own session.
    The DAG-executor-time helpers stay on the request/executor session
    because that session has its own commit point and the executor itself
    is the unit of work.

    Failures inside this helper are logged but never re-raised; the audit
    write must never mask the original outcome the caller is reporting.
    """
    maker = session_maker or _default_session_maker()
    try:
        message = f"{operation}: {_format_agent_error(result)}"
        async with maker() as session:
            session.add(
                TaskEvent(
                    instance_id=instance_id,
                    node_id=node_id,
                    event_type="node_agent_error",
                    old_status=str(node_status) if node_status is not None else None,
                    new_status="failed",
                    message=message[:2048],
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - defensive: audit failure must not bubble
        logger.exception(
            "Failed to record independent TaskEvent for node_agent failure "
            "(instance=%s op=%s)",
            instance_id,
            operation,
        )


async def reconcile_stale_running_node_independent(
    *,
    existing_node_id: str,
    existing_instance_id: str,
    message: str,
    session_maker: Optional[Callable[[], Any]] = None,
) -> bool:
    """Reconcile a stale `running` DB row + append a `reconcile_stale_container`
    task_event in an INDEPENDENT session that commits independently of the
    surrounding request.

    Returns True iff the reconcile write committed successfully. Failures are
    logged and the function returns False; the caller (preflight) treats this
    the same as "could not reconcile" and keeps the conflict, which is the
    safe fallback.
    """
    maker = session_maker or _default_session_maker()
    try:
        async with maker() as session:
            node_row = (
                await session.execute(
                    select(TaskInstanceNode).where(TaskInstanceNode.id == existing_node_id)
                )
            ).scalar_one_or_none()
            instance_row = (
                await session.execute(
                    select(TaskInstance).where(TaskInstance.id == existing_instance_id)
                )
            ).scalar_one_or_none()
            if not node_row or not instance_row:
                logger.warning(
                    "reconcile independent: node=%s instance=%s not found in DB; "
                    "skipping",
                    existing_node_id,
                    existing_instance_id,
                )
                return False

            prior_status = node_row.status
            node_row.container_id = None
            node_row.container_name = None
            node_row.status = NodeStatus.STOPPED
            instance_row.status = TaskStatus.STOPPED

            session.add(
                TaskEvent(
                    instance_id=existing_instance_id,
                    node_id=existing_node_id,
                    event_type="reconcile_stale_container",
                    old_status=str(prior_status) if prior_status is not None else None,
                    new_status="stopped",
                    message=message[:2048],
                )
            )
            await session.commit()
            return True
    except Exception:  # noqa: BLE001 - defensive: audit failure must not bubble
        logger.exception(
            "Failed to record independent reconcile event (instance=%s node=%s)",
            existing_instance_id,
            existing_node_id,
        )
        return False


class DAGExecutor:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_client = AgentClient()

    async def get_instance_with_graph(self, instance_id: str) -> Optional[TaskInstance]:
        result = await self.db.execute(
            select(TaskInstance).where(TaskInstance.id == instance_id)
        )
        return result.scalar_one_or_none()

    async def get_root_nodes(self, instance_id: str) -> list[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode)
            .where(TaskInstanceNode.instance_id == instance_id)
            .where(TaskInstanceNode.id.notin_(
                select(TaskInstanceEdge.to_node_id).where(TaskInstanceEdge.instance_id == instance_id)
            ))
        )
        return list(result.scalars().all())

    async def get_leaf_nodes(self, instance_id: str) -> list[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode)
            .where(TaskInstanceNode.instance_id == instance_id)
            .where(TaskInstanceNode.id.notin_(
                select(TaskInstanceEdge.from_node_id).where(TaskInstanceEdge.instance_id == instance_id)
            ))
        )
        return list(result.scalars().all())

    async def get_downstream_nodes(
        self, instance_id: str, node_id: str
    ) -> list[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode)
            .join(
                TaskInstanceEdge,
                TaskInstanceEdge.to_node_id == TaskInstanceNode.id
            )
            .where(TaskInstanceEdge.instance_id == instance_id)
            .where(TaskInstanceEdge.from_node_id == node_id)
        )
        return list(result.scalars().all())

    async def get_upstream_nodes(
        self, instance_id: str, node_id: str
    ) -> list[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode)
            .join(
                TaskInstanceEdge,
                TaskInstanceEdge.from_node_id == TaskInstanceNode.id
            )
            .where(TaskInstanceEdge.instance_id == instance_id)
            .where(TaskInstanceEdge.to_node_id == node_id)
        )
        return list(result.scalars().all())

    async def get_node_by_id(self, node_id: str) -> Optional[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.id == node_id)
        )
        return result.scalar_one_or_none()

    async def get_node_machine(self, node_id: str) -> Optional[NodeModel]:
        result = await self.db.execute(
            select(NodeModel).where(NodeModel.id == node_id)
        )
        return result.scalar_one_or_none()

    def _get_agent_endpoint(self, machine: NodeModel) -> str:
        return machine.agent_address or machine.management_ip

    async def _record_agent_failure_event(
        self,
        *,
        instance_id: str,
        node: Optional[TaskInstanceNode],
        operation: str,
        result: dict,
    ) -> None:
        """Persist a task_event when a node_agent call fails (non-2xx / unreachable).

        Keeps the failure trail visible in the UI / API even when the operator
        cannot ssh into the worker host. Uses event_type=`node_agent_error`,
        new_status=`failed`, message=<operation>: <node_agent status + body>.
        """
        try:
            message = f"{operation}: {_format_agent_error(result)}"
            self.db.add(
                TaskEvent(
                    instance_id=instance_id,
                    node_id=node.id if node is not None else None,
                    event_type="node_agent_error",
                    old_status=str(node.status) if node is not None and node.status is not None else None,
                    new_status="failed",
                    message=message[:2048],
                )
            )
            await self.db.flush()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to record TaskEvent for node_agent failure (instance=%s op=%s)",
                instance_id,
                operation,
            )

    async def update_node_status(
        self, node: TaskInstanceNode, status: NodeStatus, error_message: Optional[str] = None
    ) -> None:
        node.status = status
        if error_message:
            node.error_message = error_message

    async def update_task_status(self, task: TaskInstance, status: TaskStatus) -> None:
        task.status = status

    async def get_all_instance_nodes(self, instance_id: str) -> list[TaskInstanceNode]:
        result = await self.db.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id)
        )
        return list(result.scalars().all())

    async def start_node(
        self, node: TaskInstanceNode, instance_id: str
    ) -> tuple[bool, Optional[str]]:
        machine = await self.get_node_machine(node.node_id)
        if not machine:
            return False, f"Node machine not found: {node.node_id}"

        container_name = f"{instance_id}_{node.id}"

        instance = await self.get_instance_with_graph(instance_id)
        if not instance:
            return False, "Task instance not found"
        template_result = await self.db.execute(
            select(TaskTemplate).where(TaskTemplate.id == instance.template_id)
        )
        template = template_result.scalar_one_or_none()
        if not template:
            return False, "Task template not found"

        all_nodes = await self.get_all_instance_nodes(instance_id)
        machines: dict[str, NodeModel] = {}
        for peer in all_nodes:
            if peer.node_id not in machines:
                peer_machine = await self.get_node_machine(peer.node_id)
                if peer_machine:
                    machines[peer.node_id] = peer_machine

        command, runtime_env = compose_container_runtime(
            instance, template, node, all_nodes, machines
        )
        request = build_container_start_request(node)
        request.command = command
        from services.platform_runtime import apply_platform_runtime

        enable_scratch = bool((node.env or {}).get("PLATFORM_SCRATCH") == "1")
        request.env = apply_platform_runtime(
            request,
            instance_id,
            node.id,
            runtime_env,
            enable_scratch=enable_scratch,
        )

        success, result = await self.agent_client.start_container(
            management_ip=self._get_agent_endpoint(machine),
            task_id=instance_id,
            node_id=node.id,
            container_name=container_name,
            request=request,
        )

        if success:
            node.container_id = result.get("container_id")
            node.container_name = container_name
            await self.db.flush()
            return True, None

        await self._record_agent_failure_event(
            instance_id=instance_id,
            node=node,
            operation="start_container",
            result=result,
        )
        return False, _format_agent_error(result)

    async def stop_node(self, node: TaskInstanceNode) -> tuple[bool, Optional[str]]:
        machine = await self.get_node_machine(node.node_id)
        if not machine:
            return True, None

        success, result = await self.agent_client.stop_container(
            management_ip=self._get_agent_endpoint(machine),
            task_id=node.instance_id,
            node_id=node.id,
        )
        if success:
            return True, None
        await self._record_agent_failure_event(
            instance_id=node.instance_id,
            node=node,
            operation="stop_container",
            result=result,
        )
        return False, _format_agent_error(result)

    async def remove_node(self, node: TaskInstanceNode) -> tuple[bool, Optional[str]]:
        machine = await self.get_node_machine(node.node_id)
        if not machine:
            return True, None

        success, result = await self.agent_client.delete_container(
            management_ip=self._get_agent_endpoint(machine),
            task_id=node.instance_id,
            node_id=node.id,
        )
        if success:
            node.container_id = None
            node.container_name = None
            node.error_message = None
            await self.update_node_status(node, NodeStatus.STOPPED)
            await self.db.flush()
            return True, None
        await self._record_agent_failure_event(
            instance_id=node.instance_id,
            node=node,
            operation="delete_container",
            result=result,
        )
        return False, _format_agent_error(result)

    async def get_node_status(
        self, node: TaskInstanceNode
    ) -> tuple[str, bool, Optional[str]]:
        machine = await self.get_node_machine(node.node_id)
        if not machine:
            return "unknown", False, "Node machine not found"

        return await self.agent_client.get_container_status(
            management_ip=self._get_agent_endpoint(machine),
            task_id=node.instance_id,
            node_id=node.id,
        )

    async def execute_dag_start(
        self,
        instance_id: str,
        *,
        claimed_start: bool = False,
    ) -> tuple[bool, Optional[str]]:
        from services.routing_network import instance_waiting_for_network_ready

        waiting_order = await instance_waiting_for_network_ready(self.db, instance_id)
        if waiting_order:
            return (
                False,
                f"Order {waiting_order.id} is waiting for external router network-ready",
            )

        instance = await self.get_instance_with_graph(instance_id)
        if not instance:
            return False, "Task instance not found"

        if instance.status == TaskStatus.RUNNING or (
            instance.status == TaskStatus.STARTING and not claimed_start
        ):
            return True, None

        if instance.status != TaskStatus.STARTING:
            await self.update_task_status(instance, TaskStatus.STARTING)
        instance.error_message = None

        root_nodes = await self.get_root_nodes(instance_id)
        if not root_nodes:
            await self.update_task_status(instance, TaskStatus.RUNNING)
            instance.start_time = business_now()
            await self.db.commit()
            return True, None

        started_nodes: dict[str, bool] = {}
        failed_nodes: set[str] = set()

        pending_nodes = {n.id for n in root_nodes}
        running_nodes: dict[str, asyncio.Task] = {}

        from services.health_checker import HealthChecker

        health_checker = HealthChecker(self.db)

        async def start_and_monitor(node: TaskInstanceNode):
            await self.update_node_status(node, NodeStatus.STARTING)

            success, error = await self.start_node(node, instance_id)
            if not success:
                failed_nodes.add(node.id)
                await self.update_node_status(node, NodeStatus.FAILED, error)
                return False

            await self.update_node_status(node, NodeStatus.RUNNING)

            is_ready, ready_error = await health_checker.wait_for_health(
                node, self.agent_client
            )

            if not is_ready:
                failed_nodes.add(node.id)
                await self.update_node_status(node, NodeStatus.FAILED, ready_error)
                await self.stop_node(node)
                return False

            await self.update_node_status(node, NodeStatus.READY)
            started_nodes[node.id] = True
            return True

        while pending_nodes or running_nodes:
            if failed_nodes:
                break

            while pending_nodes and len(running_nodes) < 10:
                node_id = pending_nodes.pop()
                node = await self.get_node_by_id(node_id)
                if node:
                    task = asyncio.create_task(start_and_monitor(node))
                    running_nodes[node_id] = task

            if not running_nodes:
                break

            done, _ = await asyncio.wait(
                running_nodes.values(), return_when=asyncio.FIRST_COMPLETED
            )

            for completed_task in done:
                node_id = None
                for nid, t in running_nodes.items():
                    if t == completed_task:
                        node_id = nid
                        break

                if node_id:
                    del running_nodes[node_id]

                success = completed_task.result()
                if not success:
                    continue

                if node_id:
                    downstream = await self.get_downstream_nodes(instance_id, node_id)
                    for downstream_node in downstream:
                        upstream_ready = all(
                            started_nodes.get(uid, False)
                            for uid in await self._get_upstream_ids(instance_id, downstream_node.id)
                        )
                        if upstream_ready and downstream_node.id not in started_nodes:
                            pending_nodes.add(downstream_node.id)

            await asyncio.sleep(0.1)

        if failed_nodes:
            await self._rollback_started_nodes(instance_id, started_nodes, failed_nodes)
            instance.error_message = f"Node(s) failed: {', '.join(failed_nodes)}"
            await self.update_task_status(instance, TaskStatus.FAILED)
            await self.db.commit()
            return False, f"Node(s) failed: {failed_nodes}"

        await self.update_task_status(instance, TaskStatus.RUNNING)
        instance.start_time = business_now()
        await self.db.commit()
        return True, None

    async def _get_upstream_ids(self, instance_id: str, node_id: str) -> list[str]:
        upstream = await self.get_upstream_nodes(instance_id, node_id)
        return [n.id for n in upstream]

    async def _rollback_started_nodes(
        self,
        instance_id: str,
        started_nodes: dict[str, bool],
        failed_nodes: set[str] | None = None,
    ) -> None:
        """失败回滚：删除已启动/失败节点的 Docker 容器，避免残留 Exited 容器。"""
        failed_nodes = failed_nodes or set()
        target_ids = {node_id for node_id, started in started_nodes.items() if started}
        target_ids |= failed_nodes
        for node_id in target_ids:
            node = await self.get_node_by_id(node_id)
            if not node:
                continue
            await self.remove_node(node)

    async def execute_dag_stop(self, instance_id: str) -> tuple[bool, Optional[str]]:
        instance = await self.get_instance_with_graph(instance_id)
        if not instance:
            return False, "Task instance not found"

        if instance.status in (TaskStatus.STOPPED, TaskStatus.PENDING):
            return True, None

        await self.update_task_status(instance, TaskStatus.STOPPING)

        leaf_nodes = await self.get_leaf_nodes(instance_id)
        stopped_nodes: set[str] = set()
        pending_stops: set[str] = {n.id for n in leaf_nodes}
        running_stops: dict[str, asyncio.Task] = {}

        while pending_stops or running_stops:
            while pending_stops and len(running_stops) < 10:
                node_id = pending_stops.pop()
                node = await self.get_node_by_id(node_id)
                if node:
                    task = asyncio.create_task(self._stop_node_async(node))
                    running_stops[node_id] = task

            if not running_stops:
                break

            done, _ = await asyncio.wait(
                running_stops.values(), return_when=asyncio.FIRST_COMPLETED
            )

            for completed_task in done:
                node_id = None
                for nid, t in running_stops.items():
                    if t == completed_task:
                        node_id = nid
                        break

                if node_id:
                    del running_stops[node_id]
                    stopped_nodes.add(node_id)

                    upstream = await self.get_upstream_nodes(instance_id, node_id)
                    for upstream_node in upstream:
                        all_downstream_done = all(
                            d in stopped_nodes
                            for d in await self._get_downstream_ids(instance_id, upstream_node.id)
                        )
                        if all_downstream_done and upstream_node.id not in stopped_nodes:
                            pending_stops.add(upstream_node.id)

            await asyncio.sleep(0.1)

        await self.update_task_status(instance, TaskStatus.STOPPED)
        instance.end_time = business_now()
        await self.db.commit()
        return True, None

    async def _get_downstream_ids(self, instance_id: str, node_id: str) -> list[str]:
        downstream = await self.get_downstream_nodes(instance_id, node_id)
        return [n.id for n in downstream]

    async def _stop_node_async(self, node: TaskInstanceNode) -> bool:
        success, _ = await self.stop_node(node)
        if success:
            await self.update_node_status(node, NodeStatus.STOPPED)
        return success
