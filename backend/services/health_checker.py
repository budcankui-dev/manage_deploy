import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import TaskInstanceNode, Node as NodeModel
from enums import HealthCheckType, NodeStatus
from agents.agent_client import AgentClient

logger = logging.getLogger(__name__)


class HealthChecker:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_agent_endpoint(self, machine: NodeModel) -> str:
        return machine.agent_address or machine.management_ip

    async def wait_for_health(
        self,
        node: TaskInstanceNode,
        agent_client: AgentClient,
        timeout: int = 30,
        interval: int = 5,
        max_retries: int = 3,
    ) -> tuple[bool, Optional[str]]:
        # Even without custom health checks, we should still verify the container
        # is actually running. Otherwise fast-fail containers may be marked "ready".
        if not node.health_check:
            return await self._wait_for_running(node, agent_client, interval, max_retries)

        health_config = node.health_check
        check_type = health_config.get("type")
        timeout = health_config.get("timeout", timeout)
        interval = health_config.get("interval", interval)
        max_retries = health_config.get("retry", max_retries)

        machine = await self._get_node_machine(node.node_id)
        if not machine:
            return False, f"Node machine not found: {node.node_id}"

        for attempt in range(max_retries):
            status, is_healthy, status_message = await agent_client.get_container_status(
                management_ip=self._get_agent_endpoint(machine),
                task_id=node.instance_id,
                node_id=node.id,
            )
            if status != "running":
                if attempt < max_retries - 1:
                    await asyncio.sleep(interval)
                    continue
                return False, status_message or f"Container status is {status}"

            is_healthy, message = await self._perform_health_check(
                agent_client, self._get_agent_endpoint(machine), node, check_type, health_config
            )

            if is_healthy:
                return True, None

            if attempt < max_retries - 1:
                await asyncio.sleep(interval)

        return False, message or "Health check failed"

    async def _wait_for_running(
        self,
        node: TaskInstanceNode,
        agent_client: AgentClient,
        interval: int,
        max_retries: int,
    ) -> tuple[bool, Optional[str]]:
        machine = await self._get_node_machine(node.node_id)
        if not machine:
            return False, f"Node machine not found: {node.node_id}"

        for attempt in range(max_retries):
            status, _healthy, message = await agent_client.get_container_status(
                management_ip=self._get_agent_endpoint(machine),
                task_id=node.instance_id,
                node_id=node.id,
            )
            if status == "running":
                return True, None
            if attempt < max_retries - 1:
                await asyncio.sleep(interval)

        return False, message or "Container is not running"

    async def _perform_health_check(
        self,
        agent_client: AgentClient,
        management_ip: str,
        node: TaskInstanceNode,
        check_type: str,
        health_config: dict,
    ) -> tuple[bool, Optional[str]]:
        if check_type == HealthCheckType.PORT.value:
            return await self._check_port(agent_client, management_ip, node, health_config)
        elif check_type == HealthCheckType.HTTP.value:
            return await self._check_http(agent_client, management_ip, node, health_config)
        elif check_type == HealthCheckType.LOG.value:
            return await self._check_log(agent_client, management_ip, node, health_config)
        elif check_type == HealthCheckType.CONTAINER.value:
            return await self._check_container(agent_client, management_ip, node, health_config)
        else:
            return True, None

    async def _check_port(
        self,
        agent_client: AgentClient,
        management_ip: str,
        node: TaskInstanceNode,
        health_config: dict,
    ) -> tuple[bool, Optional[str]]:
        port = health_config.get("port")
        if not port:
            return False, "Port not specified in health check config"

        is_open, error = await agent_client.check_port(
            management_ip=management_ip,
            task_id=node.instance_id,
            node_id=node.id,
            port=port,
        )
        return is_open, error

    async def _check_http(
        self,
        agent_client: AgentClient,
        management_ip: str,
        node: TaskInstanceNode,
        health_config: dict,
    ) -> tuple[bool, Optional[str]]:
        url = health_config.get("url")
        if not url:
            return False, "URL not specified in health check config"

        is_healthy, error = await agent_client.check_http(
            management_ip=management_ip,
            task_id=node.instance_id,
            node_id=node.id,
            url=url,
        )
        return is_healthy, error

    async def _check_log(
        self,
        agent_client: AgentClient,
        management_ip: str,
        node: TaskInstanceNode,
        health_config: dict,
    ) -> tuple[bool, Optional[str]]:
        keyword = health_config.get("keyword")
        if not keyword:
            return False, "Keyword not specified in health check config"

        is_found, error = await agent_client.check_log(
            management_ip=management_ip,
            task_id=node.instance_id,
            node_id=node.id,
            keyword=keyword,
        )
        return is_found, error

    async def _check_container(
        self,
        agent_client: AgentClient,
        management_ip: str,
        node: TaskInstanceNode,
        health_config: dict,
    ) -> tuple[bool, Optional[str]]:
        container_name = health_config.get("container")
        if not container_name:
            return False, "Container name not specified in health check config"

        is_running, error = await agent_client.check_container_running(
            management_ip=management_ip,
            task_id=node.instance_id,
            container_name=container_name,
        )
        return is_running, error

    async def _get_node_machine(self, node_id: str) -> Optional[NodeModel]:
        result = await self.db.execute(
            select(NodeModel).where(NodeModel.id == node_id)
        )
        return result.scalar_one_or_none()
