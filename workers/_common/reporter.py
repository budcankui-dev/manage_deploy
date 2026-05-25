"""向 Task Manager 上报业务指标。"""

from __future__ import annotations

import os
from typing import Any

import httpx


def report_metric(
    metric_key: str,
    metric_value: float,
    *,
    unit: str | None = None,
    tags: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> None:
    base = os.environ["MANAGER_API_BASE"].rstrip("/")
    instance_id = os.environ["TASK_INSTANCE_ID"]
    url = f"{base}/api/instances/{instance_id}/metrics"
    payload: dict[str, Any] = {
        "metric_key": metric_key,
        "metric_value": metric_value,
    }
    if unit:
        payload["unit"] = unit
    if tags:
        payload["tags"] = tags
    node_id = os.environ.get("TASK_NODE_INSTANCE_ID")
    if node_id:
        payload["node_instance_id"] = node_id

    headers: dict[str, str] = {}
    token = os.environ.get("SERVICE_API_TOKEN")
    if token:
        headers["X-Service-Token"] = token

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code >= 500 and attempt < 2:
                import time

                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    if last_error:
        raise last_error
