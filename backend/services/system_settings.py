"""Runtime system settings for standard and debug modes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import SystemSetting
from services.modality_catalog import MODALITIES, normalize_modality_priority_map

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
    "rule": "规则解析",
}

BENCHMARK_ROUTING_MODE_LABELS = {
    "internal_auto": "自动路由",
    "external": "外部路由系统",
}


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
