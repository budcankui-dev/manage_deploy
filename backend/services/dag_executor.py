import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    TaskInstance,
    TaskInstanceNode,
    TaskInstanceEdge,
    Node as NodeModel,
    TaskTemplate,
)
from enums import TaskStatus, NodeStatus
from schemas import ContainerStartRequest
from services.runtime_fields import build_container_start_request
from services.runtime_composer import compose_container_runtime
from agents.agent_client import AgentClient

logger = logging.getLogger(__name__)


def func_now() -> datetime:
    return datetime.utcnow()


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
        request.env = runtime_env

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

        return success, result.get("error") if not success else None

    async def stop_node(self, node: TaskInstanceNode) -> tuple[bool, Optional[str]]:
        machine = await self.get_node_machine(node.node_id)
        if not machine:
            return True, None

        success, result = await self.agent_client.stop_container(
            management_ip=self._get_agent_endpoint(machine),
            task_id=node.instance_id,
            node_id=node.id,
        )
        return success, result.get("error") if not success else None

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
        return success, result.get("error") if not success else None

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

    async def execute_dag_start(self, instance_id: str) -> tuple[bool, Optional[str]]:
        instance = await self.get_instance_with_graph(instance_id)
        if not instance:
            return False, "Task instance not found"

        if instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            return True, None

        await self.update_task_status(instance, TaskStatus.STARTING)
        instance.error_message = None

        root_nodes = await self.get_root_nodes(instance_id)
        if not root_nodes:
            await self.update_task_status(instance, TaskStatus.RUNNING)
            instance.start_time = func_now()
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
            await self._rollback_started_nodes(instance_id, started_nodes)
            instance.error_message = f"Node(s) failed: {', '.join(failed_nodes)}"
            await self.update_task_status(instance, TaskStatus.FAILED)
            await self.db.commit()
            return False, f"Node(s) failed: {failed_nodes}"

        await self.update_task_status(instance, TaskStatus.RUNNING)
        instance.start_time = func_now()
        await self.db.commit()
        return True, None

    async def _get_upstream_ids(self, instance_id: str, node_id: str) -> list[str]:
        upstream = await self.get_upstream_nodes(instance_id, node_id)
        return [n.id for n in upstream]

    async def _rollback_started_nodes(
        self, instance_id: str, started_nodes: dict[str, bool]
    ) -> None:
        for node_id, started in started_nodes.items():
            if started:
                node = await self.get_node_by_id(node_id)
                if node and node.status == NodeStatus.READY:
                    await self.stop_node(node)
                    await self.update_node_status(node, NodeStatus.STOPPED)

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
        instance.end_time = func_now()
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
