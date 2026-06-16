"""Shared business-task environment variable builder for worker containers."""

from __future__ import annotations

import json
from typing import Any

from models import TaskOrder
from services.modality_catalog import modality_for_task_type, normalize_modality


GPU_TASK_TYPES = {
    "high_throughput_matmul",
    "low_latency_video_pipeline",
    "llm_text_generation",
}


def json_env(value: Any) -> str:
    """Serialize JSON env vars compactly and consistently."""
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def routing_strategy_from_business_task(business_task: dict[str, Any] | None) -> str:
    if not isinstance(business_task, dict):
        return "resource_guarantee"
    runtime_plan = business_task.get("runtime_plan") or {}
    if isinstance(runtime_plan, dict) and runtime_plan.get("routing_strategy"):
        return str(runtime_plan["routing_strategy"])
    if business_task.get("routing_strategy"):
        return str(business_task["routing_strategy"])
    return "resource_guarantee"


def modality_from_business_task(business_task: dict[str, Any] | None) -> str:
    if not isinstance(business_task, dict):
        return ""
    task_type = str(business_task.get("task_type") or "")
    raw_modality = business_task.get("modality")
    return normalize_modality(str(raw_modality), task_type) or modality_for_task_type(task_type) or str(raw_modality or "")


def build_business_env(
    *,
    order: TaskOrder | None = None,
    business_task: dict[str, Any] | None = None,
    task_role: str | None = None,
    task_instance_id: str | None = None,
    source_name: str | None = None,
    destination_name: str | None = None,
    resource_requirement: dict[str, Any] | None = None,
    result_storage: dict[str, Any] | None = None,
    routing_result: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build the shared env contract consumed by business worker images."""
    bt = dict(business_task or {})
    order_source = source_name if source_name is not None else getattr(order, "source_name", None)
    order_destination = destination_name if destination_name is not None else getattr(order, "destination_name", None)
    external_id = bt.get("external_task_id") or getattr(order, "external_task_id", None) or getattr(order, "id", None) or ""
    instance_id = task_instance_id or getattr(order, "id", None) or external_id
    task_type = str(bt.get("task_type") or getattr(order, "name", "") or "")
    modality = modality_from_business_task(bt)
    routing_strategy = routing_strategy_from_business_task(bt)
    runtime_plan = bt.get("runtime_plan") or {}
    merged_resource_requirement = resource_requirement if resource_requirement is not None else bt.get("resource_requirement")
    if task_role and isinstance(merged_resource_requirement, dict):
        role_resources = merged_resource_requirement.get(str(task_role).lower())
        if isinstance(role_resources, dict):
            merged_resource_requirement = role_resources
    merged_result_storage = result_storage if result_storage is not None else bt.get("result_storage")
    merged_routing_result = routing_result if routing_result is not None else bt.get("routing_result")

    env = {
        "BUSINESS_TASK_ID": str(external_id),
        "ORDER_ID": str(getattr(order, "id", "") or external_id),
        "CONVERSATION_ID": str(getattr(order, "conversation_id", "") or ""),
        "TASK_INSTANCE_ID": str(instance_id),
        "TASK_TYPE": task_type,
        "TASK_MODALITY": modality,
        "MODALITY": modality,
        "ROUTING_STRATEGY": routing_strategy,
        "SOURCE_NAME": str(bt.get("source_name") or order_source or ""),
        "DESTINATION_NAME": str(bt.get("destination_name") or order_destination or ""),
        "DATA_PROFILE": json_env(bt.get("data_profile")),
        "BUSINESS_OBJECTIVE": json_env(bt.get("business_objective")),
        "RUNTIME_PLAN": json_env(runtime_plan),
        "RESOURCE_REQUIREMENT": json_env(merged_resource_requirement),
        "ROUTING_RESULT": json_env(merged_routing_result),
        "RESULT_STORAGE": json_env(merged_result_storage),
        "BUSINESS_TASK_JSON": json_env(bt),
    }
    normalized_role = str(task_role or "").lower()
    if task_role:
        env["TASK_ROLE"] = str(task_role)
    if task_type in GPU_TASK_TYPES and normalized_role in {"compute", "worker", "infer", "train"}:
        env["USE_GPU"] = "true"
    return env
