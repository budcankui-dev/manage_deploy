from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
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
from services.dag_executor import DAGExecutor
from services.scheduler import TaskScheduler

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


async def _cleanup_instance_runtime(db: AsyncSession, instance: TaskInstance) -> None:
    executor = DAGExecutor(db)
    cleanup_errors: list[str] = []

    for node in instance.nodes:
        success, error = await executor.remove_node(node)
        if not success:
            cleanup_errors.append(f"{node.name}: {error or 'Unknown error'}")

    if cleanup_errors:
        raise HTTPException(
            status_code=500,
            detail="Failed to clean up node containers: " + "; ".join(cleanup_errors),
        )


async def _preflight_instance_plan(
    db: AsyncSession,
    node_plans: list[dict],
) -> InstancePreflightResponse:
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
        for container_port, host_port in ports.items():
            host_port_text = str(host_port).strip()
            if not host_port_text:
                continue
            key = (node_id, host_port_text)
            requested_ports_by_node.setdefault(key, []).append(
                (plan.get("template_node_id") or "", plan.get("name") or str(container_port))
            )

        success, result = await executor.agent_client.preflight_ports(
            management_ip=executor._get_agent_endpoint(machine),
            ports=ports,
            network_mode=plan.get("network_mode") or "bridge",
            exclude_container_name=plan.get("container_name"),
        )
        if not success:
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

    return InstancePreflightResponse(
        ok=not conflicts,
        conflicts=conflicts,
        warnings=warnings,
    )


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
        plan.append(
            {
                "template_node_id": t_node.id,
                "name": override.name if override and override.name else t_node.name,
                "ports": override.ports if override and override.ports is not None else t_node.ports,
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
        scheduled_start_time=instance.scheduled_start_time,
        scheduled_end_time=instance.scheduled_end_time,
        source_order_id=source_order_id,
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
        db_node = TaskInstanceNode(
            instance_id=db_instance.id,
            template_node_id=t_node.id,
            name=override.name if override and override.name else t_node.name,
            image=override.image if override and override.image else t_node.image,
            command=override.command if override and override.command is not None else t_node.command,
            env=override.env if override and override.env is not None else t_node.env,
            volumes=override.volumes if override and override.volumes is not None else t_node.volumes,
            ports=override.ports if override and override.ports is not None else t_node.ports,
            gpu_id=override.gpu_id if override and override.gpu_id is not None else t_node.gpu_id,
            cpu_limit=override.cpu_limit if override and override.cpu_limit is not None else t_node.cpu_limit,
            memory_limit=override.memory_limit if override and override.memory_limit is not None else t_node.memory_limit,
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(TaskInstance).options(selectinload(TaskInstance.nodes)))
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
    if not is_runtime_locked:
        instance.scheduled_start_time = payload.scheduled_start_time
        instance.scheduled_end_time = payload.scheduled_end_time

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
        if override.volumes is not None:
            node.volumes = override.volumes
        if override.ports is not None:
            node.ports = override.ports
        if override.gpu_id is not None:
            node.gpu_id = override.gpu_id
        if override.cpu_limit is not None:
            node.cpu_limit = override.cpu_limit
        if override.memory_limit is not None:
            node.memory_limit = override.memory_limit
        if override.network_mode is not None:
            node.network_mode = override.network_mode
        if override.restart_policy is not None:
            node.restart_policy = override.restart_policy
        if override.health_check is not None:
            node.health_check = override.health_check
        if override.node_id is not None:
            node.node_id = override.node_id

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
    await _cleanup_instance_runtime(db, instance)

    await db.delete(instance)
    await db.commit()
    return {"message": "Instance deleted"}


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
    if instance.status not in (TaskStatus.PENDING, TaskStatus.STOPPED, TaskStatus.FAILED):
        raise HTTPException(status_code=400, detail=f"Cannot start instance in status: {instance.status}")
    preflight = await _preflight_instance_plan(db, await _build_preflight_plan_from_instance(instance))
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
        tags=payload.tags,
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
