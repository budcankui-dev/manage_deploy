import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from enums import DeploymentMode, OrderStatus, TaskStatus
from models import (
    BusinessObjectiveEvaluation,
    BusinessTemplateCatalog,
    Node as NodeModel,
    NodeBaseline,
    TaskOrder,
    TaskResultObject,
    User,
)
from api.auth import get_current_user
from schemas import (
    BusinessObjective,
    BusinessObjectiveEvaluationResponse,
    BusinessObjectiveEvaluationResult,
    BusinessTaskCreate,
    BusinessTaskListResponse,
    BusinessTaskResponse,
    BusinessTemplateCatalogCreate,
    BusinessTemplateCatalogResponse,
    TaskInstanceCreate,
    TaskInstanceNodeOverride,
    TaskResultObjectResponse,
)
from services.business_evaluator import evaluate_business_objective
from services.business_task_query import (
    BusinessTaskListFilters,
    list_business_tasks,
    summarize_business_tasks,
)

from .instances import _create_instance_from_template

router = APIRouter(prefix="/api", tags=["business-tasks"])

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _is_uuid(value: str) -> bool:
    return bool(UUID_PATTERN.match(value))


async def _resolve_hostname_to_uuid(db: AsyncSession, hostname: str) -> str:
    """Resolve hostname to node UUID. Raises HTTPException if not found."""
    result = await db.execute(select(NodeModel).where(NodeModel.hostname == hostname))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {hostname}")
    return node.id


async def build_instance_create_from_business_task(
    db: AsyncSession,
    payload: BusinessTaskCreate,
    template_id: str,
    role_node_names: dict[str, str],
) -> TaskInstanceCreate:
    shared_env = {
        "BUSINESS_TASK_ID": payload.external_task_id,
        "TASK_TYPE": payload.task_type,
        "MODALITY": payload.modality or "",
        "DATA_PROFILE": _json_env(payload.data_profile),
        "BUSINESS_OBJECTIVE": payload.business_objective.model_dump_json(),
        "RUNTIME_PLAN": _json_env(payload.runtime_plan),
        "RESOURCE_REQUIREMENT": _json_env(payload.resource_requirement),
        "ROUTING_RESULT": payload.routing_result.model_dump_json(),
        "RESULT_STORAGE": _json_env(payload.result_storage),
    }
    if payload.task_type == "high_throughput_matmul":
        shared_env["USE_GPU"] = "true"
    overrides: list[TaskInstanceNodeOverride] = []
    gpu_roles = set()
    if payload.task_type == "high_throughput_matmul":
        gpu_roles.add("compute")
    elif payload.task_type == "low_latency_video_pipeline":
        gpu_roles.add("compute")
    elif payload.task_type == "llm_text_generation":
        gpu_roles.add("compute")
    for role, template_node_name in role_node_names.items():
        placement = payload.routing_result.placements.get(role)
        if role == "compute" and placement is None:
            placement = payload.routing_result.placements.get("worker")
        raw_node_id = _placement_node_name(placement)
        if not raw_node_id:
            raise HTTPException(status_code=400, detail=f"Missing placement for role: {role}")
        if _is_uuid(raw_node_id):
            node_id = raw_node_id
        else:
            node_id = await _resolve_hostname_to_uuid(db, raw_node_id)
        env = dict(shared_env)
        env["TASK_ROLE"] = role
        placement_gpu_id = _placement_gpu_id(placement)
        gpu_id = placement_gpu_id if placement_gpu_id is not None else ("all" if role in gpu_roles else None)
        if placement_gpu_id is not None:
            env["GPU_DEVICE"] = placement_gpu_id
        overrides.append(
            TaskInstanceNodeOverride(
                template_node_name=template_node_name,
                node_id=node_id,
                env=env,
                gpu_id=gpu_id,
            )
        )

    # 业务任务一律 SCHEDULED + 强制 end_time（未传则取 now + default_scheduled_duration_hours）。
    # scheduled_start_time = now() 既保留"立即跑"的体验，又借用现成的 schedule_task_start。
    now = datetime.utcnow()
    hours = max(1, int(settings.default_scheduled_duration_hours or 2))
    end_time = payload.scheduled_end_time or (now + timedelta(hours=hours))

    return TaskInstanceCreate(
        template_id=template_id,
        name=payload.name or f"{payload.task_type}-{payload.external_task_id}",
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=now,
        scheduled_end_time=end_time,
        auto_start=False,
        keep_after_stop=payload.keep_after_stop,
        node_overrides=overrides,
    )


@router.post("/business-template-catalog", response_model=BusinessTemplateCatalogResponse)
async def create_business_template_catalog(
    payload: BusinessTemplateCatalogCreate,
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == payload.task_type)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="task_type already exists")

    row = BusinessTemplateCatalog(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/business-template-catalog", response_model=list[BusinessTemplateCatalogResponse])
async def list_business_template_catalog(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(BusinessTemplateCatalog).order_by(BusinessTemplateCatalog.task_type.asc()))
    return rows.scalars().all()


@router.put("/business-template-catalog/{task_type}", response_model=BusinessTemplateCatalogResponse)
async def upsert_business_template_catalog(
    task_type: str,
    payload: BusinessTemplateCatalogCreate,
    db: AsyncSession = Depends(get_db),
):
    if payload.task_type != task_type:
        raise HTTPException(status_code=400, detail="task_type in body must match path")
    result = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == task_type)
    )
    row = result.scalar_one_or_none()
    if row:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    else:
        row = BusinessTemplateCatalog(**payload.model_dump())
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/business-tasks", response_model=BusinessTaskResponse)
async def create_business_task(payload: BusinessTaskCreate, db: AsyncSession = Depends(get_db)):
    existing_order = await db.execute(
        select(TaskOrder).where(TaskOrder.external_task_id == payload.external_task_id)
    )
    if existing_order.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="external_task_id already exists")

    catalog = await _get_catalog(db, payload.task_type)
    role_node_names = {
        "source": catalog.source_node_name,
        "compute": catalog.compute_node_name,
        "sink": catalog.sink_node_name,
    }
    instance_create = await build_instance_create_from_business_task(
        db,
        payload,
        template_id=catalog.template_id,
        role_node_names=role_node_names,
    )

    order = TaskOrder(
        external_task_id=payload.external_task_id,
        template_id=catalog.template_id,
        name=instance_create.name,
        description=payload.description,
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=instance_create.scheduled_start_time,
        scheduled_end_time=instance_create.scheduled_end_time,
        auto_start=False,
        keep_after_stop=payload.keep_after_stop,
        runtime_config={
            "business_task": payload.model_dump(mode="json"),
            "node_overrides": [item.model_dump() for item in instance_create.node_overrides],
        },
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    try:
        instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)
        order.materialized_instance_id = instance.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
        await db.commit()
        return BusinessTaskResponse(
            order_id=order.id,
            instance_id=instance.id,
            task_type=payload.task_type,
            status="materialized",
        )
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = str(exc)
        await db.commit()
        raise


@router.get("/business-tasks", response_model=BusinessTaskListResponse)
async def list_business_tasks_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: str | None = None,
    routing_policy: str | None = None,
    order_status: OrderStatus | None = None,
    deployment_status: TaskStatus | None = None,
    business_success: bool | None = None,
    q: str | None = None,
    include_cancelled: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = None if current_user.role == "admin" else current_user.id
    filters = BusinessTaskListFilters(
        page=page,
        page_size=page_size,
        task_type=task_type,
        routing_policy=routing_policy,
        order_status=order_status,
        deployment_status=deployment_status,
        business_success=business_success,
        q=q,
        include_cancelled=include_cancelled,
    )
    return await list_business_tasks(db, filters, user_id=user_id)


@router.get("/business-tasks/{instance_id}/evaluation", response_model=BusinessObjectiveEvaluationResponse)
async def get_business_task_evaluation(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BusinessObjectiveEvaluation)
        .where(BusinessObjectiveEvaluation.instance_id == instance_id)
        .order_by(BusinessObjectiveEvaluation.created_at.desc())
    )
    row = result.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Business evaluation not found")
    return row


@router.get("/business-tasks/{instance_id}/results", response_model=list[TaskResultObjectResponse])
async def list_business_task_results(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskResultObject)
        .where(TaskResultObject.instance_id == instance_id)
        .order_by(TaskResultObject.created_at.asc())
    )
    return result.scalars().all()


@router.get("/business-tasks/summary")
async def business_task_summary(
    is_benchmark: bool | None = None,
    benchmark_run_id: str | None = None,
    task_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await summarize_business_tasks(
        db,
        is_benchmark=is_benchmark,
        benchmark_run_id=benchmark_run_id,
        task_type=task_type,
    )


async def _lookup_baseline(
    db: AsyncSession,
    routing_result: dict[str, Any],
    task_type: str | None,
    metric_key: str,
) -> float | None:
    """Look up baseline value for the worker node used in this task."""
    if not task_type:
        return None
    placements = routing_result.get("placements") or []
    # placements is a list of {"node_id": role, "worker_host": hostname}
    worker_host = None
    if isinstance(placements, list):
        for p in placements:
            if p.get("node_id") in ("compute", "worker"):
                worker_host = p.get("worker_host")
                break
    elif isinstance(placements, dict):
        worker_host = _placement_node_name(placements.get("worker") or placements.get("compute"))
    if not worker_host:
        return None
    # Resolve hostname/display name/UUID to node_id.
    node = (
        await db.execute(
            select(NodeModel).where(
                (NodeModel.id == worker_host)
                | (NodeModel.hostname == worker_host)
                | (NodeModel.display_name == worker_host)
            )
        )
    ).scalar_one_or_none()
    if not node:
        return None
    baseline = (
        await db.execute(
            select(NodeBaseline).where(
                NodeBaseline.node_id == node.id,
                NodeBaseline.task_type == task_type,
                NodeBaseline.metric_key == metric_key,
            )
        )
    ).scalar_one_or_none()
    return baseline.baseline_value if baseline else None


def _placement_node_name(placement: Any) -> str | None:
    if isinstance(placement, str):
        return placement
    if isinstance(placement, dict):
        for key in ("node_id", "node_name", "worker_host", "hostname"):
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


async def evaluate_and_store_business_metric(
    db: AsyncSession,
    instance_id: str,
    metric_key: str,
    metric_value: float,
    tags: dict[str, Any] | None,
) -> BusinessObjectiveEvaluation | None:
    order = await _get_order_for_instance(db, instance_id)
    if not order or not order.runtime_config:
        return None

    business_task = order.runtime_config.get("business_task") or order.runtime_config.get("extra")
    if not business_task:
        return None

    objective_data = business_task.get("business_objective")
    if not objective_data:
        return None

    objective = BusinessObjective(**objective_data)
    routing_result = order.runtime_config.get("routing_result") or business_task.get("routing_result") or {}
    estimated_metric = routing_result.get("estimated_metric") or {}
    estimated_value = estimated_metric.get("metric_value")
    object_uris = _extract_object_uris(tags)
    result_metadata = _extract_result_metadata(tags)

    # Look up baseline value for the worker node
    baseline_value = await _lookup_baseline(
        db,
        routing_result=routing_result,
        task_type=business_task.get("task_type"),
        metric_key=metric_key,
    )

    existing = (
        await db.execute(
            select(BusinessObjectiveEvaluation).where(
                BusinessObjectiveEvaluation.instance_id == instance_id,
                BusinessObjectiveEvaluation.metric_key == metric_key,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    evaluation = evaluate_business_objective(
        objective,
        actual_metric_key=metric_key,
        actual_value=metric_value,
        object_uris=object_uris,
        task_type=business_task.get("task_type"),
        estimated_value=estimated_value,
        baseline_value=baseline_value,
    )
    if evaluation.target_value is None:
        return None
    row = BusinessObjectiveEvaluation(
        instance_id=instance_id,
        task_type=business_task.get("task_type") or "unknown",
        routing_strategy=routing_result.get("strategy"),
        metric_key=evaluation.metric_key,
        actual_value=evaluation.actual_value,
        target_value=evaluation.target_value,
        operator=evaluation.operator,
        unit=evaluation.unit,
        business_success=evaluation.business_success,
        failure_reason=evaluation.failure_reason,
        estimated_value=evaluation.estimated_value,
        estimation_error_ratio=evaluation.estimation_error_ratio,
        object_uris={"uris": evaluation.object_uris, "result_metadata": result_metadata},
    )
    db.add(row)
    for obj in _extract_objects(tags):
        db.add(
            TaskResultObject(
                instance_id=instance_id,
                name=obj["name"],
                uri=obj["uri"],
                content_type=obj.get("content_type"),
            )
        )
    await db.flush()
    return row


async def _get_catalog(db: AsyncSession, task_type: str) -> BusinessTemplateCatalog:
    result = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == task_type)
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=404, detail=f"Business template catalog not found: {task_type}")
    return catalog


async def _get_order_for_instance(db: AsyncSession, instance_id: str) -> TaskOrder | None:
    result = await db.execute(select(TaskOrder).where(TaskOrder.materialized_instance_id == instance_id))
    return result.scalar_one_or_none()


def _json_env(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _extract_objects(tags: dict[str, Any] | None) -> list[dict[str, str]]:
    if not tags:
        return []
    raw_objects = tags.get("objects")
    if isinstance(raw_objects, list):
        return [
            item
            for item in raw_objects
            if isinstance(item, dict) and item.get("name") and item.get("uri")
        ]
    raw_uris = tags.get("object_uris") or []
    if isinstance(raw_uris, list):
        return [
            {"name": uri.rsplit("/", 1)[-1] or "object", "uri": uri}
            for uri in raw_uris
            if isinstance(uri, str)
        ]
    return []


def _extract_object_uris(tags: dict[str, Any] | None) -> list[str]:
    return [item["uri"] for item in _extract_objects(tags)]


def _extract_result_metadata(tags: dict[str, Any] | None) -> dict[str, Any]:
    if not tags:
        return {}
    raw = tags.get("result")
    if isinstance(raw, dict):
        return {
            key: raw[key]
            for key in (
                "compute_latency_ms",
                "effective_gflops",
                "matrix_size",
                "batch_count",
                "seed",
                "aggregation",
                "mean_effective_gflops",
                "min_effective_gflops",
                "max_effective_gflops",
                "observation_duration_sec",
                "observed_duration_sec",
                "sample_interval_sec",
                "sample_batch_count",
                "warmup_batches",
                "sample_count",
                "min_samples",
                "samples",
            )
            if raw.get(key) is not None
        }
    metadata: dict[str, Any] = {}
    for key in ("compute_latency_ms", "matrix_size", "batch_count", "seed"):
        if tags.get(key) is not None:
            metadata[key] = tags[key]
    return metadata


__all__ = ["build_instance_create_from_business_task", "evaluate_business_objective"]
