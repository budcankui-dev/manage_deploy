"""实例创建时的端口/宏解析。"""

from __future__ import annotations

from typing import Any, Optional


def _port_number(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def resolve_port_values(
    port_defs: Optional[list],
    port_values: Optional[dict],
    legacy_ports: Optional[dict] = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """将命名端口变量解析为 Docker ports 映射与 port_values 字典。"""
    normalized: dict[str, int] = {}
    for item in port_defs or []:
        if isinstance(item, str) and item.strip():
            name = item.strip()
            default = None
            label = None
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            default = _port_number(item.get("default"))
            label = item.get("label")
        else:
            continue
        if not name:
            continue
        raw = (port_values or {}).get(name)
        port = _port_number(raw)
        if port is None:
            port = default
        if port is not None:
            normalized[name] = port

    for key, raw in (port_values or {}).items():
        if key in normalized:
            continue
        port = _port_number(raw)
        if port is not None:
            normalized[str(key)] = port

    if not normalized and legacy_ports:
        docker_ports = {str(k): str(v) for k, v in legacy_ports.items()}
        for container_port, host_port in legacy_ports.items():
            port = _port_number(host_port) or _port_number(container_port)
            if port is not None:
                normalized[str(container_port)] = port
        return docker_ports, normalized

    docker_ports = {str(port): str(port) for port in sorted(set(normalized.values()))}
    return docker_ports, normalized
