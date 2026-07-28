import asyncio
import logging
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from agents.agent_client import AgentClient
from api.auth import get_current_user
from config import settings
from database import async_session_maker, get_db
from enums import (
    ConversationStatus,
    DeploymentMode,
    OrderStatus,
    RoutingRequestStatus,
    RoutingStatus,
    TaskStatus,
    UserRole,
)
from models import (
    BusinessObjectiveEvaluation,
    BusinessTemplateCatalog,
    Conversation,
    Node as NodeModel,
    NodeBaseline,
    RoutingRequest,
    TaskMetric,
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
from services.business_env import build_business_env
from services.dag_executor import DAGExecutor
from services.node_resolver import resolve_node_id
from services.instance_lifecycle import cleanup_instance_runtime
from services.order_sync import (
    mark_orders_completed_for_instance,
    purge_instance_artifacts_preserve_evidence,
    purge_order_instances_by_source_order,
    purge_order_instance_artifacts,
    reconcile_orphan_orders,
)
from services.port_plan import format_service_url, get_business_address
from services.routing_resource_events import emit_release_events_for_order
from services.routing_payload_builder import build_routing_payload
from services.routing_policy import normalize_routing_policy, require_routing_policy
from services.routing_network import (
    build_network_bindings,
    instance_waiting_for_network_ready,
    mark_network_binding_ready,
)
from services.scheduler import TaskScheduler
from services.system_settings import (
    benchmark_compute_allocation_mode_from_settings,
    get_runtime_settings,
    modality_priority_map_from_settings,
    routing_resource_options_from_settings,
)
from services.time_utils import business_now
from services.topology_catalog import COMPUTE_NODE_ALIASES, TERMINAL_NODE_ALIASES
from services.user_access_guide import build_user_access_guide

from .instances import _build_preflight_plan_from_instance, _create_instance_from_template, _preflight_instance_plan

router = APIRouter(prefix="/api/orders", tags=["orders"])
logger = logging.getLogger(__name__)


BENCHMARK_TASK_CONFIGS = {
    "high_throughput_matmul": {
        "label": "矩阵乘法计算任务",
        "modality": "高通量计算模态",
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
    },
    "low_latency_video_pipeline": {
        "label": "视频AI推理任务",
        "modality": "低时延转发模态",
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
            "model_path": "models/yolov5n-fp32.onnx",
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
    },
    "metaverse_video_fusion": {
        "label": "元宇宙沉浸式交互",
        "modality": "低时延转发模态",
        "default_profile": {
            "profile_id": "metaverse_offline_fusion_720p",
            "frame_count": 180,
            "resolution": "720p",
            "fps": 30,
            "frame_stride": 1,
            "warmup_frames": 10,
            "measured_frames": 170,
            "seed": 42,
            "video0_asset": "cam0.mp4",
            "video1_asset": "cam1.mp4",
            "fusion_mode": "modnet_offline",
            "modnet_checkpoint": "MODNet/pretrained/modnet_webcam_portrait_matting.ckpt",
            "strict_gpu": True,
            "use_gpu": True,
        },
        "business_objective": {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "unit": "ms",
        },
        "default_compute_gpu": "0",
    },
}


async def _ensure_internal_benchmark_routing_enabled(db: AsyncSession) -> None:
    runtime_settings = await get_runtime_settings(db)
    if runtime_settings.get("benchmark_routing_mode") != "internal_auto":
        raise HTTPException(
            status_code=409,
            detail="当前系统配置为等待外部节点分配结果，请在系统设置中切换路由方式后再使用系统自动分配。",
        )


def _benchmark_run_id(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    benchmark = config.get("benchmark")
    if isinstance(benchmark, dict):
        value = benchmark.get("run_id")
        return str(value) if value else None
    return None


ACTIVE_INSTANCE_STATUSES = {
    TaskStatus.STARTING,
    TaskStatus.RUNNING,
    TaskStatus.STOPPING,
}


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _reject_active_instance_for_cleanup(instance: TaskInstance) -> None:
    if instance.status in ACTIVE_INSTANCE_STATUSES:
        raise RuntimeError(
            f"实例正在启动中/运行中/停止中（当前状态：{_status_value(instance.status)}），请等待完成或先停止任务后再清理"
        )


async def _background_benchmark_start(instance_id: str) -> None:
    async with async_session_maker() as session:
        executor = DAGExecutor(session)
        success, error = await executor.execute_dag_start(instance_id, claimed_start=True)
        if not success:
            logger.warning(
                "Background benchmark start failed instance=%s error=%s",
                instance_id,
                error or "unknown error",
            )


_BACKGROUND_BENCHMARK_START_TASKS: dict[str, asyncio.Task] = {}


def _schedule_background_benchmark_start(instance_id: str) -> bool:
    existing = _BACKGROUND_BENCHMARK_START_TASKS.get(instance_id)
    if existing and not existing.done():
        return False

    task = asyncio.create_task(_background_benchmark_start(instance_id))
    _BACKGROUND_BENCHMARK_START_TASKS[instance_id] = task

    def finish(done_task: asyncio.Task, current_instance_id: str = instance_id) -> None:
        if _BACKGROUND_BENCHMARK_START_TASKS.get(current_instance_id) is done_task:
            _BACKGROUND_BENCHMARK_START_TASKS.pop(current_instance_id, None)
        if done_task.cancelled():
            return
        try:
            error = done_task.exception()
        except asyncio.CancelledError:
            return
        if error:
            logger.error(
                "Background benchmark start crashed instance=%s",
                current_instance_id,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(finish)
    return True


def _benchmark_task_type(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        value = business_task.get("task_type")
        return str(value) if value else None
    return None


class BenchmarkRunSummary(BaseModel):
    benchmark_run_id: str
    task_type: str
    created_at: datetime
    order_count: int


def _apply_order_visibility(query, current_user: User):
    if current_user.role != UserRole.ADMIN:
        query = query.where(TaskOrder.user_id == current_user.id)
    return query


def _is_admin_user(current_user: User) -> bool:
    return current_user.role == UserRole.ADMIN or current_user.role == UserRole.ADMIN.value


def _ensure_order_owner_or_admin(order: TaskOrder, current_user: User) -> None:
    if not _is_admin_user(current_user) and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该工单")


async def _cleanup_materialized_order_instance(
    db: AsyncSession,
    order: TaskOrder,
    task_scheduler: TaskScheduler,
) -> TaskInstance | None:
    """Stop and purge runtime containers for an order before deleting/cleaning records."""
    if not order.materialized_instance_id:
        return None
    instance_row = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == order.materialized_instance_id)
    )
    instance = instance_row.scalar_one_or_none()
    if not instance:
        return None
    _reject_active_instance_for_cleanup(instance)
    await task_scheduler.cancel_all_schedules(instance.id)
    cleanup_warnings = await cleanup_instance_runtime(db, instance)
    if cleanup_warnings:
        raise RuntimeError(f"容器清理失败：{'；'.join(cleanup_warnings)}")
    return instance


async def _detach_order_references_before_delete(db: AsyncSession, order: TaskOrder) -> None:
    """Detach conversational/routing references that would block physical order deletion."""
    conversation_by_id: dict[str, Conversation] = {}
    if order.conversation_id:
        conversation_row = await db.execute(select(Conversation).where(Conversation.id == order.conversation_id))
        conversation = conversation_row.scalar_one_or_none()
        if conversation:
            conversation_by_id[conversation.id] = conversation

    conversation_rows = await db.execute(
        select(Conversation).where(Conversation.materialized_order_id == order.id)
    )
    for conversation in conversation_rows.scalars().all():
        conversation_by_id[conversation.id] = conversation

    for conversation in conversation_by_id.values():
        if conversation.materialized_order_id == order.id:
            conversation.materialized_order_id = None
        conversation.status = ConversationStatus.CANCELLED

    routing_rows = await db.execute(select(RoutingRequest).where(RoutingRequest.order_id == order.id))
    for routing in routing_rows.scalars().all():
        routing.order_id = None


async def _resolve_batch_orders(
    db: AsyncSession,
    request: BatchOperationRequest,
    current_user: User | None = None,
) -> tuple[list[TaskOrder], dict[str, str]]:
    """Resolve explicit order IDs or a benchmark run scope for batch operations."""
    if request.order_ids:
        rows = await db.execute(select(TaskOrder).where(TaskOrder.id.in_(request.order_ids)))
        order_by_id = {
            order.id: order
            for order in rows.scalars().all()
            if order.deleted_at is None
        }
        missing = {
            order_id: "Order not found"
            for order_id in request.order_ids
            if order_id not in order_by_id
        }
        visible_orders: list[TaskOrder] = []
        for order_id in request.order_ids:
            order = order_by_id.get(order_id)
            if not order:
                continue
            if current_user is not None and not _is_admin_user(current_user) and order.user_id != current_user.id:
                missing[order_id] = "Access denied"
                continue
            visible_orders.append(order)
        return visible_orders, missing

    if not request.benchmark_run_id:
        raise HTTPException(status_code=400, detail="order_ids or benchmark_run_id is required")

    query = select(TaskOrder).where(TaskOrder.deleted_at.is_(None))
    if current_user is not None:
        query = _apply_order_visibility(query, current_user)
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
    task_type = _benchmark_task_type(order)
    if task_type:
        result = await db.execute(
            select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == task_type)
        )
        catalog = result.scalar_one_or_none()
        if catalog:
            return catalog

    result = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.template_id == order.template_id)
    )
    return result.scalars().first()


async def _template_id_for_order(db: AsyncSession, order: TaskOrder) -> str:
    catalog = await _catalog_for_order(db, order)
    return catalog.template_id if catalog else order.template_id


def _benchmark_config(task_type: str) -> dict:
    try:
        return BENCHMARK_TASK_CONFIGS[task_type]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported benchmark task_type: {task_type}") from exc


def _normal_node_kind(node: NodeModel) -> str:
    return str(node.node_kind or "worker").lower()


def _node_can_host_endpoint_container(node: NodeModel) -> bool:
    """Current topology keeps source/sink endpoint containers on h1-h13 only."""
    return (
        node.hostname in TERMINAL_NODE_ALIASES
        and bool(node.is_schedulable)
        and bool(node.is_routable)
        and node.deleted_at is None
        and _normal_node_kind(node) == "terminal"
    )


def _node_can_host_benchmark_endpoint(node: NodeModel) -> bool:
    """Batch business evaluation deploys source/sink on terminal-side nodes only."""
    return (
        node.hostname in TERMINAL_NODE_ALIASES
        and bool(node.is_schedulable)
        and bool(node.is_routable)
        and node.deleted_at is None
        and _normal_node_kind(node) == "terminal"
    )


def _node_can_host_compute(node: NodeModel) -> bool:
    """Compute placement must stay on compute-capable topology nodes."""
    return (
        node.hostname in COMPUTE_NODE_ALIASES
        and bool(node.is_schedulable)
        and bool(node.is_routable)
        and node.deleted_at is None
        and _normal_node_kind(node) == "worker"
    )


def _prefer_gpu_nodes(nodes: list[NodeModel]) -> list[NodeModel]:
    with_gpu = [node for node in nodes if int(node.gpu_count or 0) > 0]
    return with_gpu or nodes


def _rank_compute_nodes_by_baseline(
    nodes: list[NodeModel],
    baselines_by_node_id: dict[str, NodeBaseline],
) -> list[NodeModel]:
    """Use any measured baseline, but prefer stable/GPU/stronger nodes first."""
    if not nodes:
        return []
    sample_baseline = next(iter(baselines_by_node_id.values()), None)
    reverse_metric = _baseline_better_direction(
        sample_baseline.metric_key if sample_baseline else None,
        sample_baseline.operator if sample_baseline else None,
    ) == "higher"

    def score(node: NodeModel) -> tuple[int, int, float, str]:
        baseline = baselines_by_node_id.get(node.id)
        stable_rank = 0 if baseline and _baseline_is_stable(baseline.raw_values) else 1
        gpu_rank = 0 if int(node.gpu_count or 0) > 0 else 1
        value = float(baseline.baseline_value if baseline else 0)
        metric_rank = -value if reverse_metric else value
        return (stable_rank, gpu_rank, metric_rank, node.hostname or "")

    return sorted(nodes, key=score)


async def _deployable_endpoint_nodes(db: AsyncSession) -> list[NodeModel]:
    rows = await db.execute(
        select(NodeModel)
        .where(
            NodeModel.is_schedulable == True,
            NodeModel.is_routable == True,
            NodeModel.deleted_at.is_(None),
        )
        .order_by(NodeModel.hostname.asc())
    )
    return [node for node in rows.scalars().all() if _node_can_host_benchmark_endpoint(node)]


def _pick_endpoint_pair(endpoint_nodes: list[NodeModel], index: int) -> tuple[NodeModel, NodeModel]:
    if not endpoint_nodes:
        raise HTTPException(
            status_code=400,
            detail="No deployable endpoint nodes available for source/sink containers",
        )
    if len(endpoint_nodes) == 1:
        return endpoint_nodes[0], endpoint_nodes[0]
    source = endpoint_nodes[index % len(endpoint_nodes)]
    sink = endpoint_nodes[(index + 1) % len(endpoint_nodes)]
    return source, sink


def _merged_benchmark_profile(task_type: str, data_profile: dict | None) -> dict:
    config = _benchmark_config(task_type)
    return {**config["default_profile"], **(data_profile or {})}


def _default_compute_gpu_for_order(order: TaskOrder) -> str | None:
    task_type = _benchmark_task_type(order)
    if not task_type:
        return "0"
    try:
        return _benchmark_config(task_type).get("default_compute_gpu") or "0"
    except HTTPException:
        return "0"


async def _network_ready_wait_message(db: AsyncSession, instance_id: str) -> str | None:
    waiting_order = await instance_waiting_for_network_ready(db, instance_id)
    if waiting_order:
        return f"工单 {waiting_order.id} 等待外部路由系统确认 network-ready"
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
    metadata = routing_result.get("metadata") if isinstance(routing_result, dict) else None
    allocation_mode = (
        metadata.get("compute_allocation_mode")
        if isinstance(metadata, dict)
        else None
    )
    placements = routing_result.get("placements")
    placement = None
    if isinstance(placements, list):
        for item in placements:
            if isinstance(item, dict) and _placement_role(item) in ("compute", "worker"):
                placement = item
                break

    host = "unknown"
    gpu = _default_compute_gpu_for_order(order) or "none"
    if isinstance(placement, dict):
        host = (
            placement.get("topology_node_id")
            or host
        )
        gpu = placement.get("gpu_device") or gpu
    if allocation_mode == "node":
        return f"{host}:node"
    return f"{host}:gpu={gpu}"


def _is_gpu_benchmark_order(order: TaskOrder) -> bool:
    task_type = _benchmark_task_type(order)
    return task_type in {
        "high_throughput_matmul",
        "low_latency_video_pipeline",
        "metaverse_video_fusion",
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
            if _placement_role(placement) != role:
                continue
            gpu_device = placement.get("gpu_device")
            if gpu_device is not None:
                return str(gpu_device)
    return None


def _routing_decision_task_type(order: TaskOrder, business_task: dict[str, Any] | None) -> str | None:
    if isinstance(business_task, dict) and business_task.get("task_type"):
        return str(business_task["task_type"])
    return _benchmark_task_type(order)


def _routing_decision_metric_key(
    order: TaskOrder,
    business_task: dict[str, Any] | None,
) -> str | None:
    objective = (business_task or {}).get("business_objective") if isinstance(business_task, dict) else None
    if isinstance(objective, dict) and objective.get("metric_key"):
        return str(objective["metric_key"])
    task_type = _routing_decision_task_type(order, business_task)
    if not task_type:
        return None
    try:
        return _benchmark_config(task_type)["business_objective"].get("metric_key")
    except HTTPException:
        return None


def _node_identity(node: NodeModel | None) -> dict[str, Any] | None:
    if node is None:
        return None
    return {
        "id": node.id,
        "hostname": node.hostname,
        "display_name": node.display_name,
        "topology_node_id": node.topology_node_id or node.hostname,
        "business_ip": node.business_ip,
        "business_ipv6": node.business_ipv6,
        "node_kind": node.node_kind,
        "gpu_count": node.gpu_count,
        "gpu_model": node.gpu_model,
        "gpu_memory_mb": node.gpu_memory_mb,
        "cpu_model": node.cpu_model,
        "cpu_cores": node.cpu_cores,
        "memory_mb": node.memory_mb,
    }


def _baseline_summary(baseline: NodeBaseline | None) -> dict[str, Any] | None:
    if baseline is None:
        return None
    return {
        "task_type": baseline.task_type,
        "metric_key": baseline.metric_key,
        "baseline_value": baseline.baseline_value,
        "operator": baseline.operator,
        "unit": baseline.unit,
        "run_count": baseline.run_count,
        "raw_values": baseline.raw_values,
    }


def _baseline_better_direction(metric_key: str | None, operator: str | None = None) -> str:
    metric = (metric_key or "").lower()
    if operator and str(operator).strip() in {"<", "<="}:
        return "lower"
    if any(token in metric for token in ("latency", "delay", "time", "duration", "p90", "p95")):
        return "lower"
    return "higher"


def _metric_display_name(metric_key: str | None) -> str:
    return {
        "effective_gflops": "有效计算吞吐量",
        "frame_latency_p90_ms": "帧推理时延 P90",
        "tokens_per_second": "文本生成吞吐量",
    }.get(metric_key or "", metric_key or "业务指标")


def _node_display_name(node: NodeModel) -> str:
    return node.display_name or node.hostname or node.topology_node_id or node.id


def _selected_compute_topology_id(routing_result: dict[str, Any] | None) -> str | None:
    if not isinstance(routing_result, dict):
        return None
    placements = routing_result.get("placements")
    if not isinstance(placements, list):
        return None
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        if _placement_role(placement) in {"compute", "worker", "infer", "inference", "train"}:
            return _placement_topology_key(placement)
    return None


async def _build_node_capability_profile(
    db: AsyncSession,
    order: TaskOrder,
    routing_result: dict[str, Any] | None,
    business_task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    task_type = _routing_decision_task_type(order, business_task)
    metric_key = _routing_decision_metric_key(order, business_task)
    if not task_type or not metric_key:
        return None

    selected_topology_id = _selected_compute_topology_id(routing_result)
    rows = await db.execute(
        select(NodeModel)
        .where(
            NodeModel.deleted_at.is_(None),
            NodeModel.is_schedulable == True,
            NodeModel.is_routable == True,
        )
        .order_by(NodeModel.hostname.asc())
    )
    compute_nodes = [node for node in rows.scalars().all() if _node_can_host_compute(node)]
    if not compute_nodes:
        return None

    node_ids = [node.id for node in compute_nodes]
    baseline_rows = await db.execute(
        select(NodeBaseline).where(
            NodeBaseline.node_id.in_(node_ids),
            NodeBaseline.task_type == task_type,
            NodeBaseline.metric_key == metric_key,
        )
    )
    baselines_by_node_id: dict[str, NodeBaseline] = {}
    for baseline in baseline_rows.scalars().all():
        baselines_by_node_id.setdefault(baseline.node_id, baseline)

    baseline_values = list(baselines_by_node_id.values())
    better_direction = _baseline_better_direction(
        metric_key,
        baseline_values[0].operator if baseline_values else None,
    )
    reverse = better_direction == "higher"

    ranked_nodes = [
        (node, baselines_by_node_id.get(node.id))
        for node in compute_nodes
        if baselines_by_node_id.get(node.id) is not None
    ]
    ranked_nodes.sort(
        key=lambda item: item[1].baseline_value if item[1] else 0,
        reverse=reverse,
    )
    rank_by_node_id = {node.id: index + 1 for index, (node, _) in enumerate(ranked_nodes)}

    nodes_by_key: dict[str, NodeModel] = {}
    for node in compute_nodes:
        nodes_by_key[node.hostname] = node
        nodes_by_key[node.id] = node
        if node.topology_node_id:
            nodes_by_key[node.topology_node_id] = node
    selected_node = nodes_by_key.get(selected_topology_id or "") if selected_topology_id else None
    selected_baseline = baselines_by_node_id.get(selected_node.id) if selected_node else None
    selected_rank = rank_by_node_id.get(selected_node.id) if selected_node else None

    metric_label = _metric_display_name(metric_key)
    unit = selected_baseline.unit if selected_baseline else (baseline_values[0].unit if baseline_values else None)
    if selected_baseline and selected_rank:
        if selected_rank == 1 and better_direction == "lower":
            headline = "低时延表现最优"
            description = (
                f"该节点在同类算力节点中历史 {metric_label} 排名第 1 / {len(ranked_nodes)}，"
                "适合低时延相关策略。"
            )
        elif selected_rank == 1:
            headline = "计算吞吐表现最优"
            description = (
                f"该节点在同类算力节点中历史 {metric_label} 排名第 1 / {len(ranked_nodes)}，"
                "适合计算能力优先或完成时间优先的任务。"
            )
        else:
            headline = "已分配节点能力画像"
            description = (
                f"该节点在同类算力节点中历史 {metric_label} 排名第 {selected_rank} / {len(ranked_nodes)}，"
                "下表展示候选节点基线表现，便于核对当前策略下的分配结果。"
            )
    elif selected_node:
        headline = "已分配计算节点，等待基线数据"
        description = "当前节点已完成分配，但暂未找到该任务类型的历史基线，请先在业务测评页完成基线测试。"
    else:
        headline = "等待计算节点分配"
        description = "完成节点分配后，这里会根据本系统历史基线展示算力节点匹配结果。"

    candidate_rows = []
    for node, baseline in ranked_nodes:
        candidate_rows.append({
            "node_id": node.id,
            "node_name": _node_display_name(node),
            "hostname": node.hostname,
            "topology_node_id": node.topology_node_id or node.hostname,
            "baseline": _baseline_summary(baseline),
            "rank": rank_by_node_id.get(node.id),
            "selected": bool(selected_node and node.id == selected_node.id),
            "gpu_count": node.gpu_count,
            "gpu_model": node.gpu_model,
        })

    return {
        "title": "算力节点能力画像",
        "task_type": task_type,
        "metric_key": metric_key,
        "metric_label": metric_label,
        "unit": unit,
        "better_direction": better_direction,
        "selected_node": _node_identity(selected_node) if selected_node else None,
        "selected_baseline": _baseline_summary(selected_baseline),
        "selected_rank": selected_rank,
        "candidate_count": len(ranked_nodes),
        "headline": headline,
        "description": description,
        "candidate_rows": candidate_rows,
        "missing_baseline_count": max(len(compute_nodes) - len(ranked_nodes), 0),
    }


def _placement_topology_key(value: dict[str, Any]) -> str | None:
    raw = value.get("topology_node_id") or value.get("hostname")
    return str(raw) if raw else None


async def _build_routing_decision_summary(
    db: AsyncSession,
    order: TaskOrder,
    routing_result: dict[str, Any] | None,
    business_task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(routing_result, dict):
        return None
    placements = routing_result.get("placements")
    if not isinstance(placements, list):
        placements = []

    topology_ids = {
        key
        for item in placements
        if isinstance(item, dict)
        for key in [_placement_topology_key(item)]
        if key
    }
    metadata = routing_result.get("metadata") if isinstance(routing_result.get("metadata"), dict) else {}
    candidate_scores = metadata.get("candidate_scores") if isinstance(metadata, dict) else None
    if isinstance(candidate_scores, list):
        for item in candidate_scores:
            if isinstance(item, dict):
                key = _placement_topology_key(item)
                if key:
                    topology_ids.add(key)

    nodes_by_key: dict[str, NodeModel] = {}
    if topology_ids:
        rows = await db.execute(
            select(NodeModel).where(
                NodeModel.deleted_at.is_(None),
                NodeModel.hostname.in_(topology_ids) | NodeModel.topology_node_id.in_(topology_ids),
            )
        )
        for node in rows.scalars().all():
            nodes_by_key[node.hostname] = node
            if node.topology_node_id:
                nodes_by_key[node.topology_node_id] = node

    task_type = _routing_decision_task_type(order, business_task)
    metric_key = _routing_decision_metric_key(order, business_task)
    baseline_by_node_id: dict[str, NodeBaseline] = {}
    node_ids = {node.id for node in nodes_by_key.values()}
    if node_ids and task_type:
        query = select(NodeBaseline).where(
            NodeBaseline.node_id.in_(node_ids),
            NodeBaseline.task_type == task_type,
        )
        if metric_key:
            query = query.where(NodeBaseline.metric_key == metric_key)
        rows = await db.execute(query)
        for baseline in rows.scalars().all():
            baseline_by_node_id.setdefault(baseline.node_id, baseline)

    def enrich(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        key = _placement_topology_key(item)
        node = nodes_by_key.get(key or "")
        if node:
            result["node"] = _node_identity(node)
            result["baseline"] = _baseline_summary(baseline_by_node_id.get(node.id))
        return result

    selected_compute = None
    for item in placements:
        if isinstance(item, dict) and _placement_role(item) in {"compute", "worker", "infer", "inference", "train"}:
            selected_compute = enrich(item)
            break

    enriched_candidates = [
        enrich(item)
        for item in candidate_scores
        if isinstance(item, dict)
    ] if isinstance(candidate_scores, list) else []

    decision = {
        "strategy": routing_result.get("strategy"),
        "selected_strategy": routing_result.get("selected_strategy"),
        "external_routing_id": routing_result.get("external_routing_id"),
        "selected_compute": selected_compute,
        "path": metadata.get("path") if isinstance(metadata, dict) else None,
        "selected_reason": metadata.get("selected_reason") if isinstance(metadata, dict) else None,
        "candidate_scores": enriched_candidates,
        "estimated_metric": routing_result.get("estimated_metric"),
        "metadata": metadata,
    }
    return {key: value for key, value in decision.items() if value not in (None, [], {})}


def _order_to_response(
    order: TaskOrder,
    instance_exists: bool | None = None,
    deployment_status: TaskStatus | None = None,
    evaluation: BusinessObjectiveEvaluation | None = None,
    owner: User | None = None,
) -> TaskOrderResponse:
    rc = order.runtime_config or {}
    bt = rc.get("business_task") or {}
    rp = bt.get("runtime_plan") or {}
    routing_result = rc.get("routing_result") if isinstance(rc.get("routing_result"), dict) else {}
    routing_metadata = routing_result.get("metadata") if isinstance(routing_result.get("metadata"), dict) else {}
    routing_dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    raw_priority = routing_dag.get("priority") or bt.get("priority")
    try:
        business_priority = int(raw_priority) if raw_priority is not None else None
    except (TypeError, ValueError):
        business_priority = None
    data = TaskOrderResponse.model_validate(order)
    updates = {
        "owner_user_id": order.user_id,
        "owner_username": owner.username if owner else None,
        "task_type": bt.get("task_type"),
        "routing_policy": (
            normalize_routing_policy(routing_result.get("strategy"))
            or normalize_routing_policy(routing_result.get("routing_policy"))
            or normalize_routing_policy(bt.get("routing_policy"))
            or normalize_routing_policy(rp.get("routing_strategy"))
            or normalize_routing_policy(bt.get("routing_strategy"))
        ),
        "route_source_label": routing_metadata.get("route_source_label"),
        "business_priority": business_priority,
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


async def _metric_evidence_summary(
    db: AsyncSession,
    instance_id: str | None,
    business_task: dict[str, Any] | None,
) -> TaskOrderEvaluationSummary | None:
    """Build read-only result evidence when no formal evaluation is available.

    Lightweight user-access demos may intentionally differ from the official
    benchmark profile, so they are not judged against node baselines.  The
    latest reported metric is still useful proof that the business container
    actually ran, and the order detail page can display it without adding it to
    benchmark success-rate statistics.
    """
    if not instance_id or not isinstance(business_task, dict):
        return None
    objective = business_task.get("business_objective")
    if not isinstance(objective, dict):
        return None
    metric_key = objective.get("metric_key")
    if not metric_key:
        return None
    row = await db.execute(
        select(TaskMetric)
        .where(TaskMetric.instance_id == instance_id, TaskMetric.metric_key == metric_key)
        .order_by(TaskMetric.reported_at.desc(), TaskMetric.id.desc())
    )
    metric = row.scalar_one_or_none()
    if not metric:
        return None
    from api.business_tasks import _extract_result_metadata

    return TaskOrderEvaluationSummary(
        metric_key=metric.metric_key,
        actual_value=metric.metric_value,
        target_value=None,
        unit=metric.unit,
        business_success=None,
        failure_reason="当前仅展示运行证据，尚未形成正式业务目标判定，不纳入业务目标成功率统计。",
        result_metadata=_extract_result_metadata(metric.tags),
    )


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


async def _users_by_ids(db: AsyncSession, user_ids: list[str]) -> dict[str, User]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {row.id: row for row in rows.scalars()}


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
async def create_order(
    payload: TaskOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        user_id=current_user.id,
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
    user_map = await _users_by_ids(db, [order.user_id for order in orders if order.user_id])
    for order in orders:
        exists, deployment_status = await _instance_state(db, order.materialized_instance_id)
        responses.append(
            _order_to_response(
                order,
                instance_exists=exists,
                deployment_status=deployment_status,
                evaluation=eval_map.get(order.materialized_instance_id or ""),
                owner=user_map.get(order.user_id or ""),
            )
        )
    return responses


@router.get("/benchmark/runs", response_model=list[BenchmarkRunSummary])
async def list_benchmark_runs(
    task_type: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List existing benchmark runs without loading every order into the UI."""
    query = select(TaskOrder).where(
        TaskOrder.is_benchmark.is_(True),
        TaskOrder.deleted_at.is_(None),
    )
    query = _apply_order_visibility(query, current_user)
    rows = await db.execute(query.order_by(TaskOrder.created_at.desc()))

    runs: dict[str, BenchmarkRunSummary] = {}
    max_runs = max(1, min(limit, 100))
    for order in rows.scalars().all():
        run_id = _benchmark_run_id(order)
        order_task_type = _benchmark_task_type(order)
        if not run_id or not order_task_type or (task_type and order_task_type != task_type):
            continue
        if run_id in runs:
            runs[run_id].order_count += 1
            continue
        if len(runs) >= max_runs:
            continue
        runs[run_id] = BenchmarkRunSummary(
            benchmark_run_id=run_id,
            task_type=order_task_type,
            created_at=order.created_at,
            order_count=1,
        )
    return list(runs.values())


@router.get("/{order_id}", response_model=TaskOrderDetailResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order, instance, evaluation = await get_order_detail_context(db, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    config = order.runtime_config or {}
    business_task = config.get("business_task")
    routing_result = config.get("routing_result")
    if not isinstance(routing_result, dict) and isinstance(business_task, dict):
        routing_result = business_task.get("routing_result")

    instance_exists, deployment_status = await _instance_state(db, order.materialized_instance_id)
    owner = None
    if order.user_id:
        owner = (
            await db.execute(select(User).where(User.id == order.user_id))
        ).scalar_one_or_none()
    base = _order_to_response(
        order,
        instance_exists=instance_exists,
        deployment_status=deployment_status,
        evaluation=evaluation,
        owner=owner,
    )
    detail = TaskOrderDetailResponse.model_validate(base.model_dump())
    detail.business_task = business_task if isinstance(business_task, dict) else None
    detail.routing_result = routing_result if isinstance(routing_result, dict) else None
    detail.routing_decision = await _build_routing_decision_summary(
        db,
        order,
        detail.routing_result,
        detail.business_task,
    )
    detail.node_capability_profile = await _build_node_capability_profile(
        db,
        order,
        detail.routing_result,
        detail.business_task,
    )
    detail.user_access_guide = await build_user_access_guide(
        db,
        order,
        instance,
        detail.business_task,
        detail.routing_result,
    )

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
            biz_addr = get_business_address(machine, settings.prefer_business_ipv6) if machine else None
            port_values = _instance_node_port_values(inst_node)
            node_port_access_urls: dict[str, str] = {}
            if port_values and biz_addr:
                for port_name, port_val in port_values.items():
                    try:
                        port_int = int(port_val)
                    except (TypeError, ValueError):
                        continue
                    node_port_access_urls[str(port_name)] = format_service_url(biz_addr, port_int)
            if role in ("compute", "worker") and not (gpu_device or gpu_id):
                routing_gpu = _gpu_from_routing_result(routing_result, role)
                gpu_device = routing_gpu or None
            node_placements.append(
                TaskOrderNodePlacementSummary(
                    role=role,
                    instance_node_name=inst_node.name,
                    node_id=inst_node.node_id,
                    hostname=machine.hostname if machine else None,
                    image=inst_node.image,
                    container_id=inst_node.container_id,
                    container_name=inst_node.container_name,
                    business_address=biz_addr,
                    gpu_id=gpu_id,
                    gpu_device=gpu_device,
                    port_values=port_values,
                    port_access_urls=node_port_access_urls or None,
                    status=inst_node.status,
                    error_message=inst_node.error_message,
                )
            )
            if not port_values:
                continue
            if not machine:
                continue
            for port_name, port_val in port_values.items():
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
            node_count=len(inst_nodes),
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
    elif instance:
        detail.evaluation = await _metric_evidence_summary(
            db,
            instance.id,
            detail.business_task,
        )
    return detail


@router.delete("/{order_id}")
async def delete_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _ensure_order_owner_or_admin(order, current_user)
    task_scheduler = TaskScheduler()
    try:
        await _cleanup_materialized_order_instance(db, order, task_scheduler)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=f"{exc}，工单未删除") from exc
    await emit_release_events_for_order(
        db,
        order,
        reason="delete_order",
        metadata={"instance_id": order.materialized_instance_id},
    )
    await _detach_order_references_before_delete(db, order)
    await purge_order_instances_by_source_order(db, order.id)
    await purge_order_instance_artifacts(db, order.materialized_instance_id)
    await db.delete(order)
    await db.commit()
    return {"message": "工单已删除"}


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _ensure_order_owner_or_admin(order, current_user)

    if order.status == OrderStatus.CANCELLED:
        return {"message": "工单已取消", "status": OrderStatus.CANCELLED.value}
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="当前状态不可取消，请在工单详情中查看运行状态或删除废弃工单")

    order.status = OrderStatus.CANCELLED
    order.routing_status = RoutingStatus.CANCELLED.value
    await emit_release_events_for_order(
        db,
        order,
        reason="cancel_order",
        metadata={"instance_id": order.materialized_instance_id},
    )

    if order.conversation_id:
        conversation_row = await db.execute(select(Conversation).where(Conversation.id == order.conversation_id))
        conversation = conversation_row.scalar_one_or_none()
        if conversation and conversation.materialized_order_id == order.id:
            conversation.status = ConversationStatus.CANCELLED

    if order.routing_request_id:
        routing_row = await db.execute(select(RoutingRequest).where(RoutingRequest.id == order.routing_request_id))
        routing = routing_row.scalar_one_or_none()
        if routing:
            routing.status = RoutingRequestStatus.CANCELLED

    await db.commit()
    return {"message": "工单已取消", "status": OrderStatus.CANCELLED.value}


@router.post("/batch/delete", response_model=BatchOperationResponse)
async def batch_delete_orders(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    succeeded: list[str] = []
    if not _is_admin_user(current_user) and not request.order_ids:
        raise HTTPException(status_code=403, detail="普通用户只能批量删除自己选中的工单")
    orders, failed = await _resolve_batch_orders(db, request, current_user)
    task_scheduler = TaskScheduler()
    for order in orders:
        try:
            await _cleanup_materialized_order_instance(db, order, task_scheduler)
            await emit_release_events_for_order(
                db,
                order,
                reason="delete_order",
                metadata={"instance_id": order.materialized_instance_id, "batch": True},
            )
            await _detach_order_references_before_delete(db, order)
            await purge_order_instances_by_source_order(db, order.id)
            await purge_order_instance_artifacts(db, order.materialized_instance_id)
            await db.delete(order)
            succeeded.append(order.id)
        except RuntimeError as exc:
            failed[order.id] = str(exc)
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
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin role required")
    succeeded: list[str] = []
    orders, failed = await _resolve_batch_orders(db, request, current_user)
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

            _reject_active_instance_for_cleanup(instance)
            await task_scheduler.cancel_all_schedules(instance.id)
            cleanup_warnings = await cleanup_instance_runtime(db, instance)
            if cleanup_warnings:
                raise RuntimeError(f"容器清理失败：{'；'.join(cleanup_warnings)}")
            await emit_release_events_for_order(
                db,
                order,
                reason="cleanup_instance",
                metadata={"instance_id": instance.id, "preserve_order": True},
            )
            await purge_instance_artifacts_preserve_evidence(db, instance.id)
            if order.status == OrderStatus.MATERIALIZED:
                order.status = OrderStatus.COMPLETED
            succeeded.append(order.id)
        except Exception as exc:
            failed[order.id] = str(exc)

    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/{order_id}/stop-runtime")
async def stop_order_runtime(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止并清理工单当前部署实例，保留工单、路由结果、评估和结果证据。"""
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _ensure_order_owner_or_admin(order, current_user)

    if not order.materialized_instance_id:
        return {"message": "当前工单没有已生成实例", "stopped": False}

    result = await db.execute(
        select(TaskInstance)
        .options(selectinload(TaskInstance.nodes))
        .where(TaskInstance.id == order.materialized_instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        if order.status == OrderStatus.MATERIALIZED:
            order.status = OrderStatus.COMPLETED
        await db.commit()
        return {"message": "运行实例已不存在，已保留工单证据", "stopped": False}

    executor = DAGExecutor(db)
    if instance.status not in (TaskStatus.STOPPED, TaskStatus.PENDING):
        success, error = await executor.execute_dag_stop(instance.id)
        if not success:
            raise HTTPException(status_code=500, detail=error or "停止实例失败")

    await emit_release_events_for_order(
        db,
        order,
        reason="stop_order_runtime",
        metadata={"instance_id": instance.id, "preserve_order": True},
    )
    cleanup_warnings = await cleanup_instance_runtime(db, instance)
    if cleanup_warnings:
        raise HTTPException(status_code=409, detail=f"容器清理失败：{'；'.join(cleanup_warnings)}")
    await purge_instance_artifacts_preserve_evidence(db, instance.id)
    if order.status == OrderStatus.MATERIALIZED:
        order.status = OrderStatus.COMPLETED
    await db.commit()
    return {"message": "任务运行已停止，工单证据已保留", "stopped": True}


@router.post("/{order_id}/materialize", response_model=dict)
async def materialize_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_order_owner_or_admin(order, current_user)
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Order is cancelled")

    config = order.runtime_config or {}
    try:
        instance = TaskInstanceCreate(
            template_id=await _template_id_for_order(db, order),
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
async def materialize_pending_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin role required")
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
                template_id=await _template_id_for_order(db, order),
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
    model_config = ConfigDict(extra="forbid")

    task_node_id: str
    topology_node_id: str
    gpu_device: Optional[str] = None


class RoutingResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placements: list[RoutingPlacement] = Field(default_factory=list)
    strategy: Optional[str] = None
    selected_strategy: Optional[str] = None
    external_routing_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    estimated_metric: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    require_network_ready: bool = True

    @model_validator(mode="after")
    def _validate_strategy(self):
        if self.strategy is not None:
            self.strategy = require_routing_policy(self.strategy, field_name="strategy")
        return self


def _placement_role(placement: RoutingPlacement | dict[str, Any]) -> str:
    if isinstance(placement, RoutingPlacement):
        return str(placement.task_node_id or "").lower()
    return str(placement.get("task_node_id") or "").lower()


def _routing_dag_nodes_by_role(order: TaskOrder) -> dict[str, dict[str, Any]]:
    dag = order.routing_input_dag if isinstance(order.routing_input_dag, dict) else {}
    nodes = dag.get("nodes") if isinstance(dag, dict) else None
    if not isinstance(nodes, list):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for key in (node.get("task_node_id"), node.get("task_role")):
            if key:
                result[str(key).lower()] = node
    return result


def _routing_dag_resources_by_role(order: TaskOrder) -> dict[str, dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}
    for role, node in _routing_dag_nodes_by_role(order).items():
        value = node.get("resources") if isinstance(node, dict) else None
        if isinstance(value, dict):
            resources[role] = value
    return resources


def _role_set(value: Any) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return set()
    return {str(item).lower() for item in value if item is not None}


def _platform_deployment_policy(order: TaskOrder) -> tuple[set[str] | None, set[str] | None]:
    """Platform-owned deployment policy.

    The external router decides placements and paths. Whether a logical DAG node
    becomes a container is owned by this platform and can be stored on the order.
    """
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    deployment = config.get("platform_deployment") or config.get("deployment_plan") or {}
    if not isinstance(deployment, dict):
        return None, None
    return (
        _role_set(deployment.get("deployable_roles")),
        _role_set(deployment.get("non_deployable_roles") or deployment.get("virtual_roles")),
    )


def _platform_deployment_mode(order: TaskOrder) -> str | None:
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    deployment = config.get("platform_deployment") or config.get("deployment_plan") or {}
    if not isinstance(deployment, dict):
        return None
    mode = deployment.get("mode")
    return str(mode) if mode else None


def _placement_is_deployable(
    order: TaskOrder,
    placement: RoutingPlacement,
    dag_nodes_by_role: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Return whether this logical DAG node should be materialized as a container.

    Deployment is a platform-owned policy. New integrations should not ask the
    router to decide this; use runtime_config.platform_deployment instead.
    """
    role = str(placement.task_node_id or "").lower()
    deployable_roles, non_deployable_roles = _platform_deployment_policy(order)
    if deployable_roles is not None:
        return role in deployable_roles
    if non_deployable_roles is not None:
        return role not in non_deployable_roles

    dag_nodes_by_role = dag_nodes_by_role or _routing_dag_nodes_by_role(order)
    dag_node = dag_nodes_by_role.get(role)
    if isinstance(dag_node, dict) and isinstance(dag_node.get("deployable"), bool):
        return bool(dag_node["deployable"])

    return True


def _complete_platform_fixed_endpoint_placements(
    order: TaskOrder,
    placements: list[RoutingPlacement],
    dag_nodes_by_role: dict[str, dict[str, Any]],
) -> list[RoutingPlacement]:
    """Add platform-known deployable endpoints that the router does not need to compute.

    Routers only need to choose work/compute nodes. If source/sink are deployable
    containers in this platform, their physical names are already fixed by the
    user/DAG, so the platform can add them before materialization.
    """
    completed = list(placements)
    existing_roles = {str(item.task_node_id or "").lower() for item in completed}

    for role in ("source", "sink"):
        if role in existing_roles:
            continue
        dag_node = dag_nodes_by_role.get(role)
        if not dag_node:
            continue
        topology_node_id = dag_node.get("fixed_topology_node_id")
        if not topology_node_id:
            topology_node_id = order.source_name if role == "source" else order.destination_name
        if not topology_node_id:
            continue
        candidate = RoutingPlacement(
            task_node_id=role,
            topology_node_id=str(topology_node_id),
        )
        if _placement_is_deployable(order, candidate, dag_nodes_by_role):
            completed.append(candidate)

    return completed


def _placement_topology_node_id(placement: RoutingPlacement | dict[str, Any]) -> str | None:
    if isinstance(placement, RoutingPlacement):
        return placement.topology_node_id
    value = placement.get("topology_node_id")
    return str(value) if value else None


def _placement_gpu_ids(placement: RoutingPlacement | dict[str, Any]) -> list[str]:
    if isinstance(placement, RoutingPlacement):
        return [str(placement.gpu_device)] if placement.gpu_device is not None else []
    if placement.get("gpu_device") is not None:
        return [str(placement["gpu_device"])]
    return []


def _instance_node_port_values(node: TaskInstanceNode) -> dict[str, Any] | None:
    if isinstance(node.port_values, dict) and node.port_values:
        return node.port_values
    if not isinstance(node.ports, dict) or not node.ports:
        return None
    values: dict[str, Any] = {}
    for container_port, host_port in node.ports.items():
        raw_name = str(container_port).split("/", 1)[0]
        name = (node.name or "service") if raw_name.isdigit() else raw_name
        try:
            values[name] = int(host_port)
        except (TypeError, ValueError):
            values[name] = host_port
    return values or None


def _compute_gpu_slots_from_placements(
    placements: list[RoutingPlacement] | list[dict[str, Any]],
) -> set[tuple[str, str]]:
    slots: set[tuple[str, str]] = set()
    for placement in placements:
        if _placement_role(placement) not in {"compute", "worker", "infer", "train"}:
            continue
        topology_node_id = _placement_topology_node_id(placement)
        if not topology_node_id:
            continue
        for gpu_id in _placement_gpu_ids(placement):
            slots.add((topology_node_id, gpu_id))
    return slots


def _normalize_effective_placement_resources(
    order: TaskOrder,
    placements: list[RoutingPlacement],
) -> list[RoutingPlacement]:
    """Persist the GPU slot the platform will reserve for compute roles.

    If the router omits a GPU id for a GPU-backed compute role, the platform
    reserves GPU 0 as the resource slot before conflict checks. This keeps
    routing_result, UI display, and release events consistent without implying
    anything about the physical node's GPU count.
    """
    default_gpu = _default_compute_gpu_for_order(order)
    if default_gpu is None:
        return placements

    normalized: list[RoutingPlacement] = []
    for placement in placements:
        role = str(placement.task_node_id or "").lower()
        if role in {"compute", "worker", "infer", "train"} and placement.gpu_device is None:
            normalized.append(placement.model_copy(update={"gpu_device": default_gpu}))
        else:
            normalized.append(placement)
    return normalized


async def _resolve_topology_node(db: AsyncSession, raw: str) -> NodeModel:
    result = await db.execute(
        select(NodeModel).where(
            NodeModel.deleted_at.is_(None),
            (
                (NodeModel.id == raw)
                | (NodeModel.hostname == raw)
                | (NodeModel.topology_node_id == raw)
            ),
        )
    )
    node = result.scalar_one_or_none()
    if node:
        return node

    raise HTTPException(status_code=422, detail=f"Node not found by alias/topology id: {raw}")


async def _validate_deployable_placements(
    db: AsyncSession,
    order: TaskOrder,
    placements: list[RoutingPlacement],
    dag_nodes_by_role: dict[str, dict[str, Any]],
) -> None:
    for placement in placements:
        if not _placement_is_deployable(order, placement, dag_nodes_by_role):
            continue
        role = str(placement.task_node_id or "").lower()
        node = await _resolve_topology_node(db, placement.topology_node_id)
        if node.deleted_at is not None:
            raise HTTPException(status_code=422, detail=f"Node is deleted: {node.hostname}")
        if role in {"compute", "worker", "infer", "train"}:
            if not _node_can_host_compute(node):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Compute role '{role}' requires one of compute-1/2/3 with node_kind=worker, "
                        f"got {node.hostname} ({_normal_node_kind(node)})"
                    ),
                )
        elif role in {"source", "sink", "input", "output", "video"}:
            if not _node_can_host_endpoint_container(node):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Endpoint role '{role}' requires one of h1-h13 with node_kind=terminal "
                        f"because this order deploys endpoint containers. "
                        f"Use platform_deployment.deployable_roles=[] for route-only checks."
                    ),
                )


def _routing_request_placements(
    placements: list[RoutingPlacement],
) -> list[dict[str, Any]]:
    return [placement.model_dump(exclude_none=True) for placement in placements]


def _routing_placements_from_runtime(value: Any) -> list[RoutingPlacement]:
    if not isinstance(value, list):
        return []
    placements: list[RoutingPlacement] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        task_node_id = item.get("task_node_id")
        topology_node_id = item.get("topology_node_id")
        if not task_node_id or not topology_node_id:
            continue
        placements.append(
            RoutingPlacement(
                task_node_id=str(task_node_id),
                topology_node_id=str(topology_node_id),
                gpu_device=str(item["gpu_device"]) if item.get("gpu_device") is not None else None,
            )
        )
    return placements


def _routing_payload_from_runtime_result(
    runtime_result: dict[str, Any],
    fallback: RoutingResultPayload,
) -> RoutingResultPayload:
    """Build a sync payload from persisted routing data for idempotent retries."""
    return RoutingResultPayload(
        placements=[],
        strategy=runtime_result.get("strategy") or fallback.strategy,
        selected_strategy=runtime_result.get("selected_strategy") or fallback.selected_strategy,
        external_routing_id=runtime_result.get("external_routing_id") or fallback.external_routing_id,
        metadata=runtime_result.get("metadata") if isinstance(runtime_result.get("metadata"), dict) else {},
        estimated_metric=(
            runtime_result.get("estimated_metric")
            if isinstance(runtime_result.get("estimated_metric"), dict)
            else {}
        ),
        result_payload=(
            runtime_result.get("result_payload")
            if isinstance(runtime_result.get("result_payload"), dict)
            else {}
        ),
        require_network_ready=bool(runtime_result.get("network_ready_required", False)),
    )


async def _sync_conversation_after_order_routing(
    db: AsyncSession,
    order: TaskOrder,
    payload: RoutingResultPayload,
    placements: list[RoutingPlacement],
    network_bindings: list[dict[str, Any]],
    require_network_ready: bool,
) -> None:
    """Keep the user conversation view aligned with order-id based routing."""
    routing: RoutingRequest | None = None
    if order.routing_request_id:
        routing = (
            await db.execute(select(RoutingRequest).where(RoutingRequest.id == order.routing_request_id))
        ).scalar_one_or_none()
    if routing is None and order.conversation_id:
        routing = (
            await db.execute(
                select(RoutingRequest)
                .where(RoutingRequest.order_id == order.id)
                .order_by(RoutingRequest.created_at.desc())
            )
        ).scalars().first()

    placement_rows = _routing_request_placements(placements)
    if routing is not None:
        routing.status = RoutingRequestStatus.COMPLETED
        routing.strategy = payload.strategy or routing.strategy
        if payload.selected_strategy:
            routing.selected_strategy = payload.selected_strategy
        elif payload.strategy:
            routing.selected_strategy = payload.strategy
        routing.placements = placement_rows
        routing.estimated_metric = payload.estimated_metric or routing.estimated_metric
        routing.external_routing_id = payload.external_routing_id or routing.external_routing_id
        result_payload = dict(payload.result_payload or {})
        if payload.metadata:
            result_payload["metadata"] = payload.metadata
        result_payload["network_bindings"] = network_bindings
        result_payload["network_ready_required"] = require_network_ready
        routing.result_payload = result_payload
        routing.error_message = None
        routing.completed_at = business_now()

    conversation: Conversation | None = None
    if order.conversation_id:
        conversation = (
            await db.execute(select(Conversation).where(Conversation.id == order.conversation_id))
        ).scalar_one_or_none()
    elif routing is not None:
        conversation = (
            await db.execute(select(Conversation).where(Conversation.id == routing.conversation_id))
        ).scalar_one_or_none()

    if conversation is not None:
        conversation.materialized_order_id = order.id
        deployment_mode = _platform_deployment_mode(order)
        if deployment_mode == "route_only" and order.materialized_instance_id is None:
            conversation.status = (
                ConversationStatus.READY_TO_SUBMIT
                if require_network_ready
                else ConversationStatus.SUBMITTED
            )
        else:
            conversation.status = (
                ConversationStatus.READY_TO_SUBMIT
                if require_network_ready
                else ConversationStatus.SUBMITTED
            )
        conversation.updated_at = business_now()


def _order_compute_gpu_slots(order: TaskOrder) -> set[tuple[str, str]]:
    config = order.runtime_config if isinstance(order.runtime_config, dict) else {}
    routing_result = config.get("routing_result")
    if not isinstance(routing_result, dict):
        return set()
    placements = routing_result.get("placements")
    if isinstance(placements, list):
        return _compute_gpu_slots_from_placements([p for p in placements if isinstance(p, dict)])
    return set()


def _time_windows_overlap(left: TaskOrder, right: TaskOrder) -> bool:
    left_start = left.business_start_time or left.scheduled_start_time
    left_end = left.business_end_time or left.scheduled_end_time
    right_start = right.business_start_time or right.scheduled_start_time
    right_end = right.business_end_time or right.scheduled_end_time
    if left_start and right_end and right_end <= left_start:
        return False
    if right_start and left_end and left_end <= right_start:
        return False
    return True


async def _ensure_no_active_gpu_slot_conflicts(
    db: AsyncSession,
    order: TaskOrder,
    placements: list[RoutingPlacement],
) -> None:
    requested_slots = _compute_gpu_slots_from_placements(placements)
    if not requested_slots:
        return

    rows = await db.execute(
        select(TaskOrder).where(
            TaskOrder.id != order.id,
            TaskOrder.deleted_at.is_(None),
            TaskOrder.routing_status.in_(
                [
                    RoutingStatus.NETWORK_BINDING_READY.value,
                    RoutingStatus.COMPLETED.value,
                ]
            ),
            TaskOrder.status == OrderStatus.MATERIALIZED,
            TaskOrder.materialized_instance_id.is_not(None),
        )
    )
    candidates = rows.scalars().all()
    instance_ids = [item.materialized_instance_id for item in candidates if item.materialized_instance_id]
    if not instance_ids:
        return

    instance_rows = await db.execute(select(TaskInstance).where(TaskInstance.id.in_(instance_ids)))
    instance_status = {instance.id: instance.status for instance in instance_rows.scalars().all()}
    active_statuses = {
        TaskStatus.PENDING,
        TaskStatus.SCHEDULED,
        TaskStatus.STARTING,
        TaskStatus.RUNNING,
        TaskStatus.STOPPING,
    }
    for candidate in candidates:
        status = instance_status.get(candidate.materialized_instance_id or "")
        if status not in active_statuses:
            continue
        if not _time_windows_overlap(order, candidate):
            continue
        overlap = requested_slots & _order_compute_gpu_slots(candidate)
        if overlap:
            slot_text = ", ".join(f"{host}:gpu{gpu}" for host, gpu in sorted(overlap))
            raise HTTPException(
                status_code=409,
                detail=f"GPU slot conflict for {slot_text}; release previous task before routing",
            )


async def receive_routing_result(
    order_id: str,
    payload: RoutingResultPayload,
    db: AsyncSession = Depends(get_db),
):
    """Materialize an order from validated routing placements.

    The external HTTP entrypoint is /api/routing-orders/{order_id}/result,
    which enforces claim-before-result before calling this implementation.
    """
    row = await db.execute(
        select(TaskOrder).where(TaskOrder.id == order_id).with_for_update()
    )
    order = row.scalar_one_or_none()
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.materialized_instance_id:
        rc = order.runtime_config or {}
        routing_result = rc.get("routing_result") if isinstance(rc.get("routing_result"), dict) else {}
        existing_placements = _routing_placements_from_runtime(routing_result.get("placements"))
        persisted_payload = _routing_payload_from_runtime_result(routing_result, payload)
        await _sync_conversation_after_order_routing(
            db,
            order,
            persisted_payload,
            existing_placements or payload.placements,
            routing_result.get("network_bindings") or [],
            bool(routing_result.get("network_ready_required", False)),
        )
        await db.commit()
        return {
            "status": "ok",
            "order_id": order_id,
            "routing_status": order.routing_status,
            "instance_id": order.materialized_instance_id,
            "network_bindings": routing_result.get("network_bindings", []),
            "network_ready_required": bool(routing_result.get("network_ready_required", False)),
            "network_ready": bool(routing_result.get("network_ready", False)),
            "idempotent": True,
        }
    if order.routing_status not in {
        RoutingStatus.PENDING.value,
        RoutingStatus.COMPUTING.value,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot accept routing result when routing_status is '{order.routing_status}'",
        )

    dag_nodes_by_role = _routing_dag_nodes_by_role(order)
    effective_placements = _complete_platform_fixed_endpoint_placements(
        order,
        payload.placements,
        dag_nodes_by_role,
    )
    effective_placements = _normalize_effective_placement_resources(order, effective_placements)
    await _validate_deployable_placements(db, order, effective_placements, dag_nodes_by_role)
    await _ensure_no_active_gpu_slot_conflicts(db, order, effective_placements)

    # Persist routing result
    order.routing_status = RoutingStatus.COMPUTING.value
    rc = order.runtime_config or {}
    resource_requirement = _routing_dag_resources_by_role(order)
    business_task = rc.get("business_task")
    if isinstance(business_task, dict) and resource_requirement:
        business_task["resource_requirement"] = resource_requirement
        rc["business_task"] = business_task
    routing_result = {
        "placements": [p.model_dump(exclude_none=True) for p in effective_placements],
    }
    if len(effective_placements) != len(payload.placements):
        routing_result["router_placements"] = [p.model_dump(exclude_none=True) for p in payload.placements]
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
    enabled_template_node_names: list[str] = []
    for placement in effective_placements:
        role = placement.task_node_id
        template_node_name = role_node_names.get(role) if catalog else role
        if template_node_name is None:
            template_node_name = role

        if not _placement_is_deployable(order, placement, dag_nodes_by_role):
            continue

        try:
            resolved_node_id = await resolve_node_id(db, placement.topology_node_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        bt = (order.runtime_config or {}).get("business_task", {})
        env = build_business_env(
            order=order,
            business_task=bt,
            task_role=role,
            task_instance_id=order.id,  # updated after instance creation
            resource_requirement=resource_requirement,
            routing_result=routing_result,
        )
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
        if template_node_name not in enabled_template_node_names:
            enabled_template_node_names.append(template_node_name)

    if not enabled_template_node_names:
        deployment_mode = _platform_deployment_mode(order)
        route_only = deployment_mode == "route_only"
        # The terminal-transfer task represents a real data-plane route, so it
        # must wait for the external router to confirm flow installation. Keep
        # older route-only decision tasks immediately complete for compatibility.
        task_type = _benchmark_task_type(order)
        require_network_ready = (
            bool(payload.require_network_ready)
            if task_type == "terminal_route_transfer"
            else False
        )
        order.materialized_instance_id = None
        order.status = OrderStatus.PENDING if route_only else OrderStatus.COMPLETED
        order.routing_status = (
            RoutingStatus.NETWORK_BINDING_READY.value
            if require_network_ready
            else RoutingStatus.COMPLETED.value
        )
        rc["deployment_required"] = False
        if route_only:
            rc["manual_start_required"] = True
        if route_only:
            rc["deployment_mode"] = "route_only"
        rc["routing_result"] = {
            **routing_result,
            "network_bindings": [],
            "network_ready_required": require_network_ready,
            "network_ready": not require_network_ready,
        }
        if route_only:
            rc["routing_result"]["deployment_mode"] = "route_only"
            rc["routing_result"]["route_only"] = True
        order.runtime_config = rc
        flag_modified(order, "runtime_config")
        await _sync_conversation_after_order_routing(
            db,
            order,
            payload,
            effective_placements,
            [],
            require_network_ready,
        )
        await db.commit()
        return {
            "status": "ok",
            "order_id": order_id,
            "routing_status": order.routing_status,
            "deployment_required": False,
            "deployment_mode": deployment_mode,
            "instance_id": None,
            "network_bindings": [],
            "network_ready_required": require_network_ready,
            "network_ready": not require_network_ready,
        }

    # Create instance
    start_time = order.business_start_time or order.scheduled_start_time or business_now()
    end_time = order.business_end_time or order.scheduled_end_time or (start_time + timedelta(hours=1))
    instance_create = TaskInstanceCreate(
        template_id=catalog.template_id if catalog else order.template_id,
        name=order.name,
        deployment_mode=DeploymentMode.IMMEDIATE if payload.require_network_ready else DeploymentMode.SCHEDULED,
        scheduled_start_time=start_time,
        scheduled_end_time=end_time,
        auto_start=False,
        keep_after_stop=order.keep_after_stop,
        enabled_template_node_names=enabled_template_node_names,
        node_overrides=overrides,
    )
    instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)

    # Update TASK_INSTANCE_ID in each node's env now that we have the real instance id
    for node in instance.nodes:
        if node.env and node.env.get("TASK_INSTANCE_ID") == order.id:
            node.env = {**node.env, "TASK_INSTANCE_ID": instance.id}
            flag_modified(node, "env")

    network_bindings = await build_network_bindings(db, order, instance)
    require_network_ready = bool(payload.require_network_ready)
    mark_network_binding_ready(order, network_bindings, require_ready=require_network_ready)
    flag_modified(order, "runtime_config")
    order.materialized_instance_id = instance.id
    order.status = OrderStatus.MATERIALIZED
    order.error_message = None
    order.routing_status = (
        RoutingStatus.NETWORK_BINDING_READY.value
        if require_network_ready
        else RoutingStatus.COMPLETED.value
    )
    await _sync_conversation_after_order_routing(
        db,
        order,
        payload,
        effective_placements,
        network_bindings,
        require_network_ready,
    )

    await db.commit()
    return {
        "status": "ok",
        "order_id": order_id,
        "routing_status": order.routing_status,
        "instance_id": instance.id,
        "network_bindings": network_bindings,
        "network_ready_required": require_network_ready,
        "network_ready": not require_network_ready,
    }


class BatchBenchmarkRequest(BaseModel):
    task_type: str = "high_throughput_matmul"
    count: int = Field(default=10, ge=1, le=30)
    benchmark_run_id: Optional[str] = None
    data_profile: dict = Field(default_factory=dict)
    routing_strategy: Optional[str] = None
    source_name: Optional[str] = None
    destination_name: Optional[str] = None

    @model_validator(mode="after")
    def _validate_routing_strategy(self):
        if not self.routing_strategy:
            self.routing_strategy = (
                "low_latency_forwarding"
                if self.task_type == "metaverse_video_fusion"
                else "resource_guarantee"
            )
        self.routing_strategy = require_routing_policy(
            self.routing_strategy,
            field_name="routing_strategy",
        )
        return self


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
    business_start_time = business_now()
    business_end_time = business_start_time + timedelta(hours=1)
    run_id = payload.benchmark_run_id or f"{payload.task_type}-{business_start_time.strftime('%Y%m%d%H%M%S')}"
    runtime_settings = await get_runtime_settings(db)
    modality_priority_map = modality_priority_map_from_settings(runtime_settings)
    resource_options = routing_resource_options_from_settings(runtime_settings)
    endpoint_nodes = await _deployable_endpoint_nodes(db)
    endpoint_by_hostname = {node.hostname: node for node in endpoint_nodes}
    fixed_source = endpoint_by_hostname.get(payload.source_name or "") if payload.source_name else None
    fixed_sink = endpoint_by_hostname.get(payload.destination_name or "") if payload.destination_name else None
    if payload.source_name and not fixed_source:
        raise HTTPException(status_code=400, detail=f"source_name is not a deployable endpoint node: {payload.source_name}")
    if payload.destination_name and not fixed_sink:
        raise HTTPException(status_code=400, detail=f"destination_name is not a deployable endpoint node: {payload.destination_name}")
    for i in range(payload.count):
        auto_source_node, auto_sink_node = _pick_endpoint_pair(endpoint_nodes, i)
        source_node = fixed_source or auto_source_node
        sink_node = fixed_sink or auto_sink_node
        source_name = source_node.hostname
        destination_name = sink_node.hostname
        order_name = f"benchmark-{payload.task_type}-{run_id}-{i + 1}"
        runtime_config = {
            "benchmark": {
                "run_id": run_id,
                "created_at": business_start_time.isoformat(),
                "sample_count": payload.count,
                "profile": data_profile,
                "mode": "acceptance-run",
            },
            "business_task": {
                "task_type": payload.task_type,
                "modality": benchmark_config["modality"],
                "data_profile": data_profile,
                "business_objective": business_objective,
                "runtime_plan": {"routing_strategy": payload.routing_strategy},
                "routing_strategy": payload.routing_strategy,
            },
            "platform_deployment": {
                "deployable_roles": ["source", "compute", "sink"],
                "note": "business objective benchmark runs deploy endpoint containers on real topology nodes",
            },
        }
        order = TaskOrder(
            user_id=current_user.id,
            template_id=catalog.template_id,
            name=order_name,
            status=OrderStatus.PENDING,
            routing_status=RoutingStatus.PENDING.value,
            runtime_config=runtime_config,
            is_benchmark=True,
            source_name=source_name,
            destination_name=destination_name,
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
            source_name=source_name,
            destination_name=destination_name,
            business_start_time=business_start_time,
            business_end_time=business_end_time,
            data_profile=data_profile,
            modality_priority_map=modality_priority_map,
            routing_strategy=payload.routing_strategy,
            **resource_options,
        )
        effective_resources = _routing_dag_resources_by_role(order)
        if effective_resources:
            business_task = runtime_config["business_task"]
            business_task["resource_requirement"] = effective_resources
            order.runtime_config = runtime_config
            flag_modified(order, "runtime_config")
        order_ids.append(order.id)

    await db.commit()
    return {"created": len(order_ids), "order_ids": order_ids, "benchmark_run_id": run_id}


class BenchmarkRunScopedRequest(BaseModel):
    benchmark_run_id: Optional[str] = None
    task_type: Optional[str] = None


class ControlledBenchmarkStartRequest(BenchmarkRunScopedRequest):
    max_parallel: int = Field(default=8, ge=1, le=10)
    per_compute_slot_limit: int = Field(default=1, ge=1, le=4)
    cleanup_evaluated: bool = True
    retry_failed: bool = False
    wait_seconds: int = Field(default=0, ge=0, le=30)


class ManagedBenchmarkRunRequest(ControlledBenchmarkStartRequest):
    poll_interval_seconds: int = Field(default=5, ge=1, le=30)
    max_rounds: int = Field(default=720, ge=1, le=3000)


_MANAGED_BENCHMARK_TASKS: dict[str, asyncio.Task] = {}
_MANAGED_BENCHMARK_STATUS: dict[str, dict[str, Any]] = {}
_MANAGED_BENCHMARK_LOCK = asyncio.Lock()
_MANAGED_BENCHMARK_ACTIVE_PHASES = {"running", "waiting_resource", "cleaning", "recovering"}
_MANAGED_BENCHMARK_WATCHDOG_JOB_ID = "managed_benchmark_watchdog"


def _managed_benchmark_key(task_type: str | None, benchmark_run_id: str | None) -> str:
    return f"{task_type or '*'}::{benchmark_run_id or '*'}"


def _benchmark_status_payload(
    key: str,
    *,
    phase: str,
    message: str,
    payload: ManagedBenchmarkRunRequest,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    now = business_now().isoformat()
    previous = _MANAGED_BENCHMARK_STATUS.get(key, {})
    status = {
        **previous,
        "key": key,
        "phase": phase,
        "message": message,
        "benchmark_run_id": payload.benchmark_run_id,
        "task_type": payload.task_type,
        "max_parallel": payload.max_parallel,
        "per_compute_slot_limit": payload.per_compute_slot_limit,
        "poll_interval_seconds": payload.poll_interval_seconds,
        "updated_at": now,
        "error": error,
    }
    if not previous.get("started_at"):
        status["started_at"] = now
    if progress is not None:
        status["progress"] = progress
    _MANAGED_BENCHMARK_STATUS[key] = status
    return status


def _is_managed_benchmark_running(key: str) -> bool:
    task = _MANAGED_BENCHMARK_TASKS.get(key)
    return bool(task and not task.done())


async def _set_managed_benchmark_control(
    *,
    benchmark_run_id: str,
    task_type: str | None,
    phase: str,
    payload: ManagedBenchmarkRunRequest | None = None,
    user_id: str | None = None,
    error: str | None = None,
    session_maker=None,
    db: AsyncSession | None = None,
) -> int:
    """Persist enough run intent to rebuild the in-memory controller after restart."""
    now = business_now().isoformat()
    async def apply(session: AsyncSession) -> int:
        updated = 0
        rows = await session.execute(
            select(TaskOrder).where(
                TaskOrder.is_benchmark.is_(True),
                TaskOrder.deleted_at.is_(None),
            )
        )
        for order in rows.scalars().all():
            if _benchmark_run_id(order) != benchmark_run_id:
                continue
            if task_type and _benchmark_task_type(order) != task_type:
                continue
            config = dict(order.runtime_config or {})
            benchmark = dict(config.get("benchmark") or {})
            previous = dict(benchmark.get("managed_run") or {})
            control = {
                **previous,
                "phase": phase,
                "updated_at": now,
                "error": error,
            }
            if not control.get("started_at"):
                control["started_at"] = now
            if user_id:
                control["requested_by"] = user_id
            if payload is not None:
                control.update({
                    "max_parallel": payload.max_parallel,
                    "per_compute_slot_limit": payload.per_compute_slot_limit,
                    "cleanup_evaluated": payload.cleanup_evaluated,
                    "retry_failed": payload.retry_failed,
                    "poll_interval_seconds": payload.poll_interval_seconds,
                    "max_rounds": payload.max_rounds,
                })
            if phase not in _MANAGED_BENCHMARK_ACTIVE_PHASES:
                control["finished_at"] = now
            else:
                control.pop("finished_at", None)
            benchmark["managed_run"] = control
            config["benchmark"] = benchmark
            order.runtime_config = config
            flag_modified(order, "runtime_config")
            updated += 1
        await session.commit()
        return updated

    if db is not None:
        return await apply(db)
    session_maker = session_maker or async_session_maker
    async with session_maker() as session:
        return await apply(session)


async def _set_managed_benchmark_control_safely(**kwargs) -> None:
    try:
        await _set_managed_benchmark_control(**kwargs)
    except Exception:
        logger.exception(
            "Failed to persist managed benchmark state run=%s phase=%s",
            kwargs.get("benchmark_run_id"),
            kwargs.get("phase"),
        )


def _schedule_managed_benchmark_task(
    key: str,
    payload: ManagedBenchmarkRunRequest,
    user_id: str,
) -> asyncio.Task:
    task = asyncio.create_task(_run_managed_benchmark_loop(key, payload, user_id))
    _MANAGED_BENCHMARK_TASKS[key] = task
    task.add_done_callback(
        lambda done_task, task_key=key: (
            _MANAGED_BENCHMARK_TASKS.pop(task_key, None)
            if _MANAGED_BENCHMARK_TASKS.get(task_key) is done_task
            else None
        )
    )
    return task


def _request_managed_benchmark_stop(benchmark_run_id: str | None, task_type: str | None) -> None:
    if not benchmark_run_id:
        return
    for key, status in _MANAGED_BENCHMARK_STATUS.items():
        if status.get("benchmark_run_id") != benchmark_run_id:
            continue
        if task_type and status.get("task_type") != task_type:
            continue
        status["stop_requested"] = True
        status["phase"] = "stopping"
        status["message"] = "已收到停止请求，正在停止本轮测评并释放运行实例。"
        status["updated_at"] = business_now().isoformat()


async def _wait_for_managed_benchmark_tasks(
    benchmark_run_id: str | None,
    task_type: str | None,
    *,
    timeout_seconds: float = 60,
) -> None:
    if not benchmark_run_id:
        return
    tasks = [
        task
        for key, task in _MANAGED_BENCHMARK_TASKS.items()
        if not task.done()
        and (status := _MANAGED_BENCHMARK_STATUS.get(key))
        and status.get("benchmark_run_id") == benchmark_run_id
        and (not task_type or status.get("task_type") == task_type)
    ]
    if not tasks:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=409,
            detail="后台测评仍在完成当前操作，请稍后重试停止本轮测评。",
        ) from exc


async def _wait_for_background_benchmark_starts(
    instance_ids: list[str],
    *,
    timeout_seconds: float = 60,
) -> None:
    tasks = [
        task
        for instance_id in instance_ids
        if (task := _BACKGROUND_BENCHMARK_START_TASKS.get(instance_id)) and not task.done()
    ]
    if not tasks:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=409,
            detail="部分实例仍在启动，请稍后重试停止本轮测评。",
        ) from exc


async def _run_managed_benchmark_loop(
    key: str,
    payload: ManagedBenchmarkRunRequest,
    user_id: str,
) -> None:
    payload = payload.model_copy(update={"wait_seconds": 0})
    try:
        idle_rounds = 0
        consecutive_errors = 0
        for round_index in range(1, payload.max_rounds + 1):
            status = _MANAGED_BENCHMARK_STATUS.get(key, {})
            if status.get("stop_requested"):
                _benchmark_status_payload(
                    key,
                    phase="stopped",
                    message="当前测评轮次已停止。",
                    payload=payload,
                    progress=status.get("progress"),
                )
                await _set_managed_benchmark_control_safely(
                    benchmark_run_id=payload.benchmark_run_id,
                    task_type=payload.task_type,
                    phase="stopped",
                    payload=payload,
                    user_id=user_id,
                )
                return

            try:
                async with async_session_maker() as session:
                    user = await session.get(User, user_id)
                    if not user:
                        raise RuntimeError("当前登录用户不存在，请重新登录后再运行测评。")
                    progress = await _advance_controlled_benchmark_run(session, payload, user)
                    await session.commit()
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise
                _benchmark_status_payload(
                    key,
                    phase="waiting_resource",
                    message=f"后台推进暂时异常，正在自动重试（{consecutive_errors}/3）。",
                    payload=payload,
                    progress=_MANAGED_BENCHMARK_STATUS.get(key, {}).get("progress"),
                    error=str(exc),
                )
                await asyncio.sleep(payload.poll_interval_seconds)
                continue

            total = int(progress.get("total") or 0)
            evaluated = int(progress.get("evaluated") or 0)
            active = int(progress.get("active") or 0)
            waiting_route = int(progress.get("waiting_route") or 0)
            pending = int(progress.get("pending_to_start") or 0)
            started = int(progress.get("started") or 0)
            cleaned = int(progress.get("cleaned") or 0)
            cleanup_pending = int(progress.get("cleanup_pending") or 0)
            waiting = len(progress.get("waiting_resource") or {})
            failed = len(progress.get("failed") or {})

            progress["round"] = round_index
            if total > 0 and evaluated >= total and not cleanup_pending:
                _benchmark_status_payload(
                    key,
                    phase="completed",
                    message=f"本轮 {evaluated}/{total} 个测评任务已完成评估。",
                    payload=payload,
                    progress=progress,
                )
                await _set_managed_benchmark_control_safely(
                    benchmark_run_id=payload.benchmark_run_id,
                    task_type=payload.task_type,
                    phase="completed",
                    payload=payload,
                    user_id=user_id,
                )
                return

            if total > 0 and evaluated >= total and cleanup_pending:
                idle_rounds += 1
                phase = "cleaning"
                message = (
                    f"本轮 {evaluated}/{total} 个任务已完成评估，"
                    f"正在重试清理剩余 {cleanup_pending} 个运行实例。"
                )
            elif not total:
                idle_rounds += 1
                phase = "waiting"
                message = "当前轮次还没有可运行的测评工单，请先创建并完成节点分配。"
            elif started or active:
                idle_rounds = 0
                phase = "running"
                message = (
                    f"测评运行中：已评估 {evaluated}/{total}，"
                    f"本轮启动 {started} 个，运行中 {active} 个，已释放实例 {cleaned} 个。"
                )
            elif pending or waiting or waiting_route:
                idle_rounds += 1
                phase = "waiting_resource"
                message = (
                    f"等待资源释放后继续推进：已评估 {evaluated}/{total}，"
                    f"待路由 {waiting_route} 个，待启动 {pending} 个，资源等待 {waiting} 个。"
                )
            else:
                idle_rounds += 1
                phase = "blocked"
                message = (
                    f"当前轮次暂无法继续推进：已评估 {evaluated}/{total}，"
                    f"失败/异常 {failed} 个。请查看工单后重试或停止本轮测评。"
                )

            _benchmark_status_payload(
                key,
                phase=phase,
                message=message,
                payload=payload,
                progress=progress,
            )
            if phase == "blocked" and idle_rounds >= 3:
                await _set_managed_benchmark_control_safely(
                    benchmark_run_id=payload.benchmark_run_id,
                    task_type=payload.task_type,
                    phase="blocked",
                    payload=payload,
                    user_id=user_id,
                )
                return
            await asyncio.sleep(payload.poll_interval_seconds if idle_rounds else 2)

        status = _MANAGED_BENCHMARK_STATUS.get(key, {})
        _benchmark_status_payload(
            key,
            phase="blocked",
            message="后台测评推进已达到最大轮询次数，请刷新后查看工单状态或重新运行。",
            payload=payload,
            progress=status.get("progress"),
        )
        await _set_managed_benchmark_control_safely(
            benchmark_run_id=payload.benchmark_run_id,
            task_type=payload.task_type,
            phase="blocked",
            payload=payload,
            user_id=user_id,
        )
    except asyncio.CancelledError:
        status = _MANAGED_BENCHMARK_STATUS.get(key, {})
        explicitly_stopped = bool(status.get("stop_requested"))
        persisted_phase = "stopped" if explicitly_stopped else "recovering"
        _benchmark_status_payload(
            key,
            phase=persisted_phase,
            message=(
                "当前测评轮次已停止。"
                if explicitly_stopped
                else "后台进程中断，重启后将自动恢复当前测评轮次。"
            ),
            payload=payload,
            progress=status.get("progress"),
        )
        await _set_managed_benchmark_control_safely(
            benchmark_run_id=payload.benchmark_run_id,
            task_type=payload.task_type,
            phase=persisted_phase,
            payload=payload,
            user_id=user_id,
        )
        raise
    except Exception as exc:
        status = _MANAGED_BENCHMARK_STATUS.get(key, {})
        _benchmark_status_payload(
            key,
            phase="failed",
            message="后台测评推进遇到异常，请刷新后重试或停止本轮测评。",
            payload=payload,
            progress=status.get("progress"),
            error=str(exc),
        )
        await _set_managed_benchmark_control_safely(
            benchmark_run_id=payload.benchmark_run_id,
            task_type=payload.task_type,
            phase="failed",
            payload=payload,
            user_id=user_id,
            error=str(exc),
        )


async def restore_managed_benchmark_runs(session_maker=None) -> int:
    """Recreate controllers whose durable run marker survived a process restart."""
    session_maker = session_maker or async_session_maker
    candidates: dict[tuple[str, str], tuple[TaskOrder, dict[str, Any]]] = {}
    async with session_maker() as db:
        rows = await db.execute(
            select(TaskOrder).where(
                TaskOrder.is_benchmark.is_(True),
                TaskOrder.deleted_at.is_(None),
            )
        )
        for order in rows.scalars().all():
            run_id = _benchmark_run_id(order)
            task_type = _benchmark_task_type(order)
            benchmark = (order.runtime_config or {}).get("benchmark") or {}
            control = benchmark.get("managed_run") or {}
            if not run_id or not task_type or control.get("phase") not in _MANAGED_BENCHMARK_ACTIVE_PHASES:
                continue
            key = (task_type, run_id)
            previous = candidates.get(key)
            if previous is None or str(control.get("updated_at") or "") > str(previous[1].get("updated_at") or ""):
                candidates[key] = (order, control)

    restored = 0
    for (task_type, run_id), (order, control) in candidates.items():
        user_id = str(control.get("requested_by") or order.user_id or "")
        if not user_id:
            await _set_managed_benchmark_control_safely(
                benchmark_run_id=run_id,
                task_type=task_type,
                phase="failed",
                error="managed benchmark owner is missing",
                session_maker=session_maker,
            )
            continue
        try:
            payload = ManagedBenchmarkRunRequest(
                benchmark_run_id=run_id,
                task_type=task_type,
                max_parallel=control.get("max_parallel", 8),
                per_compute_slot_limit=control.get("per_compute_slot_limit", 1),
                cleanup_evaluated=control.get("cleanup_evaluated", True),
                retry_failed=control.get("retry_failed", False),
                poll_interval_seconds=control.get("poll_interval_seconds", 5),
                max_rounds=control.get("max_rounds", 720),
            )
        except Exception as exc:
            await _set_managed_benchmark_control_safely(
                benchmark_run_id=run_id,
                task_type=task_type,
                phase="failed",
                user_id=user_id,
                error=f"invalid persisted managed benchmark config: {exc}",
                session_maker=session_maker,
            )
            continue

        task_key = _managed_benchmark_key(task_type, run_id)
        async with _MANAGED_BENCHMARK_LOCK:
            if _is_managed_benchmark_running(task_key):
                continue
            _benchmark_status_payload(
                task_key,
                phase="recovering",
                message="检测到未完成测评轮次，后台已自动恢复推进。",
                payload=payload,
                progress=None,
            )
            _schedule_managed_benchmark_task(task_key, payload, user_id)
            restored += 1
    if restored:
        logger.info("Restored %d managed benchmark run(s)", restored)
    return restored


async def shutdown_managed_benchmark_tasks() -> None:
    """Quiesce in-memory benchmark work so durable controllers can recover it."""
    tasks = [
        task
        for task in [
            *_BACKGROUND_BENCHMARK_START_TASKS.values(),
            *_MANAGED_BENCHMARK_TASKS.values(),
        ]
        if not task.done()
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def start_managed_benchmark_watchdog(interval_seconds: int = 15) -> None:
    """Periodically restore a controller that disappeared without a terminal state."""
    from services.scheduler import scheduler

    if scheduler.get_job(_MANAGED_BENCHMARK_WATCHDOG_JOB_ID):
        scheduler.remove_job(_MANAGED_BENCHMARK_WATCHDOG_JOB_ID)
    scheduler.add_job(
        restore_managed_benchmark_runs,
        trigger="interval",
        seconds=interval_seconds,
        id=_MANAGED_BENCHMARK_WATCHDOG_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


@router.post("/benchmark/managed-run")
async def start_managed_benchmark_run(
    payload: ManagedBenchmarkRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """后台托管推进本轮测评，避免浏览器切页或请求超时导致轮次卡住。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    payload = payload or ManagedBenchmarkRunRequest()
    if not payload.benchmark_run_id:
        raise HTTPException(status_code=400, detail="benchmark_run_id is required")

    key = _managed_benchmark_key(payload.task_type, payload.benchmark_run_id)
    async with _MANAGED_BENCHMARK_LOCK:
        if _is_managed_benchmark_running(key):
            status = _MANAGED_BENCHMARK_STATUS.get(key)
            if status:
                return {**status, "already_running": True}
        status = _benchmark_status_payload(
            key,
            phase="running",
            message="已启动后台测评推进，页面会自动刷新进度。",
            payload=payload,
            progress=None,
        )
        status.pop("stop_requested", None)
        await _set_managed_benchmark_control(
            benchmark_run_id=payload.benchmark_run_id,
            task_type=payload.task_type,
            phase="running",
            payload=payload,
            user_id=current_user.id,
            db=db,
        )
        _schedule_managed_benchmark_task(key, payload, current_user.id)
    return {**status, "already_running": False}


@router.get("/benchmark/managed-run/status")
async def managed_benchmark_run_status(
    benchmark_run_id: str,
    task_type: str | None = None,
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    key = _managed_benchmark_key(task_type, benchmark_run_id)
    status = _MANAGED_BENCHMARK_STATUS.get(key)
    if not status:
        return {
            "key": key,
            "benchmark_run_id": benchmark_run_id,
            "task_type": task_type,
            "phase": "idle",
            "message": "当前轮次没有后台测评任务。",
            "running": False,
            "progress": None,
        }
    return {**status, "running": _is_managed_benchmark_running(key)}


@router.post("/benchmark/stop", response_model=BatchOperationResponse)
async def stop_benchmark_run(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止当前测评轮次的未完成运行，释放容器，保留已完成证据。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    _request_managed_benchmark_stop(request.benchmark_run_id, request.task_type)
    await _wait_for_managed_benchmark_tasks(request.benchmark_run_id, request.task_type)
    orders, failed = await _resolve_batch_orders(db, request, current_user)
    if orders:
        # Serialize cancellation with external /result callbacks. The callback
        # also locks the order row, so it either finishes materialization first
        # (and is cleaned below) or observes CANCELLED and returns 409.
        locked_rows = await db.execute(
            select(TaskOrder).where(TaskOrder.id.in_([order.id for order in orders])).with_for_update()
        )
        locked_by_id = {order.id: order for order in locked_rows.scalars().all()}
        orders = [locked_by_id[order.id] for order in orders if order.id in locked_by_id]
    order_ids = [order.id for order in orders]
    task_scheduler = TaskScheduler()
    succeeded: list[str] = []
    instance_ids = [order.materialized_instance_id for order in orders if order.materialized_instance_id]
    await _wait_for_background_benchmark_starts(instance_ids)
    evaluated_instance_ids: set[str] = set()
    if instance_ids:
        evaluation_rows = await db.execute(
            select(BusinessObjectiveEvaluation.instance_id).where(
                BusinessObjectiveEvaluation.instance_id.in_(instance_ids)
            )
        )
        evaluated_instance_ids = set(evaluation_rows.scalars().all())

    # Publish cancellation before the slower remote container cleanup. This
    # prevents the external router from claiming more orders during shutdown.
    for order in orders:
        if order.status == OrderStatus.COMPLETED or order.materialized_instance_id:
            continue
        order.status = OrderStatus.CANCELLED
        order.routing_status = RoutingStatus.CANCELLED.value
        if order.routing_request_id:
            routing_row = await db.execute(
                select(RoutingRequest).where(RoutingRequest.id == order.routing_request_id)
            )
            routing = routing_row.scalar_one_or_none()
            if routing:
                routing.status = RoutingRequestStatus.CANCELLED
    await db.commit()

    for order_id in order_ids:
        try:
            order = await db.get(TaskOrder, order_id)
            if not order:
                failed[order_id] = "Order not found during benchmark stop"
                continue
            # 已评估/已完成的工单保留作为验收证据，不反向改状态。
            if order.status == OrderStatus.COMPLETED:
                succeeded.append(order.id)
                continue

            if not order.materialized_instance_id:
                order.status = OrderStatus.CANCELLED
                order.routing_status = RoutingStatus.CANCELLED.value
                if order.routing_request_id:
                    routing_row = await db.execute(
                        select(RoutingRequest).where(RoutingRequest.id == order.routing_request_id)
                    )
                    routing = routing_row.scalar_one_or_none()
                    if routing:
                        routing.status = RoutingRequestStatus.CANCELLED
                await emit_release_events_for_order(
                    db,
                    order,
                    reason="stop_benchmark_run",
                    metadata={"benchmark_run_id": request.benchmark_run_id, "cancel_unmaterialized": True},
                )
                succeeded.append(order.id)
                await db.commit()
                continue

            result = await db.execute(
                select(TaskInstance)
                .options(selectinload(TaskInstance.nodes))
                .where(TaskInstance.id == order.materialized_instance_id)
            )
            instance = result.scalar_one_or_none()
            if not instance:
                if order.status == OrderStatus.MATERIALIZED:
                    if order.materialized_instance_id in evaluated_instance_ids:
                        order.status = OrderStatus.COMPLETED
                    else:
                        order.status = OrderStatus.CANCELLED
                        order.error_message = order.error_message or "测评已停止，关联实例不存在"
                succeeded.append(order.id)
                await db.commit()
                continue

            await task_scheduler.cancel_all_schedules(instance.id)
            if instance.status not in (TaskStatus.STOPPED, TaskStatus.PENDING):
                executor = DAGExecutor(db)
                success, error = await executor.execute_dag_stop(instance.id)
                if not success:
                    raise RuntimeError(error or "停止实例失败")

            cleanup_warnings = await cleanup_instance_runtime(db, instance)
            if cleanup_warnings:
                raise RuntimeError(f"容器清理失败：{'；'.join(cleanup_warnings)}")

            await emit_release_events_for_order(
                db,
                order,
                reason="stop_benchmark_run",
                metadata={"instance_id": instance.id, "benchmark_run_id": request.benchmark_run_id},
            )
            await purge_instance_artifacts_preserve_evidence(db, instance.id)
            if order.status == OrderStatus.MATERIALIZED:
                if instance.id in evaluated_instance_ids:
                    order.status = OrderStatus.COMPLETED
                else:
                    order.status = OrderStatus.CANCELLED
                    order.error_message = order.error_message or "测评已手动停止"
            succeeded.append(order.id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            failed[order_id] = str(exc)

    if request.benchmark_run_id:
        await _set_managed_benchmark_control_safely(
            benchmark_run_id=request.benchmark_run_id,
            task_type=request.task_type,
            phase="stopped",
            user_id=current_user.id,
            error="; ".join(failed.values()) if failed else None,
            db=db,
        )
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/batch-auto-route")
async def batch_auto_route(
    payload: BenchmarkRunScopedRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-route all pending benchmark orders."""
    await _ensure_internal_benchmark_routing_enabled(db)
    runtime_settings = await get_runtime_settings(db)
    compute_allocation_mode = benchmark_compute_allocation_mode_from_settings(runtime_settings)
    query = select(TaskOrder).where(
        TaskOrder.status == OrderStatus.PENDING.value,
        TaskOrder.routing_status == RoutingStatus.PENDING.value,
        TaskOrder.is_benchmark == True,
    )
    rows = await db.execute(_apply_order_visibility(query, current_user))
    orders = rows.scalars().all()
    run_id = payload.benchmark_run_id if payload else None
    if run_id:
        orders = [order for order in orders if _benchmark_run_id(order) == run_id]
    task_type = payload.task_type if payload else None
    if task_type:
        _benchmark_config(task_type)
        orders = [order for order in orders if _benchmark_task_type(order) == task_type]

    pools_by_task_type: dict[str, dict[str, Any]] = {}
    skipped_unhealthy_nodes: list[dict[str, str]] = []
    required_task_types = {t for t in (_benchmark_task_type(order) for order in orders) if t}
    if task_type:
        required_task_types.add(task_type)
    for required_type in required_task_types:
        pool = await _benchmark_routing_pool(db, required_type)
        pools_by_task_type[required_type] = pool
        skipped_unhealthy_nodes.extend(pool.get("skipped_unhealthy_nodes", []))

    routed = 0
    failed = []
    for order in orders:
        try:
            order_task_type = _benchmark_task_type(order)
            if not order_task_type:
                raise RuntimeError("Benchmark order missing task_type")
            routing_pool = pools_by_task_type.get(order_task_type)
            if not routing_pool or not routing_pool["compute"]:
                raise RuntimeError(f"No baseline compute nodes available for {order_task_type}")
            picked, compute_gpu_id = _pick_benchmark_nodes(
                routing_pool,
                order,
                compute_allocation_mode=compute_allocation_mode,
            )
            await _do_auto_route(
                db,
                order,
                picked,
                compute_gpu_id,
                compute_allocation_mode=compute_allocation_mode,
            )
            routed += 1
        except Exception as exc:
            failed.append({"order_id": order.id, "error": str(exc)})

    await db.commit()
    return {
        "routed": routed,
        "failed": failed,
        "skipped_unhealthy_nodes": skipped_unhealthy_nodes,
    }


@router.post("/start-all-routed")
async def start_all_routed_benchmark_orders(
    payload: BenchmarkRunScopedRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start all materialized benchmark orders for the current user."""
    query = select(TaskOrder).where(
        TaskOrder.status == OrderStatus.MATERIALIZED.value,
        TaskOrder.routing_status.in_(
            [
                RoutingStatus.COMPLETED.value,
                RoutingStatus.NETWORK_BINDING_READY.value,
            ]
        ),
        TaskOrder.is_benchmark == True,
        TaskOrder.materialized_instance_id.is_not(None),
    )
    rows = await db.execute(_apply_order_visibility(query, current_user))
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

        startable_statuses = {TaskStatus.PENDING, TaskStatus.SCHEDULED, TaskStatus.STOPPED}
        if payload.retry_failed:
            startable_statuses.add(TaskStatus.FAILED)
        if instance.status not in startable_statuses:
            status_value = instance.status.value if hasattr(instance.status, "value") else str(instance.status)
            failed[order.id] = f"Cannot start instance in status: {status_value}"
            continue

        waiting_message = await _network_ready_wait_message(db, instance_id)
        if waiting_message:
            failed[order.id] = waiting_message
            continue

        try:
            preflight = await _preflight_instance_plan(
                db,
                await _build_preflight_plan_from_instance(instance),
                exclude_instance_id=instance_id,
                instance_id_for_events=instance_id,
            )
            if not preflight.ok:
                messages = "; ".join(issue.message for issue in preflight.conflicts)
                failed[order.id] = f"启动前预检查失败: {messages}"
                continue
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
    *,
    include_completed: bool = False,
) -> list[TaskOrder]:
    query = select(TaskOrder).where(TaskOrder.is_benchmark == True)
    if include_completed:
        query = query.where(
            TaskOrder.status.in_([
                OrderStatus.PENDING.value,
                OrderStatus.MATERIALIZED.value,
                OrderStatus.COMPLETED.value,
            ]),
            TaskOrder.routing_status.in_([
                RoutingStatus.PENDING.value,
                RoutingStatus.COMPUTING.value,
                RoutingStatus.NETWORK_BINDING_READY.value,
                RoutingStatus.COMPLETED.value,
            ]),
        )
    else:
        query = query.where(
            TaskOrder.status == OrderStatus.MATERIALIZED.value,
            TaskOrder.routing_status.in_([
                RoutingStatus.COMPLETED.value,
                RoutingStatus.NETWORK_BINDING_READY.value,
            ]),
            TaskOrder.materialized_instance_id.is_not(None),
        )
    rows = await db.execute(_apply_order_visibility(query, current_user))
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
        stopped, stop_error = await executor.execute_dag_stop(instance.id)
        if not stopped:
            raise RuntimeError(stop_error or "failed to stop benchmark instance")

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

    cleanup_warnings = await cleanup_instance_runtime(db, refreshed)
    if cleanup_warnings:
        raise RuntimeError(f"容器清理失败：{'；'.join(cleanup_warnings)}")
    await emit_release_events_for_order(
        db,
        order,
        reason="benchmark_cleanup",
        metadata={"instance_id": instance.id, "preserve_order": True},
    )
    await purge_instance_artifacts_preserve_evidence(db, refreshed.id)
    await mark_orders_completed_for_instance(db, refreshed.id)
    if order.status == OrderStatus.MATERIALIZED:
        order.status = OrderStatus.COMPLETED
    return True


async def _cleanup_evaluated_benchmark_orders(
    db: AsyncSession,
    orders: list[TaskOrder],
    instance_map: dict[str, TaskInstance],
    eval_map: dict[str, BusinessObjectiveEvaluation],
) -> tuple[list[str], dict[str, str]]:
    """Clean evaluated runtimes, including results reported during this advance."""
    cleaned: list[str] = []
    failed: dict[str, str] = {}
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
    return cleaned, failed


async def _reevaluate_orders_from_latest_metrics(
    db: AsyncSession,
    orders: list[TaskOrder],
    *,
    missing_metric_is_failure: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """Rebuild missing/stale business evaluations from reported task_metrics."""
    from api.business_tasks import evaluate_and_store_business_metric

    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for order in orders:
        instance_id = order.materialized_instance_id
        if not instance_id:
            failed[order.id] = "Order has no materialized instance"
            continue
        business_task = (order.runtime_config or {}).get("business_task") or {}
        objective = business_task.get("business_objective") or {}
        metric_key = objective.get("metric_key")
        if not metric_key:
            failed[order.id] = "Order missing business objective metric_key"
            continue

        metric = (
            await db.execute(
                select(TaskMetric)
                .where(
                    TaskMetric.instance_id == instance_id,
                    TaskMetric.metric_key == metric_key,
                )
                .order_by(TaskMetric.reported_at.desc(), TaskMetric.id.desc())
            )
        ).scalars().first()
        if not metric:
            if missing_metric_is_failure:
                failed[order.id] = f"No reported metric found for {metric_key}"
            continue

        row = await evaluate_and_store_business_metric(
            db,
            instance_id=instance_id,
            metric_key=metric.metric_key,
            metric_value=metric.metric_value,
            tags=metric.tags,
        )
        if row is None:
            failed[order.id] = "Metric exists but evaluation could not be built; check baseline/objective"
            continue
        succeeded.append(order.id)
    return succeeded, failed


async def _advance_controlled_benchmark_run(
    db: AsyncSession,
    payload: ControlledBenchmarkStartRequest,
    current_user: User,
) -> dict[str, Any]:
    run_orders = await _controlled_benchmark_orders(db, payload, current_user, include_completed=True)
    orders = [order for order in run_orders if order.status == OrderStatus.MATERIALIZED]
    startable_instance_ids = {
        order.materialized_instance_id
        for order in orders
        if order.materialized_instance_id
    }
    recalc_succeeded, recalc_failed = await _reevaluate_orders_from_latest_metrics(
        db,
        [order for order in run_orders if order.materialized_instance_id],
        missing_metric_is_failure=False,
    )
    if recalc_succeeded:
        await db.flush()
    run_instance_map = await _instances_for_orders(db, run_orders)
    instance_map = {
        instance_id: instance
        for instance_id, instance in run_instance_map.items()
        if instance_id in startable_instance_ids
    }
    run_eval_map = await _latest_evaluations_by_instance(
        db,
        [order.materialized_instance_id for order in run_orders if order.materialized_instance_id],
    )
    eval_map = {
        instance_id: evaluation
        for instance_id, evaluation in run_eval_map.items()
        if instance_id in startable_instance_ids
    }

    # A process restart can leave the durable claim at STARTING after its
    # in-memory asyncio task disappears. Node Agent startup is idempotent, so
    # re-dispatch only orphaned, unevaluated benchmark starts.
    recovered_start_ids: list[str] = []
    for order in orders:
        instance_id = order.materialized_instance_id
        instance = instance_map.get(instance_id or "")
        if (
            instance_id
            and instance_id not in eval_map
            and instance
            and instance.status == TaskStatus.STARTING
            and _schedule_background_benchmark_start(instance_id)
        ):
            recovered_start_ids.append(instance_id)

    cleaned: list[str] = []
    failed: dict[str, str] = dict(recalc_failed)
    if payload.cleanup_evaluated:
        initial_cleaned, initial_cleanup_failed = await _cleanup_evaluated_benchmark_orders(
            db,
            orders,
            instance_map,
            eval_map,
        )
        cleaned.extend(initial_cleaned)
        failed.update(initial_cleanup_failed)
        if cleaned:
            await db.commit()
            run_instance_map = await _instances_for_orders(db, run_orders)
            instance_map = {
                instance_id: instance
                for instance_id, instance in run_instance_map.items()
                if instance_id in startable_instance_ids
            }

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
    background_start_ids: list[str] = []
    skipped_busy: list[str] = []
    waiting_resource: dict[str, str] = {}
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
        startable_statuses = {TaskStatus.PENDING, TaskStatus.SCHEDULED, TaskStatus.STOPPED}
        if payload.retry_failed:
            startable_statuses.add(TaskStatus.FAILED)
        if instance.status not in startable_statuses:
            status_value = instance.status.value if hasattr(instance.status, "value") else str(instance.status)
            failed[order.id] = f"Cannot start instance in status: {status_value}"
            continue

        waiting_message = await _network_ready_wait_message(db, instance_id)
        if waiting_message:
            waiting_resource[order.id] = waiting_message
            continue

        slot = _benchmark_compute_slot(order)
        if active_by_slot[slot] >= payload.per_compute_slot_limit:
            skipped_busy.append(order.id)
            waiting_resource[order.id] = "当前计算节点/GPU 槽位正在执行其他测评，等待下一轮自动推进。"
            continue

        try:
            preflight = await _preflight_instance_plan(
                db,
                await _build_preflight_plan_from_instance(instance),
                exclude_instance_id=instance_id,
                instance_id_for_events=instance_id,
            )
            if not preflight.ok:
                messages = "; ".join(issue.message for issue in preflight.conflicts)
                waiting_resource[order.id] = f"启动前资源暂不可用，等待下一轮自动推进：{messages}"
                continue
            instance.status = TaskStatus.STARTING
            instance.error_message = None
            await db.flush()
            started.append(instance_id)
            background_start_ids.append(instance_id)
            active_by_slot[slot] += 1
            active_orders += 1
        except Exception as exc:
            failed[order.id] = str(exc)

    if background_start_ids:
        # Commit the claimed STARTING state before handing work to an
        # independent session. Otherwise the request session could overwrite a
        # fast background completion back to STARTING.
        await db.commit()
        for instance_id in background_start_ids:
            _schedule_background_benchmark_start(instance_id)

    if payload.wait_seconds:
        await asyncio.sleep(payload.wait_seconds)

    run_instance_map = await _instances_for_orders(db, run_orders)
    eval_map = await _latest_evaluations_by_instance(
        db,
        [order.materialized_instance_id for order in run_orders if order.materialized_instance_id],
    )
    if payload.cleanup_evaluated:
        final_cleaned, final_cleanup_failed = await _cleanup_evaluated_benchmark_orders(
            db,
            orders,
            run_instance_map,
            eval_map,
        )
        cleaned.extend(final_cleaned)
        failed.update(final_cleanup_failed)
        if final_cleaned:
            await db.commit()
            run_instance_map = await _instances_for_orders(db, run_orders)
    success_count = sum(1 for evaluation in eval_map.values() if evaluation.business_success)
    evaluated_count = len(eval_map)
    cleanup_pending = (
        sum(1 for instance_id in eval_map if instance_id in run_instance_map)
        if payload.cleanup_evaluated
        else 0
    )
    waiting_route = sum(
        1
        for order in run_orders
        if not order.materialized_instance_id
        and order.routing_status in {
            RoutingStatus.PENDING.value,
            RoutingStatus.COMPUTING.value,
        }
    )
    pending_to_start = 0
    active_orders = 0
    for order in run_orders:
        instance_id = order.materialized_instance_id
        if not instance_id or instance_id in eval_map:
            continue
        instance = run_instance_map.get(instance_id)
        if instance and instance.status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            active_orders += 1
        elif order.status == OrderStatus.MATERIALIZED:
            pending_to_start += 1

    return {
        "total": len(run_orders),
        "evaluated": evaluated_count,
        "success": success_count,
        "active": active_orders,
        "waiting_route": waiting_route,
        "pending_to_start": pending_to_start,
        "started": len(started),
        "recovered_starts": recovered_start_ids,
        "skipped_busy": skipped_busy,
        "waiting_resource": waiting_resource,
        "cleaned": len(cleaned),
        "cleanup_pending": cleanup_pending,
        "failed": failed,
        "instance_ids": started,
        "success_rate": success_count / evaluated_count if evaluated_count else None,
    }


@router.post("/benchmark/recalculate", response_model=BatchOperationResponse)
async def recalculate_benchmark_evaluations(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按当前验收轮次重算业务目标评估，不重新启动容器。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    orders, failed = await _resolve_batch_orders(db, request)
    succeeded, recalc_failed = await _reevaluate_orders_from_latest_metrics(db, orders)
    failed.update(recalc_failed)
    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


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
    return await _advance_controlled_benchmark_run(db, payload, current_user)


async def _do_auto_route(
    db: AsyncSession,
    order: TaskOrder,
    picked: dict,
    compute_gpu_id: str | None,
    *,
    compute_allocation_mode: str = "gpu_slot",
):
    """Shared logic: resolve picked nodes, build overrides, create instance, update order."""
    catalog = await _catalog_for_order(db, order)
    role_node_names = {
        "source": catalog.source_node_name if catalog else None,
        "compute": catalog.compute_node_name if catalog else None,
        "sink": catalog.sink_node_name if catalog else None,
    }

    overrides: list[TaskInstanceNodeOverride] = []
    resource_requirement = _routing_dag_resources_by_role(order)
    for role, node in picked.items():
        template_node_name = role_node_names.get(role) or role
        bt = (order.runtime_config or {}).get("business_task", {})
        env = build_business_env(
            order=order,
            business_task=bt,
            task_role=role,
            task_instance_id=order.id,
            resource_requirement=resource_requirement,
        )
        gpu_id = compute_gpu_id if role == "compute" else None
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
            "task_node_id": role,
            "topology_node_id": node.hostname,
            **({"gpu_device": compute_gpu_id} if role == "compute" and compute_gpu_id is not None else {}),
        }
        for role, node in picked.items()
    ]
    rc = order.runtime_config or {}
    business_task = rc.get("business_task") or {}
    if isinstance(business_task, dict) and resource_requirement:
        business_task["resource_requirement"] = resource_requirement
        rc["business_task"] = business_task
    runtime_plan = business_task.get("runtime_plan") or {}
    task_strategy = (
        normalize_routing_policy(runtime_plan.get("routing_strategy"))
        or normalize_routing_policy(business_task.get("routing_strategy"))
        or "resource_guarantee"
    )
    rc["routing_result"] = {
        "strategy": task_strategy,
        "placements": placements,
        "metadata": {
            "mode": "benchmark_auto_route",
            "route_source": "platform_managed",
            "route_source_label": "系统自动分配",
            # Preserve the policy selected for this order even if the global
            # setting changes before the managed benchmark finishes.
            "compute_allocation_mode": compute_allocation_mode,
            "description": "平台按当前可用终端节点和计算节点完成本轮测评分配。",
        },
    }
    order.runtime_config = rc
    flag_modified(order, "runtime_config")
    order.routing_status = RoutingStatus.COMPLETED.value
    order.error_message = None

    start_time = order.business_start_time or order.scheduled_start_time or business_now()
    end_time = order.business_end_time or order.scheduled_end_time or (start_time + timedelta(hours=1))
    instance_create = TaskInstanceCreate(
        template_id=catalog.template_id if catalog else order.template_id,
        name=order.name,
        # Batch benchmark orders are advanced by /start-controlled-routed so
        # the selected compute/GPU slot is never over-subscribed accidentally.
        deployment_mode=DeploymentMode.IMMEDIATE if order.is_benchmark else DeploymentMode.SCHEDULED,
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

    network_bindings = await build_network_bindings(db, order, instance)
    mark_network_binding_ready(order, network_bindings, require_ready=False)
    if not order.is_benchmark:
        ts = TaskScheduler()
        if order.business_start_time:
            await ts.schedule_task_start(instance.id, order.business_start_time)
        if order.business_end_time:
            await ts.schedule_task_end(instance.id, order.business_end_time)

    flag_modified(order, "runtime_config")
    order.materialized_instance_id = instance.id
    order.status = OrderStatus.MATERIALIZED


def _baseline_is_stable(raw_values: list[float] | None) -> bool:
    if not raw_values:
        return False
    if len(raw_values) == 1:
        return True
    median = statistics.median(raw_values)
    if median <= 0:
        return True
    return statistics.stdev(raw_values) < median * 0.10


async def _filter_nodes_with_healthy_agents(
    nodes: list[NodeModel],
) -> tuple[list[NodeModel], list[dict[str, str]]]:
    """Keep local demo routing away from nodes whose Node Agent is unreachable."""
    if not nodes:
        return [], []

    client = AgentClient(timeout=2)

    async def probe(node: NodeModel) -> tuple[NodeModel, bool, str | None]:
        endpoint = node.agent_address or node.management_ip
        if not endpoint:
            return node, False, "missing agent endpoint"
        ok, payload = await client.health(endpoint)
        if ok:
            return node, True, None
        reason = payload.get("error") if isinstance(payload, dict) else None
        return node, False, reason or "node_agent unhealthy"

    results = await asyncio.gather(*(probe(node) for node in nodes))
    healthy = [node for node, ok, _reason in results if ok]
    skipped = [
        {
            "hostname": node.hostname,
            "reason": reason or "node_agent unhealthy",
        }
        for node, ok, reason in results
        if not ok
    ]
    return healthy, skipped


async def _benchmark_routing_pool(db: AsyncSession, task_type: str | None) -> dict[str, Any]:
    schedulable_rows = await db.execute(
        select(NodeModel).where(
            NodeModel.is_schedulable == True,
            NodeModel.is_routable == True,
            NodeModel.deleted_at.is_(None),
        )
    )
    schedulable = schedulable_rows.scalars().all()
    if not schedulable:
        raise HTTPException(status_code=400, detail="No schedulable nodes available")

    skipped_unhealthy_nodes: list[dict[str, str]] = []
    schedulable, skipped = await _filter_nodes_with_healthy_agents(schedulable)
    skipped_unhealthy_nodes.extend(skipped)
    if not schedulable:
        raise HTTPException(status_code=400, detail="No healthy schedulable nodes available")

    compute_candidates: list[NodeModel] = []
    if task_type:
        baselines = (
            await db.execute(select(NodeBaseline).where(NodeBaseline.task_type == task_type))
        ).scalars().all()
        baselines_by_node_id: dict[str, NodeBaseline] = {}
        for baseline in baselines:
            baselines_by_node_id.setdefault(baseline.node_id, baseline)
        baseline_node_ids = set(baselines_by_node_id)
        compute_candidates = [
            node
            for node in schedulable
            if node.id in baseline_node_ids and _node_can_host_compute(node)
        ]
        compute_candidates = _rank_compute_nodes_by_baseline(compute_candidates, baselines_by_node_id)

    terminal_nodes = [
        node for node in schedulable if _node_can_host_benchmark_endpoint(node)
    ]
    if not terminal_nodes:
        raise HTTPException(
            status_code=400,
            detail="No terminal endpoint nodes available for benchmark source/sink containers",
        )
    return {
        "terminal": terminal_nodes,
        "compute": compute_candidates,
        "skipped_unhealthy_nodes": skipped_unhealthy_nodes,
    }


def _pick_fixed_or_random_endpoint(
    terminal_nodes: list[NodeModel],
    fixed_hostname: str | None,
) -> NodeModel:
    terminal_by_hostname = {node.hostname: node for node in terminal_nodes}
    if fixed_hostname and fixed_hostname in terminal_by_hostname:
        return terminal_by_hostname[fixed_hostname]
    return random.choice(terminal_nodes)


def _benchmark_order_index(order: TaskOrder | None) -> int:
    if not order:
        return 0
    config = order.runtime_config or {}
    benchmark = config.get("benchmark") if isinstance(config, dict) else None
    run_id = str(benchmark.get("run_id") or "") if isinstance(benchmark, dict) else ""
    name = str(order.name or "")
    if run_id and name.startswith(f"benchmark-") and name.endswith(tuple(str(i) for i in range(10))):
        suffix = name.rsplit("-", 1)[-1]
        if suffix.isdigit():
            return max(0, int(suffix) - 1)
    try:
        return abs(hash(order.id or "")) % 10_000
    except Exception:
        return 0


def _benchmark_compute_gpu_slots(nodes: list[NodeModel]) -> list[tuple[NodeModel, str]]:
    """Expand each eligible compute node into independently schedulable GPU slots."""
    slots: list[tuple[NodeModel, str]] = []
    for node in nodes:
        for gpu_index in range(max(1, int(node.gpu_count or 0))):
            slots.append((node, str(gpu_index)))
    return slots


def _pick_benchmark_nodes(
    pool: dict[str, list[NodeModel]],
    order: TaskOrder | None = None,
    *,
    compute_allocation_mode: str = "node",
) -> tuple[dict[str, NodeModel], str]:
    compute_candidates = [node for node in pool["compute"] if _node_can_host_compute(node)]
    if not compute_candidates:
        raise RuntimeError("No compute-capable nodes available")
    if compute_allocation_mode == "gpu_slot":
        compute_gpu_slots = _benchmark_compute_gpu_slots(compute_candidates)
    else:
        compute_gpu_slots = [(node, "0") for node in compute_candidates]
    if not compute_gpu_slots:
        raise RuntimeError("No compute GPU slots available")
    index = _benchmark_order_index(order)
    compute, gpu_id = compute_gpu_slots[index % len(compute_gpu_slots)]
    terminal = pool["terminal"] or compute_candidates
    return {
        "source": _pick_fixed_or_random_endpoint(terminal, order.source_name if order else None),
        "compute": compute,
        "sink": _pick_fixed_or_random_endpoint(terminal, order.destination_name if order else None),
    }, gpu_id


@router.post("/{order_id}/auto-route")
async def auto_route_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Built-in automatic routing strategy for evaluation orders."""
    await _ensure_internal_benchmark_routing_enabled(db)
    runtime_settings = await get_runtime_settings(db)
    row = await db.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    order = row.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.role != UserRole.ADMIN and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot route orders owned by another user")
    if not order.is_benchmark:
        raise HTTPException(status_code=400, detail="系统自动分配仅支持业务测评工单")
    if order.routing_status != RoutingStatus.PENDING.value:
        raise HTTPException(status_code=400, detail=f"Order routing_status is '{order.routing_status}', expected 'pending'")

    task_type = _benchmark_task_type(order)
    routing_pool = await _benchmark_routing_pool(db, task_type)
    if not routing_pool["compute"]:
        raise HTTPException(status_code=400, detail="No baseline compute nodes available")

    picked, compute_gpu_id = _pick_benchmark_nodes(
        routing_pool,
        order,
        compute_allocation_mode=benchmark_compute_allocation_mode_from_settings(runtime_settings),
    )
    await _do_auto_route(
        db,
        order,
        picked,
        compute_gpu_id,
        compute_allocation_mode=benchmark_compute_allocation_mode_from_settings(runtime_settings),
    )
    await db.commit()
    return {"status": "ok", "order_id": order_id, "instance_id": order.materialized_instance_id}
