"""Runtime system settings for standard and debug modes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import SystemSetting
from services.modality_catalog import (
    MODALITIES,
    TASK_TYPE_MODALITY,
    normalize_modality,
    normalize_modality_priority_map,
)

SYSTEM_RUNTIME_KEY = "runtime_modes"
PRODUCTION_MODE = "production"
DEVELOPMENT_MODE = "development"

DEFAULT_RUNTIME_SETTINGS: dict[str, Any] = {
    "environment_mode": PRODUCTION_MODE,
    "intent_parser_mode": "llm",
    "intent_rule_fallback_enabled": True,
    "benchmark_routing_mode": "external",
    "expert_mode": True,
    "show_internal_controls": False,
    "show_routing_dag_json": False,
    "modality_priority_map": normalize_modality_priority_map(),
    "task_modality_override_enabled": False,
    "task_modality_overrides": {},
    "task_resource_override_enabled": False,
    "task_resource_overrides": {},
    "benchmark_execution_defaults": {
        "default_task_count": 30,
        "max_parallel": 2,
        "per_compute_slot_limit": 1,
    },
    "notes": "标准模式用于常规运行；调试模式用于联调、排障和快速回归。",
}

ENVIRONMENT_MODE_LABELS = {
    PRODUCTION_MODE: "标准模式",
    DEVELOPMENT_MODE: "调试模式",
}

LEGACY_ENVIRONMENT_MODES = {
    "expert_demo": PRODUCTION_MODE,
    "external_integration": PRODUCTION_MODE,
    "local_mock": DEVELOPMENT_MODE,
}

INTENT_PARSER_MODE_LABELS = {
    "llm": "大模型/智能体解析",
    "rule": "系统解析流程",
}

BENCHMARK_ROUTING_MODE_LABELS = {
    "internal_auto": "自动路由",
    "external": "外部路由系统",
}

TASK_RESOURCE_ROLES = ("source", "compute", "sink")
RESOURCE_KEYS = ("cpu_units", "mem_mb", "cpu_mem_mb", "disk_mb", "gpu_units", "gpu_mem_mb")


def normalize_benchmark_execution_defaults(value: dict[str, Any] | None = None) -> dict[str, int]:
    defaults = DEFAULT_RUNTIME_SETTINGS["benchmark_execution_defaults"]
    source = value if isinstance(value, dict) else {}

    def _int_in_range(key: str, minimum: int, maximum: int) -> int:
        raw = source.get(key, defaults[key])
        try:
            number = int(raw)
        except (TypeError, ValueError):
            number = defaults[key]
        return max(minimum, min(maximum, number))

    return {
        "default_task_count": _int_in_range("default_task_count", 1, 30),
        "max_parallel": _int_in_range("max_parallel", 1, 10),
        "per_compute_slot_limit": _int_in_range("per_compute_slot_limit", 1, 4),
    }


def normalize_task_modality_overrides(value: dict[str, Any] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(value, dict):
        return result
    for task_type, raw_modality in value.items():
        task_key = str(task_type or "").strip()
        if task_key not in TASK_TYPE_MODALITY:
            continue
        modality = normalize_modality(str(raw_modality or ""), task_key)
        if modality in MODALITIES:
            result[task_key] = modality
    return result


def normalize_task_resource_overrides(value: dict[str, Any] | None = None) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    if not isinstance(value, dict):
        return result

    for task_type, role_map in value.items():
        task_key = str(task_type or "").strip()
        if not task_key or not isinstance(role_map, dict):
            continue
        normalized_roles: dict[str, dict[str, int]] = {}
        for role, raw_resources in role_map.items():
            role_key = str(role or "").strip().lower()
            if role_key not in TASK_RESOURCE_ROLES or not isinstance(raw_resources, dict):
                continue
            normalized_resources: dict[str, int] = {}
            for key in RESOURCE_KEYS:
                if key not in raw_resources:
                    continue
                try:
                    number = int(raw_resources[key])
                except (TypeError, ValueError):
                    continue
                if number < 0:
                    continue
                normalized_resources[key] = number
            if normalized_resources:
                normalized_roles[role_key] = normalized_resources
        if normalized_roles:
            result[task_key] = normalized_roles
    return result


def _normalized_settings(value: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_RUNTIME_SETTINGS)
    if isinstance(value, dict):
        merged.update(value)

    merged["environment_mode"] = LEGACY_ENVIRONMENT_MODES.get(
        merged.get("environment_mode"),
        merged.get("environment_mode"),
    )
    if merged["environment_mode"] not in ENVIRONMENT_MODE_LABELS:
        merged["environment_mode"] = DEFAULT_RUNTIME_SETTINGS["environment_mode"]
    if merged["intent_parser_mode"] not in INTENT_PARSER_MODE_LABELS:
        merged["intent_parser_mode"] = DEFAULT_RUNTIME_SETTINGS["intent_parser_mode"]
    if merged["benchmark_routing_mode"] not in BENCHMARK_ROUTING_MODE_LABELS:
        merged["benchmark_routing_mode"] = DEFAULT_RUNTIME_SETTINGS["benchmark_routing_mode"]

    merged["intent_rule_fallback_enabled"] = bool(merged.get("intent_rule_fallback_enabled", True))
    merged["expert_mode"] = bool(merged.get("expert_mode", True))
    merged["show_internal_controls"] = bool(merged.get("show_internal_controls", False))
    merged["show_routing_dag_json"] = bool(merged.get("show_routing_dag_json", False))
    merged["modality_priority_map"] = normalize_modality_priority_map(
        merged.get("modality_priority_map")
    )
    merged["task_modality_override_enabled"] = bool(
        merged.get("task_modality_override_enabled", False)
    )
    merged["task_modality_overrides"] = normalize_task_modality_overrides(
        merged.get("task_modality_overrides")
    )
    merged["task_resource_override_enabled"] = bool(
        merged.get("task_resource_override_enabled", False)
    )
    merged["task_resource_overrides"] = normalize_task_resource_overrides(
        merged.get("task_resource_overrides")
    )
    merged["benchmark_execution_defaults"] = normalize_benchmark_execution_defaults(
        merged.get("benchmark_execution_defaults")
    )
    merged["modality_priority_rows"] = [
        {"modality": modality, "priority": merged["modality_priority_map"][modality]}
        for modality in MODALITIES
    ]
    merged["dashscope_configured"] = bool(settings.dashscope_api_key)
    merged["dashscope_model"] = settings.dashscope_model
    merged["labels"] = {
        "environment_mode": ENVIRONMENT_MODE_LABELS[merged["environment_mode"]],
        "intent_parser_mode": INTENT_PARSER_MODE_LABELS[merged["intent_parser_mode"]],
        "benchmark_routing_mode": BENCHMARK_ROUTING_MODE_LABELS[merged["benchmark_routing_mode"]],
    }
    return merged


async def get_runtime_settings(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == SYSTEM_RUNTIME_KEY))
    ).scalar_one_or_none()
    return _normalized_settings(row.value if row else None)


async def update_runtime_settings(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    updated_by: str | None = None,
) -> dict[str, Any]:
    value = _normalized_settings(payload)
    # Derived read-only fields should not be persisted.
    persisted = {
        key: value[key]
        for key in DEFAULT_RUNTIME_SETTINGS
        if key in value
    }

    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == SYSTEM_RUNTIME_KEY))
    ).scalar_one_or_none()
    if not row:
        row = SystemSetting(
            key=SYSTEM_RUNTIME_KEY,
            value=persisted,
            description="系统运行模式配置",
            updated_by=updated_by,
        )
        db.add(row)
    else:
        row.value = persisted
        row.updated_by = updated_by
    await db.commit()
    await db.refresh(row)
    return _normalized_settings(row.value)


def should_use_llm_intent_parser(runtime_settings: dict[str, Any]) -> bool:
    return (
        runtime_settings.get("intent_parser_mode") == "llm"
        and bool(settings.dashscope_api_key)
    )


def allow_rule_intent_fallback(runtime_settings: dict[str, Any]) -> bool:
    return bool(runtime_settings.get("intent_rule_fallback_enabled", True))


def modality_priority_map_from_settings(runtime_settings: dict[str, Any] | None) -> dict[str, int]:
    return normalize_modality_priority_map(
        (runtime_settings or {}).get("modality_priority_map")
    )


def modality_for_task_from_settings(
    task_type: str | None,
    default_modality: str | None,
    runtime_settings: dict[str, Any] | None,
) -> str | None:
    if not task_type:
        return default_modality
    settings_value = runtime_settings or {}
    if not settings_value.get("task_modality_override_enabled", False):
        return default_modality
    overrides = normalize_task_modality_overrides(
        settings_value.get("task_modality_overrides")
    )
    return overrides.get(task_type) or default_modality


def routing_resource_options_from_settings(
    runtime_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    settings_value = runtime_settings or {}
    return {
        "task_resource_override_enabled": bool(
            settings_value.get("task_resource_override_enabled", False)
        ),
        "task_resource_overrides": normalize_task_resource_overrides(
            settings_value.get("task_resource_overrides")
        ),
    }
