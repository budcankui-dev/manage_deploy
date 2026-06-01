import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from enums import DeploymentMode, NodeStatus, TaskStatus
from models import (
    Node as NodeModel,
    TaskEvent,
    TaskInstance,
    TaskInstanceEdge,
    TaskInstanceNode,
    TaskMetric,
    TaskTemplate,
    TaskTemplateEdge,
    TaskTemplateNode,
)
from schemas import (
    BatchOperationRequest,
    BatchOperationResponse,
    InstancePreflightIssue,
    InstancePreflightResponse,
    TaskEventResponse,
    TaskInstanceCreate,
    TaskInstanceNodeOverride,
    TaskInstanceResponse,
    TaskInstanceSchedule,
    TaskInstanceSimple,
    TaskInstanceUpdate,
    TaskMetricReport,
    TaskMetricResponse,
    TemplateMetricSummary,
)
from services.dag_executor import (
    DAGExecutor,
    record_agent_failure_event_independent,
    reconcile_stale_running_node_independent,
)
from services.runtime_fields import apply_runtime_overrides, build_container_start_request, pick_override
from services.scheduler import TaskScheduler
from services.order_sync import mark_orders_cancelled_for_instance
from services.port_plan import (
    extract_host_ports,
    find_running_port_conflict_records,
    format_running_port_conflict_message,
    get_business_address,
)
from services.auto_port_allocator import auto_allocate_ports
from services.instance_builder import resolve_port_values

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instances", tags=["instances"])


def _find_override(t_node: TaskTemplateNode, overrides: list[TaskInstanceNodeOverride]) -> TaskInstanceNodeOverride | None:
    for item in overrides:
        if item.template_node_id and item.template_node_id == t_node.id:
            return item
        if item.template_node_name and item.template_node_name == t_node.name:
            return item
    return None


def _find_instance_node_override(
    node: TaskInstanceNode, overrides: list[TaskInstanceNodeOverride]
) -> TaskInstanceNodeOverride | None:
    for item in overrides:
        if item.template_node_id and item.template_node_id == node.template_node_id:
            return item
        if item.template_node_name and item.template_node_name == node.name:
            return item
    return None


async def _cleanup_instance_runtime(db: AsyncSession, instance: TaskInstance) -> list[str]:
    """顺序删除各节点容器（AsyncSession 不支持并发 flush）。"""
    executor = DAGExecutor(db)
    errors: list[str] = []

    for node in instance.nodes:
        success, error = await executor.remove_node(node)
        if not success:
            errors.append(f"{node.name}: {error or 'Unknown error'}")
    return errors


async def _preflight_instance_plan(
    db: AsyncSession,
    node_plans: list[dict],
    exclude_instance_id: str | None = None,
    *,
    instance_id_for_events: str | None = None,
) -> InstancePreflightResponse:
    """Run port preflight against each node_agent.

    When `instance_id_for_events` is set (i.e. we are preflight-checking an
    existing instance, not creating a new one) a `task_event` is written
    whenever node_agent itself is unreachable / returns 5xx, so the
    failure trail is visible in the UI in addition to the HTTP response.
    """
    executor = DAGExecutor(db)
    conflicts: list[InstancePreflightIssue] = []
    warnings: list[InstancePreflightIssue] = []
    requested_ports_by_node: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for plan in node_plans:
        node_id = plan.get("node_id")
        if not node_id:
            conflicts.append(
                InstancePreflightIssue(
                    template_node_id=plan.get("template_node_id"),
                    template_node_name=plan.get("name"),
                    level="conflict",
                    message="未指定部署节点",
                )
            )
            continue

        machine = await executor.get_node_machine(node_id)
        if not machine:
            conflicts.append(
                InstancePreflightIssue(
                    template_node_id=plan.get("template_node_id"),
                    template_node_name=plan.get("name"),
                    node_id=node_id,
                    level="conflict",
                    message=f"部署节点不存在: {node_id}",
                )
            )
            continue

        ports = plan.get("ports") or {}
        network_mode = plan.get("network_mode") or "host"
        for host_port in extract_host_ports(ports, network_mode):
            host_port_text = str(host_port)
            key = (node_id, host_port_text)
            requested_ports_by_node.setdefault(key, []).append(
                (plan.get("template_node_id") or "", plan.get("name") or host_port_text)
            )

        success, result = await executor.agent_client.preflight_ports(
            management_ip=executor._get_agent_endpoint(machine),
            ports=ports,
            network_mode=network_mode,
            exclude_container_name=plan.get("container_name"),
        )
        if not success:
            if instance_id_for_events:
                # Use an INDEPENDENT session so the audit row survives a later
                # HTTPException(400) rollback of the request session.
                await record_agent_failure_event_independent(
                    instance_id=instance_id_for_events,
                    node_id=None,
                    node_status=None,
                    operation=f"preflight_ports({machine.hostname})",
                    result=result,
                )
            conflicts.append(
                InstancePreflightIssue(
                    template_node_id=plan.get("template_node_id"),
                    template_node_name=plan.get("name"),
                    node_id=node_id,
                    node_hostname=machine.hostname,
                    level="conflict",
                    message=result.get("error") or "节点预检查失败",
                )
            )
            continue

        for message in result.get("conflicts", []):
            conflicts.append(
                InstancePreflightIssue(
                    template_node_id=plan.get("template_node_id"),
                    template_node_name=plan.get("name"),
                    node_id=node_id,
                    node_hostname=machine.hostname,
                    level="conflict",
                    message=message,
                )
            )
        for message in result.get("warnings", []):
            warnings.append(
                InstancePreflightIssue(
                    template_node_id=plan.get("template_node_id"),
                    template_node_name=plan.get("name"),
                    node_id=node_id,
                    node_hostname=machine.hostname,
                    level="warning",
                    message=message,
                )
            )

    for (node_id, host_port), owners in requested_ports_by_node.items():
        if len(owners) <= 1:
            continue
        machine = await executor.get_node_machine(node_id)
        owner_names = "、".join(name for _template_id, name in owners)
        conflicts.append(
            InstancePreflightIssue(
                node_id=node_id,
                node_hostname=machine.hostname if machine else None,
                level="conflict",
                message=f"同一次部署中有多个节点尝试占用宿主机端口 {host_port}: {owner_names}",
            )
        )

    records = await find_running_port_conflict_records(
        db, node_plans, exclude_instance_id=exclude_instance_id
    )
    for record in records:
        existing_node = record["existing_node"]
        existing_instance = record["existing_instance"]
        overlap_text = ",".join(sorted(record["overlap"]))

        # On-demand reconcile: if the DB believes this node is running but
        # node_agent reports its container as removed, mark the stale row
        # stopped and skip the conflict so the new deployment can proceed.
        if await _reconcile_stale_running_node(
            executor=executor,
            existing_node=existing_node,
            existing_instance=existing_instance,
        ):
            continue

        conflicts.append(
            InstancePreflightIssue(
                level="conflict",
                message=format_running_port_conflict_message(
                    record["worker_id"],
                    overlap_text,
                    existing_instance.name,
                    existing_node.name,
                ),
            )
        )

    return InstancePreflightResponse(
        ok=not conflicts,
        conflicts=conflicts,
        warnings=warnings,
    )


# Status values that node_agent's /containers/{task}/{node}/status returns
# when the underlying docker container no longer exists on the worker.
_NODE_AGENT_REMOVED_STATUSES = frozenset({"not_found", "removed", "not_running"})


async def _reconcile_stale_running_node(
    *,
    executor: DAGExecutor,
    existing_node: TaskInstanceNode,
    existing_instance: TaskInstance,
) -> bool:
    """Return True iff the existing node was reconciled (DB updated to stopped).

    Decision matrix:
        * existing_node.container_id is blank -> nothing to reconcile, treat
          the DB record as authoritative and keep the conflict.
        * node_agent reports container removed/not_found -> update DB, write
          a `reconcile_stale_container` task_event, and signal the caller to
          drop this conflict.
        * node_agent says the container is still running -> keep the conflict.
        * node_agent is unreachable -> keep the conflict (do not silently
          believe stale DB rows could be right; also do not pretend the
          worker is healthy).
    """
    if not existing_node.container_id:
        return False

    machine = await executor.get_node_machine(existing_node.node_id)
    if not machine:
        return False

    try:
        status, _healthy, message = await executor.agent_client.get_container_status(
            management_ip=executor._get_agent_endpoint(machine),
            task_id=existing_node.instance_id,
            node_id=existing_node.id,
        )
    except Exception as exc:  # noqa: BLE001 - defensive, do not swallow silently
        logger.warning(
            "preflight reconcile: unable to reach node_agent for instance=%s node=%s: %s; "
            "keeping stale DB conflict",
            existing_node.instance_id,
            existing_node.id,
            exc,
        )
        return False

    if status in _NODE_AGENT_REMOVED_STATUSES:
        prior_container_id = existing_node.container_id
        prior_node_status = existing_node.status
        reconcile_message = (
            f"Reconciled stale instance state on {machine.hostname}: "
            f"container {prior_container_id} reported as {status} by node_agent; "
            f"marking node {existing_node.name} (was {prior_node_status}) and "
            f"instance 「{existing_instance.name}」 stopped"
        )
        # Persist the reconcile via an INDEPENDENT session. The request session
        # (executor.db) may still be rolled back by a later HTTPException(400)
        # if other conflicts in this preflight remain unreconcilable; the audit
        # row + the stale-row cleanup must survive that rollback.
        committed = await reconcile_stale_running_node_independent(
            existing_node_id=existing_node.id,
            existing_instance_id=existing_node.instance_id,
            message=reconcile_message,
        )
        if not committed:
            # Independent write failed; do NOT mutate in-memory state, do NOT
            # signal the conflict as resolved. Keep the conflict, log was
            # already emitted by the helper.
            return False
        # Mirror the committed state into the in-memory ORM objects so any
        # subsequent inspection within this request (e.g. response building)
        # sees the same values that landed in the DB.
        existing_node.container_id = None
        existing_node.container_name = None
        existing_node.status = NodeStatus.STOPPED
        existing_instance.status = TaskStatus.STOPPED
        return True

    if status == "unknown" or (isinstance(status, str) and status.startswith("error")):
        # node_agent itself reachable but reports an error path (HTTP 5xx
        # surfaced as status='unknown' by agent_client, or docker SDK error
        # bubbled through docker_handler). Do not modify DB.
        logger.warning(
            "preflight reconcile: node_agent returned status=%s message=%r for instance=%s node=%s; "
            "keeping stale DB conflict",
            status,
            message,
            existing_node.instance_id,
            existing_node.id,
        )
        return False

    return False


async def _build_preflight_plan_from_create(
    db: AsyncSession,
    payload: TaskInstanceCreate,
) -> list[dict]:
    template_result = await db.execute(
        select(TaskTemplate).where(TaskTemplate.id == payload.template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    nodes_result = await db.execute(
        select(TaskTemplateNode).where(TaskTemplateNode.template_id == payload.template_id)
    )
    template_nodes = nodes_result.scalars().all()

    plan: list[dict] = []
    for t_node in template_nodes:
        override = _find_override(t_node, payload.node_overrides)
        legacy_ports = override.ports if override and override.ports is not None else t_node.ports
        resolved_ports, _ = resolve_port_values(
            t_node.port_defs,
            override.port_values if override else None,
            legacy_ports,
        )
        plan.append(
            {
                "template_node_id": t_node.id,
                "name": override.name if override and override.name else t_node.name,
                "ports": resolved_ports or legacy_ports,
                "network_mode": override.network_mode if override and override.network_mode else t_node.network_mode,
                "node_id": override.node_id if override and override.node_id else t_node.node_id,
                "container_name": None,
            }
        )
    return plan


async def _build_preflight_plan_from_instance(instance: TaskInstance) -> list[dict]:
    return [
        {
            "template_node_id": node.template_node_id,
            "name": node.name,
            "ports": node.ports,
            "network_mode": node.network_mode,
            "node_id": node.node_id,
            "container_name": node.container_name,
        }
        for node in instance.nodes
    ]


async def _create_instance_from_template(
    db: AsyncSession,
    instance: TaskInstanceCreate,
    source_order_id: str | None = None,
) -> TaskInstance:
    template_result = await db.execute(
        select(TaskTemplate).where(TaskTemplate.id == instance.template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    status = TaskStatus.SCHEDULED if instance.deployment_mode == DeploymentMode.SCHEDULED else TaskStatus.PENDING
    db_instance = TaskInstance(
        template_id=instance.template_id,
        name=instance.name,
        status=status,
        deployment_mode=instance.deployment_mode,
        scheduled_start_time=instance.scheduled_start_time,
        scheduled_end_time=instance.scheduled_end_time,
        source_order_id=source_order_id,
        macro_values=instance.macro_values,
        keep_after_stop=instance.keep_after_stop,
    )
    db.add(db_instance)
    await db.flush()

    nodes_result = await db.execute(
        select(TaskTemplateNode).where(TaskTemplateNode.template_id == instance.template_id)
    )
    template_nodes = nodes_result.scalars().all()

    edges_result = await db.execute(
        select(TaskTemplateEdge).where(TaskTemplateEdge.template_id == instance.template_id)
    )
    template_edges = edges_result.scalars().all()

    instance_node_map: dict[str, str] = {}
    for t_node in template_nodes:
        override = _find_override(t_node, instance.node_overrides)
        legacy_ports = pick_override(t_node, override, "ports")

        # Auto-allocate ports for port_defs with auto=true
        user_port_values = override.port_values if override else None
        if t_node.port_defs and any(
            isinstance(pd, dict) and pd.get("auto") for pd in t_node.port_defs
        ):
            target_node_id = (override.node_id if override and override.node_id else t_node.node_id)
            machine = (await db.execute(
                select(NodeModel).where(NodeModel.id == target_node_id)
            )).scalar_one_or_none()
            if machine:
                agent_addr = machine.agent_address or f"http://{machine.management_ip}:8001"
                user_port_values = await auto_allocate_ports(
                    agent_address=agent_addr,
                    port_defs=t_node.port_defs,
                    existing_port_values=user_port_values,
                )

        resolved_ports, normalized_port_values = resolve_port_values(
            t_node.port_defs,
            user_port_values,
            legacy_ports,
        )
        db_node = TaskInstanceNode(
            instance_id=db_instance.id,
            template_node_id=t_node.id,
            name=override.name if override and override.name else t_node.name,
            image=override.image if override and override.image else t_node.image,
            command=override.command if override and override.command is not None else t_node.command,
            env=override.env if override and override.env is not None else t_node.env,
            volumes=pick_override(t_node, override, "volumes"),
            volume_mounts=pick_override(t_node, override, "volume_mounts"),
            port_defs=t_node.port_defs,
            port_values=normalized_port_values or None,
            ports=resolved_ports or legacy_ports,
            gpu_id=pick_override(t_node, override, "gpu_id"),
            cpu_limit=pick_override(t_node, override, "cpu_limit"),
            cpu_reservation=pick_override(t_node, override, "cpu_reservation"),
            cpu_shares=pick_override(t_node, override, "cpu_shares"),
            cpuset_cpus=pick_override(t_node, override, "cpuset_cpus"),
            cpu_quota=pick_override(t_node, override, "cpu_quota"),
            cpu_period=pick_override(t_node, override, "cpu_period"),
            memory_limit=pick_override(t_node, override, "memory_limit"),
            memory_reservation=pick_override(t_node, override, "memory_reservation"),
            memory_swap_limit=pick_override(t_node, override, "memory_swap_limit"),
            network_mode=override.network_mode if override and override.network_mode else t_node.network_mode,
            restart_policy=override.restart_policy if override and override.restart_policy else t_node.restart_policy,
            health_check=override.health_check if override and override.health_check is not None else t_node.health_check,
            node_id=override.node_id if override and override.node_id else t_node.node_id,
            status=NodeStatus.PENDING,
        )
        db.add(db_node)
        await db.flush()
        instance_node_map[t_node.id] = db_node.id

    for t_edge in template_edges:
        db_edge = TaskInstanceEdge(
            instance_id=db_instance.id,
            from_node_id=instance_node_map.get(t_edge.from_node_id, t_edge.from_node_id),
            to_node_id=instance_node_map.get(t_edge.to_node_id, t_edge.to_node_id),
        )
        db.add(db_edge)

    if instance.deployment_mode == DeploymentMode.SCHEDULED:
        if not instance.scheduled_start_time:
            raise HTTPException(status_code=400, detail="scheduled_start_time is required for scheduled mode")
        task_scheduler = TaskScheduler()
        await task_scheduler.schedule_task_start(db_instance.id, instance.scheduled_start_time)
        if instance.scheduled_end_time:
            await task_scheduler.schedule_task_end(db_instance.id, instance.scheduled_end_time)

    if instance.auto_start and instance.deployment_mode == DeploymentMode.IMMEDIATE:
        # Commit instance so sink's metric-report API calls (from containers) can query it
        await db.commit()
        preflight = await _preflight_instance_plan(db, await _build_preflight_plan_from_create(db, instance))
        if not preflight.ok:
            messages = "; ".join(issue.message for issue in preflight.conflicts)
            raise HTTPException(status_code=400, detail=f"启动前预检查失败: {messages}")
        executor = DAGExecutor(db)
        success, error = await executor.execute_dag_start(db_instance.id)
        if not success:
            raise HTTPException(status_code=500, detail=error or "Failed to start instance")

    await db.commit()
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == db_instance.id)
    )
    return result.scalar_one()


@router.post("", response_model=TaskInstanceResponse)
async def create_instance(
    instance: TaskInstanceCreate,
    db: AsyncSession = Depends(get_db),
):
    return await _create_instance_from_template(db, instance=instance)


@router.post("/preflight", response_model=InstancePreflightResponse)
async def preflight_instance_create(
    payload: TaskInstanceCreate,
    db: AsyncSession = Depends(get_db),
):
    plan = await _build_preflight_plan_from_create(db, payload)
    return await _preflight_instance_plan(db, plan)


@router.get("", response_model=list[TaskInstanceSimple])
async def list_instances(
    status: str | None = Query(None),
    template_id: str | None = Query(None),
    deployment_mode: str | None = Query(None),
    source_order_id: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(TaskInstance).options(selectinload(TaskInstance.nodes))
    if status:
        query = query.where(TaskInstance.status == status)
    if template_id:
        query = query.where(TaskInstance.template_id == template_id)
    if deployment_mode:
        query = query.where(TaskInstance.deployment_mode == deployment_mode)
    if source_order_id:
        query = query.where(TaskInstance.source_order_id == source_order_id)
    if q:
        query = query.where(TaskInstance.name.ilike(f"%{q}%"))
    query = query.order_by(TaskInstance.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{instance_id}", response_model=TaskInstanceResponse)
async def get_instance(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Enrich nodes with business_address
    for inst_node in instance.nodes:
        machine = (await db.execute(
            select(NodeModel).where(NodeModel.id == inst_node.node_id)
        )).scalar_one_or_none()
        if machine:
            object.__setattr__(inst_node, "business_address", get_business_address(machine))
        else:
            object.__setattr__(inst_node, "business_address", None)

    return instance


@router.put("/{instance_id}", response_model=TaskInstanceResponse)
async def update_instance(
    instance_id: str,
    payload: TaskInstanceUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    is_runtime_locked = instance.status in (
        TaskStatus.RUNNING,
        TaskStatus.STARTING,
        TaskStatus.STOPPING,
    )

    if is_runtime_locked:
        if payload.scheduled_start_time is not None or payload.scheduled_end_time is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot update schedule while instance is running/starting/stopping",
            )
        if payload.node_overrides:
            raise HTTPException(
                status_code=400,
                detail="Cannot update node runtime parameters while instance is running/starting/stopping",
            )

    if payload.name is not None:
        instance.name = payload.name
    if payload.keep_after_stop is not None:
        instance.keep_after_stop = payload.keep_after_stop
    if not is_runtime_locked:
        instance.scheduled_start_time = payload.scheduled_start_time
        instance.scheduled_end_time = payload.scheduled_end_time
        if payload.macro_values is not None:
            instance.macro_values = payload.macro_values

    template_nodes_result = await db.execute(
        select(TaskTemplateNode).where(TaskTemplateNode.template_id == instance.template_id)
    )
    template_nodes_by_id = {n.id: n for n in template_nodes_result.scalars().all()}

    if (
        not is_runtime_locked
        and payload.scheduled_start_time
        and instance.status == TaskStatus.PENDING
    ):
        instance.status = TaskStatus.SCHEDULED
        task_scheduler = TaskScheduler()
        await task_scheduler.schedule_task_start(instance_id, payload.scheduled_start_time)
        if payload.scheduled_end_time:
            await task_scheduler.schedule_task_end(instance_id, payload.scheduled_end_time)

    for node in instance.nodes:
        override = _find_instance_node_override(node, payload.node_overrides)
        if not override:
            continue
        if override.name is not None:
            node.name = override.name
        if override.image is not None:
            node.image = override.image
        if override.command is not None:
            node.command = override.command
        if override.env is not None:
            node.env = override.env
        apply_runtime_overrides(node, override)
        if override.port_values is not None:
            t_node = template_nodes_by_id.get(node.template_node_id)
            port_defs = node.port_defs or (t_node.port_defs if t_node else None)
            resolved_ports, normalized_port_values = resolve_port_values(
                port_defs,
                override.port_values,
                override.ports if override.ports is not None else node.ports,
            )
            node.port_values = normalized_port_values or None
            if resolved_ports:
                node.ports = resolved_ports

    await db.commit()
    await db.refresh(instance)
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == instance_id)
    )
    return result.scalar_one()


@router.delete("/{instance_id}")
async def delete_instance(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    task_scheduler = TaskScheduler()
    await task_scheduler.cancel_all_schedules(instance_id)
    cleanup_warnings = await _cleanup_instance_runtime(db, instance)
    await mark_orders_cancelled_for_instance(db, instance_id)

    await db.delete(instance)
    await db.commit()
    response = {"message": "Instance deleted"}
    if cleanup_warnings:
        response["warnings"] = cleanup_warnings
    return response


@router.post("/{instance_id}/start")
async def start_instance(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
        return {"message": "Instance already running"}
    if instance.status not in (TaskStatus.PENDING, TaskStatus.SCHEDULED, TaskStatus.STOPPED, TaskStatus.FAILED):
        raise HTTPException(status_code=400, detail=f"Cannot start instance in status: {instance.status}")
    preflight = await _preflight_instance_plan(
        db,
        await _build_preflight_plan_from_instance(instance),
        exclude_instance_id=instance_id,
        instance_id_for_events=instance_id,
    )
    if not preflight.ok:
        messages = "; ".join(issue.message for issue in preflight.conflicts)
        raise HTTPException(status_code=400, detail=f"启动前预检查失败: {messages}")
    executor = DAGExecutor(db)
    success, error = await executor.execute_dag_start(instance_id)
    if not success:
        raise HTTPException(status_code=500, detail=error)
    return {"message": "Instance started"}


@router.post("/{instance_id}/stop")
async def stop_instance(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status in (TaskStatus.STOPPED, TaskStatus.PENDING):
        return {"message": "Instance already stopped"}
    executor = DAGExecutor(db)
    success, error = await executor.execute_dag_stop(instance_id)
    if not success:
        raise HTTPException(status_code=500, detail=error)
    return {"message": "Instance stopped"}


@router.post("/{instance_id}/restart")
async def restart_instance(instance_id: str, db: AsyncSession = Depends(get_db)):
    await stop_instance(instance_id, db)
    return await start_instance(instance_id, db)


@router.post("/batch/start", response_model=BatchOperationResponse)
async def batch_start_instances(request: BatchOperationRequest, db: AsyncSession = Depends(get_db)):
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for instance_id in request.instance_ids:
        try:
            executor = DAGExecutor(db)
            success, error = await executor.execute_dag_start(instance_id)
            if success:
                succeeded.append(instance_id)
            else:
                failed[instance_id] = error or "Unknown error"
        except HTTPException as exc:
            failed[instance_id] = str(exc.detail)
        except Exception as exc:
            failed[instance_id] = str(exc)
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/batch/stop", response_model=BatchOperationResponse)
async def batch_stop_instances(request: BatchOperationRequest, db: AsyncSession = Depends(get_db)):
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for instance_id in request.instance_ids:
        try:
            executor = DAGExecutor(db)
            success, error = await executor.execute_dag_stop(instance_id)
            if success:
                succeeded.append(instance_id)
            else:
                failed[instance_id] = error or "Unknown error"
        except Exception as exc:
            failed[instance_id] = str(exc)
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/batch/delete", response_model=BatchOperationResponse)
async def batch_delete_instances(request: BatchOperationRequest, db: AsyncSession = Depends(get_db)):
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    task_scheduler = TaskScheduler()
    for instance_id in request.instance_ids:
        try:
            result = await db.execute(
                select(TaskInstance)
                .options(selectinload(TaskInstance.nodes))
                .where(TaskInstance.id == instance_id)
            )
            instance = result.scalar_one_or_none()
            if not instance:
                failed[instance_id] = "Instance not found"
                continue

            await task_scheduler.cancel_all_schedules(instance_id)
            await _cleanup_instance_runtime(db, instance)
            await mark_orders_cancelled_for_instance(db, instance_id)
            await db.delete(instance)
            succeeded.append(instance_id)
        except Exception as exc:
            failed[instance_id] = str(exc)
    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.put("/{instance_id}/schedule")
async def schedule_instance(instance_id: str, schedule: TaskInstanceSchedule, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    instance.scheduled_start_time = schedule.scheduled_start_time
    instance.scheduled_end_time = schedule.scheduled_end_time
    if schedule.keep_after_stop is not None:
        instance.keep_after_stop = schedule.keep_after_stop
    if schedule.scheduled_start_time:
        instance.status = TaskStatus.SCHEDULED
        task_scheduler = TaskScheduler()
        await task_scheduler.schedule_task_start(instance_id, schedule.scheduled_start_time)
    if schedule.scheduled_end_time:
        task_scheduler = TaskScheduler()
        await task_scheduler.schedule_task_end(instance_id, schedule.scheduled_end_time)
    await db.commit()
    return {"message": "Schedule updated"}


@router.get("/{instance_id}/events", response_model=list[TaskEventResponse])
async def get_instance_events(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskEvent).where(TaskEvent.instance_id == instance_id).order_by(TaskEvent.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{instance_id}/nodes/{node_id}/logs")
async def get_node_logs(instance_id: str, node_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance_id).where(TaskInstanceNode.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    from agents.agent_client import AgentClient
    node_result = await db.execute(select(NodeModel).where(NodeModel.id == node.node_id))
    machine = node_result.scalar_one_or_none()
    if not machine:
        raise HTTPException(status_code=404, detail="Node machine not found")
    logs, error = await AgentClient().get_container_logs(
        management_ip=machine.agent_address or machine.management_ip,
        task_id=instance_id,
        node_id=node_id,
    )
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"logs": logs or ""}


_ALLOWED_METRIC_TAGS = frozenset([
    "result", "objects", "object_uris",
    "compute_latency_ms", "matrix_size", "batch_count", "seed",
    "end_to_end_latency_ms", "codec", "preset",
])


def _trim_metric_tags(tags: dict | None) -> dict | None:
    """
    在写入 TaskMetric 之前，从 tags 中移除敏感或过大字段（主要是 checksum）。
    保留白名单 keys 和顶层结构；删除 result.checksum 等深层敏感字段。
    """
    if not tags:
        return None
    allowed = _ALLOWED_METRIC_TAGS
    result: dict = {}
    for key, val in tags.items():
        if key not in allowed:
            continue
        if isinstance(val, dict):
            filtered = {k: v for k, v in val.items() if k not in ("checksum", "result_json", "raw")}
            if filtered:
                result[key] = filtered
        else:
            result[key] = val
    return result if result else None


@router.post("/{instance_id}/metrics", response_model=TaskMetricResponse)
async def report_metric(instance_id: str, payload: TaskMetricReport, db: AsyncSession = Depends(get_db)):
    instance_result = await db.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    instance = instance_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    metric = TaskMetric(
        instance_id=instance_id,
        template_id=instance.template_id,
        node_instance_id=payload.node_instance_id,
        metric_key=payload.metric_key,
        metric_value=payload.metric_value,
        unit=payload.unit,
        tags=_trim_metric_tags(payload.tags),
        reported_at=payload.reported_at or datetime.utcnow(),
    )
    db.add(metric)
    from api.business_tasks import evaluate_and_store_business_metric

    await evaluate_and_store_business_metric(
        db,
        instance_id=instance_id,
        metric_key=payload.metric_key,
        metric_value=payload.metric_value,
        tags=payload.tags,
    )
    await db.commit()
    await db.refresh(metric)
    return metric


@router.get("/metrics/template-summary", response_model=list[TemplateMetricSummary])
async def template_metric_summary(template_id: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(
        TaskMetric.template_id,
        TaskMetric.metric_key,
        func.count(TaskMetric.id),
        func.avg(TaskMetric.metric_value),
        func.min(TaskMetric.metric_value),
        func.max(TaskMetric.metric_value),
    ).group_by(TaskMetric.template_id, TaskMetric.metric_key)
    if template_id:
        query = query.where(TaskMetric.template_id == template_id)
    rows = (await db.execute(query)).all()
    return [
        TemplateMetricSummary(
            template_id=row[0],
            metric_key=row[1],
            count=row[2],
            avg=float(row[3]),
            min=float(row[4]),
            max=float(row[5]),
        )
        for row in rows
    ]
