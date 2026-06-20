"""Routing policy dictionary shared by API validation and summaries."""

from __future__ import annotations

from typing import Any

VALID_ROUTING_POLICIES = {
    "cost_priority",
    "low_latency_forwarding",
    "resource_guarantee",
    "fastest_completion",
    "load_balance",
}

def normalize_routing_policy(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text in VALID_ROUTING_POLICIES:
        return text
    return default


def require_routing_policy(value: Any, *, field_name: str = "routing_strategy") -> str:
    normalized = normalize_routing_policy(value)
    if normalized is None:
        allowed = ", ".join(sorted(VALID_ROUTING_POLICIES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return normalized
