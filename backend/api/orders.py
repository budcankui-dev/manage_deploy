import asyncio
import random
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from api.auth import get_current_user
from config import settings
from database import get_db
from enums import DeploymentMode, OrderStatus, RoutingStatus, TaskStatus, UserRole
from models import (
    BusinessObjectiveEvaluation,
    BusinessTemplateCatalog,
    Node as NodeModel,
    TaskInstance,
    TaskInstanceNode,
    TaskOrder,
    User,
)
from schemas import (
    BatchOperationRequest,
    BatchOperationResponse,
    TaskInstanceCreate,
    TaskInstanceNodeOverride,
    TaskOrderCreate,
    TaskOrderDetailResponse,
    TaskOrderEvaluationSummary,
    TaskOrderInstanceSummary,
    TaskOrderNodePlacementSummary,
    TaskOrderResponse,
)
from services.business_task_query import get_order_detail_context
from services.dag_executor import DAGExecutor
from services.order_materialize import _resolve_node_id
from services.instance_lifecycle import cleanup_instance_runtime
from services.order_sync import (
    mark_orders_completed_for_instance,
    purge_instance_artifacts_preserve_evidence,
    purge_order_instance_artifacts,
    reconcile_orphan_orders,
)
from services.port_plan import format_service_url, get_business_address
from services.routing_payload_builder import build_routing_payload
from services.scheduler import TaskScheduler

from .instances import _create_instance_from_template

router = APIRouter(prefix="/api/orders", tags=["orders"])


BENCHMARK_TASK_CONFIGS = {
    "high_throughput_matmul": {
        "label": "矩阵乘法计算任务",
        "modality": "high_throughput_compute",
        "default_profile": {
            "profile_id": "gpu_standard",
            "matrix_size": 1024,
            "batch_count": 50,
            "seed": 42,
            "warmup_batches": 3,
            "observation_duration_sec": 10,
            "sample_interval_sec": 1,
            "sample_batch_count": 5,
            "min_samples": 5,
            "max_samples": 12,
        },
        "business_objective": {
            "metric_key": "effective_gflops",
            "operator": ">=",
            "unit": "GFLOPS",
        },
        "default_compute_gpu": "0",
        "source_name": "benchmark-source",
        "destination_name": "benchmark-sink",
    },
    "low_latency_video_pipeline": {
        "label": "视频AI推理任务",
        "modality": "low_latency_forwarding",
        "default_profile": {
            "profile_id": "video_industrial_inspection_720p",
            "frame_count": 100,
            "resolution": "720p",
            "fps": 30,
            "frame_stride": 30,
            "warmup_frames": 10,
            "measured_frames": 30,
            "work_units": 45000,
            "seed": 42,
            "video_asset": "bottle-detection.mp4",
            "inference_mode": "yolo_onnx",
            "model_name": "yolov5n",
            "model_path": "models/yolov5n.onnx",
            "class_names_path": "models/coco.names",
            "confidence_threshold": 0.25,
            "nms_threshold": 0.45,
            "max_detections": 8,
        },
        "business_objective": {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "unit": "ms",
        },
        "default_compute_gpu": "0",
        "source_name": "benchmark-video-source",
        "destination_name": "benchmark-video-sink",
    },
}


def _benchmark_run_id(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    benchmark = config.get("benchmark")
    if isinstance(benchmark, dict):
        value = benchmark.get("run_id")
        return str(value) if value else None
    return None


def _benchmark_task_type(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        value = business_task.get("task_type")
        return str(value) if value else None
    return None


async def _resolve_batch_orders(
    db: AsyncSession,
    request: BatchOperationRequest,
) -> tuple[list[TaskOrder], dict[str, str]]:
    """Resolve explicit order IDs or a benchmark run scope for batch operations."""
    if request.order_ids:
        rows = await db.execute(select(TaskOrder).where(TaskOrder.id.in_(request.order_ids)))
        order_by_id = {order.id: order for order in rows.scalars().all()}
        missing = {
            order_id: "Order not found"
            for order_id in request.order_ids
            if order_id not in order_by_id
        }
        return [order_by_id[order_id] for order_id in request.order_ids if order_id in order_by_id], missing

    if not request.benchmark_run_id:
        raise HTTPException(status_code=400, detail="order_ids or benchmark_run_id is required")

    query = select(TaskOrder)
    if request.is_benchmark is not None:
        query = query.where(TaskOrder.is_benchmark == request.is_benchmark)
    else:
        query = query.where(TaskOrder.is_benchmark == True)
    rows = await db.execute(query)
    orders = [
        order
        for order in rows.scalars().all()
        if _benchmark_run_id(order) == request.benchmark_run_id
        and (not request.task_type or _benchmark_task_type(order) == request.task_type)
    ]
    return orders, {}


async def _catalog_for_order(db: AsyncSession, order: TaskOrder) -> BusinessTemplateCatalog | None:
    query = select(BusinessTemplateCatalog).where(
        BusinessTemplateCatalog.template_id == order.template_id
    )
    task_type = _benchmark_task_type(order)
    if task_type:
        query = query.where(BusinessTemplateCatalog.task_type == task_type)
    rows = (await db.execute(query)).scalars().all()
    return rows[0] if rows else None


def _benchmark_config(task_type: str) -> dict:
    try:
        return BENCHMARK_TASK_CONFIGS[task_type]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported benchmark task_type: {task_type}") from exc


def _merged_benchmark_profile(task_type: str, data_profile: dict | None) -> dict:
    config = _benchmark_config(task_type)
    return {**config["default_profile"], **(data_profile or {})}


def _default_compute_gpu_for_order(order: TaskOrder) -> str | None:
    task_type = _benchmark_task_type(order)
    if not task_type:
        return None
    try:
        return _benchmark_config(task_type).get("default_compute_gpu")
    except HTTPException:
        return None


def _benchmark_routing_result(order: TaskOrder) -> dict:
    config = order.runtime_config or {}
    routing_result = config.get("routing_result")
    if isinstance(routing_result, dict):
        return routing_result
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        routing_result = business_task.get("routing_result")
        if isinstance(routing_result, dict):
            return routing_result
    return {}


def _benchmark_compute_slot(order: TaskOrder) -> str:
    """Return the compute host/GPU slot used to limit benchmark concurrency."""
    routing_result = _benchmark_routing_result(order)
    placements = routing_result.get("placements")
    placement = None
    if isinstance(placements, list):
        for item in placements:
            if isinstance(item, dict) and item.get("node_id") in ("compute", "worker"):
                placement = item
                break
    elif isinstance(placements, dict):
        placement = placements.get("compute") or placements.get("worker")

    host = "unknown"
    gpu = _default_compute_gpu_for_order(order) or "none"
    if isinstance(placement, dict):
        host = (
            placement.get("worker_host")
            or placement.get("hostname")
            or placement.get("node_name")
            or placement.get("node_id")
            or host
        )
        gpu = (
            placement.get("gpu_device")
            or (placement.get("gpu_indices") or [None])[0]
            or gpu
        )
    elif isinstance(placement, str):
        host = placement
    return f"{host}:gpu={gpu}"


def _is_gpu_benchmark_order(order: TaskOrder) -> bool:
    task_type = _benchmark_task_type(order)
    return task_type in {
        "high_throughput_matmul",
        "low_latency_video_pipeline",
        "llm_text_generation",
    }


def _gpu_from_routing_result(routing_result: dict | None, role: str) -> str | None:
    if not isinstance(routing_result, dict):
        return None
    placements = routing_result.get("placements")
    if isinstance(placements, list):
        for placement in placements:
            if not isinstance(placement, dict):
                continue
            if placement.get("node_id") != role:
                continue
            gpu_device = placement.get("gpu_device")
            if gpu_device is not None:
                return str(gpu_device)
            gpu_indices = placement.get("gpu_indices")
            if isinstance(gpu_indices, list) and gpu_indices:
                return str(gpu_indices[0])
    if isinstance(placements, dict):
        placement = placements.get(role)
        if isinstance(placement, dict):
            gpu_device = placement.get("gpu_device")
            if gpu_device is not None:
                return str(gpu_device)
            gpu_indices = placement.get("gpu_indices")
            if isinstance(gpu_indices, list) and gpu_indices:
                return str(gpu_indices[0])
    return None


def _order_to_response(
    order: TaskOrder,
    instance_exists: bool | None = None,
    deployment_status: TaskStatus | None = None,
    evaluation: BusinessObjectiveEvaluation | None = None,
) -> TaskOrderResponse:
    rc = order.runtime_config or {}
    bt = rc.get("business_task") or {}
    rp = bt.get("runtime_plan") or {}
    data = TaskOrderResponse.model_validate(order)
    updates = {
        "task_type": bt.get("task_type"),
        "routing_policy": bt.get("routing_policy") or rp.get("routing_strategy"),
    }
    if instance_exists is not None:
        updates["instance_exists"] = instance_exists
    if deployment_status is not None:
        updates["deployment_status"] = deployment_status
    if evaluation is not None:
        updates.update(
            {
                "metric_key": evaluation.metric_key,
                "actual_value": evaluation.actual_value,
                "target_value": evaluation.target_value,
                "unit": evaluation.unit,
                "business_success": evaluation.business_success,
                "failure_reason": evaluation.failure_reason,
            }
        )
    return data.model_copy(update=updates)


async def _latest_evaluations_by_instance(
    db: AsyncSession,
    instance_ids: list[str],
) -> dict[str, BusinessObjectiveEvaluation]:
    if not instance_ids:
        return {}
    rows = await db.execute(
        select(BusinessObjectiveEvaluation)
        .where(BusinessObjectiveEvaluation.instance_id.in_(instance_ids))
        .order_by(
            BusinessObjectiveEvaluation.instance_id.asc(),
            BusinessObjectiveEvaluation.created_at.desc(),
        )
    )
    latest: dict[str, BusinessObjectiveEvaluation] = {}
    for row in rows.scalars():
        if row.instance_id not in latest:
            latest[row.instance_id] = row
    return latest


async def _instance_state(
    db: AsyncSession,
    instance_id: str | None,
) -> tuple[bool | None, TaskStatus | None]:
    if not instance_id:
        return None, None
    row = await db.execute(
        select(TaskInstance.id, TaskInstance.status).where(TaskInstance.id == instance_id)
    )
    result = row.first()
    if not result:
        return False, None
    return True, result.status


async def _instance_exists(db: AsyncSession, instance_id: str | None) -> bool | None:
    exists, _ = await _instance_state(db, instance_id)
    return exists


@router.post("", response_model=TaskOrderResponse)
async def create_order(payload: TaskOrderCreate, db: AsyncSession = Depends(get_db)):
    if payload.external_task_id:
        exists = await db.execute(
            select(TaskOrder).where(TaskOrder.external_task_id == payload.external_task_id)
        )
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="external_task_id already exists")

    runtime_config = {"node_overrides": [item.model_dump() for item in payload.node_overrides], "extra": payload.extra}
    order = TaskOrder(
        external_task_id=payload.external_task_id,
        template_id=payload.template_id,
        name=payload.name,
        description=payload.description,
        deployment_mode=payload.deployment_mode,
        scheduled_start_time=payload.scheduled_start_time,
        scheduled_end_time=payload.scheduled_end_time,
        auto_start=payload.auto_start,
        runtime_config=runtime_config,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _order_to_response(order)


@router.get("", response_model=list[TaskOrderResponse])
async def list_orders(
    status: OrderStatus | None = None,
    is_benchmark: bool | None = None,
    benchmark_run_id: str | None = None,
    task_type: str | None = None,
    limit: int = 100,
    include_cancelled: bool = False,
    reconcile: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if reconcile:
        if await reconcile_orphan_orders(db):
            await db.commit()

    query = select(TaskOrder)
    if current_user.role != "admin":
        query = query.where(TaskOrder.user_id == current_user.id)
    if is_benchmark is not None:
        query = query.where(TaskOrder.is_benchmark == is_benchmark)
    if status:
        query = query.where(TaskOrder.status == status)
    elif not include_cancelled:
        query = query.where(TaskOrder.status != OrderStatus.CANCELLED)
    rows = await db.execute(query.order_by(TaskOrder.created_at.desc()))
    orders = rows.scalars().all()
    if benchmark_run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == benchmark_run_id]
    if task_type:
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]
    orders = orders[: max(1, min(limit, 500))]

    responses: list[TaskOrderResponse] = []
    eval_map = await _latest_evaluations_by_instance(
        db,
        [order.materialized_instance_id for order in orders if order.materialized_instance_id],
    )
    for order in orders:
        exists, deployment_status = await _instance_state(db, order.materialized_instance_id)
        responses.append(
            _order_to_response(
                order,
                instance_exists=exists,
                deployment_status=deployment_status,
                evaluation=eval_map.get(order.materialized_instance_id or ""),
            )
        )
    return responses


@router.get("/{order_id}", response_model=TaskOrderDetailResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order, instance, evaluation = await get_order_detail_context(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    config = order.runtime_config or {}
    business_task = config.get("business_task")
    routing_result = config.get("routing_result")
    if not isinstance(routing_result, dict) and isinstance(business_task, dict):
        routing_result = business_task.get("routing_result")

    instance_exists, deployment_status = await _instance_state(db, order.materialized_instance_id)
    base = _order_to_response(
        order,
        instance_exists=instance_exists,
        deployment_status=deployment_status,
    )
    detail = TaskOrderDetailResponse.model_validate(base.model_dump())
    detail.business_task = business_task if isinstance(business_task, dict) else None
    detail.routing_result = routing_result if isinstance(routing_result, dict) else None

    if instance:
        # Build port_access_urls from instance nodes
        port_access_urls: dict[str, str] = {}
        node_placements: list[TaskOrderNodePlacementSummary] = []
        inst_nodes_result = await db.execute(
            select(TaskInstanceNode).where(TaskInstanceNode.instance_id == instance.id)
        )
        inst_nodes = inst_nodes_result.scalars().all()
        for inst_node in inst_nodes:
            machine = (await db.execute(
                select(NodeModel).where(NodeModel.id == inst_node.node_id)
            )).scalar_one_or_none()
            env = inst_node.env or {}
            role = env.get("TASK_ROLE") or inst_node.name
            gpu_device = env.get("GPU_DEVICE")
            gpu_id = inst_node.gpu_id
            if role in ("compute", "worker") and not (gpu_device or gpu_id):
                routing_gpu = _gpu_from_routing_result(routing_result, role)
                gpu_device = routing_gpu or None
            node_placements.append(
                TaskOrderNodePlacementSummary(
                    role=role,
                    instance_node_name=inst_node.name,
                    node_id=inst_node.node_id,
                    hostname=machine.hostname if machine else None,
                    gpu_id=gpu_id,
                    gpu_device=gpu_device,
                    port_values=inst_node.port_values,
                    status=inst_node.status,
                )
            )
            if not inst_node.port_values:
                continue
            if not machine:
                continue
            biz_addr = get_business_address(machine, settings.prefer_business_ipv6)
            for port_name, port_val in inst_node.port_values.items():
                try:
                    port_int = int(port_val)
                except (TypeError, ValueError):
                    continue
                key = f"{inst_node.name}/{port_name}"
                port_access_urls[key] = format_service_url(biz_addr, port_int)
        detail.node_placements = node_placements

        detail.instance = TaskOrderInstanceSummary(
            id=instance.id,
            status=instance.status,
            node_count=len(instance.nodes or []),
            error_message=instance.error_message,
            port_access_urls=port_access_urls or None,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )
    if evaluation:
        object_uris = evaluation.object_uris if isinstance(evaluation.object_uris, dict) else {}
        result_metadata = object_uris.get("result_metadata")
        if not isinstance(result_metadata, dict):
            result_metadata = None
        detail.evaluation = TaskOrderEvaluationSummary(
            metric_key=evaluation.metric_key,
            actual_value=evaluation.actual_value,
            target_value=evaluation.target_value,
            unit=evaluation.unit,
            business_success=evaluation.business_success,
            failure_reason=evaluation.failure_reason,
            estimated_value=evaluation.estimated_value,
            estimation_error_ratio=evaluation.estimation_error_ratio,
            result_metadata=result_metadata,
        )
    return detail


@router.delete("/{order_id}")
async def delete_order(order_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await purge_order_instance_artifacts(db, order.materialized_instance_id)
    await db.delete(order)
    await db.commit()
    return {"message": "Order deleted"}


@router.post("/batch/delete", response_model=BatchOperationResponse)
async def batch_delete_orders(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    succeeded: list[str] = []
    orders, failed = await _resolve_batch_orders(db, request)
    for order in orders:
        try:
            await purge_order_instance_artifacts(db, order.materialized_instance_id)
            await db.delete(order)
            succeeded.append(order.id)
        except Exception as exc:
            failed[order.id] = str(exc)
    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/batch/cleanup-instances", response_model=BatchOperationResponse)
async def batch_cleanup_order_instances(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理工单关联实例，保留工单、路由结果、评估结果和结果对象作为验收证据。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    succeeded: list[str] = []
    orders, failed = await _resolve_batch_orders(db, request)
    task_scheduler = TaskScheduler()

    for order in orders:
        try:
            if not order.materialized_instance_id:
                succeeded.append(order.id)
                continue

            result = await db.execute(
                select(TaskInstance)
                .options(selectinload(TaskInstance.nodes))
                .where(TaskInstance.id == order.materialized_instance_id)
            )
            instance = result.scalar_one_or_none()
            if not instance:
                succeeded.append(order.id)
                continue

            await task_scheduler.cancel_all_schedules(instance.id)
            await cleanup_instance_runtime(db, instance)
            await purge_instance_artifacts_preserve_evidence(db, instance.id)
            if order.status == OrderStatus.MATERIALIZED:
                order.status = OrderStatus.COMPLETED
            succeeded.append(order.id)
        except Exception as exc:
            failed[order.id] = str(exc)

    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/{order_id}/materialize", response_model=dict)
async def materialize_order(order_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Order is cancelled")

    config = order.runtime_config or {}
    try:
        instance = TaskInstanceCreate(
            template_id=order.template_id,
            name=order.name,
            deployment_mode=order.deployment_mode,
            scheduled_start_time=order.scheduled_start_time,
            scheduled_end_time=order.scheduled_end_time,
            auto_start=order.auto_start,
            node_overrides=config.get("node_overrides", []),
        )
        created = await _create_instance_from_template(db, instance, source_order_id=order.id)
        order.materialized_instance_id = created.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
        await db.commit()
        return {"order_id": order.id, "instance_id": created.id, "status": "materialized"}
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = str(exc)
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Materialization failed: {exc}") from exc


@router.post("/materialize/pending", response_model=dict)
async def materialize_pending_orders(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(TaskOrder).where(TaskOrder.status == OrderStatus.PENDING).order_by(TaskOrder.created_at.asc())
    )
    orders = rows.scalars().all()
    success = []
    failed = {}
    for order in orders:
        try:
            config = order.runtime_config or {}
            instance = TaskInstanceCreate(
                template_id=order.template_id,
                name=order.name,
                deployment_mode=order.deployment_mode,
                scheduled_start_time=order.scheduled_start_time,
                scheduled_end_time=order.scheduled_end_time,
                auto_start=order.auto_start,
                node_overrides=config.get("node_overrides", []),
            )
            created = await _create_instance_from_template(db, instance, source_order_id=order.id)
            order.materialized_instance_id = created.id
            order.status = OrderStatus.MATERIALIZED
            order.error_message = None
            success.append(order.id)
        except Exception as exc:
            order.status = OrderStatus.FAILED
            order.error_message = str(exc)
            failed[order.id] = str(exc)
        await db.commit()
    return {"succeeded": success, "failed": failed}


class RoutingPlacement(BaseModel):
    node_id: str
    worker_host: str
    gpu_device: Optional[str] = None


class RoutingResultPayload(BaseModel):
    placements: list[RoutingPlacement]
    strategy: Optional[str] = None
    selected_strategy: Optional[str] = None
    external_routing_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    estimated_metric: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


@router.post("/{order_id}/routing-result")
async def receive_routing_result(
    order_id: str,
    payload: RoutingResultPayload,
    db: AsyncSession = Depends(get_db),
):
    """接收外部路由系统的计算结果（节点放置 + GPU 分配），并自动物化实例。"""
    row = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.materialized_instance_id:
        raise HTTPException(status_code=409, detail="Routing result already processed")
    if order.routing_status not in {
        RoutingStatus.PENDING.value,
        RoutingStatus.COMPUTING.value,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot accept routing result when routing_status is '{order.routing_status}'",
        )

    # Persist routing result
    order.routing_status = RoutingStatus.COMPUTING.value
    rc = order.runtime_config or {}
    routing_result = {
        "placements": [p.model_dump() for p in payload.placements],
    }
    if payload.strategy:
        routing_result["strategy"] = payload.strategy
    if payload.selected_strategy:
        routing_result["selected_strategy"] = payload.selected_strategy
    if payload.external_routing_id:
        routing_result["external_routing_id"] = payload.external_routing_id
    if payload.metadata:
        routing_result["metadata"] = payload.metadata
    if payload.estimated_metric:
        routing_result["estimated_metric"] = payload.estimated_metric
    if payload.result_payload:
        routing_result["result_payload"] = payload.result_payload
    if payload.extra:
        routing_result["extra"] = payload.extra
    rc["routing_result"] = routing_result
    order.runtime_config = rc
    flag_modified(order, "runtime_config")

    # Resolve role -> template_node_name from catalog
    catalog = await _catalog_for_order(db, order)
    role_node_names = {
        "source": catalog.source_node_name if catalog else None,
        "compute": catalog.compute_node_name if catalog else None,
        "worker": catalog.compute_node_name if catalog else None,
        "sink": catalog.sink_node_name if catalog else None,
    }

    # Build node_overrides from placements list
    overrides: list[TaskInstanceNodeOverride] = []
    for placement in payload.placements:
        role = placement.node_id  # node_id field carries the role name from router
        template_node_name = role_node_names.get(role) if catalog else role
        if template_node_name is None:
            template_node_name = role

        try:
            resolved_node_id = await _resolve_node_id(db, placement.worker_host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        env: dict[str, str] = {
            "TASK_ROLE": role,
            "SOURCE_NAME": order.source_name or "",
            "DESTINATION_NAME": order.destination_name or "",
        }
        # Inject business task env vars from runtime_config
        bt = (order.runtime_config or {}).get("business_task", {})
        if bt:
            import json
            env["TASK_TYPE"] = bt.get("task_type") or ""
            env["DATA_PROFILE"] = json.dumps(bt.get("data_profile") or {})
            env["BUSINESS_OBJECTIVE"] = json.dumps(bt.get("business_objective") or {})
            env["RUNTIME_PLAN"] = json.dumps(bt.get("runtime_plan") or {})
            env["TASK_INSTANCE_ID"] = order.id  # will be updated after instance creation
            if bt.get("task_type") in {"high_throughput_matmul", "low_latency_video_pipeline", "llm_text_generation"} and role in ("compute", "worker"):
                env["USE_GPU"] = "true"
        if placement.gpu_device is not None:
            env["GPU_DEVICE"] = placement.gpu_device
        elif order.is_benchmark and role in ("compute", "worker"):
            default_gpu = _default_compute_gpu_for_order(order)
            if default_gpu is not None:
                env["GPU_DEVICE"] = default_gpu

        gpu_id = placement.gpu_device
        if gpu_id is None and order.is_benchmark and role in ("compute", "worker"):
            gpu_id = _default_compute_gpu_for_order(order)
        overrides.append(TaskInstanceNodeOverride(
            template_node_name=template_node_name,
            node_id=resolved_node_id,
            env=env,
            gpu_id=gpu_id,
        ))

    # Create instance
    start_time = order.business_start_time or order.scheduled_start_time or datetime.utcnow()
    end_time = order.business_end_time or order.scheduled_end_time or (start_time + timedelta(hours=1))
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
    instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)

    # Update TASK_INSTANCE_ID in each node's env now that we have the real instance id
    for node in instance.nodes:
        if node.env and node.env.get("TASK_INSTANCE_ID") == order.id:
            node.env = {**node.env, "TASK_INSTANCE_ID": instance.id}
            flag_modified(node, "env")

    # Register scheduled jobs
    ts = TaskScheduler()
    if order.business_start_time:
        await ts.schedule_task_start(instance.id, order.business_start_time)
    if order.business_end_time:
        await ts.schedule_task_end(instance.id, order.business_end_time)

    order.materialized_instance_id = instance.id
    order.status = OrderStatus.MATERIALIZED
    order.routing_status = RoutingStatus.COMPLETED.value

    await db.commit()
    return {"status": "ok", "order_id": order_id, "routing_status": "completed", "instance_id": instance.id}


class BatchBenchmarkRequest(BaseModel):
    task_type: str = "high_throughput_matmul"
    count: int = Field(default=10, ge=1, le=30)
    benchmark_run_id: Optional[str] = None
    data_profile: dict = Field(default_factory=dict)
    routing_strategy: str = "resource_guarantee"


@router.post("/batch-benchmark")
async def create_batch_benchmark(
    payload: BatchBenchmarkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    catalog_row = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == payload.task_type)
    )
    catalog = catalog_row.scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=404, detail=f"No catalog entry for task_type: {payload.task_type}")

    benchmark_config = _benchmark_config(payload.task_type)
    data_profile = _merged_benchmark_profile(payload.task_type, payload.data_profile)
    business_objective = dict(benchmark_config["business_objective"])
    order_ids = []
    business_start_time = datetime.utcnow()
    business_end_time = business_start_time + timedelta(hours=1)
    run_id = payload.benchmark_run_id or f"{payload.task_type}-{business_start_time.strftime('%Y%m%d%H%M%S')}"
    for i in range(payload.count):
        order_name = f"benchmark-{payload.task_type}-{run_id}-{i + 1}"
        runtime_config = {
            "benchmark": {
                "run_id": run_id,
                "created_at": business_start_time.isoformat(),
                "sample_count": payload.count,
                "profile": data_profile,
                "mode": "mock-route-ready",
            },
            "business_task": {
                "task_type": payload.task_type,
                "modality": benchmark_config["modality"],
                "data_profile": data_profile,
                "business_objective": business_objective,
                "runtime_plan": {"routing_strategy": payload.routing_strategy},
                "routing_strategy": payload.routing_strategy,
            }
        }
        order = TaskOrder(
            user_id=current_user.id,
            template_id=catalog.template_id,
            name=order_name,
            status=OrderStatus.PENDING,
            routing_status=RoutingStatus.PENDING.value,
            runtime_config=runtime_config,
            is_benchmark=True,
            source_name=benchmark_config["source_name"],
            destination_name=benchmark_config["destination_name"],
            business_start_time=business_start_time,
            business_end_time=business_end_time,
            scheduled_start_time=business_start_time,
            scheduled_end_time=business_end_time,
        )
        db.add(order)
        await db.flush()
        order.routing_input_dag = build_routing_payload(
            order_id=order.id,
            order_name=order.name,
            task_type=payload.task_type,
            modality=benchmark_config["modality"],
            source_name=benchmark_config["source_name"],
            destination_name=benchmark_config["destination_name"],
            business_start_time=business_start_time,
            business_end_time=business_end_time,
            data_profile=data_profile,
        )
        order_ids.append(order.id)

    await db.commit()
    return {"created": len(order_ids), "order_ids": order_ids, "benchmark_run_id": run_id}


class BenchmarkRunScopedRequest(BaseModel):
    benchmark_run_id: Optional[str] = None
    task_type: Optional[str] = None


class ControlledBenchmarkStartRequest(BenchmarkRunScopedRequest):
    max_parallel: int = Field(default=2, ge=1, le=10)
    per_compute_slot_limit: int = Field(default=1, ge=1, le=4)
    cleanup_evaluated: bool = True
    wait_seconds: int = Field(default=0, ge=0, le=30)


@router.post("/batch-auto-route")
async def batch_auto_route(
    payload: BenchmarkRunScopedRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-route all pending benchmark orders."""
    rows = await db.execute(
        select(TaskOrder).where(
            TaskOrder.status == OrderStatus.PENDING.value,
            TaskOrder.routing_status == RoutingStatus.PENDING.value,
            TaskOrder.is_benchmark == True,
            TaskOrder.user_id == current_user.id,
        )
    )
    orders = rows.scalars().all()
    run_id = payload.benchmark_run_id if payload else None
    if run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == run_id]
    task_type = payload.task_type if payload else None
    if task_type:
        _benchmark_config(task_type)
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]

    schedulable_rows = await db.execute(
        select(NodeModel).where(NodeModel.is_schedulable == True, NodeModel.deleted_at.is_(None))
    )
    schedulable = schedulable_rows.scalars().all()
    if not schedulable:
        raise HTTPException(status_code=400, detail="No schedulable nodes available")

    routed = 0
    failed = []
    for order in orders:
        try:
            picked = {role: random.choice(schedulable) for role in ("source", "compute", "sink")}
            await _do_auto_route(db, order, picked)
            routed += 1
        except Exception as exc:
            failed.append({"order_id": order.id, "error": str(exc)})

    await db.commit()
    return {"routed": routed, "failed": failed}


@router.post("/start-all-routed")
async def start_all_routed_benchmark_orders(
    payload: BenchmarkRunScopedRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start all materialized benchmark orders for the current user."""
    rows = await db.execute(
        select(TaskOrder).where(
            TaskOrder.status == OrderStatus.MATERIALIZED.value,
            TaskOrder.routing_status == RoutingStatus.COMPLETED.value,
            TaskOrder.is_benchmark == True,
            TaskOrder.user_id == current_user.id,
            TaskOrder.materialized_instance_id.is_not(None),
        )
    )
    orders = rows.scalars().all()
    run_id = payload.benchmark_run_id if payload else None
    if run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == run_id]
    task_type = payload.task_type if payload else None
    if task_type:
        _benchmark_config(task_type)
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]

    started: list[str] = []
    skipped: list[str] = []
    failed: dict[str, str] = {}

    for order in orders:
        instance_id = order.materialized_instance_id
        if not instance_id:
            failed[order.id] = "Order has no materialized instance"
            continue

        result = await db.execute(
            select(TaskInstance)
            .options(selectinload(TaskInstance.nodes))
            .where(TaskInstance.id == instance_id)
        )
        instance = result.scalar_one_or_none()
        if not instance:
            failed[order.id] = "Materialized instance not found"
            continue

        if instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            skipped.append(instance_id)
            continue

        if instance.status not in (
            TaskStatus.PENDING,
            TaskStatus.SCHEDULED,
            TaskStatus.STOPPED,
            TaskStatus.FAILED,
        ):
            failed[order.id] = f"Cannot start instance in status: {instance.status}"
            continue

        try:
            executor = DAGExecutor(db)
            success, error = await executor.execute_dag_start(instance_id)
            if success:
                started.append(instance_id)
            else:
                failed[order.id] = error or "Unknown error"
        except Exception as exc:
            failed[order.id] = str(exc)

    return {
        "started": len(started),
        "skipped": len(skipped),
        "failed": failed,
        "instance_ids": started,
    }


async def _controlled_benchmark_orders(
    db: AsyncSession,
    payload: BenchmarkRunScopedRequest | None,
    current_user: User,
) -> list[TaskOrder]:
    rows = await db.execute(
        select(TaskOrder).where(
            TaskOrder.routing_status == RoutingStatus.COMPLETED.value,
            TaskOrder.is_benchmark == True,
            TaskOrder.user_id == current_user.id,
            TaskOrder.materialized_instance_id.is_not(None),
        )
    )
    orders = rows.scalars().all()
    run_id = payload.benchmark_run_id if payload else None
    if run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == run_id]
    task_type = payload.task_type if payload else None
    if task_type:
        _benchmark_config(task_type)
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]
    return sorted(orders, key=lambda item: (item.created_at, item.name))


async def _instances_for_orders(
    db: AsyncSession,
    orders: list[TaskOrder],
) -> dict[str, TaskInstance]:
    instance_ids = [
        order.materialized_instance_id
        for order in orders
        if order.materialized_instance_id
    ]
    if not instance_ids:
        return {}
    rows = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id.in_(instance_ids))
    )
    return {instance.id: instance for instance in rows.scalars().all()}


async def _cleanup_evaluated_benchmark_instance(
    db: AsyncSession,
    order: TaskOrder,
    instance: TaskInstance,
) -> bool:
    """Stop/remove a benchmark runtime instance while preserving order evidence."""
    if instance.status not in (TaskStatus.STOPPED, TaskStatus.PENDING):
        executor = DAGExecutor(db)
        await executor.execute_dag_stop(instance.id)

    refreshed = (
        await db.execute(
            select(TaskInstance)
            .options(selectinload(TaskInstance.nodes))
            .where(TaskInstance.id == instance.id)
        )
    ).scalar_one_or_none()
    if not refreshed:
        if order.status == OrderStatus.MATERIALIZED:
            order.status = OrderStatus.COMPLETED
        return False

    await cleanup_instance_runtime(db, refreshed)
    await purge_instance_artifacts_preserve_evidence(db, refreshed.id)
    await mark_orders_completed_for_instance(db, refreshed.id)
    if order.status == OrderStatus.MATERIALIZED:
        order.status = OrderStatus.COMPLETED
    return True


@router.post("/start-controlled-routed")
async def start_controlled_routed_benchmark_orders(
    payload: ControlledBenchmarkStartRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start benchmark orders with compute/GPU-slot concurrency control.

    The acceptance target compares each sample with the historical single-task
    baseline of the selected compute node. Starting all samples at once measures
    resource contention instead, so this endpoint advances the run in controlled
    waves and optionally removes already evaluated runtime containers while
    keeping order/evaluation evidence.
    """
    payload = payload or ControlledBenchmarkStartRequest()
    orders = await _controlled_benchmark_orders(db, payload, current_user)
    instance_map = await _instances_for_orders(db, orders)
    eval_map = await _latest_evaluations_by_instance(
        db,
        [order.materialized_instance_id for order in orders if order.materialized_instance_id],
    )

    cleaned: list[str] = []
    failed: dict[str, str] = {}
    if payload.cleanup_evaluated:
        for order in orders:
            instance_id = order.materialized_instance_id
            if not instance_id or instance_id not in eval_map:
                continue
            instance = instance_map.get(instance_id)
            if not instance:
                continue
            try:
                if await _cleanup_evaluated_benchmark_instance(db, order, instance):
                    cleaned.append(instance_id)
            except Exception as exc:
                failed[order.id] = f"cleanup evaluated instance failed: {exc}"
        if cleaned:
            await db.commit()
            instance_map = await _instances_for_orders(db, orders)

    active_by_slot: defaultdict[str, int] = defaultdict(int)
    active_orders = 0
    for order in orders:
        instance_id = order.materialized_instance_id
        if not instance_id or instance_id in eval_map:
            continue
        instance = instance_map.get(instance_id)
        if instance and instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            active_by_slot[_benchmark_compute_slot(order)] += 1
            active_orders += 1

    started: list[str] = []
    skipped_busy: list[str] = []
    executor = DAGExecutor(db)
    for order in orders:
        if len(started) >= payload.max_parallel:
            break
        instance_id = order.materialized_instance_id
        if not instance_id or instance_id in eval_map:
            continue
        instance = instance_map.get(instance_id)
        if not instance:
            failed[order.id] = "Materialized instance not found"
            continue
        if instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            continue
        if instance.status not in (
            TaskStatus.PENDING,
            TaskStatus.SCHEDULED,
            TaskStatus.STOPPED,
            TaskStatus.FAILED,
        ):
            failed[order.id] = f"Cannot start instance in status: {instance.status}"
            continue

        slot = _benchmark_compute_slot(order)
        if active_by_slot[slot] >= payload.per_compute_slot_limit:
            skipped_busy.append(order.id)
            continue

        try:
            success, error = await executor.execute_dag_start(instance_id)
            if success:
                started.append(instance_id)
                active_by_slot[slot] += 1
                active_orders += 1
            else:
                failed[order.id] = error or "Unknown error"
        except Exception as exc:
            failed[order.id] = str(exc)

    if payload.wait_seconds:
        await asyncio.sleep(payload.wait_seconds)

    eval_map = await _latest_evaluations_by_instance(
        db,
        [order.materialized_instance_id for order in orders if order.materialized_instance_id],
    )
    success_count = sum(1 for evaluation in eval_map.values() if evaluation.business_success)
    evaluated_count = len(eval_map)
    pending_to_start = 0
    for order in orders:
        instance_id = order.materialized_instance_id
        if not instance_id or instance_id in eval_map:
            continue
        instance = instance_map.get(instance_id)
        if instance is None or instance.status not in (TaskStatus.RUNNING, TaskStatus.STARTING):
            pending_to_start += 1

    return {
        "total": len(orders),
        "evaluated": evaluated_count,
        "success": success_count,
        "active": active_orders,
        "pending_to_start": pending_to_start,
        "started": len(started),
        "skipped_busy": skipped_busy,
        "cleaned": len(cleaned),
        "failed": failed,
        "instance_ids": started,
        "success_rate": success_count / evaluated_count if evaluated_count else None,
    }


async def _do_auto_route(db: AsyncSession, order: TaskOrder, picked: dict):
    """Shared logic: resolve picked nodes, build overrides, create instance, update order."""
    catalog = await _catalog_for_order(db, order)
    role_node_names = {
        "source": catalog.source_node_name if catalog else None,
        "compute": catalog.compute_node_name if catalog else None,
        "sink": catalog.sink_node_name if catalog else None,
    }

    overrides: list[TaskInstanceNodeOverride] = []
    for role, node in picked.items():
        template_node_name = role_node_names.get(role) or role
        env: dict[str, str] = {
            "TASK_ROLE": role,
            "SOURCE_NAME": order.source_name or "",
            "DESTINATION_NAME": order.destination_name or "",
        }
        bt = (order.runtime_config or {}).get("business_task", {})
        if bt:
            import json
            env["TASK_TYPE"] = bt.get("task_type") or ""
            env["DATA_PROFILE"] = json.dumps(bt.get("data_profile") or {})
            env["BUSINESS_OBJECTIVE"] = json.dumps(bt.get("business_objective") or {})
            env["RUNTIME_PLAN"] = json.dumps(bt.get("runtime_plan") or {})
            env["TASK_INSTANCE_ID"] = order.id
            if bt.get("task_type") in {"high_throughput_matmul", "low_latency_video_pipeline", "llm_text_generation"} and role in ("compute", "worker"):
                env["USE_GPU"] = "true"
        gpu_id = _default_compute_gpu_for_order(order) if role == "compute" else None
        if gpu_id is not None:
            env["GPU_DEVICE"] = gpu_id
        overrides.append(TaskInstanceNodeOverride(
            template_node_name=template_node_name,
            node_id=node.id,
            env=env,
            gpu_id=gpu_id,
        ))

    placements = [
        {
            "node_id": role,
            "worker_host": node.hostname,
            **({"gpu_device": _default_compute_gpu_for_order(order)} if role == "compute" and _default_compute_gpu_for_order(order) is not None else {}),
        }
        for role, node in picked.items()
    ]
    rc = order.runtime_config or {}
    business_task = rc.get("business_task") or {}
    runtime_plan = business_task.get("runtime_plan") or {}
    rc["routing_result"] = {
        "strategy": runtime_plan.get("routing_strategy") or business_task.get("routing_strategy"),
        "placements": placements,
    }
    order.runtime_config = rc
    flag_modified(order, "runtime_config")
    order.routing_status = RoutingStatus.COMPLETED.value

    start_time = order.business_start_time or order.scheduled_start_time or datetime.utcnow()
    end_time = order.business_end_time or order.scheduled_end_time or (start_time + timedelta(hours=1))
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
    instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)

    for node_obj in instance.nodes:
        if node_obj.env and node_obj.env.get("TASK_INSTANCE_ID") == order.id:
            node_obj.env = {**node_obj.env, "TASK_INSTANCE_ID": instance.id}
            flag_modified(node_obj, "env")

    ts = TaskScheduler()
    if order.business_start_time:
        await ts.schedule_task_start(instance.id, order.business_start_time)
    if order.business_end_time:
        await ts.schedule_task_end(instance.id, order.business_end_time)

    order.materialized_instance_id = instance.id
    order.status = OrderStatus.MATERIALIZED


@router.post("/{order_id}/auto-route")
async def auto_route_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mock router: randomly assigns schedulable nodes, then calls routing-result logic."""
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.role != UserRole.ADMIN and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot route orders owned by another user")
    if not order.is_benchmark:
        raise HTTPException(status_code=400, detail="Mock auto-route is only available for benchmark orders")
    if order.routing_status != RoutingStatus.PENDING.value:
        raise HTTPException(status_code=400, detail=f"Order routing_status is '{order.routing_status}', expected 'pending'")

    schedulable_rows = await db.execute(
        select(NodeModel).where(NodeModel.is_schedulable == True, NodeModel.deleted_at.is_(None))
    )
    schedulable = schedulable_rows.scalars().all()
    if not schedulable:
        raise HTTPException(status_code=400, detail="No schedulable nodes available")

    picked = {role: random.choice(schedulable) for role in ("source", "compute", "sink")}
    await _do_auto_route(db, order, picked)
    await db.commit()
    return {"status": "ok", "order_id": order_id, "instance_id": order.materialized_instance_id}
