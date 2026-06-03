"""自动端口分配服务。

在实例物化时，对 port_defs 中 auto=true 的端口调用 Node Agent /ports/available
获取可用端口，填充 port_values。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _allocate_from_range(
    auto_ports: list[dict[str, Any]],
    start: int,
    end: int,
    exclude_ports: list[int] | None = None,
) -> list[int]:
    excluded = set(exclude_ports or [])
    allocated: list[int] = []
    for port in range(start, end + 1):
        if port in excluded:
            continue
        allocated.append(port)
        excluded.add(port)
        if len(allocated) >= len(auto_ports):
            break
    return allocated


async def auto_allocate_ports(
    agent_address: str,
    port_defs: list[dict[str, Any]] | None,
    existing_port_values: dict[str, Any] | None = None,
    exclude_ports: list[int] | None = None,
) -> dict[str, int]:
    """对 auto=true 且未显式指定的端口，调用 Node Agent 获取可用端口。

    Returns:
        合并后的 port_values 字典（包含已有值和新分配值）
    """
    if not port_defs:
        return dict(existing_port_values or {})

    result = dict(existing_port_values or {})
    auto_ports: list[dict[str, Any]] = []

    for item in port_defs:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if not name:
            continue
        if not item.get("auto", False):
            continue
        if name in result and result[name]:
            continue
        auto_ports.append(item)

    if not auto_ports:
        return result

    port_range = auto_ports[0].get("range", [18000, 19999])
    start = port_range[0] if len(port_range) > 0 else 18000
    end = port_range[1] if len(port_range) > 1 else 19999

    all_exclude = list(exclude_ports or [])
    for v in result.values():
        try:
            all_exclude.append(int(v))
        except (TypeError, ValueError):
            pass

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{agent_address}/ports/available",
                json={
                    "count": len(auto_ports),
                    "start": start,
                    "end": end,
                    "exclude": all_exclude,
                    "network_mode": "host",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning(f"auto_allocate_ports: agent call failed: {exc}")
        data = {"ports": _allocate_from_range(auto_ports, start, end, all_exclude)}

    allocated = data.get("ports", [])
    for i, item in enumerate(auto_ports):
        name = item["name"]
        if i < len(allocated):
            result[name] = allocated[i]
        else:
            default = item.get("default")
            if default is not None:
                result[name] = int(default)
            logger.warning(f"auto_allocate_ports: not enough ports for {name}")

    return result
