import asyncio
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
    mark_network_binding_ready,
)
from services.scheduler import TaskScheduler
from services.system_settings import (
    get_runtime_settings,
    modality_priority_map_from_settings,
    routing_resource_options_from_settings,
)
from services.time_utils import business_now
from services.topology_catalog import COMPUTE_NODE_ALIASES, TERMINAL_NODE_ALIASES

from .instances import _build_preflight_plan_from_instance, _create_instance_from_template, _preflight_instance_plan

router = APIRouter(prefix="/api/orders", tags=["orders"])


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
        await executor.execute_dag_start(instance_id, claimed_start=True)


def _schedule_background_benchmark_start(instance_id: str) -> None:
    asyncio.create_task(_background_benchmark_start(instance_id))


def _benchmark_task_type(order: TaskOrder) -> str | None:
    config = order.runtime_config or {}
    business_task = config.get("business_task")
    if isinstance(business_task, dict):
        value = business_task.get("task_type")
        return str(value) if value else None
    return None


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
        return {"message": "当前工单没有已部署实例", "stopped": False}

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
            conversation.status = ConversationStatus.AWAITING_ROUTING
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
        order.materialized_instance_id = None
        order.status = OrderStatus.PENDING if route_only else OrderStatus.COMPLETED
        order.routing_status = RoutingStatus.COMPLETED.value
        rc["deployment_required"] = False
        if route_only:
            rc["manual_start_required"] = True
        if route_only:
            rc["deployment_mode"] = "route_only"
        rc["routing_result"] = {
            **routing_result,
            "network_bindings": [],
            "network_ready_required": False,
            "network_ready": True,
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
            False,
        )
        await db.commit()
        return {
            "status": "ok",
            "order_id": order_id,
            "routing_status": "completed",
            "deployment_required": False,
            "deployment_mode": deployment_mode,
            "instance_id": None,
            "network_bindings": [],
            "network_ready_required": False,
            "network_ready": True,
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
    routing_strategy: str = "resource_guarantee"
    source_name: Optional[str] = None
    destination_name: Optional[str] = None

    @model_validator(mode="after")
    def _validate_routing_strategy(self):
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
    max_parallel: int = Field(default=3, ge=1, le=10)
    per_compute_slot_limit: int = Field(default=1, ge=1, le=4)
    cleanup_evaluated: bool = True
    retry_failed: bool = False
    wait_seconds: int = Field(default=0, ge=0, le=30)


@router.post("/benchmark/stop", response_model=BatchOperationResponse)
async def stop_benchmark_run(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止当前测评轮次的未完成运行，释放容器，保留已完成证据。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    orders, failed = await _resolve_batch_orders(db, request, current_user)
    task_scheduler = TaskScheduler()
    succeeded: list[str] = []

    for order in orders:
        try:
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
                continue

            result = await db.execute(
                select(TaskInstance)
                .options(selectinload(TaskInstance.nodes))
                .where(TaskInstance.id == order.materialized_instance_id)
            )
            instance = result.scalar_one_or_none()
            if not instance:
                if order.status == OrderStatus.MATERIALIZED:
                    order.status = OrderStatus.CANCELLED
                    order.error_message = order.error_message or "测评已停止，关联实例不存在"
                succeeded.append(order.id)
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
                order.status = OrderStatus.CANCELLED
                order.error_message = order.error_message or "测评已手动停止"
            succeeded.append(order.id)
        except Exception as exc:
            failed[order.id] = str(exc)

    await db.commit()
    return BatchOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/batch-auto-route")
async def batch_auto_route(
    payload: BenchmarkRunScopedRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-route all pending benchmark orders."""
    await _ensure_internal_benchmark_routing_enabled(db)
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
            picked = _pick_benchmark_nodes(routing_pool, order)
            await _do_auto_route(db, order, picked)
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
    query = select(TaskOrder).where(
        TaskOrder.status.in_([OrderStatus.MATERIALIZED.value, OrderStatus.COMPLETED.value])
        if include_completed
        else TaskOrder.status == OrderStatus.MATERIALIZED.value,
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
    await emit_release_events_for_order(
        db,
        order,
        reason="benchmark_cleanup",
        metadata={"instance_id": instance.id, "preserve_order": True},
    )

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
    run_orders = await _controlled_benchmark_orders(db, payload, current_user, include_completed=True)
    orders = [order for order in run_orders if order.status == OrderStatus.MATERIALIZED]
    startable_instance_ids = {
        order.materialized_instance_id
        for order in orders
        if order.materialized_instance_id
    }
    recalc_succeeded, recalc_failed = await _reevaluate_orders_from_latest_metrics(
        db,
        run_orders,
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

    cleaned: list[str] = []
    failed: dict[str, str] = dict(recalc_failed)
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

        slot = _benchmark_compute_slot(order)
        if active_by_slot[slot] >= payload.per_compute_slot_limit:
            skipped_busy.append(order.id)
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
    success_count = sum(1 for evaluation in eval_map.values() if evaluation.business_success)
    evaluated_count = len(eval_map)
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
            "task_node_id": role,
            "topology_node_id": node.hostname,
            **({"gpu_device": _default_compute_gpu_for_order(order)} if role == "compute" and _default_compute_gpu_for_order(order) is not None else {}),
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
            "description": "平台按当前可用终端节点和计算节点完成本轮测评分配。",
        },
    }
    order.runtime_config = rc
    flag_modified(order, "runtime_config")
    order.routing_status = RoutingStatus.COMPLETED.value

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


def _pick_benchmark_nodes(pool: dict[str, list[NodeModel]], order: TaskOrder | None = None) -> dict[str, NodeModel]:
    compute_candidates = [node for node in pool["compute"] if _node_can_host_compute(node)]
    if not compute_candidates:
        raise RuntimeError("No compute-capable nodes available")
    index = _benchmark_order_index(order)
    compute = compute_candidates[index % len(compute_candidates)]
    terminal = pool["terminal"] or compute_candidates
    return {
        "source": _pick_fixed_or_random_endpoint(terminal, order.source_name if order else None),
        "compute": compute,
        "sink": _pick_fixed_or_random_endpoint(terminal, order.destination_name if order else None),
    }


@router.post("/{order_id}/auto-route")
async def auto_route_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Built-in automatic routing strategy for evaluation orders."""
    await _ensure_internal_benchmark_routing_enabled(db)
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

    picked = _pick_benchmark_nodes(routing_pool, order)
    await _do_auto_route(db, order, picked)
    await db.commit()
    return {"status": "ok", "order_id": order_id, "instance_id": order.materialized_instance_id}
